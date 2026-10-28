"""Learning curve: span F1 on the citation classes as a function of training-set size.

    uv run python scripts/learning_curve.py <spacy|gbert> main      # 15, 30, 45, 60 of batch 1 -> full batch 2
    uv run python scripts/learning_curve.py <spacy|gbert> extended  # 60..105 (batch 1 + part of batch 2) -> other half of batch 2
    uv run python scripts/learning_curve.py table                   # collect results from MLflow into a Markdown table

Main curve: the training set is the first N decisions of a seeded shuffle of batch 1 (shuffle
seed = training seed), evaluated on all 90 decisions of batch 2. Extended curve: batch 2 is split
once (seed 7) into a 45-decision training pool and a 45-decision test half; the training set is
all of batch 1 plus the first K of the pool, K in 0, 15, 30, 45; evaluated on the test half only.
The 60-point is run in both curves so that the two test sets can be compared. Only the span
models are trained (no outcome head). Every run is logged to MLflow as lc-<model>-<curve>-n<N>-s<seed>.
"""

from __future__ import annotations

import random
import sys
import time

from caselaw_extraction import tracking
from caselaw_extraction.gold import load_batch_texts, load_gold, write_predictions
from caselaw_extraction.scoring import score_file

MAIN_SIZES = (15, 30, 45, 60)
EXT_K = (0, 15, 30, 45)
SEEDS = {"main": (0, 1, 2), "extended": (0, 1)}
SPLIT_SEED = 7


def split_batch2() -> tuple[list[str], list[str]]:
    ids = sorted(g.decision_id for g in load_gold("batch2"))
    rng = random.Random(SPLIT_SEED)
    rng.shuffle(ids)
    return ids[:45], ids[45:]  # training pool, test half


def train_predict(model: str, train, ev, seed: int):
    t0 = time.time()
    if model == "spacy":
        from caselaw_extraction import spacy_extractor as sx

        nlp, info = sx.train_ner(train, epochs=20, seed=seed)
        sx.predict_ner(nlp, ev)
    else:
        from caselaw_extraction import transformer_extractor as tx

        tok, mdl, info = tx.train_token_classifier(train, "deepset/gbert-base", epochs=4, seed=seed)
        tx.predict_token_classifier(tok, mdl, ev)
    return time.time() - t0, info


def run(model: str, curve: str) -> None:
    b1 = load_gold("batch1")
    b2 = {g.decision_id: g for g in load_gold("batch2")}
    pool, test_half = split_batch2()
    points = MAIN_SIZES if curve == "main" else EXT_K
    for seed in SEEDS[curve]:
        for pt in points:
            if curve == "main":
                ids = [g.decision_id for g in b1]
                random.Random(seed).shuffle(ids)
                keep = set(ids[:pt])
                train = [g for g in b1 if g.decision_id in keep]
                ev = load_batch_texts("batch2")
                only = None
                n = pt
            else:
                train = b1 + [b2[d] for d in pool[:pt]]
                ev = [d for d in load_batch_texts("batch2") if d.decision_id in set(test_half)]
                only = set(test_half)
                n = 60 + pt
            name = f"lc-{model}-{curve}-n{n}-s{seed}"
            secs, info = train_predict(model, train, ev, seed)
            out = write_predictions("batch2", f"lc/{name}", ev)
            tables, metrics = score_file(out, "batch2", only_ids=only)
            n_spans = sum(len(g.spans) for g in train)
            with tracking.run(
                name,
                {
                    "extractor": model,
                    "curve": curve,
                    "n_train_decisions": n,
                    "n_train_spans": n_spans,
                    "seed": seed,
                    "eval": "batch2" if only is None else "batch2-half",
                },
                tags={"learning_curve": "1"},
            ) as log:
                log.metrics({**metrics, "train_seconds": secs})
                log.text(tables, "scores.md")
            print(
                f"{name}: decisions={n} spans={n_spans} span_f1={metrics['span_f1_exact']:.4f} "
                f"entity_f1={metrics['entity_f1']:.4f} train={secs:.0f}s",
                flush=True,
            )


def table() -> None:
    import mlflow

    mlflow.set_tracking_uri(tracking.TRACKING_URI)
    exp = mlflow.get_experiment_by_name(tracking.EXPERIMENT)
    df = mlflow.search_runs([exp.experiment_id], filter_string="tags.learning_curve = '1'")
    df = df.drop_duplicates("tags.mlflow.runName", keep="first")
    rows = {}
    for _, r in df.iterrows():
        key = (r["params.extractor"], r["params.curve"], int(r["params.n_train_decisions"]))
        rows.setdefault(key, []).append(r["metrics.span_f1_exact"])
    print("| model | curve | train decisions | seeds | span F1 mean | min | max |")
    print("|---|---|---|---|---|---|---|")
    for key in sorted(rows):
        v = rows[key]
        print(
            f"| {key[0]} | {key[1]} | {key[2]} | {len(v)} | {sum(v) / len(v):.4f} | {min(v):.4f} | {max(v):.4f} |"
        )


if __name__ == "__main__":
    if sys.argv[1] == "table":
        table()
    else:
        run(sys.argv[1], sys.argv[2])
