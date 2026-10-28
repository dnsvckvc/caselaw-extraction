"""Pick decisions for a human spot check of the model-labelled gold set and print them with
their gold spans inline, so a human can read them without Label Studio.

    uv run python scripts/gold/spot_check.py <batch> --pick 10 --seed 7    # choose and list
    uv run python scripts/gold/spot_check.py <batch> --show <decision_id>   # print one decision

The chosen ids are written to data/gold/<batch>/spot_check.ids.json. The human writes findings
to data/gold/<batch>/spot_check.md (template printed by --pick).
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from caselaw_extraction.gold import load_gold


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("batch")
    ap.add_argument("--pick", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--show", default="")
    args = ap.parse_args()
    gold = {g.decision_id: g for g in load_gold(args.batch)}
    ids_path = Path(f"data/gold/{args.batch}/spot_check.ids.json")
    if args.pick:
        rng = random.Random(args.seed)
        ids = rng.sample(sorted(gold), args.pick)
        ids_path.write_text(json.dumps(ids, indent=1))
        md = Path(f"data/gold/{args.batch}/spot_check.md")
        if not md.exists():
            rows = "\n".join(
                f"| {i} | {d} | {len(gold[d].spans)} | {gold[d].outcome} |  |  |  |"
                for i, d in enumerate(ids, 1)
            )
            md.write_text(
                "# Human spot check of the model-labelled gold set\n\n"
                "For each decision: read it with the gold spans inline, count wrong spans (should not be\n"
                "there or wrong boundary), missed spans, and say whether the outcome is right.\n\n"
                "| # | decision_id | gold spans | gold outcome | wrong spans | missed spans | outcome ok? |\n"
                "|---|---|---|---|---|---|---|\n" + rows + "\n\nNotes:\n\n"
            )
        print(f"{len(ids)} decisions -> {ids_path}; findings template: {md}")
        for i, d in enumerate(ids, 1):
            print(f"  {i:2d}. {d}  spans={len(gold[d].spans)}  outcome={gold[d].outcome}")
        return
    if args.show:
        g = gold[args.show]
        out, pos = [], 0
        for s in g.spans:
            out.append(g.text[pos : s["start"]])
            out.append(f"«{s['label']}»{g.text[s['start'] : s['end']]}«/»")
            pos = s["end"]
        out.append(g.text[pos:])
        print(f"=== {g.decision_id}  gold outcome: {g.outcome}  gold spans: {len(g.spans)}")
        print("".join(out))


if __name__ == "__main__":
    main()
