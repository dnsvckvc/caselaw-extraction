"""Citation treatment with Jev 1.14: is a BGE or file-number citation routine standard text?

The prompt is prompt 2 of the pilot (docs/jev-treatment.md, docs/citation-treatment-guideline.md)
and is frozen: change it only on the dev windows of `scripts/jev/treatment.py`. The routine
selector of the API reads one label, `routine_standard`, at any probability
(docs/plan-routine-selector.md).

`label_run` labels every `bge` and `docket` citation of a run. It appends to
`<run>/treatment.jsonl` as it goes, so a stopped job resumes, and writes
`<run>/treatment.parquet` (one row per citation span) at the end.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

JEV = "typesafe/jev-1.14"
JEV_SNAPSHOT = "typesafe/jev-1.14-20261014"  # the snapshot the pilot measured
BASE = "https://openrouter.ai/api"
ROUTINE = "routine_standard"
BEFORE, AFTER = 400, 200
JSONL, PARQUET = "treatment.jsonl", "treatment.parquet"

INSTRUCTIONS = (
    "Der Text ist ein Ausschnitt aus einem Urteil des Schweizerischen Bundesgerichts. Die zu beurteilende "
    "Zitierung ist mit [[ ]] markiert. Wie verwendet das Bundesgericht diese Zitierung im Ausschnitt? "
    "Regeln: case_history geht vor. party_or_lower_court nur, wenn die Zuschreibung im Ausschnitt sichtbar ist. "
    "Eine Zitierung in einer Liste folgt der Aussage, welche die Liste stützt. Beruft sich eine Partei oder die "
    "Vorinstanz darauf und sagt das Bundesgericht, sie helfe nicht oder sei nicht anwendbar: negative_treatment."
)
CRITERIA = {
    "routine_standard": "Standardtext des Gerichts dazu, wie eine Beschwerde an das Bundesgericht funktioniert: Eintreten, Streitwert, Zwischenentscheid, Begründungspflicht, Rügeprinzip, Sachverhaltsprüfung, Willkürformel, Kosten vor Bundesgericht. Passt auf fast jede Beschwerde, auch wenn hier angewendet. Dazu gehören alle Regeln zum Verfahren vor dem Bundesgericht selbst (BGG), auch wenn sie im Fall entscheidend sind: ob ein End- oder Zwischenentscheid nach Art. 90 ff. BGG vorliegt, Anforderungen an Rechtsbegehren, Revisionsgründe nach Art. 121 ff. BGG, Nichtigkeit ausserhalb der Beschwerde, Prüfung von Ermessen, Beweiswürdigung und antizipierter Beweiswürdigung, Rechtsfragen von grundsätzlicher Bedeutung.",
    "substantive_rule": "Eigene Erwägung des Gerichts mit der Zitierung als Beleg für eine Regel zur streitigen Rechtsfrage, auch Regeln des Zivilprozesses oder des SchKG, welche die Vorinstanz anzuwenden hatte. Sagt das Gericht, eine Vorinstanz sei davon abgewichen, gehört es auch hierher. Regeln zum Verfahren vor dem Bundesgericht selbst gehören nicht hierher.",
    "party_or_lower_court": "Die Zitierung gibt wieder, was eine Partei, die Vorinstanz oder eine andere Stelle gesagt oder angeführt hat, ohne dass das Gericht es im selben Satz übernimmt.",
    "negative_treatment": "Das Gericht grenzt den zitierten Entscheid ab, schränkt ihn ein, stellt ihn in Frage, weicht davon ab, ändert ihn, sagt, er sei hier nicht anwendbar, oder lässt offen, ob er noch gilt.",
    "case_history": "Die Zitierung nennt einen früheren Entscheid in demselben Streit, ein zusammenhängendes Verfahren oder das angefochtene Urteil, zum Beispiel das Urteil, gegen das sich die Revision richtet, oder einen früheren Rückweisungsentscheid.",
}

TREATMENT_SCHEMA = pa.schema(
    [
        ("span_id", pa.string()),
        ("label", pa.string()),
        ("p", pa.float64()),  # top probability
        ("probabilities", pa.string()),  # JSON object, label -> probability
        ("model", pa.string()),  # the snapshot that answered
        ("labelled_at", pa.string()),
    ]
)


def window(text: str, start: int, end: int) -> str:
    """The pilot's window: 400 characters before the citation, 200 after, citation in [[ ]]."""
    left = text[max(0, start - BEFORE) : start]
    return re.sub(r"\s+", " ", f"{left}[[{text[start:end]}]]{text[end : end + AFTER]}").strip()


