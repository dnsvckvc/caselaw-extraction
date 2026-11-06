"""Pilot, subproject 2: citation treatment with Jev 1.14 against Haiku 5.5, on 300 labelled windows.

    uv run python scripts/jev/treatment.py sample          # data/gold/treatment/windows.jsonl
    op run --env-file scripts/jev/openrouter.op.env -- \
      uv run python scripts/jev/treatment.py predict <jev|haiku> <dev|test>
    uv run python scripts/jev/treatment.py report <dev|test|confirm>
    uv run python scripts/jev/treatment.py sample-confirm  # appends 150 random windows, part "confirm"

Windows come from decisions outside the pool that was read to write the guideline (hash % 10 != 0), at most one per
decision: 150 at random and 150 that match the keyword filter, so that rare classes appear. Sixty are dev (30 + 30).
See docs/citation-treatment-guideline.md.

The confirm part checks the routine filter that was chosen after the test results (docs/jev-treatment.md): 150 random
windows from decisions that the first 300 windows did not use.
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import numpy as np
from sklearn.metrics import accuracy_score, f1_score

from caselaw_extraction import tracking
from caselaw_extraction.treatment import (
    AFTER,
    BEFORE,
    CRITERIA,
    INSTRUCTIONS,
    JEV,
    _post,
    call_jev,
    window,
)

GOLD = Path("data/gold/treatment")
WINDOWS = GOLD / "windows.jsonl"
KEYWORDS = re.compile(
    r"beruf(?:t|en) sich|verweis(?:t|en) auf|macht geltend|machen geltend|abweich|Praxisänderung|anders als"
    r"|nicht einschlägig|nicht vergleichbar|nicht übertragbar|unterscheidet sich|offen ?(?:ge)?lass|entgegen"
    r"|im Gegensatz|präzisier|Rückweisung|in dieser Sache|Vorinstanz (?:erwog|stützt|verwies)",
    re.I,
)
LABELS_FILE = GOLD / "labels.jsonl"
OUT = Path("data/pred/treatment")
HAIKU = "anthropic/claude-haiku-5.5"
MAX_COST_USD = 1.0
WORKERS = 8
ROUTINE_RE = re.compile(r"\bBGG\b")


def call_haiku(text: str, key: str) -> dict:
    labels = "\n".join(f"- {k}: {v}" for k, v in CRITERIA.items())
    body = {
        "model": HAIKU,
        "temperature": 0,
        # Haiku 5.5 sometimes starts hidden reasoning and used up 50 tokens before the label
        "max_tokens": 200,
        "reasoning": {"enabled": False},
        "usage": {"include": True},
        "messages": [
            {"role": "system", "content": f"{INSTRUCTIONS}\n\nKategorien:\n{labels}"},
            {"role": "user", "content": f"Ausschnitt:\n{text}"},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "treatment",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"label": {"type": "string", "enum": list(CRITERIA)}},
                    "required": ["label"],
                    "additionalProperties": False,
                },
            },
        },
    }
    r = _post("/v1/chat/completions", body, key)
    choice = r["choices"][0]
    if not choice["message"].get("content"):
        # keep the raw response so that the cause (refusal, length, provider error) can be read
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "haiku-empty.jsonl").open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        raise RuntimeError(
            f"empty content, finish_reason {choice.get('finish_reason')}, "
            f"native {choice.get('native_finish_reason')}, refusal {choice['message'].get('refusal')!r}"
        )
    return {
        "model": r.get("model"),
        "pred": json.loads(choice["message"]["content"])["label"],
        "confidence": None,
        "probabilities": None,
        "input_tokens": r["usage"]["prompt_tokens"],
        "output_tokens": r["usage"]["completion_tokens"],
        "cost": r["usage"].get("cost"),
        "latency_s": r["latency_s"],
    }


def predict(which: str, part: str) -> None:
    key = os.environ["OPENROUTER_API_KEY"]
    fn = {"jev": call_jev, "haiku": call_haiku}[which]
    rows = [json.loads(ln) for ln in WINDOWS.read_text().splitlines()]
    rows = [r for r in rows if r["part"] == part]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{which}-{part}.jsonl"
    done = [json.loads(ln) for ln in path.read_text().splitlines()] if path.exists() else []
    seen = {d["span_id"] for d in done}
    spent = sum(d["cost"] or 0 for d in done)
    todo = [r for r in rows if r["span_id"] not in seen]
    errors = 0

    def one(r: dict) -> tuple[dict, dict | None, str]:
        try:
            return r, fn(r["window"], key), ""
        except Exception as e:  # noqa: BLE001 - the error is counted and the window can be rerun
            return r, None, str(e)

    with path.open("a") as f, ThreadPoolExecutor(WORKERS) as pool:
        for n in range(0, len(todo), WORKERS * 5):
            if spent >= MAX_COST_USD:
                print(f"stopped at the spending cap, USD {spent:.4f}")
                break
            for r, out, err in pool.map(one, todo[n : n + WORKERS * 5]):
                if out is None:
                    errors += 1
                    print(r["span_id"], err[:200])
                    continue
                spent += out["cost"] or 0
                f.write(json.dumps({"span_id": r["span_id"], **out}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{min(n + WORKERS * 5, len(todo))}/{len(todo)} USD {spent:.4f}", flush=True)
    print(f"done, errors {errors}, USD {spent:.4f}")


def _score(y: list[str], p: list[str]) -> dict[str, float]:
    yb = [v == "routine_standard" for v in y]
    pb = [v == "routine_standard" for v in p]
    return {
        "n": len(y),
        "accuracy": accuracy_score(y, p),
        "macro_f1": f1_score(y, p, labels=list(CRITERIA), average="macro", zero_division=0),
        "routine_binary_f1": f1_score(yb, pb, zero_division=0),
        "routine_binary_accuracy": accuracy_score(yb, pb),
    }


def report(part: str) -> None:
    meta = {r["span_id"]: r for r in map(json.loads, WINDOWS.read_text().splitlines())}
    gold = {r["span_id"]: r["label"] for r in map(json.loads, LABELS_FILE.read_text().splitlines())}
    ids = [i for i, m in meta.items() if m["part"] == part and gold[i] != "unclear"]
    print(
        "gold",
        Counter(gold[i] for i in ids),
        "unclear left out",
        sum(gold[i] == "unclear" and m["part"] == part for i, m in meta.items()),
    )
    preds = {}
    for w in ("jev", "haiku"):
        path = OUT / f"{w}-{part}.jsonl"
        if path.exists():
            preds[w] = {r["span_id"]: r for r in map(json.loads, path.read_text().splitlines())}
    for w, d in preds.items():
        # a window without an answer counts as wrong; the statistics below skip it
        if missing := [i for i in ids if i not in d]:
            print(f"{w}: {len(missing)} windows without an answer, counted as wrong")
        d.update({i: {"pred": "no_answer"} for i in missing})
    results = {}
    for stratum in ("random", "targeted", "all"):
        sub = [i for i in ids if stratum == "all" or meta[i]["stratum"] == stratum]
        if not sub:
            continue
        y = [gold[i] for i in sub]
        res = {
            "regex_bgg": _score(
                y,
                [
                    "routine_standard"
                    if ROUTINE_RE.search(meta[i]["window"])
                    else "substantive_rule"
                    for i in sub
                ],
            )
        }
        res["majority"] = _score(y, ["routine_standard"] * len(y))
        for w, d in preds.items():
            res[w] = _score(y, [d[i]["pred"] or "refused" for i in sub])
        results[stratum] = res
        print(f"\n{stratum}")
        for name, m in res.items():
            print(name, {k: round(v, 3) for k, v in m.items()})
    for w, d in preds.items():
        y = [gold[i] for i in ids]
        p = [d[i]["pred"] for i in ids]
        answered = np.array(["cost" in d[i] for i in ids])
        right = np.array([a == b for a, b in zip(y, p, strict=True)])[answered]
        print(f"\n{w}: class | n | recall | precision")
        for c in CRITERIA:
            a, b = np.array(y) == c, np.array(p) == c
            print(
                f"{c} | {a.sum()} | {(a & b).sum() / max(a.sum(), 1):.2f} | {(a & b).sum() / max(b.sum(), 1):.2f}"
            )
        print(
            "confusions",
            Counter((a, b) for a, b in zip(y, p, strict=True) if a != b).most_common(10),
        )
        marked = [g for g, q in zip(y, p, strict=True) if q == "routine_standard"]
        hit = sum(g == "routine_standard" for g in marked)
        print(
            f"routine filter: marked {len(marked)}, precision {hit / max(len(marked), 1):.3f}, recall {hit / max(y.count('routine_standard'), 1):.3f}"
        )
        rows = [d[i] for i in ids if "cost" in d[i]]
        print(
            "usd",
            round(sum(r["cost"] or 0 for r in rows), 5),
            "tokens in",
            np.mean([r["input_tokens"] for r in rows]),
            "tokens out",
            np.mean([r["output_tokens"] or 0 for r in rows]),
            "latency p50",
            round(float(np.median([r["latency_s"] for r in rows])), 3),
            "p95",
            round(float(np.percentile([r["latency_s"] for r in rows], 95)), 3),
            "models",
            sorted({r["model"] for r in rows}),
        )
        if rows[0]["probabilities"]:
            top = np.array([max(r["probabilities"].values()) for r in rows])
            print("top probability | n | mean | accuracy")
            edges = [0, 0.7, 0.8, 0.9, 0.95, 1.0001]
            for lo, hi in zip(edges, edges[1:], strict=False):
                k = (top >= lo) & (top < hi)
                if k.any():
                    print(
                        f"{lo:.2f}-{min(hi, 1):.2f} | {k.sum()} | {top[k].mean():.3f} | {right[k].mean():.3f}"
                    )
            ece = sum(
                (k.mean() * abs(right[k].mean() - top[k].mean()))
                for b in range(10)
                if (k := np.minimum((top * 10).astype(int), 9) == b).any()
            )
            print("ece_top", round(float(ece), 3))
    if len(preds) == 2:
        j = np.array([preds["jev"][i]["pred"] == gold[i] for i in ids])
        h = np.array([preds["haiku"][i]["pred"] == gold[i] for i in ids])
        rng = np.random.default_rng(0)
        idx = rng.integers(0, len(ids), (2000, len(ids)))
        d = j[idx].mean(1) - h[idx].mean(1)
        print(
            f"\nJev minus Haiku accuracy {j.mean() - h.mean():+.3f}, 95% bootstrap [{np.percentile(d, 2.5):+.3f}, {np.percentile(d, 97.5):+.3f}]; Jev only right {(j & ~h).sum()}, Haiku only right {(h & ~j).sum()}"
        )
        if part == "test":
            with tracking.run("jev-1.14-treatment", {"models": f"{JEV},{HAIKU}"}) as log:
                log.metrics({f"{w}_{k}": v for w in preds for k, v in results["all"][w].items()})


def sample() -> None:
    rows = duckdb.sql("""
        SELECT c.span_id, c.decision_id, c.kind, c.key, s.start, s."end", t.text
        FROM 'data/runs/regex-v0.4/citations.parquet' c
        JOIN 'data/runs/regex-v0.4/spans.parquet' s USING (span_id)
        JOIN 'data/runs/texts.parquet' t ON t.decision_id = c.decision_id
        WHERE c.kind IN ('bge', 'docket') AND hash(c.decision_id) % 10 <> 0
        ORDER BY c.span_id
    """).fetchall()
    rng = random.Random(5)
    rng.shuffle(rows)
    used, plain, targeted = set(), [], []
    for r in rows:
        if r[1] not in used and len(plain) < 150:
            used.add(r[1])
            plain.append(r)
    for r in rows:
        w = r[6][max(0, r[4] - BEFORE) : r[5] + AFTER]
        if r[1] not in used and KEYWORDS.search(w) and len(targeted) < 150:
            used.add(r[1])
            targeted.append(r)
    GOLD.mkdir(parents=True, exist_ok=True)
    out = []
    for stratum, group in (("random", plain), ("targeted", targeted)):
        for n, r in enumerate(group):
            out.append(
                {
                    "span_id": r[0],
                    "decision_id": r[1],
                    "kind": r[2],
                    "key": r[3],
                    "stratum": stratum,
                    "part": "dev" if n < 30 else "test",
                    "window": window(r[6], r[4], r[5]),
                }
            )
    rng.shuffle(out)
    WINDOWS.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
    print(len(out), "windows", sum(o["kind"] == "docket" for o in out), "file numbers")


def sample_confirm() -> None:
    old = [json.loads(ln) for ln in WINDOWS.read_text().splitlines()]
    assert not any(o["part"] == "confirm" for o in old), "confirm windows exist already"
    used = {o["decision_id"] for o in old}
    rows = duckdb.sql("""
        SELECT c.span_id, c.decision_id, c.kind, c.key, s.start, s."end", t.text
        FROM 'data/runs/regex-v0.4/citations.parquet' c
        JOIN 'data/runs/regex-v0.4/spans.parquet' s USING (span_id)
        JOIN 'data/runs/texts.parquet' t ON t.decision_id = c.decision_id
        WHERE c.kind IN ('bge', 'docket') AND hash(c.decision_id) % 10 <> 0
        ORDER BY c.span_id
    """).fetchall()
    rng = random.Random(7)
    rng.shuffle(rows)
    out = []
    for r in rows:
        if r[1] not in used and len(out) < 150:
            used.add(r[1])
            out.append(
                {
                    "span_id": r[0],
                    "decision_id": r[1],
                    "kind": r[2],
                    "key": r[3],
                    "stratum": "random",
                    "part": "confirm",
                    "window": window(r[6], r[4], r[5]),
                }
            )
    with WINDOWS.open("a") as f:
        f.write("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out))
    print(len(out), "confirm windows", sum(o["kind"] == "docket" for o in out), "file numbers")


if __name__ == "__main__":
    if sys.argv[1] == "sample":
        sample()
    elif sys.argv[1] == "sample-confirm":
        sample_confirm()
    elif sys.argv[1] == "predict":
        predict(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "report":
        report(sys.argv[2])
    else:
        raise SystemExit(__doc__)
