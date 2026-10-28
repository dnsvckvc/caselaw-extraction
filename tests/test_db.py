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
    assert counts["decision"] == 3 and counts["citation"] > 0 and counts["centrality"] == 7
    try:
        pg, duck = PostgresStore(DEFAULT_DSN, name), DuckDBStore(runs_dir / name)
        assert graph.top_statutes(pg, 5) == graph.top_statutes(duck, 5)
        assert [r["node"] for r in graph.central_decisions(pg, 7)] == [
            r["node"] for r in graph.central_decisions(duck, 7)
        ]
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
