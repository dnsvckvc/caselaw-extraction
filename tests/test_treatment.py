"""The Jev 1.14 labelling job (no network: `fake_jev` stands in) and old run directories."""

from __future__ import annotations

import json
import shutil

import pyarrow.compute as pc
import pyarrow.parquet as pq

from caselaw_extraction import graph, treatment
from caselaw_extraction.store import DuckDBStore
from tests.conftest import fake_jev


def test_window_marks_the_citation():
    text = "a" * 500 + "BGE 140 III 86" + " b\n\n c " + "z" * 300
    w = treatment.window(text, 500, 514)
    assert w.startswith("a" * 400) and "[[BGE 140 III 86]] b c " in w
    assert len(w) == 400 + len("[[BGE 140 III 86]]") + 200 - 2  # a whitespace run becomes one space


def test_label_run_resumes_and_writes_parquet(synthetic_run, tmp_path):
    runs_dir, name = synthetic_run
    run = tmp_path / name
    shutil.copytree(runs_dir / name, run)
    (run / treatment.JSONL).unlink()
    texts = runs_dir / "texts.parquet"
    calls: list[str] = []

    def counting(window: str, key: str) -> dict:
        calls.append(window)
        return fake_jev(window, key)

    first = treatment.label_run(run, texts, "k", limit=3, call=counting, log=str)
    assert first["labelled"] == 3 and len(calls) == 3
    rest = treatment.label_run(run, texts, "k", call=counting, log=str)
    n = len(treatment.citation_windows(run, texts))
    assert rest["labelled"] == n and len(calls) == n  # no span is sent twice
    assert rest["routine"] == 1 and rest["errors"] == 0 and rest["stopped"] == ""
    table = pq.read_table(run / treatment.PARQUET)
    assert table.num_rows == n and set(table.schema.names) == set(treatment.TREATMENT_SCHEMA.names)
    routine = table.filter(pc.equal(table["label"], treatment.ROUTINE)).to_pylist()
    assert routine[0]["p"] == 0.9 and json.loads(routine[0]["probabilities"])["routine_standard"]


def test_label_run_stops_on_another_snapshot_and_at_the_cap(synthetic_run, tmp_path):
    runs_dir, name = synthetic_run
    run = tmp_path / name
    shutil.copytree(runs_dir / name, run)
    (run / treatment.JSONL).unlink()
    texts = runs_dir / "texts.parquet"

    def other_snapshot(window: str, key: str) -> dict:
        return {**fake_jev(window, key), "model": "typesafe/jev-1.15-20270101"}

    out = treatment.label_run(run, texts, "k", call=other_snapshot, log=str)
    assert out["labelled"] == 0 and "jev-1.15" in out["stopped"]

    out = treatment.label_run(run, texts, "k", max_cost=0.0, call=fake_jev, log=str)
    assert out["labelled"] == 0 and out["stopped"].startswith("spending cap")


def test_run_without_labels_or_variant_column(synthetic_run, tmp_path):
    """A run written before the selector: no treatment.parquet, centrality without `variant`."""
    runs_dir, name = synthetic_run
    run = tmp_path / name
    shutil.copytree(runs_dir / name, run)
    (run / treatment.PARQUET).unlink()
    cent = pq.read_table(run / "centrality.parquet")
    cent = cent.filter(pc.equal(cent["variant"], "all")).drop_columns(["variant"])
    pq.write_table(cent, run / "centrality.parquet")
    store = DuckDBStore(run)
    try:
        assert store.query("SELECT count(*) AS n FROM citation_treatment")[0]["n"] == 0
        assert graph.central_decisions(store, 3)[0]["in_degree"] == 2
        assert graph.trend_by_year(store, True) == graph.trend_by_year(store)
        assert graph.build_graph(store, True).number_of_edges() == (
            graph.build_graph(store).number_of_edges()
        )
    finally:
        store.close()
