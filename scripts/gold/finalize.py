"""Merge two passes and adjudications into the gold set; optionally import to Label Studio.

Environment: GOLD_BATCH=batch2 (default batch1), GOLD_PASSES=a,c (default a,b).

    uv run python scripts/gold/finalize.py --check <decision_id>   # validate one adjudication file
    uv run python scripts/gold/finalize.py                          # write data/gold/<batch>.gold.jsonl
    uv run python scripts/gold/finalize.py --import                 # also post annotations to LS
    uv run python scripts/gold/finalize.py --import --replace       # overwrite existing ground truth

Adjudication file data/gold/<batch>/edits/adj/<decision_id>.json:
{
  "keep": ["a1", "b3"],          # disputed span ids (from disagreements.json) that belong in gold
  "outcome": "dismissed",        # required only when outcome_a != outcome_b
  "drop": ["Ziffer 1 des Vergleichs"],                     # agreed spans to remove, by exact text
  "relabel": [{"text": "Art. 117 GOG/ZH", "label": "OTHER_LAW"}],   # agreed spans, by exact text
  "add": [{"text": "Art. 72 ff.", "label": "BARE_ARTICLE", "occurrence": 1}],  # like apply_edits
  "comment": "optional"
}
Disputed ids not listed in "keep" are dropped. A decision without disputes needs no file unless
the adjudicator overrides agreed spans with drop / relabel / add (a guideline decision that both
passes applied the old way).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, "scripts/gold")
sys.path.insert(0, "scripts")
from apply_edits import occurrences  # noqa: E402
from common import BATCH_DIR, GOLD_FILE, LABELS, OUTCOMES, load_tasks  # noqa: E402

PA, PB = (os.environ.get("GOLD_PASSES") or "a,b").split(",")
DIS = BATCH_DIR / "disagreements.json"
OUT = GOLD_FILE


def key(s: dict) -> tuple[int, int, str]:
    return (s["start"], s["end"], s["label"])


def resolve(
    did: str, report: dict, a: dict, b: dict, text: str = ""
) -> tuple[dict | None, list[str]]:
    """Return (gold record, problems)."""
    problems: list[str] = []
    r = report.get(did)
    if r is None:
        return None, [f"{did}: not in disagreements.json (run agreement.py first)"]
    disputed = {d["id"]: d for d in r["disputed"]}
    outcome_conflict = r["outcome_a"] != r["outcome_b"]
    adj_path = BATCH_DIR / "edits" / "adj" / f"{did}.json"
    adj = json.loads(adj_path.read_text()) if adj_path.exists() else None
    if (disputed or outcome_conflict) and adj is None:
        return None, [
            f"{did}: {len(disputed)} disputed spans, outcome conflict={outcome_conflict}, no adjudication file yet"
        ]
    keep = set(adj.get("keep", [])) if adj else set()
    for k in keep:
        if k not in disputed:
            problems.append(f"{did}: keep id {k!r} is not a disputed id ({sorted(disputed)})")
    outcome = r["outcome_a"]
    if outcome_conflict:
        outcome = (adj or {}).get("outcome")
        if outcome not in OUTCOMES:
            problems.append(
                f"{did}: outcomes differ (a={r['outcome_a']}, b={r['outcome_b']}); adjudication must set a valid outcome"
            )
    if problems:
        return None, problems
    sa = {key(s): s for s in a["spans"]}
    sb = {key(s): s for s in b["spans"]}
    agreed = [sa[k] for k in sorted(sa.keys() & sb.keys())]
    kept = [
        {"start": d["start"], "end": d["end"], "label": d["label"], "text": d["text"]}
        for i, d in disputed.items()
        if i in keep
    ]
    spans = sorted(agreed + kept, key=lambda s: (s["start"], s["end"]))
    # adjudicator overrides of agreed spans (guideline decisions applied after both passes)
    if adj:
        drop = set(adj.get("drop", []))
        before = len(spans)
        spans = [s for s in spans if s["text"] not in drop]
        if drop and before - len(spans) == 0:
            problems.append(f"{did}: drop matched no span: {sorted(drop)}")
        for r in adj.get("relabel", []):
            hit = [s for s in spans if s["text"] == r["text"]]
            if not hit or r["label"] not in LABELS:
                problems.append(f"{did}: relabel {r!r} matched no span or unknown label")
            for s in hit:
                s = dict(s)
                s["label"] = r["label"]
                spans = [s if x["text"] == r["text"] else x for x in spans]
        for a_ in adj.get("add", []):
            occ = occurrences(text, a_["text"])
            n = int(a_.get("occurrence", 1))
            if a_.get("label") not in LABELS or not occ or not 1 <= n <= len(occ):
                problems.append(f"{did}: add {a_!r}: {len(occ)} occurrence(s) found")
                continue
            s0, e0 = occ[n - 1]
            spans.append({"start": s0, "end": e0, "label": a_["label"], "text": text[s0:e0]})
        spans.sort(key=lambda s: (s["start"], s["end"]))
    for s1, s2 in zip(spans, spans[1:], strict=False):
        if s2["start"] < s1["end"]:
            problems.append(f"{did}: kept spans overlap: {s1['text']!r} / {s2['text']!r}")
    if problems:
        return None, problems
    return {
        "decision_id": did,
        "task_index": a["task_index"],
        "outcome": outcome,
        "spans": [{k: s[k] for k in ("start", "end", "label", "text")} for s in spans],
        "n_agreed": len(agreed),
        "n_disputed": len(disputed),
        "n_kept": len(kept),
        "outcome_conflict": outcome_conflict,
        "comment": (adj or {}).get("comment", ""),
    }, []


def to_ls_result(rec: dict) -> list[dict]:
    res = [
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
        for s in rec["spans"]
    ]
    res.append(
        {
            "from_name": "outcome",
            "to_name": "text",
            "type": "choices",
            "value": {"choices": [rec["outcome"]]},
        }
    )
    if rec.get("comment"):
        res.append(
            {
                "from_name": "comment",
                "to_name": "text",
                "type": "textarea",
                "value": {"text": [rec["comment"]]},
            }
        )
    return res


def main() -> None:
    args = sys.argv[1:]
    report = json.loads(DIS.read_text()) if DIS.exists() else {}
    tasks = load_tasks()
    dids = [t["data"]["decision_id"] for t in tasks]
    if args[:1] == ["--check"]:
        did = args[1]
        a = json.loads((BATCH_DIR / "ann" / PA / f"{did}.json").read_text())
        b = json.loads((BATCH_DIR / "ann" / PB / f"{did}.json").read_text())
        text = next(t["data"]["text"] for t in tasks if t["data"]["decision_id"] == did)
        rec, problems = resolve(did, report, a, b, text)
        if problems:
            print("problems:\n - " + "\n - ".join(problems))
            raise SystemExit(1)
        assert rec
        print(
            f"OK {did}: {len(rec['spans'])} spans ({rec['n_agreed']} agreed + {rec['n_kept']} kept of {rec['n_disputed']} disputed), outcome={rec['outcome']}"
        )
        return
    records: list[dict] = []
    pending: list[str] = []
    texts = {t["data"]["decision_id"]: t["data"]["text"] for t in tasks}
    for did in dids:
        pa, pb = BATCH_DIR / "ann" / PA / f"{did}.json", BATCH_DIR / "ann" / PB / f"{did}.json"
        if not (pa.exists() and pb.exists()):
            pending.append(f"{did}: missing pass {PA if not pa.exists() else PB}")
            continue
        rec, problems = resolve(
            did, report, json.loads(pa.read_text()), json.loads(pb.read_text()), texts[did]
        )
        if problems:
            pending.extend(problems)
        else:
            records.append(rec)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    print(f"gold records written: {len(records)}/{len(dids)} -> {OUT}")
    if pending:
        print(f"pending ({len(pending)}):")
        for p in pending:
            print(" -", p)
    if "--import" in args:
        from labelstudio_api import Client

        c = Client()
        ls_tasks = c.call("GET", "/api/tasks?project=1&page_size=500")
        items = ls_tasks["tasks"] if isinstance(ls_tasks, dict) else ls_tasks
        by_did = {t["data"]["decision_id"]: t["id"] for t in items}
        n = n_replaced = 0
        for rec in records:
            tid = by_did[rec["decision_id"]]
            existing = c.call("GET", f"/api/tasks/{tid}/annotations")
            gt = [an for an in existing if an.get("ground_truth")]
            body = {"result": to_ls_result(rec), "ground_truth": True, "was_cancelled": False}
            if gt and "--replace" in args:
                c.call("PATCH", f"/api/annotations/{gt[0]['id']}", body)
                n_replaced += 1
                continue
            if gt:
                continue
            c.call("POST", f"/api/tasks/{tid}/annotations", body)
            n += 1
        print(
            f"Label Studio project 1: {n} ground-truth annotations imported, {n_replaced} replaced"
        )


if __name__ == "__main__":
    main()
