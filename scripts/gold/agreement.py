"""Compare two annotation passes; write the disagreement file for adjudication.

Environment: GOLD_BATCH=batch2 (default batch1), GOLD_PASSES=a,c (default a,b).

uv run python scripts/gold/agreement.py            # summary + data/gold/disagreements.json
uv run python scripts/gold/agreement.py <decision_id>   # print one decision's disagreements
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "scripts/gold")
from common import BATCH, BATCH_DIR, CITATION_LABELS, NEGATIVE_LABELS, load_tasks  # noqa: E402


def ctx(text: str, start: int, end: int, w: int = 60) -> str:
    return (
        text[max(0, start - w) : start] + "⟦" + text[start:end] + "⟧" + text[end : end + w]
    ).replace("\n", " ")


def key(s: dict) -> tuple[int, int, str]:
    return (s["start"], s["end"], s["label"])


PA, PB = (os.environ.get("GOLD_PASSES") or "a,b").split(",")


def main() -> None:
    tasks = {t["data"]["decision_id"]: t for t in load_tasks()}
    only = sys.argv[1] if len(sys.argv) > 1 else None
    rows = []
    tot = Counter()
    per_label = {lab: Counter() for lab in CITATION_LABELS + NEGATIVE_LABELS}
    report: dict[str, dict] = {}
    for did, task in tasks.items():
        pa, pb = BATCH_DIR / "ann" / PA / f"{did}.json", BATCH_DIR / "ann" / PB / f"{did}.json"
        if not (pa.exists() and pb.exists()):
            continue
        a, b = json.loads(pa.read_text()), json.loads(pb.read_text())
        text = task["data"]["text"]
        sa = {key(s): s for s in a["spans"]}
        sb = {key(s): s for s in b["spans"]}
        agree = sa.keys() & sb.keys()
        only_a = sorted(sa.keys() - sb.keys())
        only_b = sorted(sb.keys() - sa.keys())
        out_agree = a["outcome"] == b["outcome"]
        tot["spans_agree"] += len(agree)
        tot["only_a"] += len(only_a)
        tot["only_b"] += len(only_b)
        tot["outcome_agree"] += out_agree
        tot["decisions"] += 1
        for k in agree:
            per_label[k[2]]["agree"] += 1
        for k in only_a:
            per_label[k[2]]["only_a"] += 1
        for k in only_b:
            per_label[k[2]]["only_b"] += 1
        disputed = []
        for i, k in enumerate(only_a):
            disputed.append(
                {
                    "id": f"a{i + 1}",
                    "source": "a",
                    "label": k[2],
                    "text": sa[k]["text"],
                    "start": k[0],
                    "end": k[1],
                    "context": ctx(text, k[0], k[1]),
                }
            )
        for i, k in enumerate(only_b):
            disputed.append(
                {
                    "id": f"b{i + 1}",
                    "source": "b",
                    "label": k[2],
                    "text": sb[k]["text"],
                    "start": k[0],
                    "end": k[1],
                    "context": ctx(text, k[0], k[1]),
                }
            )
        disputed.sort(key=lambda d: d["start"])
        report[did] = {
            "decision_id": did,
            "task_index": a["task_index"],
            "outcome_a": a["outcome"],
            "outcome_b": b["outcome"],
            "comment_a": a.get("comment", ""),
            "comment_b": b.get("comment", ""),
            "n_agree": len(agree),
            "disputed": disputed,
        }
        rows.append((did, len(agree), len(only_a), len(only_b), a["outcome"], b["outcome"]))
    if only:
        print(json.dumps(report.get(only, {}), ensure_ascii=False, indent=1))
        return
    Path(BATCH_DIR / "disagreements.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1)
    )
    n = tot["decisions"]
    print(f"batch {BATCH}; passes compared: {PA} vs {PB}; decisions with both: {n}")
    if n:
        p = tot["spans_agree"] / max(1, tot["spans_agree"] + tot["only_b"])
        r = tot["spans_agree"] / max(1, tot["spans_agree"] + tot["only_a"])
        f1 = 2 * p * r / max(1e-9, p + r)
        print(
            f"span agreement ({PB} vs {PA}): P={p:.3f} R={r:.3f} F1={f1:.3f}   "
            f"agree={tot['spans_agree']} only_a={tot['only_a']} only_b={tot['only_b']}"
        )
        print(f"outcome agreement: {tot['outcome_agree']}/{n}")
        print("per label  agree / only_a / only_b")
        for lab, c in per_label.items():
            print(f"  {lab:11s} {c['agree']:5d} {c['only_a']:5d} {c['only_b']:5d}")
        print(
            "decisions with disputes:",
            sum(
                1 for r_ in report.values() if r_["disputed"] or r_["outcome_a"] != r_["outcome_b"]
            ),
        )
    print(f"-> {BATCH_DIR / 'disagreements.json'}")


if __name__ == "__main__":
    main()
