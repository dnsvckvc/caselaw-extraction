"""Score extractors against a gold pass.

    GOLD_BATCH=batch2 uv run python scripts/score_against_gold.py [--gold a] [--extractor regex|pre]

`pre` scores the pre-annotations stored in the Label Studio tasks (regex-v0.1 at task-writing
time). `regex` runs the current regex extractor, so improvements show up immediately.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts/gold")
from common import BATCH, GOLD_FILE, load_tasks, pre_outcome, pre_spans  # noqa: E402

from caselaw_extraction import regex_extractor as rx  # noqa: E402
from caselaw_extraction.evaluate import Scores, format_table, score_decision  # noqa: E402
from caselaw_extraction.fedlex import load_code_map  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--gold",
        default="final",
        help="pass name under data/gold/ann, or 'final' for batch1.gold.jsonl",
    )
    ap.add_argument("--extractor", default="regex", choices=["regex", "pre"])
    args = ap.parse_args()
    if args.gold == "final":
        gold = {r["decision_id"]: r for r in map(json.loads, GOLD_FILE.read_text().splitlines())}
    else:
        gold = {
            p.stem: json.loads(p.read_text())
            for p in Path(f"data/gold/{BATCH}/ann/{args.gold}").glob("*.json")
        }
    code_map = load_code_map()
    scores = Scores()
    n = 0
    for task in load_tasks():
        did = task["data"]["decision_id"]
        if did not in gold:
            continue
        text = task["data"]["text"]
        g = gold[did]
        gold_spans = [(s["start"], s["end"], s["label"]) for s in g["spans"]]
        if args.extractor == "pre":
            pred_spans = [(s["start"], s["end"], s["label"]) for s in pre_spans(task)]
            pred_outcome = pre_outcome(task)
        else:
            ex = rx.extract(did, text, code_map)
            pred_spans = sorted({(s.start, s.end, s.label.value) for s in ex.all_spans()})
            pred_outcome = ex.outcome.value
        score_decision(scores, pred_spans, gold_spans, pred_outcome, g["outcome"])
        n += 1
    print(
        format_table(scores, f"{args.extractor} vs gold '{args.gold}' of {BATCH} ({n} decisions)")
    )


if __name__ == "__main__":
    main()
