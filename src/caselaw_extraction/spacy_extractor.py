"""spaCy extractors trained from zero on a gold batch.

Two small models: a NER model for the five span labels and a text classifier for the outcome,
which reads the ruling section only. Both use spaCy's default CPU architectures
(hash embeddings + CNN); no pretrained weights are involved.
"""

from __future__ import annotations

import random
import warnings
from pathlib import Path

import spacy
from spacy.language import Language
from spacy.training import Example
from spacy.util import compounding, minibatch

from caselaw_extraction.gold import (
    LABELS,
    OUTCOMES,
    Decision,
    dedupe,
    dispositiv,
    spans_in,
    windows,
)

MODELS = Path("models")


def _blank() -> Language:
    return spacy.blank("de")


def ner_examples(nlp: Language, decisions: list[Decision]) -> tuple[list[Example], int, int]:
    """Window-level examples. Returns (examples, n_spans, n_misaligned)."""
    examples: list[Example] = []
    n_spans = n_mis = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # W030 misaligned entities are counted below
        for d in decisions:
            for a, b in windows(d.text, d.spans):
                wtext = d.text[a:b]
                ents = [(s["start"], s["end"], s["label"]) for s in spans_in(d.spans, a, b)]
                doc = nlp.make_doc(wtext)
                ex = Example.from_dict(doc, {"entities": ents})
                n_spans += len(ents)
                n_mis += len(ents) - len(ex.reference.ents)
                examples.append(ex)
    return examples, n_spans, n_mis


def train_ner(
    train: list[Decision], epochs: int = 20, seed: int = 0, drop: float = 0.2
) -> tuple[Language, dict]:
    random.seed(seed)
    spacy.util.fix_random_seed(seed)
    nlp = _blank()
    ner = nlp.add_pipe("ner")
    for lab in LABELS:
        ner.add_label(lab)
    examples, n_spans, n_mis = ner_examples(nlp, train)
    optimizer = nlp.initialize(lambda: examples)
    history = []
    for _ep in range(epochs):
        random.shuffle(examples)
        losses: dict[str, float] = {}
        for batch in minibatch(examples, size=compounding(4.0, 32.0, 1.001)):
            nlp.update(batch, drop=drop, sgd=optimizer, losses=losses)
        history.append(losses.get("ner", 0.0))
    info = {
        "n_windows": len(examples),
        "n_spans": n_spans,
        "n_misaligned": n_mis,
        "loss_history": history,
    }
    return nlp, info


def predict_ner(nlp: Language, decisions: list[Decision]) -> None:
    for d in decisions:
        spans: list[dict] = []
        wins = windows(d.text, [])
        docs = nlp.pipe([d.text[a:b] for a, b in wins], batch_size=32)
        for (a, _b), doc in zip(wins, docs, strict=True):
            for e in doc.ents:
                spans.append(
                    {
                        "start": a + e.start_char,
                        "end": a + e.end_char,
                        "label": e.label_,
                        "text": e.text,
                    }
                )
        d.spans = dedupe(spans)


def train_textcat(train: list[Decision], epochs: int = 30, seed: int = 0) -> Language:
    random.seed(seed)
    spacy.util.fix_random_seed(seed)
    nlp = _blank()
    textcat = nlp.add_pipe("textcat")
    for o in OUTCOMES:
        textcat.add_label(o)
    examples = [
        Example.from_dict(
            nlp.make_doc(dispositiv(d.text)), {"cats": {o: float(o == d.outcome) for o in OUTCOMES}}
        )
        for d in train
    ]
    optimizer = nlp.initialize(lambda: examples)
    for _ in range(epochs):
        random.shuffle(examples)
        for batch in minibatch(examples, size=8):
            nlp.update(batch, drop=0.2, sgd=optimizer)
    return nlp


def predict_textcat(nlp: Language, decisions: list[Decision]) -> None:
    for d in decisions:
        doc = nlp(dispositiv(d.text))
        d.outcome = max(doc.cats, key=doc.cats.get) if doc.cats else "unknown"


def save(nlp: Language, name: str) -> Path:
    out = MODELS / name
    out.mkdir(parents=True, exist_ok=True)
    nlp.to_disk(out)
    return out
