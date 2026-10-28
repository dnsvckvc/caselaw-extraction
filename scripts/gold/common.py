"""Shared helpers for the gold-set labelling toolchain."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BATCH = os.environ.get("GOLD_BATCH", "batch1")  # which gold batch the toolchain works on
# A round is a later labelling pass over a finished batch (guideline v0.2 = round "v2"). Its
# task file carries the previous gold as locked pre-annotations plus new proposals; its edits,
# annotations and output live under their own names so the earlier gold stays reproducible.
ROUND = os.environ.get("GOLD_ROUND", "")
GOLD = Path("data/gold")
if ROUND:
    TASKS = Path("labeling/tasks") / f"{BATCH}.{ROUND}.json"
    BATCH_DIR = GOLD / BATCH / ROUND
    GOLD_FILE = GOLD / f"{BATCH}.gold.{ROUND}.jsonl"
else:
    TASKS = Path("labeling/tasks") / f"{BATCH}.json"
    BATCH_DIR = GOLD / BATCH  # edits/, ann/, disagreements.json for this batch
    GOLD_FILE = GOLD / f"{BATCH}.gold.jsonl"
CITATION_LABELS = ("STATUTE", "BGE", "DOCKET", "AMOUNT", "PARTY_ROLE")
NEGATIVE_LABELS = ("CONTRACT_ARTICLE", "BARE_ARTICLE", "OTHER_LAW", "JOURNAL_REF")  # v0.2
LABELS = set(CITATION_LABELS + NEGATIVE_LABELS)
OUTCOMES = {
    "approved",
    "partial_approval",
    "dismissed",
    "inadmissible",
    "moot",
    "consolidated",
    "unknown",
}


def load_tasks() -> list[dict[str, Any]]:
    return json.loads(TASKS.read_text())


def find_task(key: str) -> tuple[int, dict[str, Any]]:
    """key is a decision_id or a 1-based index into the batch."""
    tasks = load_tasks()
    if key.isdigit():
        i = int(key)
        return i, tasks[i - 1]
    for i, t in enumerate(tasks, 1):
        if t["data"]["decision_id"] == key:
            return i, t
    raise SystemExit(f"no task {key}")


def pre_spans(task: dict[str, Any]) -> list[dict[str, Any]]:
    """Pre-annotation spans, sorted by start, with 1-based ids that render_task prints."""
    res = task["predictions"][0]["result"]
    spans = [
        {
            "start": r["value"]["start"],
            "end": r["value"]["end"],
            "label": r["value"]["labels"][0],
            "text": r["value"]["text"],
        }
        for r in res
        if r["type"] == "labels"
    ]
    spans.sort(key=lambda s: (s["start"], s["end"]))
    for i, s in enumerate(spans, 1):
        s["id"] = i
    return spans


def pre_outcome(task: dict[str, Any]) -> str:
    for r in task["predictions"][0]["result"]:
        if r["type"] == "choices":
            return r["value"]["choices"][0]
    return "unknown"


def ann_path(pass_name: str, decision_id: str) -> Path:
    return BATCH_DIR / "ann" / pass_name / f"{decision_id}.json"


def edits_path(pass_name: str, decision_id: str) -> Path:
    return BATCH_DIR / "edits" / pass_name / f"{decision_id}.json"
