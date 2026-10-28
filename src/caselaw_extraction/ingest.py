"""Download the BGer Parquet file from Hugging Face and filter it into the working corpus."""

from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
from rich.progress import Progress

HF_BASE = "https://huggingface.co/datasets/voilaj/swiss-caselaw/resolve/main"
FILES = {
    "data/bger.parquet": "bger.parquet",
    "graph/citations.parquet": "opencaselaw_citations.parquet",
    "graph/statute_references.parquet": "opencaselaw_statute_references.parquet",
}
RAW_DIR = Path("data/raw")
INTERIM_DIR = Path("data/interim")
CORPUS_PATH = INTERIM_DIR / "bger_de_zivil_2020.parquet"

# The dataset's `language` column is wrong for a few 2026 rows (French and Italian texts tagged
# 'de'), so the filter also checks the text itself.
CORPUS_FILTER = (
    "language = 'de' AND branch = 'zivil' AND decision_date >= '2020-01-01' AND has_full_text "
    "AND NOT regexp_matches(substr(full_text, 1, 600), 'Arrêt du|Sentenza del|Ordonnance du')"
)
# The dataset's `chamber` column is wrong for a few rows; the text header is authoritative.
CHAMBER_SQL = """
    CASE
        WHEN regexp_matches(substr(full_text, 1, 600), '(?i)\\bI\\. ?zivilrechtliche Abteilung')
            THEN 'I. zivilrechtliche Abteilung'
        WHEN regexp_matches(substr(full_text, 1, 600), '(?i)\\bII\\. ?zivilrechtliche Abteilung')
            THEN 'II. zivilrechtliche Abteilung'
        ELSE coalesce(chamber, 'unknown')
    END AS chamber_text
"""
CORPUS_COLUMNS = [
    "decision_id",
    "docket_number",
    "decision_date",
    "chamber",
    "branch",
    "legal_area",
    "outcome",
    "bge_reference",
    "cited_decisions",
    "appealed_court_raw",
    "appealed_date",
    "appealed_docket",
    "judges",
    "clerks",
    "title",
    "regeste",
    "full_text",
    "text_length",
    "source_url",
    "content_hash",
]


def download(remote: str, local: Path, client: httpx.Client) -> None:
    """Stream one file to disk, resuming nothing: a partial file is deleted and re-fetched."""
    local.parent.mkdir(parents=True, exist_ok=True)
    tmp = local.with_suffix(local.suffix + ".part")
    with client.stream("GET", f"{HF_BASE}/{remote}", follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with Progress() as progress, tmp.open("wb") as f:
            task = progress.add_task(f"download {remote}", total=total or None)
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                progress.update(task, advance=len(chunk))
    tmp.rename(local)


def fetch_raw(force: bool = False) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    with httpx.Client(timeout=httpx.Timeout(60.0, read=600.0)) as client:
        for remote, name in FILES.items():
            local = RAW_DIR / name
            if force or not local.exists():
                download(remote, local, client)
            paths[name] = local
    return paths


def build_corpus(raw_bger: Path, out: Path = CORPUS_PATH) -> int:
    """Filter the raw BGer file to the project scope and write the working corpus."""
    out.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    cols = ", ".join(CORPUS_COLUMNS) + ", " + CHAMBER_SQL
    con.execute(
        f"COPY (SELECT {cols} FROM read_parquet('{raw_bger}') WHERE {CORPUS_FILTER} "
        f"ORDER BY decision_date, docket_number) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    n = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()
    return int(n[0]) if n else 0


def ingest(force: bool = False) -> int:
    paths = fetch_raw(force=force)
    return build_corpus(paths["bger.parquet"])
