"""Pilot, subproject 3: the outcome of a decision with Jev 1.14, on the gold set and on the disputed decisions.

    uv run python scripts/jev/outcome.py sample            # data/gold/outcome/items.jsonl
    op run --env-file scripts/jev/openrouter.op.env -- \
      uv run python scripts/jev/outcome.py predict dev     # the prompt is checked on dev only
    op run --env-file scripts/jev/openrouter.op.env -- \
      uv run python scripts/jev/outcome.py predict test    # one run after the prompt is frozen
    uv run python scripts/jev/outcome.py report <dev|test>

Two sets. `gold`: the 350 gold decisions (batches 1 to 3). `disputed`: the decisions where regex v0.4 and
gbert-b13-s0 give different outcomes and that are not in the gold set (153), labelled in
data/gold/outcome/disputed.jsonl. Dev is 40 random gold decisions; test is the other 310 and all disputed ones.
Jev reads the same ruling section as the two extractors (`dispositiv`, 1,500 characters).
See docs/jev-outcome.md.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
from sklearn.metrics import accuracy_score, f1_score

from caselaw_extraction import tracking
from caselaw_extraction.gold import dispositiv

GOLD = Path("data/gold")
ITEMS = GOLD / "outcome" / "items.jsonl"
DISPUTED = GOLD / "outcome" / "disputed.jsonl"
OUT = Path("data/pred/outcome")
JEV = "typesafe/jev-1.14"
URL = "https://openrouter.ai/api/alpha/decisions"
MAX_COST_USD = 1.0
WORKERS = 8
SCORED = ("approved", "partial_approval", "dismissed", "inadmissible", "moot")

INSTRUCTIONS = (
    "Der Text ist das Dispositiv eines Urteils des Schweizerischen Bundesgerichts. Wie entscheidet das "
    "Bundesgericht über die Beschwerde oder das Gesuch, um das es im Verfahren geht? Regeln: Ziffern zu "
    "Nebenpunkten zählen nicht: unentgeltliche Rechtspflege, Kosten, Parteientschädigung, Ausstand, Sistierung, "
    "Vereinigung, aufschiebende Wirkung, Fristerstreckung, Bestellung eines Anwalts. Wird auf die Beschwerde in "
    "Zivilsachen nicht eingetreten und die subsidiäre Verfassungsbeschwerde beurteilt, zählt die "
    "Verfassungsbeschwerde. Wird auf die Beschwerde einer Partei nicht eingetreten und die einer anderen "
    "beurteilt, zählt die beurteilte. Wird ein Teil abgeschrieben und der Rest beurteilt, zählt der Rest, "
    "ausser der Rest betrifft nur Kosten."
)
CRITERIA = {
    "approved": "Die Beschwerde oder das Gesuch (Revision, Erläuterung, Berichtigung, Fristwiederherstellung) wird gutgeheissen, auch 'gutgeheissen, soweit darauf einzutreten ist'. Auch: der Entscheid wird aufgehoben und die Sache zurückgewiesen, ohne dass die Beschwerde im Übrigen abgewiesen wird.",
    "partial_approval": "Die Beschwerde wird teilweise gutgeheissen, oder ein Teil wird gutgeheissen und im Übrigen abgewiesen oder nicht eingetreten. Auch bei mehreren Beschwerden, wenn eine gutgeheissen und eine andere abgewiesen wird.",
    "dismissed": "Die Beschwerde oder das Gesuch wird abgewiesen, auch 'abgewiesen, soweit darauf einzutreten ist'.",
    "inadmissible": "Auf die Beschwerde oder das Gesuch wird nicht eingetreten.",
    "moot": "Das Verfahren wird als gegenstandslos oder erledigt abgeschrieben, zum Beispiel nach Rückzug oder Vergleich.",
}


def sample() -> None:
    labels: dict[str, tuple[str, str]] = {}
    for b in (1, 2, 3):
        for r in map(json.loads, (GOLD / f"batch{b}.gold.jsonl").read_text().splitlines()):
            labels[r["decision_id"]] = (r["outcome"], f"gold_batch{b}")
    for r in map(json.loads, DISPUTED.read_text().splitlines()):
        assert r["decision_id"] not in labels
        labels[r["decision_id"]] = (r["outcome"], "disputed")
    rows = duckdb.sql("""
        SELECT r.decision_id, r.outcome, g.outcome, t.text
        FROM 'data/runs/regex-v0.4/decisions.parquet' r
        JOIN 'data/runs/gbert-b13-s0/decisions.parquet' g USING (decision_id)
        JOIN 'data/runs/texts.parquet' t USING (decision_id)
        ORDER BY r.decision_id
    """).fetchall()
    rows = [r for r in rows if r[0] in labels]
    assert len(rows) == len(labels)
    gold = sorted(i for i, (_, s) in labels.items() if s != "disputed")
    dev = set(random.Random(0).sample(gold, 40))
    out = [
        {
            "decision_id": r[0],
            "set": "disputed" if labels[r[0]][1] == "disputed" else "gold",
            "source": labels[r[0]][1],
            "part": "dev" if r[0] in dev else "test",
            "label": labels[r[0]][0],
            "regex": r[1],
            "gbert": r[2],
            "text": re.sub(r"\s+", " ", dispositiv(r[3])).strip(),
        }
        for r in rows
    ]
    ITEMS.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
    print(Counter((o["part"], o["set"]) for o in out))


def call_jev(text: str, key: str) -> dict:
    body = {
        "model": JEV,
        "state": {"dispositiv": text},
        "questions": {
            "outcome": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": CRITERIA}
        },
    }
    req = urllib.request.Request(
        URL,
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(5):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.load(r)
            a = out["answers"]["outcome"]
            return {
                "model": out.get("model"),
                "pred": a.get("choice"),
                "confidence": a.get("confidence"),
                "probabilities": a.get("probabilities"),
                "input_tokens": out["usage"]["input_tokens"],
                "cost": out["usage"].get("cost"),
                "latency_s": time.time() - t0,
            }
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
        time.sleep(2**attempt)
    raise AssertionError


def predict(part: str) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    rows = [r for r in map(json.loads, ITEMS.read_text().splitlines()) if r["part"] == part]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"jev-{part}.jsonl"
    done = [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []
    seen = {d["decision_id"] for d in done}
    spent = sum(d["cost"] or 0 for d in done)
    todo = [r for r in rows if r["decision_id"] not in seen]
    errors = 0

    def one(r: dict) -> tuple[dict, dict | None, str]:
        try:
            return r, call_jev(r["text"], key), ""
        except Exception as e:  # noqa: BLE001 - the error is counted and the decision can be rerun
            return r, None, str(e)

    with path.open("a") as f, ThreadPoolExecutor(WORKERS) as pool:
        for n in range(0, len(todo), WORKERS * 5):
            if spent >= MAX_COST_USD:
                print(f"stopped at the spending cap, USD {spent:.4f}")
                break
            for r, out, err in pool.map(one, todo[n : n + WORKERS * 5]):
                if out is None:
                    errors += 1
                    print(r["decision_id"], err[:200])
                    continue
                spent += out["cost"] or 0
                f.write(
                    json.dumps({"decision_id": r["decision_id"], **out}, ensure_ascii=False) + "\n"
                )
            f.flush()
            print(f"{min(n + WORKERS * 5, len(todo))}/{len(todo)} USD {spent:.4f}", flush=True)
    print(f"done, errors {errors}, USD {spent:.4f}")


def _score(y: list[str], p: list[str]) -> dict[str, float]:
    return {
        "n": len(y),
        "accuracy": accuracy_score(y, p),
        "macro_f1": f1_score(y, p, labels=list(SCORED), average="macro", zero_division=0),
    }


def report(part: str) -> None:
    items = [r for r in map(json.loads, ITEMS.read_text().splitlines()) if r["part"] == part]
    print(
        "left out (not one of the five classes):",
        Counter(r["label"] for r in items if r["label"] not in SCORED),
    )
    items = [r for r in items if r["label"] in SCORED]
    path = OUT / f"jev-{part}.jsonl"
    jev = (
        {r["decision_id"]: r for r in map(json.loads, path.read_text().splitlines())}
        if path.exists()
        else {}
    )
    if missing := [r["decision_id"] for r in items if r["decision_id"] not in jev]:
        print(f"jev: {len(missing)} decisions without an answer, counted as wrong")
    for r in items:
        r["jev"] = jev.get(r["decision_id"], {}).get("pred") or "no_answer"
        probs = jev.get(r["decision_id"], {}).get("probabilities")
        r["top"] = max(probs.values()) if probs else 0.0
    results = {}
    for name, sub in (
        ("gold", [r for r in items if r["set"] == "gold"]),
        ("gold_batch2", [r for r in items if r["source"] == "gold_batch2"]),
        ("disputed", [r for r in items if r["set"] == "disputed"]),
    ):
        if not sub:
            continue
        y = [r["label"] for r in sub]
        res = {w: _score(y, [r[w] for r in sub]) for w in ("regex", "gbert", "jev")}
        results[name] = res
        print(f"\n{name}: labels {dict(Counter(y))}")
        for w, m in res.items():
            print(w, {k: round(v, 3) for k, v in m.items()})
        top = np.array([r["top"] for r in sub])
        right = np.array([r["jev"] == r["label"] for r in sub])
        print("jev mean top probability", round(float(top.mean()), 3))
        print("jev top probability | coverage | accuracy")
        for t in (0.8, 0.9, 0.95):
            k = top >= t
            print(
                f">= {t} | {k.mean():.3f} ({k.sum()}) | {right[k].mean() if k.any() else float('nan'):.3f}"
            )
        bins = np.minimum((top * 10).astype(int), 9)
        ece = sum(
            (bins == b).mean() * abs(right[bins == b].mean() - top[bins == b].mean())
            for b in range(10)
            if (bins == b).any()
        )
        print("jev ece_top", round(float(ece), 3))
        print(
            "jev confusions",
            Counter((r["label"], r["jev"]) for r in sub if r["jev"] != r["label"]).most_common(8),
        )
        if name == "disputed":
            tie = [r for r in sub if r["jev"] in (r["regex"], r["gbert"])]
            ok = sum(r["jev"] == r["label"] for r in tie)
            print(
                f"tie-break: jev agrees with one of the two in {len(tie)} of {len(sub)}, that label is right in {ok} ({ok / max(len(tie), 1):.3f})"
            )
            print(
                "neither regex nor gbert right:",
                sum(r["label"] not in (r["regex"], r["gbert"]) for r in sub),
            )
    rows = [jev[r["decision_id"]] for r in items if r["decision_id"] in jev]
    if rows:
        print(
            "\nusd",
            round(sum(r["cost"] or 0 for r in rows), 5),
            "tokens in",
            round(float(np.mean([r["input_tokens"] for r in rows])), 1),
            "latency p50",
            round(float(np.median([r["latency_s"] for r in rows])), 3),
            "models",
            sorted({r["model"] for r in rows}),
        )
    if part == "test" and rows:
        with tracking.run("jev-1.14-outcome", {"model": JEV}) as log:
            log.metrics(
                {
                    f"{s}_{w}_{k}": v
                    for s, res in results.items()
                    for w, m in res.items()
                    for k, v in m.items()
                }
            )


if __name__ == "__main__":
    if sys.argv[1] == "sample":
        sample()
    elif sys.argv[1] == "predict":
        predict(sys.argv[2])
    elif sys.argv[1] == "report":
        report(sys.argv[2])
    else:
        raise SystemExit(__doc__)
