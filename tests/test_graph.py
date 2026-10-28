"""Citation graph and the three headline analyses on the synthetic run."""

from __future__ import annotations

import json

from caselaw_extraction import graph
from caselaw_extraction.store import DuckDBStore


def test_top_statutes_counts_citing_decisions_not_mentions(synthetic_run):
    runs_dir, name = synthetic_run
    store = DuckDBStore(runs_dir / name)
    top = graph.top_statutes(store, 3)
    assert top[0]["key"] == "BGG 66"  # cited by all three rulings
    assert top[0]["decisions"] == 3
    by_key = {r["key"]: r for r in graph.top_statutes(store, 50)}
    assert by_key["ZGB 8"]["decisions"] == 2
    assert by_key["OR 97"]["decisions"] == 2
    assert graph.top_statutes(store, 5, code="OR")[0]["code"] == "OR"
    in_2021 = {r["key"] for r in graph.top_statutes(store, 50, year=2021)}
    assert "ZGB 8" in in_2021 and "OR 41" not in in_2021
    store.close()


def test_trend_by_year_has_one_row_per_year(synthetic_run):
    runs_dir, name = synthetic_run
    store = DuckDBStore(runs_dir / name)
    rows = graph.trend_by_year(store)
    assert [r["year"] for r in rows] == [2021, 2022, 2023]
    assert all(r["decisions"] == 1 for r in rows)
    r2021 = rows[0]
    assert r2021["bge_per_decision"] == 2.0  # BGE 140 III 86 and 140 III 115
    # BGE volume 140 is 2014; cited in 2021 -> age 7
    assert r2021["mean_bge_age"] == 7.0
    share = graph.code_share_by_year(store)
    assert float(share[0]["bgg"]) == 100.0
    store.close()


def test_centrality_ranks_the_most_cited_node_first(synthetic_run):
    runs_dir, name = synthetic_run
    store = DuckDBStore(runs_dir / name)
    g = graph.build_graph(store)
    assert g.number_of_nodes() == 3 + 3 + 1  # decisions, BGE keys, one external docket
    top = graph.central_decisions(store, 3, by="in_degree")
    assert top[0]["in_degree"] == 2
    assert top[0]["key"] in {"BGE 142 III 364", "BGE 140 III 86", "bger_4A_1_2021"}
    corpus = graph.central_decisions(store, 5, by="in_degree", kind="decision")
    assert corpus[0]["decision_id"] == "bger_4A_1_2021"
    assert corpus[0]["in_degree"] == 2
    pr = graph.central_decisions(store, 1, by="pagerank")
    assert pr[0]["rank_pagerank"] == 1
    store.close()


def test_analyses_json_is_written(synthetic_run):
    runs_dir, name = synthetic_run
    a = json.loads((runs_dir / name / "analyses.json").read_text())
    assert set(a) >= {"graph", "top_statutes", "trend_by_year", "central_pagerank"}
    assert a["graph"]["edges"] == 8  # 3 + 3 + 2 citation edges
    text = graph.format_analyses(a)
    assert "BGG 66" in text and "Most central" in text


def test_compare_runs_identical(synthetic_run):
    runs_dir, name = synthetic_run
    c = graph.compare_runs(name, name, runs_dir=runs_dir)
    for kind in ("statute", "bge", "docket"):
        assert c["citations"][kind]["jaccard"] == 1.0
        assert c["citations"][kind][f"only_{name}"] == 0
    assert c["top20_statutes_shared"] == min(
        20, len(graph.top_statutes(DuckDBStore(runs_dir / name), 20))
    )
    assert c["top20_central_shared"] == 7
    assert "Jaccard" in graph.format_comparison(c)
