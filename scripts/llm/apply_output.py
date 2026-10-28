"""Resolve an LLM extractor's output (texts in document order) to character spans.

    uv run python scripts/llm/apply_output.py <batch> <index | decision_id> <model>

Reads  data/pred/<batch>/llm_raw/<model>/<decision_id>.json:

{
  "outcome": "dismissed",
  "citations": [
    {"label": "STATUTE", "text": "Art. 42 Abs. 2 BGG"},
    {"label": "BGE", "text": "BGE 140 III 86"},
    ...                                   # every occurrence, in the order it appears
  ]
}

Each text is searched from the position where the previous one ended (whitespace-tolerant). A text
that is not found there is searched from the start of the decision and marked as a backtrack; a text
not found at all is dropped and listed. Writes <decision_id>.resolved.json next to the input.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

LABELS = {"STATUTE", "BGE", "DOCKET", "AMOUNT", "PARTY_ROLE"}
OUTCOMES = {
    "approved",
    "partial_approval",
    "dismissed",
    "inadmissible",
    "moot",
    "consolidated",
    "unknown",
}


_BGE_LEAD_RE = re.compile(r"BGE\s+$")


def pattern(needle: str) -> re.Pattern[str] | None:
    parts = [re.escape(p) for p in re.split(r"\s+", needle.strip()) if p]
    return re.compile(r"\s+".join(parts)) if parts else None


def main() -> None:
    batch, key, model = sys.argv[1], sys.argv[2], sys.argv[3]
    tasks = json.loads(Path(f"labeling/tasks/{batch}.json").read_text())
    t = (
        tasks[int(key) - 1]
        if key.isdigit()
        else next(t for t in tasks if t["data"]["decision_id"] == key)
    )
    did, text = t["data"]["decision_id"], t["data"]["text"]
    raw_path = Path(f"data/pred/{batch}/llm_raw/{model}/{did}.json")
    if not raw_path.exists():
        raise SystemExit(f"missing {raw_path}")
    try:
        raw = json.loads(raw_path.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(f"{raw_path} is not valid JSON: {e}") from e
    problems: list[str] = []
    outcome = raw.get("outcome")
    if outcome not in OUTCOMES:
        problems.append(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")
        outcome = "unknown"
    spans: list[dict] = []
    taken: list[tuple[int, int]] = []
    cursor = 0
    n_back = 0
    unresolved: list[str] = []
    for c in raw.get("citations", []):
        lab, needle = c.get("label"), c.get("text", "")
        if lab not in LABELS:
            problems.append(f"unknown label {lab!r} for {needle!r}")
            continue
        rx = pattern(needle)
        if rx is None:
            continue
        m = rx.search(text, cursor)
        if m is None:
            n_back += 1
            m = next(
                (
                    mm
                    for mm in rx.finditer(text)
                    if not any(a < mm.end() and mm.start() < b for a, b in taken)
                ),
                None,
            )
        if m is None:
            unresolved.append(needle)
            continue
        if any(a < m.end() and m.start() < b for a, b in taken):
            continue  # same span listed twice
        start, end = m.start(), m.end()
        # a BGE key given without its leading "BGE" word still denotes the full citation
        if lab == "BGE":
            lead = _BGE_LEAD_RE.search(text[max(0, start - 8) : start])
            if lead:
                start -= len(lead.group(0))
        spans.append({"start": start, "end": end, "label": lab, "text": text[start:end]})
        taken.append((start, end))
        cursor = end
    spans.sort(key=lambda s: (s["start"], s["end"]))
    out = {
        "decision_id": did,
        "outcome": outcome,
        "spans": spans,
        "n_listed": len(raw.get("citations", [])),
        "n_resolved": len(spans),
        "n_backtracked": n_back,
        "unresolved": unresolved,
        "problems": problems,
    }
    raw_path.with_suffix(".resolved.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    status = "OK" if not unresolved and not problems else "CHECK"
    print(
        f"{status} {did}: listed={out['n_listed']} resolved={out['n_resolved']} "
        f"backtracked={n_back} unresolved={len(unresolved)} outcome={outcome}"
    )
    for u in unresolved[:20]:
        print("  not found:", repr(u))
    for p in problems:
        print("  problem:", p)


if __name__ == "__main__":
    main()
