"""Print one decision as plain text for the LLM extractor (no pre-annotations).

uv run python scripts/llm/render_decision.py <batch> <index | decision_id>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    batch, key = sys.argv[1], sys.argv[2]
    tasks = json.loads(Path(f"labeling/tasks/{batch}.json").read_text())
    if key.isdigit():
        idx, t = int(key), tasks[int(key) - 1]
    else:
        idx, t = next((i, t) for i, t in enumerate(tasks, 1) if t["data"]["decision_id"] == key)
    d = t["data"]
    print(f"=== index {idx}  decision_id={d['decision_id']}  chars={len(d['text'])}")
    print("=== TEXT START")
    print(d["text"])
    print("=== TEXT END")


if __name__ == "__main__":
    main()
