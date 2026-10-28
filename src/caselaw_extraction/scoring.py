"""Score a prediction file against a gold batch; shared by the CLI and the training commands."""

from __future__ import annotations

from pathlib import Path

from caselaw_extraction.evaluate import (
    PRF,
    EntityScores,
    Scores,
    entity_keys,
    format_entity_table,
    format_label_confusion,
    format_table,
    score_decision,
)
from caselaw_extraction.gold import CITATION_LABELS, LABELS, load_gold, read_predictions


def macro_f1(confusion, classes: list[str]) -> float:
    """Mean F1 over the classes that occur in the gold labels."""
    f1s = []
    for c in classes:
        prf = PRF()
        for (g, p), n in confusion.items():
            if g == c and p == c:
                prf.tp += n
            elif p == c:
                prf.fp += n
            elif g == c:
                prf.fn += n
        f1s.append(prf.f1)
    return sum(f1s) / len(f1s) if f1s else 0.0


def score_file(
    pred: Path,
    batch: str,
    labels: tuple[str, ...] = CITATION_LABELS,
    only_ids: set[str] | None = None,
) -> tuple[str, dict[str, float]]:
    """Span scores over `labels` (default: the five citation classes, so that every extractor is
    comparable), entity scores, outcome scores, and the label confusion over all classes.
    `only_ids` restricts the gold to a subset of decisions (learning-curve hold-out halves)."""
    gold = load_gold(batch)
    if only_ids is not None:
        gold = [g for g in gold if g.decision_id in only_ids]
    preds = read_predictions(pred)
    sc, ent = Scores(labels=labels), EntityScores()
    title = f"{pred} vs {batch} gold ({len(gold)} decisions)"
    for g in gold:
        p = preds.get(g.decision_id, {"spans": [], "outcome": "unknown"})
        score_decision(
            sc,
            [(s["start"], s["end"], s["label"]) for s in p["spans"]],
            g.span_keys(),
            p["outcome"],
            g.outcome,
        )
        ent.add(entity_keys(p["spans"], g.text), entity_keys(g.spans, g.text))
    gold_classes = sorted({g.outcome for g in gold})
    mf1 = macro_f1(sc.confusion, gold_classes)
    tables = (
        format_table(sc, f"span level: {title}")
        + f"\nOutcome macro-F1 over {len(gold_classes)} gold classes: {mf1:.3f}\n\n"
        + format_entity_table(ent, f"entity level: {title}")
        + "\n\n"
        + format_label_confusion(sc, f"label confusion (overlapping spans): {title}")
    )
    metrics = {
        "span_f1_exact": sc.micro("exact").f1,
        "span_f1_overlap": sc.micro("overlap").f1,
        "entity_f1": ent.micro().f1,
        "outcome_acc": sc.outcome["correct"] / max(1, sc.outcome["total"]),
        "outcome_macro_f1": mf1,
        **{f"f1_{lab}": sc.exact[lab].f1 for lab in sc.exact},
        **{
            f"confusion_{g}_as_{p}": float(n)
            for (g, p), n in sc.label_confusion.items()
            if g != p and g in LABELS and p in LABELS
        },
    }
    return tables, metrics


def score_silver(batch: str) -> tuple[str, dict[str, float]]:
    from caselaw_extraction.silver import silver_entities

    gold = load_gold(batch)
    ent = EntityScores()
    silver = silver_entities([g.decision_id for g in gold])
    for g in gold:
        ent.add(silver[g.decision_id], entity_keys(g.spans, g.text))
    tables = format_entity_table(
        ent, f"entity level: silver vs {batch} gold ({len(gold)} decisions)"
    )
    return tables, {"entity_f1": ent.micro().f1}
