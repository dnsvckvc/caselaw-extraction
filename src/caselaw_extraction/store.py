"""One query interface over the run tables, backed by DuckDB (Parquet files of a run directory)
or by Postgres (the loaded database). The graph analyses and the API write their SQL once.

Table names are the same in both backends: `decision`, `span`, `citation`, `centrality`,
`citation_treatment`, `extraction_run`. Placeholders are written as `?`; the Postgres backend
rewrites them to `%s`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from caselaw_extraction.corpus_run import RUNS_DIR

DEFAULT_DSN = "postgresql://caselaw:caselaw@localhost:5433/caselaw"
RUN_TABLES = ("decision", "span", "citation", "centrality")
TEXTS_FILE = "texts.parquet"
_FILES = {
    "decision": "decisions.parquet",
    "span": "spans.parquet",
    "citation": "citations.parquet",
    "centrality": "centrality.parquet",
    "citation_treatment": "treatment.parquet",
}
# Views for tables whose file is optional, so that the SQL runs without them.
_EMPTY = {
    "citation_treatment": "SELECT NULL::VARCHAR AS span_id, NULL::VARCHAR AS label, "
    "NULL::DOUBLE AS p, NULL::VARCHAR AS model WHERE false",
}


class Store:
    backend: str
    run_id: str

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class DuckDBStore(Store):
    """Views over the Parquet files of one run; nothing is copied. The views carry the run_id
    column and the Postgres column names (`start_char`, `end_char`), so one SQL fits both."""

    backend = "duckdb"

    def __init__(self, run_dir: Path) -> None:
        import duckdb

        self.run_dir = Path(run_dir)
        self.run_id = self.run_dir.name.replace("'", "")
        self.con = duckdb.connect()
        for table, fname in _FILES.items():
            path = self.run_dir / fname
            if not path.exists():
                if table in _EMPTY:
                    self.con.execute(
                        f"CREATE VIEW {table} AS SELECT '{self.run_id}' AS run_id, * "
                        f"FROM ({_EMPTY[table]})"
                    )
                continue
            cols = "*"
            if table == "span":
                cols = 'span_id, decision_id, "start" AS start_char, "end" AS end_char, label, text'
            elif table == "citation_treatment":
                cols = "span_id, label, p, model"
            elif table == "centrality" and "variant" not in _columns(path):
                cols = "'all' AS variant, *"  # written before the routine selector
            self.con.execute(
                f"CREATE VIEW {table} AS SELECT '{self.run_id}' AS run_id, {cols} "
                f"FROM read_parquet('{path}')"
            )
        extractor = _extractor_of(self.run_dir).replace("'", "")
        self.con.execute(
            f"CREATE VIEW extraction_run AS SELECT '{self.run_id}' AS run_id, "
            f"'{extractor}' AS extractor"
        )
        # Decision texts are run-independent: `<runs_dir>/texts.parquet` (written by
        # `caselaw texts`), else the run's own copy, else an empty view so the SQL still runs.
        candidates = (self.run_dir.parent / TEXTS_FILE, self.run_dir / TEXTS_FILE)
        texts = next((p for p in candidates if p.exists()), None)
        if texts:
            self.con.execute(
                "CREATE VIEW decision_text AS SELECT decision_id, text "
                f"FROM read_parquet('{texts}')"
            )
        else:
            self.con.execute(
                "CREATE VIEW decision_text AS SELECT NULL::VARCHAR AS decision_id, "
                "NULL::VARCHAR AS text WHERE false"
            )

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cur = self.con.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def close(self) -> None:
        self.con.close()


class PostgresStore(Store):
    """The loaded database; `run_id` selects which extraction run the queries read."""

    backend = "postgres"

    def __init__(self, dsn: str = DEFAULT_DSN, run_id: str = "regex-v0.4") -> None:
        import psycopg
        from psycopg.rows import dict_row

        self.run_id = run_id
        self.con = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.con.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), params)
            return [dict(r) for r in cur.fetchall()]

    def close(self) -> None:
        self.con.close()


def _columns(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    return pq.read_schema(path).names


def _extractor_of(run_dir: Path) -> str:
    import json

    meta = run_dir / "run.json"
    return json.loads(meta.read_text())["extractor"] if meta.exists() else "unknown"


def dsn_from_env() -> str | None:
    """`CASELAW_DSN`, else the content of the file named by `CASELAW_DSN_FILE` (a Compose or
    Docker secret, so the connection string is not in the environment), else None."""
    if os.environ.get("CASELAW_DSN"):
        return os.environ["CASELAW_DSN"]
    path = os.environ.get("CASELAW_DSN_FILE")
    if path:
        return Path(path).read_text().strip()
    return None


def open_store(backend: str | None = None, run: str | None = None, dsn: str | None = None) -> Store:
    """Pick the backend from the arguments, else from `CASELAW_BACKEND`, `CASELAW_RUN` and
    `CASELAW_DSN` / `CASELAW_DSN_FILE` (and `CASELAW_RUNS_DIR` for the Parquet runs); without
    any of them, DuckDB over `data/runs/regex-v0.4`."""
    env_dsn = dsn_from_env()
    backend = backend or os.environ.get("CASELAW_BACKEND") or ("postgres" if env_dsn else "duckdb")
    run = run or os.environ.get("CASELAW_RUN") or "regex-v0.4"
    if backend == "postgres":
        return PostgresStore(dsn or env_dsn or DEFAULT_DSN, run)
    runs_dir = Path(os.environ.get("CASELAW_RUNS_DIR") or RUNS_DIR)
    return DuckDBStore(runs_dir / run)
