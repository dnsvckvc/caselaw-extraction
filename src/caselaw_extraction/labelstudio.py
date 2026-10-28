"""Export corpus decisions as Label Studio tasks with regex pre-annotations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from caselaw_extraction import regex_extractor as rx
from caselaw_extraction.negatives import propose
from caselaw_extraction.schema import DecisionExtraction, Outcome

MODEL_VERSION = "regex-v0.4+negatives"  # batch1: regex-v0.1; batch2: regex-v0.2


def to_prediction(
    ex: DecisionExtraction, extra: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Pre-annotation: the regex citations plus `extra` spans (the negative-class proposals of
    guideline v0.2, from `negatives.propose`), all as one result list."""
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    spans = [(s.start, s.end, s.label.value, s.text) for s in ex.all_spans()]
    spans += [(e["start"], e["end"], e["label"], e["text"]) for e in (extra or [])]
    for start, end, label, text in sorted(spans):
        key = (start, end, label)
        if key in seen:
            continue  # one statute chain yields several citations sharing one span
        seen.add(key)
        result.append(
            {
                "from_name": "label",
                "to_name": "text",
                "type": "labels",
                "value": {"start": start, "end": end, "text": text, "labels": [label]},
            }
        )
    if ex.outcome is not Outcome.UNKNOWN:
        result.append(
            {
                "from_name": "outcome",
                "to_name": "text",
                "type": "choices",
                "value": {"choices": [ex.outcome.value]},
            }
        )
    return {"model_version": MODEL_VERSION, "result": result}


def to_task(row: dict[str, Any], code_map: dict[str, str]) -> dict[str, Any]:
    text: str = row["full_text"]
    ex = rx.extract(row["decision_id"], text, code_map)
    taken = [{"start": s.start, "end": s.end} for s in ex.all_spans()]
    extra = propose(text, taken, code_map)
    return {
        "data": {
            "decision_id": row["decision_id"],
            "docket_number": row["docket_number"],
            "decision_date": str(row["decision_date"]),
            "chamber": row.get("chamber") or "",
            "legal_area": row.get("legal_area") or "",
            "dataset_outcome": row.get("outcome") or "",
            "text": text,
        },
        "predictions": [to_prediction(ex, extra)],
    }


def write_tasks(rows: list[dict[str, Any]], code_map: dict[str, str], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tasks = [to_task(r, code_map) for r in rows]
    out.write_text(json.dumps(tasks, ensure_ascii=False))
    return out
