"""Entity linking: the stage after any extractor.

A span model reads only the text. Two facts that decide whether a span is a citation are not
in the text: the list of Swiss federal acts (Fedlex) and the file number(s) of the decision
itself. This stage holds that knowledge for every extractor alike, including the regex. It
resolves each span to an identifier and drops the spans that resolve to nothing:

| label   | link                                   | dropped when                          |
|---------|----------------------------------------|---------------------------------------|
| STATUTE | (abbreviation, SR number, article)     | no code in the span is a federal act  |
| BGE     | `BGE <volume> <part> <page>`           | the span has no volume/part/page      |
| DOCKET  | normalised file number `4A_12_2020`    | it is the decision's own file number  |
| AMOUNT, PARTY_ROLE | none                        | never                                 |

The stage never changes a span boundary and never adds a span. Scores before and after linking
are reported side by side, so that a learning failure that the linking hides stays visible in
the "before" column.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from caselaw_extraction.evaluate import bge_key, norm_docket, statute_keys
from caselaw_extraction.fedlex import resolve_code
from caselaw_extraction.regex_extractor import own_dockets

REASONS = ("unknown_code", "no_article", "no_bge_key", "own_docket")
_DIGIT = re.compile(r"\d")


def docket_of(decision_id: str) -> str | None:
    """`bger_4A_12_2020` -> `4A_12/2020`; None when the id has another shape."""
    m = re.fullmatch(r"bger_(\d[A-Z])_(\d+)_(\d{4})", decision_id)
    return f"{m.group(1)}_{m.group(2)}/{m.group(3)}" if m else None


def link_spans(
    text: str, decision_id: str, spans: list[dict], code_map: dict[str, str]
) -> tuple[list[dict], Counter]:
    """Return (linked spans, drop counts by reason). Each kept span gets a `link` field."""
    own = {norm_docket(d) for d in own_dockets(text, docket_of(decision_id))}
    kept: list[dict] = []
    dropped: Counter = Counter()
    for s in spans:
        lab, t = s["label"], s["text"]
        out = dict(s)
        if lab == "STATUTE":
            if not _DIGIT.search(t):
                dropped["no_article"] += 1
                continue
            links = []
            for code, art in statute_keys(t):
                hit = resolve_code(code, code_map)
                if hit:
                    links.append({"code": hit[0], "sr": hit[1], "article": art})
            if not links:
                dropped["unknown_code"] += 1
                continue
            out["link"] = links
        elif lab == "BGE":
            k = bge_key(t, text, s["start"])
            if not k:
                dropped["no_bge_key"] += 1
                continue
            out["link"] = k
        elif lab == "DOCKET":
            key = norm_docket(t)
            if key in own:
                dropped["own_docket"] += 1
                continue
            out["link"] = key
        kept.append(out)
    return kept, dropped


def linked_name(pred: Path) -> Path:
    return pred.with_name(pred.stem + "-linked.jsonl")


def link_file(
    pred: Path, texts: dict[str, str], code_map: dict[str, str]
) -> tuple[Path, Counter, int]:
    """Link every decision of a prediction file; write `<name>-linked.jsonl`.

    Returns (output path, drop counts, number of spans before linking)."""
    total = Counter()
    n_before = 0
    out_lines = []
    for line in pred.read_text().splitlines():
        r = json.loads(line)
        n_before += len(r["spans"])
        r["spans"], dropped = link_spans(
            texts[r["decision_id"]], r["decision_id"], r["spans"], code_map
        )
        total += dropped
        out_lines.append(json.dumps(r, ensure_ascii=False))
    out = linked_name(pred)
    out.write_text("".join(ln + "\n" for ln in out_lines))
    return out, total, n_before


def format_drop_table(rows: list[tuple[str, int, Counter]]) -> str:
    lines = [
        "| prediction file | spans | " + " | ".join(REASONS) + " | kept |",
        "|---|---|" + "---|" * len(REASONS) + "---|",
    ]
    for name, n, c in rows:
        drop = sum(c.values())
        lines.append(
            f"| {name} | {n} | " + " | ".join(str(c[r]) for r in REASONS) + f" | {n - drop} |"
        )
    return "\n".join(lines)
