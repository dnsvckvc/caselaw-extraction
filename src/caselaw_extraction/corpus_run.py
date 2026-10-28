"""Full-corpus extraction: every decision through one extractor and the entity-linking stage.

A run writes `data/runs/<name>/`:

    decisions.parquet   one row per decision: metadata, predicted outcome, span counts
    spans.parquet       one row per span that survived linking
    citations.parquet   one row per linked key; a statute chain span yields one row per article
    run.json            extractor, counts, drop reasons, wall time, workers

The regex extractor runs under Dask (one process per core); the GBERT extractor runs in one
process on the GPU, because a token classifier does not gain from CPU processes. Both produce
the same three tables, so the database loader, the graph and the API do not know which
extractor made a run.
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from caselaw_extraction import regex_extractor as rx
from caselaw_extraction.fedlex import load_code_map
from caselaw_extraction.gold import Decision, dedupe
from caselaw_extraction.ingest import CORPUS_PATH
from caselaw_extraction.linking import REASONS, link_spans

RUNS_DIR = Path("data/runs")
CORPUS_COLUMNS = (
    "decision_id",
    "docket_number",
    "decision_date",
    "chamber_text",
    "legal_area",
    "outcome",
    "full_text",
    "text_length",
    "source_url",
)
KINDS = ("statute", "bge", "docket")
_BGE_KEY_RE = re.compile(r"^BGE (\d{1,3}) ([IVab]+) (\d{1,4})$")

DECISION_SCHEMA = pa.schema(
    [
        ("decision_id", pa.string()),
        ("docket_number", pa.string()),
        ("decision_date", pa.string()),
        ("year", pa.int32()),
        ("chamber", pa.string()),
        ("legal_area", pa.string()),
        ("outcome_dataset", pa.string()),
        ("outcome", pa.string()),
        ("text_length", pa.int32()),
        ("source_url", pa.string()),
        ("n_spans", pa.int32()),
        ("n_dropped", pa.int32()),
    ]
)
SPAN_SCHEMA = pa.schema(
    [
        ("span_id", pa.string()),
        ("decision_id", pa.string()),
        ("start", pa.int32()),
        ("end", pa.int32()),
        ("label", pa.string()),
        ("text", pa.string()),
    ]
)
CITATION_SCHEMA = pa.schema(
    [
        ("span_id", pa.string()),
        ("decision_id", pa.string()),
        ("kind", pa.string()),
        ("key", pa.string()),
        ("code", pa.string()),
        ("sr", pa.string()),
        ("article", pa.string()),
        ("target_decision_id", pa.string()),
    ]
)


@dataclass
class Tables:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    dropped: Counter = field(default_factory=Counter)

    def extend(self, other: Tables) -> None:
        self.decisions += other.decisions
        self.spans += other.spans
        self.citations += other.citations
        self.dropped += other.dropped


# --- corpus access --------------------------------------------------------------------------------


def load_corpus(
    corpus: Path = CORPUS_PATH, ids: Iterable[str] | None = None, limit: int | None = None
) -> list[dict[str, Any]]:
    """Corpus rows as dicts, ordered by date then docket as the corpus file is."""
    table = pq.read_table(corpus, columns=list(CORPUS_COLUMNS))
    rows = table.to_pylist()
    if ids is not None:
        wanted = set(ids)
        rows = [r for r in rows if r["decision_id"] in wanted]
    if limit is not None:
        rows = rows[:limit]
    return rows


def decision_id_of_docket(docket_key: str) -> str:
    """`4A_12_2020` (normalised file number) -> `bger_4A_12_2020` (corpus decision id)."""
    return f"bger_{docket_key}"


# --- one decision -> rows -------------------------------------------------------------------------


def flatten(
    rec: dict[str, Any], dec: Decision, code_map: dict[str, str], corpus_ids: set[str]
) -> Tables:
    """Link the spans of one decision and turn them into table rows."""
    did = rec["decision_id"]
    kept, dropped = link_spans(dec.text, did, dec.spans, code_map)
    out = Tables(dropped=Counter(dropped))
    for s in kept:
        span_id = f"{did}:{s['start']}:{s['end']}:{s['label']}"
        out.spans.append(
            {
                "span_id": span_id,
                "decision_id": did,
                "start": s["start"],
                "end": s["end"],
                "label": s["label"],
                "text": s["text"],
            }
        )
        link = s.get("link")
        if s["label"] == "STATUTE":
            for item in link:
                out.citations.append(
                    {
                        "span_id": span_id,
                        "decision_id": did,
                        "kind": "statute",
                        "key": f"{item['code']} {item['article']}",
                        "code": item["code"],
                        "sr": item["sr"],
                        "article": item["article"],
                        "target_decision_id": None,
                    }
                )
        elif s["label"] == "BGE":
            out.citations.append(
                {
                    "span_id": span_id,
                    "decision_id": did,
                    "kind": "bge",
                    "key": link,
                    "code": None,
                    "sr": None,
                    "article": None,
                    "target_decision_id": None,
                }
            )
        elif s["label"] == "DOCKET":
            target = decision_id_of_docket(link)
            out.citations.append(
                {
                    "span_id": span_id,
                    "decision_id": did,
                    "kind": "docket",
                    "key": link,
                    "code": None,
                    "sr": None,
                    "article": None,
                    "target_decision_id": target if target in corpus_ids else None,
                }
            )
    out.decisions.append(
        {
            "decision_id": did,
            "docket_number": rec["docket_number"],
            "decision_date": rec["decision_date"],
            "year": int(rec["decision_date"][:4]),
            "chamber": rec["chamber_text"],
            "legal_area": rec["legal_area"],
            "outcome_dataset": rec["outcome"],
            "outcome": dec.outcome,
            "text_length": rec["text_length"],
            "source_url": rec["source_url"],
            "n_spans": len(kept),
            "n_dropped": sum(dropped.values()),
        }
    )
    return out


def regex_decision(rec: dict[str, Any], code_map: dict[str, str]) -> Decision:
    ex = rx.extract(rec["decision_id"], rec["full_text"], code_map)
    spans = dedupe(
        [
            {"start": s.start, "end": s.end, "label": s.label.value, "text": s.text}
            for s in ex.all_spans()
        ]
    )
    return Decision(rec["decision_id"], rec["full_text"], ex.outcome.value, spans)


def regex_partition(
    recs: list[dict[str, Any]], corpus_ids: set[str], code_map: dict[str, str] | None = None
) -> list[Tables]:
    """One Dask partition: regex, then linking, for a list of corpus rows."""
    code_map = code_map or load_code_map()
    out = Tables()
    for rec in recs:
        out.extend(flatten(rec, regex_decision(rec, code_map), code_map, corpus_ids))
    return [out]


def regex_partition_file(
    path: Path, corpus_ids: set[str], code_map: dict[str, str] | None = None
) -> Tables:
    """One Dask task: read one partition file in the worker, then `regex_partition`."""
    recs = pq.read_table(path).to_pylist()
    return regex_partition(recs, corpus_ids, code_map)[0]


PARTITIONS_DIR = Path("data/interim/partitions")


def write_partitions(rows: list[dict[str, Any]], npartitions: int, out_dir: Path) -> list[Path]:
    """Split the corpus rows into `npartitions` Parquet files that the workers read themselves
    (Dask best practice: the task graph carries paths, not the texts). Rewritten when the row
    set or the partition count changes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = out_dir / "manifest.json"
    ids = [r["decision_id"] for r in rows]
    key = {"n": len(ids), "npartitions": npartitions, "first": ids[:1], "last": ids[-1:]}
    files = sorted(out_dir.glob("part-*.parquet"))
    if stamp.exists() and json.loads(stamp.read_text()) == key and len(files) == npartitions:
        return files
    for f in files:
        f.unlink()
    size = -(-len(rows) // npartitions)
    files = []
    for i in range(npartitions):
        chunk = rows[i * size : (i + 1) * size]
        if not chunk:
            break
        f = out_dir / f"part-{i:04d}.parquet"
        pq.write_table(pa.Table.from_pylist(chunk), f, compression="zstd")
        files.append(f)
    stamp.write_text(json.dumps(key))
    return files


# --- the run --------------------------------------------------------------------------------------


def _write(tables: Tables, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(tables.decisions, schema=DECISION_SCHEMA),
        out_dir / "decisions.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(tables.spans, schema=SPAN_SCHEMA),
        out_dir / "spans.parquet",
        compression="zstd",
    )
    pq.write_table(
        pa.Table.from_pylist(tables.citations, schema=CITATION_SCHEMA),
        out_dir / "citations.parquet",
        compression="zstd",
    )


def run_regex(
    rows: list[dict[str, Any]], workers: int | None, scheduler: str
) -> tuple[Tables, dict[str, Any]]:
    """Regex over `rows` with Dask. scheduler: "distributed" (LocalCluster, one process per
    worker), "processes" (multiprocessing pool) or "sync" (one process; tests)."""
    import dask
    import dask.bag as db

    code_map = load_code_map()
    corpus_ids = {r["decision_id"] for r in rows}
    workers = 1 if scheduler == "sync" else (workers or os.cpu_count() or 1)
    npartitions = max(1, min(len(rows), workers * 4))
    info: dict[str, Any] = {"workers": workers, "npartitions": npartitions, "scheduler": scheduler}
    t0 = time.perf_counter()
    if scheduler == "sync":
        bag = db.from_sequence(rows, npartitions=npartitions).map_partitions(
            regex_partition, corpus_ids, code_map
        )
    else:
        files = write_partitions(rows, npartitions, PARTITIONS_DIR / f"n{len(rows)}-p{npartitions}")
        info["partition_seconds"] = round(time.perf_counter() - t0, 2)
        bag = db.from_sequence(files, npartitions=len(files)).map(
            regex_partition_file, corpus_ids, code_map
        )
    if scheduler == "distributed":
        from dask.distributed import Client, LocalCluster

        with (
            LocalCluster(
                n_workers=workers, threads_per_worker=1, processes=True, dashboard_address=None
            ) as cluster,
            Client(cluster) as client,
        ):
            info["dashboard"] = client.dashboard_link
            parts = bag.compute()
    elif scheduler == "processes":
        parts = bag.compute(scheduler="processes", num_workers=workers)
    else:
        with dask.config.set(scheduler="synchronous"):
            parts = bag.compute()
    info["extract_seconds"] = time.perf_counter() - t0
    tables = Tables()
    for p in parts:
        tables.extend(p)
    return tables, info


def run_gbert(
    rows: list[dict[str, Any]],
    model_dir: Path,
    outcome_dir: Path | None,
    decode: str = "viterbi",
    chunk: int = 100,
) -> tuple[Tables, dict[str, Any]]:
    """GBERT token classifier (and outcome classifier when `outcome_dir` exists) in one process."""
    from caselaw_extraction import transformer_extractor as tx

    code_map = load_code_map()
    corpus_ids = {r["decision_id"] for r in rows}
    tok, mdl = tx.load_saved(model_dir)
    otok = omdl = None
    if outcome_dir is not None and outcome_dir.exists():
        otok, omdl = tx.load_saved_outcome(outcome_dir)
    info: dict[str, Any] = {
        "model_dir": str(model_dir),
        "outcome_dir": str(outcome_dir) if omdl is not None else None,
        "decode": decode,
        "device": str(tx.device()),
        "workers": 1,
        "scheduler": "single-process",
    }
    tables = Tables()
    t0 = time.perf_counter()
    for i in range(0, len(rows), chunk):
        recs = rows[i : i + chunk]
        decs = [Decision(r["decision_id"], r["full_text"]) for r in recs]
        tx.predict_token_classifier(tok, mdl, decs, decode=decode)
        if omdl is not None:
            tx.predict_outcome(otok, omdl, decs)
        for rec, dec in zip(recs, decs, strict=True):
            tables.extend(flatten(rec, dec, code_map, corpus_ids))
    info["extract_seconds"] = time.perf_counter() - t0
    return tables, info


def run_corpus(
    name: str,
    extractor: str = "regex",
    *,
    limit: int | None = None,
    ids: Iterable[str] | None = None,
    workers: int | None = None,
    scheduler: str = "distributed",
    model_dir: Path | None = None,
    outcome_dir: Path | None = None,
    decode: str = "viterbi",
    corpus: Path = CORPUS_PATH,
    runs_dir: Path = RUNS_DIR,
) -> dict[str, Any]:
    """Run one extractor over the corpus (or a subset) and write the run directory."""
    t_start = time.perf_counter()
    rows = load_corpus(corpus, ids=ids, limit=limit)
    if extractor == "regex":
        tables, info = run_regex(rows, workers, scheduler)
    elif extractor == "gbert":
        if model_dir is None:
            raise ValueError("gbert needs --model-dir")
        tables, info = run_gbert(rows, model_dir, outcome_dir, decode=decode)
    else:
        raise ValueError(f"unknown extractor {extractor!r} (regex | gbert)")
    out_dir = runs_dir / name
    _write(tables, out_dir)
    by_label = Counter(s["label"] for s in tables.spans)
    by_kind = Counter(c["kind"] for c in tables.citations)
    n_before = len(tables.spans) + sum(tables.dropped.values())
    run = {
        "name": name,
        "extractor": extractor,
        "extractor_version": rx.VERSION if extractor == "regex" else info.get("model_dir"),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus": str(corpus),
        "n_decisions": len(tables.decisions),
        "n_spans_before_linking": n_before,
        "n_spans": len(tables.spans),
        "dropped": {r: tables.dropped.get(r, 0) for r in REASONS},
        "spans_by_label": dict(sorted(by_label.items())),
        "citations_by_kind": {k: by_kind.get(k, 0) for k in KINDS},
        "docket_targets_in_corpus": sum(
            1 for c in tables.citations if c["target_decision_id"] is not None
        ),
        "outcomes": dict(Counter(d["outcome"] for d in tables.decisions)),
        "wall_seconds": round(time.perf_counter() - t_start, 2),
        "cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        **info,
    }
    run["extract_seconds"] = round(run["extract_seconds"], 2)
    (out_dir / "run.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    return run


def load_run(name: str, runs_dir: Path = RUNS_DIR) -> dict[str, Any]:
    return json.loads((runs_dir / name / "run.json").read_text())


def format_run(run: dict[str, Any]) -> str:
    lines = [
        f"run {run['name']}: {run['extractor']} ({run['extractor_version']}) over "
        f"{run['n_decisions']} decisions in {run['wall_seconds']} s "
        f"(extract {run['extract_seconds']} s, {run['workers']} worker(s), {run['scheduler']})",
        f"  spans {run['n_spans_before_linking']} -> {run['n_spans']} after linking; dropped "
        + ", ".join(f"{k} {v}" for k, v in run["dropped"].items()),
        "  by label: " + ", ".join(f"{k} {v}" for k, v in run["spans_by_label"].items()),
        "  citations: "
        + ", ".join(f"{k} {v}" for k, v in run["citations_by_kind"].items())
        + f"; docket targets in corpus {run['docket_targets_in_corpus']}",
        "  outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(run["outcomes"].items())),
    ]
    return "\n".join(lines)
