"""Run the regex extractor over the whole corpus and print coverage numbers for the report."""

from __future__ import annotations

import time
from collections import Counter

import duckdb

from caselaw_extraction import regex_extractor as rx
from caselaw_extraction.fedlex import load_code_map
from caselaw_extraction.ingest import CORPUS_PATH

code_map = load_code_map()
con = duckdb.connect()
rows = con.execute(
    f"SELECT decision_id, full_text, outcome, cited_decisions FROM read_parquet('{CORPUS_PATH}')"
).fetchall()
t0 = time.perf_counter()
labels: Counter[str] = Counter()
docs_with: Counter[str] = Counter()
codes: Counter[str] = Counter()
outcome_regex: Counter[str] = Counter()
agree = disagree = filled = 0
header_ok = Counter()
for decision_id, text, ds_outcome, _cited in rows:
    ex = rx.extract(decision_id, text, code_map)
    n = Counter(s.label.value for s in ex.all_spans())
    labels.update(n)
    docs_with.update(set(n))
    codes.update(s.code for s in ex.statutes)
    outcome_regex[ex.outcome.value] += 1
    if ds_outcome:
        if ex.outcome.value == ds_outcome:
            agree += 1
        elif ex.outcome.value != "unknown":
            disagree += 1
    elif ex.outcome.value != "unknown":
        filled += 1
    header_ok["docket"] += ex.header.docket_number != "unknown"
    header_ok["date"] += ex.header.decision_date is not None
    header_ok["chamber"] += ex.header.chamber is not None
    header_ok["appealed_court"] += ex.header.appealed_court is not None
dt = time.perf_counter() - t0
N = len(rows)
print(f"decisions: {N}   regex time: {dt:.1f}s  ({N / dt:.0f} docs/s)")
print("spans per label (total / docs with >=1):")
for k in ["STATUTE", "BGE", "DOCKET", "AMOUNT", "PARTY_ROLE"]:
    print(f"  {k:11s} {labels[k]:7d}   {docs_with[k]:5d}/{N}")
print("header fields found:", dict(header_ok))
print("regex outcome distribution:", dict(outcome_regex))
has_ds = sum(1 for r in rows if r[2])
print(
    f"outcome vs dataset: agree {agree}/{has_ds}  disagree {disagree}/{has_ds}  "
    f"filled where dataset has none: {filled}/{N - has_ds}"
)
print("top statute codes:", codes.most_common(15))
