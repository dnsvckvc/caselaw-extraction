"""Print one decision with its numbered pre-annotations inline.

    uv run python scripts/gold/render_task.py <decision_id | index>

Each pre-annotation appears as  «#12 STATUTE»Art. 42 Abs. 1 BGG«/12»  in the text.
"""

from __future__ import annotations

import sys

sys.path.insert(0, "scripts/gold")
from common import find_task, pre_outcome, pre_spans  # noqa: E402


def main() -> None:
    idx, task = find_task(sys.argv[1])
    d = task["data"]
    text: str = d["text"]
    spans = pre_spans(task)
    out: list[str] = []
    pos = 0
    for s in spans:
        out.append(text[pos : s["start"]])
        out.append(f"«#{s['id']} {s['label']}»{text[s['start'] : s['end']]}«/{s['id']}»")
        pos = s["end"]
    out.append(text[pos:])
    print(f"=== task {idx}  decision_id={d['decision_id']}  docket={d['docket_number']}")
    print(f"=== date={d['decision_date']}  chamber={d['chamber']}  legal_area={d['legal_area']}")
    print(f"=== pre-annotated outcome: {pre_outcome(task)}   pre-annotations: {len(spans)}")
    print("=== TEXT START")
    print("".join(out))
    print("=== TEXT END")


if __name__ == "__main__":
    main()
