"""Gold-set and prediction files shared by all extractors.

A gold record and a prediction record have the same shape:

    {"decision_id": str, "outcome": str, "spans": [{"start", "end", "label", "text"}]}

Gold lives in `data/gold/<batch>.gold.jsonl`; the decision texts live in the Label Studio task
file `labeling/tasks/<batch>.json`. Predictions go to `data/pred/<batch>/<extractor>.jsonl`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from caselaw_extraction.regex_extractor import DISPOSITIV_RE

GOLD_DIR = Path("data/gold")
TASKS_DIR = Path("labeling/tasks")
PRED_DIR = Path("data/pred")
CITATION_LABELS = ("STATUTE", "BGE", "DOCKET", "AMOUNT", "PARTY_ROLE")
# guideline v0.2: references that look like citations but link to nothing (see the guideline)
NEGATIVE_LABELS = ("CONTRACT_ARTICLE", "BARE_ARTICLE", "OTHER_LAW", "JOURNAL_REF")
LABELS = CITATION_LABELS + NEGATIVE_LABELS
OUTCOMES = (
    "approved",
    "partial_approval",
    "dismissed",
    "inadmissible",
    "moot",
    "consolidated",
    "unknown",
)
# BIO tag set shared by the spaCy and transformer extractors
TAGS = ["O"] + [f"{p}-{lab}" for lab in LABELS for p in ("B", "I")]
TAG2ID = {t: i for i, t in enumerate(TAGS)}


@dataclass
class Decision:
    decision_id: str
    text: str
    outcome: str = "unknown"
    spans: list[dict] = field(default_factory=list)  # start, end, label, text

    def span_keys(self) -> list[tuple[int, int, str]]:
        return [(s["start"], s["end"], s["label"]) for s in self.spans]


def load_texts(batch: str) -> dict[str, str]:
    tasks = json.loads((TASKS_DIR / f"{batch}.json").read_text())
    return {t["data"]["decision_id"]: t["data"]["text"] for t in tasks}


def load_gold(batch: str) -> list[Decision]:
    texts = load_texts(batch)
    out = []
    for line in (GOLD_DIR / f"{batch}.gold.jsonl").read_text().splitlines():
        r = json.loads(line)
        out.append(Decision(r["decision_id"], texts[r["decision_id"]], r["outcome"], r["spans"]))
    return out


def load_batch_texts(batch: str) -> list[Decision]:
    """All decisions of a batch without labels (for prediction)."""
    return [Decision(did, text) for did, text in load_texts(batch).items()]


def write_predictions(batch: str, extractor: str, decisions: list[Decision]) -> Path:
    out = PRED_DIR / batch / f"{extractor}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(
            json.dumps(
                {"decision_id": d.decision_id, "outcome": d.outcome, "spans": d.spans},
                ensure_ascii=False,
            )
            + "\n"
            for d in decisions
        )
    )
    return out


def read_predictions(path: Path) -> dict[str, dict]:
    return {r["decision_id"]: r for r in map(json.loads, path.read_text().splitlines())}


# --- windows ----------------------------------------------------------------------------------


def windows(text: str, spans: list[dict], max_chars: int = 1500) -> list[tuple[int, int]]:
    """Cut a decision into (start, end) character windows at line breaks, never inside a span.

    Windows are what the learned models train and predict on; a transformer sees at most 512
    subword pieces, which is roughly 1,500 characters of German legal text.
    """
    inside = [False] * (len(text) + 1)
    for s in spans:
        for i in range(s["start"], s["end"]):
            inside[i] = True
    out: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            cut = text.rfind("\n", start + max_chars // 2, end)
            if cut == -1:
                cut = text.rfind(" ", start + max_chars // 2, end)
            if cut == -1:
                cut = end
            while cut > start and inside[cut]:
                cut -= 1
            end = cut if cut > start else end
        out.append((start, end))
        start = end
    return out


def spans_in(spans: list[dict], start: int, end: int) -> list[dict]:
    """Spans fully inside a window, shifted to window coordinates."""
    return [
        {**s, "start": s["start"] - start, "end": s["end"] - start}
        for s in spans
        if s["start"] >= start and s["end"] <= end
    ]


# --- outcome section ----------------------------------------------------------------------------


def dispositiv(text: str, length: int = 1500) -> str:
    """The ruling section that outcome classifiers read. Falls back to the tail of the decision."""
    matches = list(DISPOSITIV_RE.finditer(text))
    if matches:
        m = matches[-1]
        return text[m.start() : m.end() + length]
    return text[-length:]


# --- BIO helpers ----------------------------------------------------------------------------------


def char_tags(text: str, spans: list[dict]) -> list[str]:
    """One BIO tag per character; token-level tags are derived from this."""
    tags = ["O"] * len(text)
    for s in spans:
        tags[s["start"]] = f"B-{s['label']}"
        for i in range(s["start"] + 1, s["end"]):
            tags[i] = f"I-{s['label']}"
    return tags


def tags_to_spans(text: str, offsets: list[tuple[int, int]], tags: list[str]) -> list[dict]:
    """Merge token tags back into character spans. A stray I- tag starts a new span."""
    out: list[dict] = []
    cur: dict | None = None
    for (a, b), t in zip(offsets, tags, strict=True):
        if a == b:
            continue
        if t == "O":
            if cur:
                out.append(cur)
                cur = None
            continue
        prefix, lab = t.split("-", 1)
        if prefix == "B" or cur is None or cur["label"] != lab:
            if cur:
                out.append(cur)
            cur = {"start": a, "end": b, "label": lab}
        else:
            cur["end"] = b
    if cur:
        out.append(cur)
    for s in out:
        # trim whitespace that a token boundary may have pulled in
        while s["end"] > s["start"] and text[s["end"] - 1].isspace():
            s["end"] -= 1
        s["text"] = text[s["start"] : s["end"]]
    return [s for s in out if s["end"] > s["start"]]


_PUNCT_TRIM = re.compile(r"[.,;:)\]]+$")


def dedupe(spans: list[dict]) -> list[dict]:
    seen: set[tuple[int, int, str]] = set()
    out = []
    for s in sorted(spans, key=lambda s: (s["start"], s["end"])):
        k = (s["start"], s["end"], s["label"])
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out
