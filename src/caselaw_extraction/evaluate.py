"""Span-level scoring of an extractor against the gold set.

Exact match: a predicted span counts as correct when (start, end, label) is in the gold set.
Overlap match: a predicted span counts as correct when it shares the label and overlaps a gold
span that no other prediction has claimed. Both are reported; exact is the headline number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

LABELS = ("STATUTE", "BGE", "DOCKET", "AMOUNT", "PARTY_ROLE")  # the citation classes
SpanKey = tuple[int, int, str]


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def add(self, other: PRF) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn


@dataclass
class Scores:
    """Span scores over one label set. Spans with a label outside `labels` are ignored on both
    sides, so an extractor that only knows the five citation classes is scored on those, and the
    negative classes of guideline v0.2 are scored when `labels` includes them."""

    labels: tuple[str, ...] = LABELS
    exact: dict[str, PRF] = field(default_factory=dict)
    overlap: dict[str, PRF] = field(default_factory=dict)
    outcome: Counter = field(default_factory=Counter)  # keys: correct, total
    confusion: Counter = field(default_factory=Counter)  # (gold, pred) -> n
    label_confusion: Counter = field(default_factory=Counter)  # (gold label|O, pred label|O)

    def __post_init__(self) -> None:
        self.exact = self.exact or {lab: PRF() for lab in self.labels}
        self.overlap = self.overlap or {lab: PRF() for lab in self.labels}

    def micro(self, kind: str = "exact") -> PRF:
        tot = PRF()
        for prf in getattr(self, kind).values():
            tot.add(prf)
        return tot


def _exact(pred: list[SpanKey], gold: list[SpanKey], labels) -> dict[str, PRF]:
    out = {lab: PRF() for lab in labels}
    ps, gs = set(pred), set(gold)
    for k in ps & gs:
        out[k[2]].tp += 1
    for k in ps - gs:
        out[k[2]].fp += 1
    for k in gs - ps:
        out[k[2]].fn += 1
    return out


def _overlap(pred: list[SpanKey], gold: list[SpanKey], labels) -> dict[str, PRF]:
    out = {lab: PRF() for lab in labels}
    unclaimed = set(gold)
    for p in sorted(pred):
        hit = next(
            (g for g in sorted(unclaimed) if g[2] == p[2] and g[0] < p[1] and p[0] < g[1]), None
        )
        if hit:
            unclaimed.discard(hit)
            out[p[2]].tp += 1
        else:
            out[p[2]].fp += 1
    for g in unclaimed:
        out[g[2]].fn += 1
    return out


def _label_confusion(pred: list[SpanKey], gold: list[SpanKey]) -> Counter:
    """(gold label, pred label) for every overlapping pair, over all labels; a gold span with no
    overlapping prediction counts as (gold, O), a prediction over no gold span as (O, pred).
    This is where a STATUTE predicted on a CONTRACT_ARTICLE becomes visible."""
    out: Counter = Counter()
    claimed_p: set[SpanKey] = set()
    for g in gold:
        hits = [p for p in pred if g[0] < p[1] and p[0] < g[1]]
        if not hits:
            out[(g[2], "O")] += 1
        for p in hits:
            out[(g[2], p[2])] += 1
            claimed_p.add(p)
    for p in pred:
        if p not in claimed_p:
            out[("O", p[2])] += 1
    return out


def score_decision(
    scores: Scores,
    pred_spans: list[SpanKey],
    gold_spans: list[SpanKey],
    pred_outcome: str | None = None,
    gold_outcome: str | None = None,
) -> None:
    scores.label_confusion.update(_label_confusion(pred_spans, gold_spans))
    labs = set(scores.labels)
    pred_spans = [k for k in pred_spans if k[2] in labs]
    gold_spans = [k for k in gold_spans if k[2] in labs]
    for lab, prf in _exact(pred_spans, gold_spans, scores.labels).items():
        scores.exact[lab].add(prf)
    for lab, prf in _overlap(pred_spans, gold_spans, scores.labels).items():
        scores.overlap[lab].add(prf)
    if gold_outcome is not None:
        scores.outcome["total"] += 1
        scores.outcome["correct"] += pred_outcome == gold_outcome
        scores.confusion[(gold_outcome, pred_outcome)] += 1


def format_table(scores: Scores, title: str) -> str:
    lines = [
        f"## {title}",
        "",
        "| Label | Gold | Pred | P (exact) | R (exact) | F1 (exact) | F1 (overlap) |",
        "|---|---|---|---|---|---|---|",
    ]
    for lab in scores.labels:
        e, o = scores.exact[lab], scores.overlap[lab]
        lines.append(
            f"| {lab} | {e.tp + e.fn} | {e.tp + e.fp} | {e.precision:.3f} | {e.recall:.3f} "
            f"| {e.f1:.3f} | {o.f1:.3f} |"
        )
    e, o = scores.micro("exact"), scores.micro("overlap")
    lines.append(
        f"| **all (micro)** | {e.tp + e.fn} | {e.tp + e.fp} | {e.precision:.3f} | {e.recall:.3f} "
        f"| **{e.f1:.3f}** | {o.f1:.3f} |"
    )
    if scores.outcome["total"]:
        acc = scores.outcome["correct"] / scores.outcome["total"]
        lines += [
            "",
            f"Outcome accuracy: {scores.outcome['correct']}/{scores.outcome['total']} = {acc:.3f}",
        ]
        wrong = [(k, v) for k, v in scores.confusion.items() if k[0] != k[1]]
        if wrong:
            lines.append(
                "Outcome errors (gold -> pred: n): "
                + ", ".join(f"{g} -> {p}: {n}" for (g, p), n in sorted(wrong, key=lambda x: -x[1]))
            )
    return "\n".join(lines)


def format_label_confusion(scores: Scores, title: str) -> str:
    """Rows = gold label, columns = predicted label, cells = overlapping span pairs."""
    labs = sorted({a for a, _ in scores.label_confusion} | {b for _, b in scores.label_confusion})
    labs = [lab for lab in labs if lab != "O"] + ["O"]
    lines = [
        f"## {title}",
        "",
        "| gold \\ pred | " + " | ".join(labs) + " |",
        "|---|" + "---|" * len(labs),
    ]
    for g in labs:
        row = [
            str(scores.label_confusion.get((g, p), 0)) if (g, p) != ("O", "O") else "" for p in labs
        ]
        lines.append(f"| {g} | " + " | ".join(row) + " |")
    return "\n".join(lines)


# --- entity level ---------------------------------------------------------------------------------
# A citation graph needs normalised keys, not character offsets. The third-party silver graph
# that ships with the dataset has no offsets, so it can only be compared at this level.

import re as _re  # noqa: E402

from caselaw_extraction import regex_extractor as _rx  # noqa: E402

ENTITY_LABELS = ("STATUTE", "BGE", "DOCKET")
_BGE_KEY_RE = _re.compile(r"(\d{1,3})\s+(Ia|Ib|IV|V|III|II|I)\s+(\d{1,4})")
_ART_TOKEN_RE = _re.compile(r"(?<![\w.])(\d{1,4}[a-z]{0,10})(?![\w/])")


def norm_docket(s: str) -> str:
    s = _re.sub(r"\s+", "", s)
    return s.replace("/", "_").replace(".", "_")


def statute_keys(span_text: str) -> set[tuple[str, str]]:
    """(code, article) for every article in a statute chain. Falls back to a loose parse for
    chains the strict pattern does not accept (typos, unknown abbreviations)."""
    m = _rx.STATUTE_RE.search(span_text)
    if m:
        code = " ".join(m.group("code").split())  # keep a year ("EPÜ 2000"); drop "SchlT"
        code = code.removeprefix("SchlT ")
        return {(code, u.group("art")) for u in _rx._UNIT_RE.finditer(m.group("units"))}
    toks = span_text.split()
    code = toks[-1] if toks else span_text
    arts = _ART_TOKEN_RE.findall(span_text)
    return {(code, a) for a in arts} or {(code, span_text)}


_BARE_PAGE_RE = _re.compile(r"^\d{1,4}$")


def bge_key(span_text: str, text: str | None = None, start: int = 0) -> str | None:
    """`BGE vol part page` for a BGE span. A bare page number (guideline v0.3 short citation,
    `BGE 140 III 86 E. 2, 115 E. 2`) inherits volume and part from the nearest full citation
    in the 150 characters before it; without the text it has no key."""
    m = _BGE_KEY_RE.search(span_text)
    if m:
        return f"BGE {m.group(1)} {m.group(2)} {m.group(3)}"
    if text is not None and _BARE_PAGE_RE.match(span_text.strip()):
        prev = list(_BGE_KEY_RE.finditer(text, max(0, start - 150), start))
        if prev:
            p = prev[-1]
            return f"BGE {p.group(1)} {p.group(2)} {span_text.strip()}"
    return None


def entity_keys(spans: list[dict], text: str | None = None) -> dict[str, set]:
    out: dict[str, set] = {lab: set() for lab in ENTITY_LABELS}
    for s in spans:
        lab, t = s["label"], s["text"]
        if lab == "STATUTE":
            out[lab] |= {f"{c.upper()} {a}" for c, a in statute_keys(t)}
        elif lab == "BGE":
            k = bge_key(t, text, s.get("start", 0))
            if k:
                out[lab].add(k)
        elif lab == "DOCKET":
            out[lab].add(norm_docket(t))
    return out


@dataclass
class EntityScores:
    prf: dict[str, PRF] = field(default_factory=lambda: {lab: PRF() for lab in ENTITY_LABELS})

    def add(self, pred: dict[str, set], gold: dict[str, set]) -> None:
        for lab in ENTITY_LABELS:
            p, g = pred.get(lab, set()), gold.get(lab, set())
            self.prf[lab].tp += len(p & g)
            self.prf[lab].fp += len(p - g)
            self.prf[lab].fn += len(g - p)

    def micro(self) -> PRF:
        tot = PRF()
        for prf in self.prf.values():
            tot.add(prf)
        return tot


def format_entity_table(scores: EntityScores, title: str) -> str:
    lines = [
        f"## {title}",
        "",
        "| Entity | Gold | Pred | P | R | F1 |",
        "|---|---|---|---|---|---|",
    ]
    for lab in ENTITY_LABELS:
        e = scores.prf[lab]
        lines.append(
            f"| {lab} | {e.tp + e.fn} | {e.tp + e.fp} | {e.precision:.3f} | {e.recall:.3f} "
            f"| {e.f1:.3f} |"
        )
    e = scores.micro()
    lines.append(
        f"| **all (micro)** | {e.tp + e.fn} | {e.tp + e.fp} | {e.precision:.3f} | {e.recall:.3f} "
        f"| **{e.f1:.3f}** |"
    )
    return "\n".join(lines)
