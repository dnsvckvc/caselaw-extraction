"""Build the task file for a later labelling round over a finished batch.

    uv run python scripts/gold/make_round.py <batch> <round> [--citations]   # e.g. batch1 v3

With --citations the current regex also proposes citation spans (STATUTE, BGE, ...) that the
batch gold does not have yet (guideline v0.3: short BGE citations, `Artikel` written out).

Writes labeling/tasks/<batch>.<round>.json: the same decisions and data as the original task
file, with pre-annotations = the current gold of the batch (citation classes, kept as they are)
plus the proposals of the negative-class pre-annotator (guideline v0.2). The gold toolchain then
works on the round with GOLD_BATCH=<batch> GOLD_ROUND=<round>.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from caselaw_extraction import regex_extractor as rx
from caselaw_extraction.fedlex import load_code_map
from caselaw_extraction.negatives import propose


def main() -> None:
    batch, rnd = sys.argv[1], sys.argv[2]
    tasks = json.loads(Path(f"labeling/tasks/{batch}.json").read_text())
    gold = {
        r["decision_id"]: r
        for r in map(json.loads, Path(f"data/gold/{batch}.gold.jsonl").read_text().splitlines())
    }
    code_map = load_code_map()
    counts: Counter = Counter()
    out = []
    for t in tasks:
        d = t["data"]
        g = gold[d["decision_id"]]
        new = propose(d["text"], g["spans"], code_map)
        if "--citations" in sys.argv:
            taken = [(s["start"], s["end"]) for s in g["spans"] + new]
            ex = rx.extract(d["decision_id"], d["text"], code_map)
            for sp in ex.all_spans():
                if not any(x < sp.end and sp.start < y for x, y in taken):
                    new.append(
                        {"start": sp.start, "end": sp.end, "label": sp.label.value, "text": sp.text}
                    )
                    taken.append((sp.start, sp.end))
        counts.update(s["label"] for s in new)
        spans = sorted(g["spans"] + new, key=lambda s: (s["start"], s["end"]))
        result = [
            {
                "from_name": "label",
                "to_name": "text",
                "type": "labels",
                "value": {
                    "start": s["start"],
                    "end": s["end"],
                    "text": s["text"],
                    "labels": [s["label"]],
                },
            }
            for s in spans
        ]
        result.append(
            {
                "from_name": "outcome",
                "to_name": "text",
                "type": "choices",
                "value": {"choices": [g["outcome"]]},
            }
        )
        out.append(
            {
                "data": d,
                "predictions": [{"model_version": f"gold+proposals-{rnd}", "result": result}],
            }
        )
    path = Path(f"labeling/tasks/{batch}.{rnd}.json")
    path.write_text(json.dumps(out, ensure_ascii=False))
    print(f"{len(out)} tasks -> {path}; proposed negatives: {dict(counts)}")


if __name__ == "__main__":
    main()