def _post(path: str, body: dict, key: str) -> dict:
    req = urllib.request.Request(
        BASE + path,
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(5):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)
            out["latency_s"] = time.time() - t0
            return out
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(2**attempt)
    raise AssertionError


def call_jev(text: str, key: str) -> dict:
    body = {
        "model": JEV,
        "state": {"ausschnitt": text},
        "questions": {
            "treatment": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}
        },
    }
    r = _post("/alpha/decisions", body, key)
    a = r["answers"]["treatment"]
    return {
        "model": r.get("model"),
        "pred": a.get("choice"),
        "confidence": a.get("confidence"),
        "probabilities": a.get("probabilities"),
        "input_tokens": r["usage"]["input_tokens"],
        "output_tokens": r["usage"].get("output_tokens"),
        "cost": r["usage"].get("cost"),
        "latency_s": r["latency_s"],
    }


def citation_windows(run_dir: Path, texts: Path) -> list[tuple[str, str]]:
    """(span_id, window) for every `bge` and `docket` citation span of a run, in span order."""
    import duckdb

    rows = duckdb.sql(
        f"""
        SELECT DISTINCT c.span_id, s."start", s."end", t.text
        FROM read_parquet('{run_dir / "citations.parquet"}') c
        JOIN read_parquet('{run_dir / "spans.parquet"}') s USING (span_id)
        JOIN read_parquet('{texts}') t ON t.decision_id = c.decision_id
        WHERE c.kind IN ('bge', 'docket')
        ORDER BY c.span_id
        """
    ).fetchall()
    return [(span_id, window(text, start, end)) for span_id, start, end, text in rows]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []


def write_parquet(run_dir: Path) -> Path:
    """`treatment.parquet` from `treatment.jsonl`; the last answer per span wins."""
    rows = {r["span_id"]: r for r in _read_jsonl(run_dir / JSONL)}
    out = run_dir / PARQUET
    table = pa.Table.from_pylist(
        [
            {
                "span_id": r["span_id"],
                "label": r["pred"],
                "p": max(r["probabilities"].values()) if r.get("probabilities") else None,
                "probabilities": json.dumps(r.get("probabilities")),
                "model": r["model"],
                "labelled_at": r["labelled_at"],
            }
            for r in rows.values()
        ],
        schema=TREATMENT_SCHEMA,
    )
    pq.write_table(table, out, compression="zstd")
    return out


def label_run(
    run_dir: Path,
    texts: Path,
    key: str,
    max_cost: float = 8.0,
    workers: int = 8,
    limit: int | None = None,
    call: Callable[[str, str], dict] = call_jev,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Label the citations of a run that have no answer yet. Stops at `max_cost` (USD) and when
    an answer comes from another snapshot than `JEV_SNAPSHOT`."""
    path = run_dir / JSONL
    done = _read_jsonl(path)
    seen = {d["span_id"] for d in done}
    spent = sum(d.get("cost") or 0 for d in done)
    todo = [w for w in citation_windows(run_dir, texts) if w[0] not in seen]
    if limit is not None:
        todo = todo[:limit]
    errors, stopped = 0, ""

    def one(w: tuple[str, str]) -> tuple[str, dict | None, str]:
        try:
            return w[0], call(w[1], key), ""
        except Exception as e:  # noqa: BLE001 - counted; the span is retried by the next run
            return w[0], None, str(e)

    batch = workers * 25
    with path.open("a") as f, ThreadPoolExecutor(workers) as pool:
        for n in range(0, len(todo), batch):
            if spent >= max_cost:
                stopped = f"spending cap USD {max_cost}"
                break
            for span_id, out, err in pool.map(one, todo[n : n + batch]):
                if out is None:
                    errors += 1
                    log(f"{span_id} {err[:200]}")
                    continue
                spent += out["cost"] or 0
                if out["model"] != JEV_SNAPSHOT:
                    stopped = f"answer from {out['model']}, expected {JEV_SNAPSHOT}"
                    continue
                row = {"span_id": span_id, **out, "labelled_at": datetime.now(UTC).isoformat()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            log(f"{min(n + batch, len(todo))}/{len(todo)} USD {spent:.4f}")
            if stopped:
                break
    labels = {r["span_id"]: r["pred"] for r in _read_jsonl(path)}
    return {
        "labelled": len(labels),
        "routine": sum(v == ROUTINE for v in labels.values()),
        "errors": errors,
        "usd": round(spent, 4),
        "stopped": stopped,
        "parquet": str(write_parquet(run_dir)) if labels else None,
    }
