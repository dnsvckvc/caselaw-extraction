"""Load a run directory into Postgres with COPY. Schema: `sql/schema.sql` in this package.

A run is loaded as a whole and replaces an earlier load of the same run_id. The run directory
is a local path or an `s3://bucket/prefix` (week 4: the loader runs as a Fargate task and reads
the Parquet from S3 through pyarrow's filesystem layer). The Fedlex code map
fills the `statute` table (abbreviation, SR number) so that the API can name an act.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from pyarrow import fs as pafs

from caselaw_extraction.corpus_run import RUNS_DIR
from caselaw_extraction.store import DEFAULT_DSN

SCHEMA_SQL = Path(__file__).resolve().parent / "sql" / "schema.sql"

# (table, parquet file, parquet column -> db column)
_LOADS = (
    (
        "decision",
        "decisions.parquet",
        {
            "decision_id": "decision_id",
            "docket_number": "docket_number",
            "decision_date": "decision_date",
            "year": "year",
            "chamber": "chamber",
            "legal_area": "legal_area",
            "outcome_dataset": "outcome_dataset",
            "outcome": "outcome",
            "text_length": "text_length",
            "source_url": "source_url",
            "n_spans": "n_spans",
            "n_dropped": "n_dropped",
        },
    ),
    (
        "span",
        "spans.parquet",
        {
            "span_id": "span_id",
            "decision_id": "decision_id",
            "start": "start_char",
            "end": "end_char",
            "label": "label",
            "text": "text",
        },
    ),
    (
        "citation",
        "citations.parquet",
        {
            "span_id": "span_id",
            "decision_id": "decision_id",
            "kind": "kind",
            "key": "key",
            "code": "code",
            "sr": "sr",
            "article": "article",
            "target_decision_id": "target_decision_id",
        },
    ),
    (
        "centrality",
        "centrality.parquet",
        {
            "node": "node",
            "kind": "kind",
            "key": "key",
            "decision_id": "decision_id",
            "in_degree": "in_degree",
            "out_degree": "out_degree",
            "pagerank": "pagerank",
            "rank_pagerank": "rank_pagerank",
            "rank_in_degree": "rank_in_degree",
        },
    ),
)


def connect(dsn: str = DEFAULT_DSN):
    import psycopg

    return psycopg.connect(dsn)


def create_schema(con) -> None:
    con.execute(SCHEMA_SQL.read_text())
    con.commit()


def _copy_rows(cur, table: str, columns: list[str], rows: list[tuple]) -> int:
    cols = ", ".join(columns)
    with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as copy:
        for row in rows:
            copy.write_row(row)
    return len(rows)


def open_run(runs_dir: Path | str, name: str) -> tuple[pafs.FileSystem, str]:
    """Filesystem and base path of `<runs_dir>/<name>`: a local directory or `s3://bucket/prefix`."""
    uri = f"{str(runs_dir).rstrip('/')}/{name}"
    if uri.startswith("s3://"):
        # An S3-compatible store (Cloudflare R2, MinIO) is selected by AWS_ENDPOINT_URL_S3 or
        # AWS_ENDPOINT_URL, as the AWS CLI does; credentials come from the usual AWS variables.
        endpoint = os.environ.get("AWS_ENDPOINT_URL_S3") or os.environ.get("AWS_ENDPOINT_URL")
        if endpoint:
            fs = pafs.S3FileSystem(
                endpoint_override=endpoint, region=os.environ.get("AWS_REGION", "auto")
            )
            return fs, uri[len("s3://") :].rstrip("/")
    if "://" in uri:
        fs, base = pafs.FileSystem.from_uri(uri)
        return fs, base.rstrip("/")
    return pafs.LocalFileSystem(), str(Path(uri).resolve())


def _exists(fs: pafs.FileSystem, path: str) -> bool:
    return fs.get_file_info(path).type != pafs.FileType.NotFound


def load_run(name: str, dsn: str = DEFAULT_DSN, runs_dir: Path | str = RUNS_DIR) -> dict[str, int]:
    """Load one run (replacing an earlier load of the same run_id). Returns rows per table."""
    fs, base = open_run(runs_dir, name)
    with fs.open_input_file(f"{base}/run.json") as f:
        meta = json.loads(f.read())
    counts: dict[str, int] = {}
    with connect(dsn) as con:
        create_schema(con)
        with con.cursor() as cur:
            cur.execute("DELETE FROM extraction_run WHERE run_id = %s", (name,))
            cur.execute(
                """
                INSERT INTO extraction_run (run_id, extractor, extractor_version, started_at,
                    n_decisions, n_spans, wall_seconds, workers, scheduler)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    meta["extractor"],
                    str(meta.get("extractor_version")),
                    meta.get("started_at"),
                    meta.get("n_decisions"),
                    meta.get("n_spans"),
                    meta.get("wall_seconds"),
                    meta.get("workers"),
                    meta.get("scheduler"),
                ),
            )
            for table, fname, mapping in _LOADS:
                path = f"{base}/{fname}"
                if not _exists(fs, path):
                    continue
                tbl = pq.read_table(path, columns=list(mapping), filesystem=fs)
                rows = [
                    (name, *vals)
                    for vals in zip(*(tbl.column(c).to_pylist() for c in mapping), strict=True)
                ]
                counts[table] = _copy_rows(cur, table, ["run_id", *mapping.values()], rows)
        con.commit()
        # Fresh statistics after a bulk COPY; without them the planner scans the citation
        # table sequentially for the aggregate endpoints (seen on the first deployment).
        con.execute("ANALYZE")
        con.commit()
    return counts


def load_statutes(code_map: dict[str, str], dsn: str = DEFAULT_DSN) -> int:
    """Fill `statute` (sr -> abbreviation) from the Fedlex code map; the first abbreviation of
    an SR number wins, the core codes are inserted first so they win over variants."""
    from caselaw_extraction.fedlex import CORE_CODES

    by_sr: dict[str, str] = {}
    for abbr, sr in list(CORE_CODES.items()) + list(code_map.items()):
        by_sr.setdefault(sr, abbr)
    with connect(dsn) as con:
        create_schema(con)
        with con.cursor() as cur:
            cur.execute("DELETE FROM statute")
            buf = io.StringIO()
            for sr, abbr in by_sr.items():
                buf.write(f"{sr}\t{abbr}\n")
            buf.seek(0)
            with cur.copy("COPY statute (sr, abbreviation) FROM STDIN") as copy:
                copy.write(buf.read())
        con.commit()
    return len(by_sr)


def table_counts(dsn: str = DEFAULT_DSN) -> dict[str, Any]:
    with connect(dsn) as con, con.cursor() as cur:
        out: dict[str, Any] = {}
        for t in ("extraction_run", "decision", "span", "citation", "centrality", "statute"):
            cur.execute(f"SELECT count(*) FROM {t}")
            out[t] = cur.fetchone()[0]
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        out["database_size"] = cur.fetchone()[0]
        return out
