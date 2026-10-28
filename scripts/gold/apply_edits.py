"""Validate an edits file against a task and write the resulting annotation.

    uv run python scripts/gold/apply_edits.py <pass> <decision_id | index>

Reads  data/gold/<batch>/edits/<pass>/<decision_id>.json  (batch from GOLD_BATCH, default
batch1) with this shape:

{
  "outcome": "dismissed",                      # required, one of the six values or "unknown"
  "delete": [3, 7],                            # pre-annotation ids to remove
  "relabel": [{"id": 5, "label": "BGE"}],      # change a label, keep boundaries
  "add": [                                     # new spans, located by exact text
    {"text": "Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG", "label": "STATUTE"},
    {"text": "BGE 140 III 86", "label": "BGE", "occurrence": 2},   # 2nd occurrence
    {"text": "Fr. 500.--", "label": "AMOUNT", "all": true}           # every occurrence
  ],
  "comment": "free text, optional"
}

Exit code 0 and "OK" when every edit applied cleanly. Otherwise each problem is listed and
nothing is written.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

sys.path.insert(0, "scripts/gold")
from common import LABELS, OUTCOMES, ann_path, edits_path, find_task, pre_spans  # noqa: E402


def occurrences(text: str, needle: str) -> list[tuple[int, int]]:
    """(start, end) of each match. Any whitespace run in `needle` matches any whitespace run
    (spaces, non-breaking spaces, line breaks) in the text, so a citation that wraps across a
    line can be given on one line."""
    parts = [re.escape(p) for p in re.split(r"\s+", needle.strip()) if p]
    if not parts:
        return []
    rx = re.compile(r"\s+".join(parts))
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def ctx(text: str, start: int, end: int, w: int = 30) -> str:
    return (
        text[max(0, start - w) : start] + "⟦" + text[start:end] + "⟧" + text[end : end + w]
    ).replace("\n", "⏎")


def main() -> None:
    pass_name, key = sys.argv[1], sys.argv[2]
    idx, task = find_task(key)
    d = task["data"]
    text: str = d["text"]
    decision_id: str = d["decision_id"]
    ep = edits_path(pass_name, decision_id)
    if not ep.exists():
        raise SystemExit(f"missing edits file {ep}")
    try:
        edits = json.loads(ep.read_text())
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"{ep} is not valid JSON: {e}. A line break inside a string must be written as "
            "a space (matching is whitespace-tolerant), not as a raw newline."
        ) from e
    errors: list[str] = []

    outcome = edits.get("outcome")
    if outcome not in OUTCOMES:
        errors.append(f"outcome must be one of {sorted(OUTCOMES)}, got {outcome!r}")

    spans = {s["id"]: dict(s) for s in pre_spans(task)}
    for sid in edits.get("delete", []):
        if sid not in spans:
            errors.append(f"delete: no pre-annotation #{sid}")
        else:
            del spans[sid]
    for r in edits.get("relabel", []):
        sid, lab = r.get("id"), r.get("label")
        if sid not in spans:
            errors.append(f"relabel: no pre-annotation #{sid} (deleted or unknown)")
        elif lab not in LABELS:
            errors.append(f"relabel #{sid}: unknown label {lab!r}")
        else:
            spans[sid]["label"] = lab

    new: list[dict[str, Any]] = []
    for a in edits.get("add", []):
        t, lab = a.get("text", ""), a.get("label")
        if lab not in LABELS:
            errors.append(f"add {t!r}: unknown label {lab!r}")
            continue
        if not t:
            errors.append("add: empty text")
            continue
        occ = occurrences(text, t)
        if not occ:
            errors.append(f"add {t!r}: text not found (check spelling, quotes ' vs ’, dashes)")
            continue
        if a.get("all"):
            chosen = occ
        elif "occurrence" in a:
            n = int(a["occurrence"])
            if not 1 <= n <= len(occ):
                errors.append(f"add {t!r}: occurrence {n} out of range 1..{len(occ)}")
                continue
            chosen = [occ[n - 1]]
        elif len(occ) == 1:
            chosen = occ
        else:
            where = "; ".join(
                f"{k + 1}: …{ctx(text, a0, b0, 25)}…" for k, (a0, b0) in enumerate(occ[:8])
            )
            errors.append(
                f'add {t!r}: {len(occ)} occurrences, give "occurrence": n or "all": true. {where}'
            )
            continue
        for a0, b0 in chosen:
            new.append({"start": a0, "end": b0, "label": lab, "text": text[a0:b0]})

    final = list(spans.values()) + new
    final.sort(key=lambda s: (s["start"], s["end"]))
    for s1, s2 in zip(final, final[1:], strict=False):
        if s2["start"] < s1["end"]:
            errors.append(
                f"overlap: {s1['label']} {s1['text']!r} and {s2['label']} {s2['text']!r} "
                f"at …{ctx(text, s1['start'], s2['end'], 20)}… (delete the old one first)"
            )
    for s in final:
        if text[s["start"] : s["end"]] != s["text"]:
            errors.append(f"internal: span text mismatch at {s['start']}")

    if errors:
        print(f"{len(errors)} problem(s) in {ep}:")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)

    out = {
        "decision_id": decision_id,
        "task_index": idx,
        "pass": pass_name,
        "outcome": outcome,
        "comment": edits.get("comment", ""),
        "spans": [{k: s[k] for k in ("start", "end", "label", "text")} for s in final],
        "n_pre": len(pre_spans(task)),
        "n_deleted": len(edits.get("delete", [])),
        "n_added": len(new),
        "n_relabeled": len(edits.get("relabel", [])),
    }
    ap = ann_path(pass_name, decision_id)
    ap.parent.mkdir(parents=True, exist_ok=True)
    ap.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(
        f"OK {decision_id}: {len(final)} spans (pre {out['n_pre']}, -{out['n_deleted']}, "
        f"+{out['n_added']}, relabeled {out['n_relabeled']}), outcome={outcome} -> {ap}"
    )


if __name__ == "__main__":
    main()
