"""Collect resolved LLM outputs into one prediction file.

uv run python scripts/llm/collect.py <batch> <model>   ->  data/pred/<batch>/llm-<model>.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    batch, model = sys.argv[1], sys.argv[2]
    tasks = json.loads(Path(f"labeling/tasks/{batch}.json").read_text())
    raw_dir = Path(f"data/pred/{batch}/llm_raw/{model}")
    out = Path(f"data/pred/{batch}/llm-{model}.jsonl")
    recs, missing, stats = [], [], {"listed": 0, "resolved": 0, "backtracked": 0, "unresolved": 0}
    for t in tasks:
        did = t["data"]["decision_id"]
        p = raw_dir / f"{did}.resolved.json"
        if not p.exists():
            missing.append(did)
            continue
        r = json.loads(p.read_text())
        recs.append({"decision_id": did, "outcome": r["outcome"], "spans": r["spans"]})
        stats["listed"] += r["n_listed"]
        stats["resolved"] += r["n_resolved"]
        stats["backtracked"] += r["n_backtracked"]
        stats["unresolved"] += len(r["unresolved"])
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    print(f"{len(recs)}/{len(tasks)} decisions -> {out}; {stats}")
    if missing:
        print("missing:", ", ".join(missing))


if __name__ == "__main__":
    main()
