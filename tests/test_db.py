"""Postgres loader: runs only when the local compose database answers."""

from __future__ import annotations

import pytest

from caselaw_extraction import db, graph
from caselaw_extraction.store import DEFAULT_DSN, DuckDBStore, PostgresStore


def _postgres_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DEFAULT_DSN, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _postgres_available(), reason="no Postgres on :5433")


def test_load_run_and_query_matches_duckdb(synthetic_run):
    runs_dir, name = synthetic_run
    counts = db.load_run(name, DEFAULT_DSN, runs_dir=runs_dir)
    assert counts["decision"] == 3 and counts["citation"] > 0
    assert counts["centrality"] == 14  # 7 nodes in each of the two variants
    spans = DuckDBStore(runs_dir / name).query(
        "SELECT count(DISTINCT span_id) AS n FROM citation WHERE kind IN ('bge', 'docket')"
    )[0]["n"]
    assert counts["citation_treatment"] == spans  # every bge and docket citation span
    try:
        pg, duck = PostgresStore(DEFAULT_DSN, name), DuckDBStore(runs_dir / name)
        assert graph.top_statutes(pg, 5) == graph.top_statutes(duck, 5)
        assert [r["node"] for r in graph.central_decisions(pg, 7)] == [
            r["node"] for r in graph.central_decisions(duck, 7)
        ]
        for variant in graph.VARIANTS:
            assert graph.central_decisions(pg, 7, variant=variant) == graph.central_decisions(
                duck, 7, variant=variant
            )
        assert graph.trend_by_year(pg, True) == graph.trend_by_year(duck, True)
        pg_years = [(r["year"], r["decisions"]) for r in graph.trend_by_year(pg)]
        assert pg_years == [(2021, 1), (2022, 1), (2023, 1)]
        # a second load replaces, it does not duplicate
        assert db.load_run(name, DEFAULT_DSN, runs_dir=runs_dir)["decision"] == 3
        assert pg.query("SELECT count(*) AS n FROM decision WHERE run_id = ?", (name,))[0]["n"] == 3
        pg.close()
        duck.close()
    finally:
        with db.connect(DEFAULT_DSN) as con:
            con.execute("DELETE FROM extraction_run WHERE run_id = %s", (name,))
            con.commit()


def test_load_texts_is_idempotent_and_served(synthetic_run):
    runs_dir, name = synthetic_run
    db.load_run(name, DEFAULT_DSN, runs_dir=runs_dir)
    assert db.load_texts(runs_dir / "texts.parquet", DEFAULT_DSN) == 3
    assert db.load_texts(runs_dir / "texts.parquet", DEFAULT_DSN) == 3
    pg = PostgresStore(DEFAULT_DSN, name)
    try:
        rows = pg.query("SELECT text FROM decision_text WHERE decision_id = ?", ("bger_4A_1_2021",))
        assert rows and "Art. 8 ZGB" in rows[0]["text"]
        assert db.table_counts(DEFAULT_DSN)["decision_text"] >= 3
    finally:
        pg.close()
