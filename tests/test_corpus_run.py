"""The full-corpus pipeline (week 3): regex + linking into the three run tables."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from caselaw_extraction import corpus_run
from caselaw_extraction.ingest import CORPUS_PATH


def _q(path: Path, sql: str):
    return duckdb.connect().execute(sql.replace("{T}", f"read_parquet('{path}')")).fetchall()


def test_run_writes_three_tables_and_metadata(synthetic_run):
    runs_dir, name = synthetic_run
    run_dir = runs_dir / name
    assert {p.name for p in run_dir.iterdir()} >= {
        "decisions.parquet",
        "spans.parquet",
        "citations.parquet",
        "run.json",
    }
    meta = json.loads((run_dir / "run.json").read_text())
    assert meta["n_decisions"] == 3
    assert meta["extractor"] == "regex"
    assert meta["extractor_version"] == "regex-v0.4"
    assert meta["n_spans"] == meta["n_spans_before_linking"] - sum(meta["dropped"].values())


def test_statute_citations_are_linked_to_fedlex(synthetic_run):
    runs_dir, name = synthetic_run
    rows = _q(
        runs_dir / name / "citations.parquet",
        "SELECT key, sr FROM {T} WHERE kind = 'statute' AND decision_id = 'bger_4A_1_2021' ORDER BY key",
    )
    assert ("ZGB 8", "210") in rows
    assert ("OR 97", "220") in rows
    assert ("BGG 66", "173.110") in rows


def test_short_bge_citation_gets_its_own_key(synthetic_run):
    runs_dir, name = synthetic_run
    keys = {
        r[0]
        for r in _q(
            runs_dir / name / "citations.parquet",
            "SELECT key FROM {T} WHERE kind = 'bge' AND decision_id = 'bger_4A_1_2021'",
        )
    }
    assert keys == {"BGE 140 III 86", "BGE 140 III 115"}


def test_docket_citation_inside_corpus_gets_a_target(synthetic_run):
    runs_dir, name = synthetic_run
    rows = _q(
        runs_dir / name / "citations.parquet",
        "SELECT decision_id, key, target_decision_id FROM {T} WHERE kind = 'docket' ORDER BY 1",
    )
    assert ("bger_5A_2_2022", "4A_1_2021", "bger_4A_1_2021") in rows
    assert ("bger_4A_3_2023", "4A_1_2021", "bger_4A_1_2021") in rows
    # cited decision outside the corpus: no target
    assert ("bger_4A_1_2021", "4A_12_2020", None) in rows


def test_outcomes_and_counts(synthetic_run):
    runs_dir, name = synthetic_run
    rows = dict(_q(runs_dir / name / "decisions.parquet", "SELECT decision_id, outcome FROM {T}"))
    assert rows == {
        "bger_4A_1_2021": "dismissed",
        "bger_5A_2_2022": "inadmissible",
        "bger_4A_3_2023": "approved",
    }
    n = _q(runs_dir / name / "decisions.parquet", "SELECT sum(n_spans) FROM {T}")[0][0]
    assert n == _q(runs_dir / name / "spans.parquet", "SELECT count(*) FROM {T}")[0][0]


def test_contract_clause_is_not_a_citation(synthetic_run):
    runs_dir, name = synthetic_run
    texts = {r[0] for r in _q(runs_dir / name / "spans.parquet", "SELECT text FROM {T}")}
    assert not any("Ziff. 4" in t for t in texts)


def test_partition_files_are_reused(tmp_path, synthetic_corpus):
    rows = corpus_run.load_corpus(synthetic_corpus)
    out = tmp_path / "parts"
    files = corpus_run.write_partitions(rows, 2, out)
    assert [f.name for f in files] == ["part-0000.parquet", "part-0001.parquet"]
    mtimes = [f.stat().st_mtime_ns for f in files]
    assert corpus_run.write_partitions(rows, 2, out) == files
    assert [f.stat().st_mtime_ns for f in files] == mtimes  # not rewritten
    assert len(corpus_run.write_partitions(rows, 3, out)) == 3  # a new count rewrites


@pytest.mark.skipif(not CORPUS_PATH.exists(), reason="needs the ingested corpus")
def test_integration_twenty_real_decisions_under_dask_processes(tmp_path):
    """The plan's integration test: 20 decisions through Dask with worker processes."""
    run = corpus_run.run_corpus(
        "it20", "regex", limit=20, workers=2, scheduler="processes", runs_dir=tmp_path
    )
    assert run["n_decisions"] == 20
    assert run["n_spans"] > 100
    assert run["citations_by_kind"]["statute"] > 0
    assert run["citations_by_kind"]["bge"] > 0
    assert set(run["dropped"]) == set(corpus_run.REASONS)
