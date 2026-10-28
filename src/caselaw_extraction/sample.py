"""Pick a stratified gold-set sample from the working corpus."""

from __future__ import annotations

from pathlib import Path

import duckdb

from caselaw_extraction.ingest import CORPUS_PATH

GOLD_DIR = Path("data/gold")
MIN_LEN, MAX_LEN = 5_000, 30_000  # keep labelling time per decision under ~20 minutes
CIVIL_CHAMBERS = ("I. zivilrechtliche Abteilung", "II. zivilrechtliche Abteilung")


def pick_sample(
    n: int, seed: int, corpus: Path = CORPUS_PATH, exclude: list[str] | None = None
) -> list[dict]:
    """n decisions, balanced over year x chamber strata, deterministic for a given seed.

    `chamber_text` is derived from the decision header at ingest time because the dataset's
    own `chamber` column is wrong for a handful of rows.
    """
    con = duckdb.connect()
    excl = ", ".join(f"'{e}'" for e in (exclude or [])) or "''"
    chambers = ", ".join(f"'{c}'" for c in CIVIL_CHAMBERS)
    rows = con.execute(
        f"""
        WITH base AS (
            SELECT decision_id, docket_number, decision_date, chamber_text AS chamber,
                   legal_area, outcome, text_length, full_text,
                   substr(decision_date, 1, 4) AS year
            FROM read_parquet('{corpus}')
            WHERE text_length BETWEEN {MIN_LEN} AND {MAX_LEN}
              AND chamber_text IN ({chambers})
              AND decision_id NOT IN ({excl})
        ),
        ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY year, chamber ORDER BY hash(decision_id || '{seed}')
            ) AS rk
            FROM base
        )
        SELECT * FROM ranked ORDER BY rk, year, chamber LIMIT {n}
        """
    ).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r, strict=True)) for r in rows]


# --- targeted sampling (batch 3) ------------------------------------------------------------------
# The learning curve (report 6.12) says random decisions feed the rare classes too slowly, so half
# of batch 3 is drawn from decisions that contain them. Membership is recorded per decision.

import random  # noqa: E402
import re  # noqa: E402

TARGET_PATTERNS = {
    "contract": re.compile(
        r"(?:Ziff\.|Ziffer|Art\.|Artikel) ?[0-9A-Z][^\n]{0,40}?(?:AVB|AGB|\bAB\b|GAV|des Vertrags"
        r"|der Vereinbarung|des Reglements|Vorsorgereglement|Statuten|Konsortialvertrag"
        r"|Mietvertrag|Arbeitsvertrag)"
    ),
    "journal": re.compile(
        r"\b(?:SJZ|AJP|ZBJV|SZZP|BlSchK|FamPra\.ch|SZW|SVR|Pra |sic!|ZBGR|Jusletter|ZSR"
        r"|plädoyer|BJM|ZR |SJ |JdT|RVJ|ZWR) ?[0-9]{2,4}"
    ),
    "foreign": re.compile(
        r"(?:§ ?[0-9]+[^\n]{0,30}(?:BGB|ZPO/|HGB|ABGB|\bGG\b)"
        r"|Art\. [0-9]+[^\n]{0,20}(?:AEUV|EUV|\bCC\b|\bCO\b))"
    ),
}
# quota per group; rarer groups are filled first; a decision counts for every group it matches
TARGET_QUOTA = {
    "foreign": 15,
    "partial_approval": 12,
    "moot": 8,
    "approved": 20,
    "contract": 30,
    "journal": 15,
}


def pick_targeted(
    n: int, seed: int, corpus: Path = CORPUS_PATH, exclude: list[str] | None = None
) -> tuple[list[dict], dict[str, list[str]]]:
    """n decisions that contain rare classes (contract clauses, journal references, foreign
    law) or rare outcomes (approved, partial approval, moot), drawn per group with quotas.
    Returns (rows, {group: [decision_id, ...]})."""
    from caselaw_extraction import regex_extractor as rx

    con = duckdb.connect()
    excl = ", ".join(f"'{e}'" for e in (exclude or [])) or "''"
    chambers = ", ".join(f"'{c}'" for c in CIVIL_CHAMBERS)
    rows = con.execute(
        f"""
        SELECT decision_id, docket_number, decision_date, chamber_text AS chamber, legal_area,
               outcome, text_length, full_text, substr(decision_date, 1, 4) AS year
        FROM read_parquet('{corpus}')
        WHERE text_length BETWEEN {MIN_LEN} AND {MAX_LEN}
          AND chamber_text IN ({chambers}) AND decision_id NOT IN ({excl})
        """
    ).fetchall()
    cols = [d[0] for d in con.description]
    pool = [dict(zip(cols, r, strict=True)) for r in rows]
    groups: dict[str, list[dict]] = {g: [] for g in TARGET_QUOTA}
    for r in pool:
        t = r["full_text"]
        for g, rxp in TARGET_PATTERNS.items():
            if rxp.search(t):
                groups[g].append(r)
        oc = rx.extract_outcome(t).value
        if oc in ("approved", "partial_approval", "moot"):
            groups[oc].append(r)
    rng = random.Random(seed)
    chosen: dict[str, dict] = {}
    membership: dict[str, list[str]] = {g: [] for g in TARGET_QUOTA}
    for g, quota in TARGET_QUOTA.items():  # dict order = priority
        cands = [r for r in groups[g] if r["decision_id"] not in chosen]
        rng.shuffle(cands)
        for r in cands[:quota]:
            chosen[r["decision_id"]] = r
    for did in chosen:
        for g in TARGET_QUOTA:
            if any(x["decision_id"] == did for x in groups[g]):
                membership[g].append(did)
    out = list(chosen.values())[:n]
    return out, {
        g: [d for d in ids if d in {r["decision_id"] for r in out}] for g, ids in membership.items()
    }
