"""The opencaselaw silver graph that ships with the dataset, read as entity sets per decision.

The graph has no character offsets, so it is compared at entity level only
(`evaluate.entity_keys`). Statute rows carry (law_code, article); citation rows carry a
normalised target such as `BGE 134 I 83` or `2C_52_2016`; the target decision id tells BGE
from file-number citations apart.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from caselaw_extraction.evaluate import norm_docket

CITATIONS = Path("data/raw/opencaselaw_citations.parquet")
STATUTES = Path("data/raw/opencaselaw_statute_references.parquet")


def silver_entities(decision_ids: list[str]) -> dict[str, dict[str, set]]:
    out = {d: {"STATUTE": set(), "BGE": set(), "DOCKET": set()} for d in decision_ids}
    con = duckdb.connect()
    il = ", ".join(f"'{d}'" for d in decision_ids)
    for did, code, art in con.execute(
        f"SELECT decision_id, law_code, article FROM read_parquet('{STATUTES}') "
        f"WHERE decision_id IN ({il})"
    ).fetchall():
        out[did]["STATUTE"].add(f"{code.upper()} {art}")
    # the target id says what was cited: bge_* is a published decision, bger_* a file number;
    # cantonal targets (the appealed decision) are outside the DOCKET label and are skipped
    for did, ref, tid in con.execute(
        "SELECT source_decision_id, target_ref, target_decision_id "
        f"FROM read_parquet('{CITATIONS}') WHERE source_decision_id IN ({il})"
    ).fetchall():
        if tid.startswith("bge_"):
            out[did]["BGE"].add("BGE " + ref.removeprefix("BGE ").replace("_", " "))
        elif tid.startswith("bger_"):
            out[did]["DOCKET"].add(norm_docket(tid.removeprefix("bger_")))
    return out
