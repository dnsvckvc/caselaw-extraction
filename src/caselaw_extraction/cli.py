"""Command line entry points: `caselaw ingest | sample | tasks | stats`."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import typer
from rich import print as rprint

from caselaw_extraction import ingest as ingest_mod
from caselaw_extraction.fedlex import load_code_map
from caselaw_extraction.gold import LABELS as LABELS_ALL
from caselaw_extraction.labelstudio import write_tasks
from caselaw_extraction.sample import GOLD_DIR, pick_sample

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.command()
def ingest(
    force: bool = typer.Option(False, help="Re-download even if the raw file exists"),
) -> None:
    """Download the BGer Parquet file and build the German civil-law working corpus."""
    n = ingest_mod.ingest(force=force)
    rprint(f"[green]corpus written[/green] {ingest_mod.CORPUS_PATH} rows={n}")


@app.command()
def sample(
    n: int = typer.Option(60, help="Number of decisions"),
    seed: int = typer.Option(1, help="Sampling seed"),
    name: str = typer.Option("batch1", help="Batch name"),
    targeted: int = typer.Option(
        0, help="of the n decisions, this many are drawn from rare-class / rare-outcome groups"
    ),
) -> None:
    """Pick a stratified sample for the gold set and record its ids. With --targeted K, K of
    the n decisions come from decisions that contain rare classes or rare outcomes (the group
    membership is written to <name>.groups.json) and n-K are stratified as before."""
    manifest = GOLD_DIR / f"{name}.ids.json"
    exclude: list[str] = []
    for other in GOLD_DIR.glob("*.ids.json"):
        if other != manifest:
            exclude += json.loads(other.read_text())
    rows: list[dict] = []
    if targeted:
        from caselaw_extraction.sample import pick_targeted

        rows, groups = pick_targeted(targeted, seed, exclude=exclude)
        (GOLD_DIR / f"{name}.groups.json").write_text(json.dumps(groups, indent=1))
        exclude += [r["decision_id"] for r in rows]
        rprint(
            f"[green]{len(rows)} targeted[/green]: "
            + ", ".join(f"{g} {len(v)}" for g, v in groups.items())
        )
    rows += pick_sample(n - len(rows), seed, exclude=exclude)
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps([r["decision_id"] for r in rows], indent=1))
    by = {}
    for r in rows:
        by.setdefault((r["year"], r["chamber"]), 0)
        by[(r["year"], r["chamber"])] += 1
    rprint(f"[green]{len(rows)} decisions[/green] -> {manifest}")
    for k, v in sorted(by.items()):
        rprint(f"  {k[0]}  {k[1]:32s} {v}")


@app.command()
def tasks(
    name: str = typer.Option("batch1", help="Batch name (must match a sample manifest)"),
    refresh_fedlex: bool = typer.Option(False, help="Re-query the Fedlex endpoint"),
) -> None:
    """Write Label Studio tasks with regex pre-annotations for a sampled batch."""
    ids = json.loads((GOLD_DIR / f"{name}.ids.json").read_text())
    con = duckdb.connect()
    id_list = ", ".join(f"'{i}'" for i in ids)
    rows = con.execute(
        f"SELECT * FROM read_parquet('{ingest_mod.CORPUS_PATH}') WHERE decision_id IN ({id_list})"
    ).fetchall()
    cols = [d[0] for d in con.description]
    recs = [dict(zip(cols, r, strict=True)) for r in rows]
    code_map = load_code_map(refresh=refresh_fedlex)
    out = write_tasks(recs, code_map, Path("labeling/tasks") / f"{name}.json")
    first = json.loads(out.read_text())[0]
    n_pred = len(first["predictions"][0]["result"])
    rprint(f"[green]{len(recs)} tasks[/green] -> {out}")
    rprint(f"  codes known: {len(code_map)}; first task has {n_pred} pre-annotations")


@app.command()
def predict(
    extractor: str = typer.Argument(..., help="regex | silver"),
    batch: str = typer.Option("batch2", help="Batch whose decisions to predict"),
    name: str = typer.Option("", help="output name, e.g. regex-v0.3 (default: the extractor)"),
) -> None:
    """Run an extractor over a batch and write data/pred/<batch>/<name>.jsonl."""
    from caselaw_extraction import regex_extractor as rx
    from caselaw_extraction.gold import load_batch_texts, write_predictions

    decisions = load_batch_texts(batch)
    if extractor == "regex":
        code_map = load_code_map()
        for d in decisions:
            ex = rx.extract(d.decision_id, d.text, code_map)
            seen: set[tuple[int, int, str]] = set()
            for s in ex.all_spans():
                k = (s.start, s.end, s.label.value)
                if k not in seen:
                    seen.add(k)
                    d.spans.append({"start": s.start, "end": s.end, "label": k[2], "text": s.text})
            d.spans.sort(key=lambda s: (s["start"], s["end"]))
            d.outcome = ex.outcome.value
    else:
        raise typer.BadParameter("predict supports: regex (learned extractors have own commands)")
    out = write_predictions(batch, name or extractor, decisions)
    rprint(f"[green]{len(decisions)} predictions[/green] -> {out}")


PREDS_ARG = typer.Argument(..., help="prediction files to link (not *-linked.jsonl)")


@app.command()
def link(
    preds: list[Path] = PREDS_ARG,
    batch: str = typer.Option("batch2", help="batch the predictions belong to (for the texts)"),
    log: bool = typer.Option(False, help="score each linked file and log it to MLflow"),
) -> None:
    """Entity-linking stage: resolve spans to Fedlex / BGE / docket keys, drop the unlinkable,
    write <name>-linked.jsonl next to each input. Applies to every extractor alike."""
    from caselaw_extraction.gold import load_texts
    from caselaw_extraction.linking import format_drop_table, link_file
    from caselaw_extraction.scoring import score_file

    texts = load_texts(batch)
    code_map = load_code_map()
    rows = []
    for pred in preds:
        if pred.stem.endswith("-linked"):
            continue
        out, dropped, n = link_file(pred, texts, code_map)
        rows.append((pred.name, n, dropped))
        if log:
            from caselaw_extraction import tracking

            tables, metrics = score_file(out, batch)
            run_name = f"{out.stem}-{batch}"
            with tracking.run(
                run_name, {"batch": batch, "pred": str(out), "stage": "linked", "source": pred.name}
            ) as lg:
                lg.metrics({**metrics, **{f"dropped_{k}": v for k, v in dropped.items()}})
                lg.text(tables, "scores.md")
                lg.artifact(str(out))
            rprint(f"[green]logged[/green] {run_name}: span F1 {metrics['span_f1_exact']:.4f}")
    print(format_drop_table(rows))


@app.command()
def score(
    pred: str = typer.Argument(..., help="prediction JSONL, or 'silver' for the dataset graph"),
    batch: str = typer.Option("batch2", help="Gold batch to score against"),
    name: str = typer.Option("", help="run name for MLflow; empty = no logging"),
    labels: str = typer.Option("citation", help="citation (5 classes) | all (9, guideline v0.2)"),
) -> None:
    """Score a prediction file against a gold batch: span level and entity level."""
    from caselaw_extraction.gold import CITATION_LABELS, LABELS
    from caselaw_extraction.scoring import score_file, score_silver

    labs = LABELS if labels == "all" else CITATION_LABELS
    tables, metrics = (
        score_silver(batch) if pred == "silver" else score_file(Path(pred), batch, labels=labs)
    )
    print(tables)
    if name:
        from caselaw_extraction import tracking

        with tracking.run(name, {"batch": batch, "pred": pred, "labels": labels}) as log:
            log.metrics(metrics)
            log.text(tables, "scores.md")
            if pred != "silver":
                log.artifact(pred)
        rprint(f"[green]logged to MLflow[/green] run {name}")


def _load_train(batches: str):
    """`batch1` or `batch1,batch3`: the gold of several batches concatenated."""
    from caselaw_extraction.gold import load_gold

    out = []
    for b in batches.split(","):
        out += load_gold(b.strip())
    return out


@app.command(name="train-spacy")
def train_spacy(
    train: str = typer.Option("batch1", help="gold batch(es) to train on, comma-separated"),
    eval: str = typer.Option("batch2", help="gold batch to predict and score"),
    epochs: int = typer.Option(20),
    seed: int = typer.Option(0),
    name: str = typer.Option("", help="prediction/model name; default spacy-s<seed>"),
) -> None:
    """Train spaCy NER + textcat from zero, predict the eval batch, score, log to MLflow."""
    import time

    from caselaw_extraction import spacy_extractor as sx
    from caselaw_extraction import tracking
    from caselaw_extraction.gold import load_batch_texts, write_predictions
    from caselaw_extraction.scoring import score_file

    t0 = time.time()
    tr = _load_train(train)
    nlp, info = sx.train_ner(tr, epochs=epochs, seed=seed)
    t_ner = time.time() - t0
    cat = sx.train_textcat(tr, seed=seed)
    t_train = time.time() - t0
    ev = load_batch_texts(eval)
    sx.predict_ner(nlp, ev)
    sx.predict_textcat(cat, ev)
    t_pred = time.time() - t0 - t_train
    name = name or f"spacy-s{seed}"
    out = write_predictions(eval, name, ev)
    sx.save(nlp, f"{name}-ner")
    sx.save(cat, f"{name}-textcat")
    tables, metrics = score_file(out, eval)
    print(tables)
    rprint(
        f"windows={info['n_windows']} spans={info['n_spans']} misaligned={info['n_misaligned']} "
        f"train={t_train:.0f}s predict={t_pred:.0f}s"
    )
    with tracking.run(
        f"{name}-{eval}",
        {
            "extractor": "spacy",
            "train": train,
            "eval": eval,
            "epochs": epochs,
            "seed": seed,
            "n_windows": info["n_windows"],
            "n_misaligned": info["n_misaligned"],
            "n_labels": len(LABELS_ALL),
        },
    ) as log:
        log.metrics(
            {
                **metrics,
                "train_seconds": t_train,
                "ner_train_seconds": t_ner,
                "predict_seconds": t_pred,
                "final_ner_loss": info["loss_history"][-1],
            }
        )
        log.text(tables, "scores.md")
        log.artifact(out)


@app.command(name="train-transformer")
def train_transformer(
    train: str = typer.Option("batch1", help="gold batch(es) to train on, comma-separated"),
    eval: str = typer.Option("batch2", help="gold batch to predict and score"),
    model: str = typer.Option("deepset/gbert-base"),
    epochs: int = typer.Option(4),
    outcome_epochs: int = typer.Option(12),
    seed: int = typer.Option(0),
    skip_spans: bool = typer.Option(False, help="only train the outcome classifier"),
    name: str = typer.Option("", help="prediction/model name; default <model>-s<seed>"),
) -> None:
    """Fine-tune a token classifier + outcome classifier, predict the eval batch, score, log."""
    import time

    from caselaw_extraction import tracking
    from caselaw_extraction import transformer_extractor as tx
    from caselaw_extraction.gold import load_batch_texts, write_predictions
    from caselaw_extraction.scoring import score_file

    short = model.split("/")[-1]
    tr = _load_train(train)
    ev = load_batch_texts(eval)
    t0 = time.time()
    info: dict = {}
    if not skip_spans:
        tok, mdl, info = tx.train_token_classifier(tr, model, epochs=epochs, seed=seed)
        t_train = time.time() - t0
        tx.predict_token_classifier(tok, mdl, ev)
        t_pred = time.time() - t0 - t_train
        base = name or f"{short}-s{seed}"
        mdl.save_pretrained(tx.MODELS / f"{base}-ner")
        tok.save_pretrained(tx.MODELS / f"{base}-ner")
    else:
        t_train = t_pred = 0.0
    t1 = time.time()
    otok, omdl = tx.train_outcome_classifier(tr, model, epochs=outcome_epochs, seed=seed)
    t_out = time.time() - t1
    tx.predict_outcome(otok, omdl, ev)
    name = name or f"{short}-s{seed}"
    omdl.save_pretrained(tx.MODELS / f"{name}-outcome")
    otok.save_pretrained(tx.MODELS / f"{name}-outcome")
    if skip_spans:
        name = f"{name}-outcome"  # the prediction file then holds outcomes only
    out = write_predictions(eval, name, ev)
    tables, metrics = score_file(out, eval)
    print(tables)
    rprint(
        f"windows={info.get('n_windows')} truncated={info.get('n_truncated')} "
        f"span_train={t_train:.0f}s predict={t_pred:.0f}s outcome_train={t_out:.0f}s"
    )
    with tracking.run(
        f"{name}-{eval}",
        {
            "extractor": "transformer",
            "model": model,
            "train": train,
            "eval": eval,
            "epochs": epochs,
            "outcome_epochs": outcome_epochs,
            "seed": seed,
            "n_windows": info.get("n_windows"),
            "n_truncated": info.get("n_truncated"),
            "n_labels": len(LABELS_ALL),
        },
    ) as log:
        log.metrics(
            {
                **metrics,
                "train_seconds": t_train,
                "predict_seconds": t_pred,
                "outcome_train_seconds": t_out,
            }
        )
        if info:
            log.metrics({"final_loss": info["loss_history"][-1]})
        log.text(tables, "scores.md")
        log.artifact(out)


MODEL_DIR_OPT = typer.Option(..., help="saved token classifier, e.g. models/gbert-base-s0-ner")


@app.command(name="predict-transformer")
def predict_transformer(
    model_dir: Path = MODEL_DIR_OPT,
    batch: str = typer.Option("batch2"),
    decode: str = typer.Option("argmax", help="argmax | viterbi (BIO-constrained)"),
    name: str = typer.Option("", help="prediction name; default <model dir>-<decode>"),
    log: bool = typer.Option(True, help="score and log to MLflow"),
) -> None:
    """Predict a batch with a saved token classifier (no outcome head); optionally with
    BIO-constrained Viterbi decoding instead of per-token argmax."""
    import time

    from caselaw_extraction import transformer_extractor as tx
    from caselaw_extraction.gold import load_batch_texts, write_predictions
    from caselaw_extraction.scoring import score_file

    tok, mdl = tx.load_saved(model_dir)
    ev = load_batch_texts(batch)
    t0 = time.time()
    tx.predict_token_classifier(tok, mdl, ev, decode=decode)
    t_pred = time.time() - t0
    name = name or f"{model_dir.name.removesuffix('-ner')}-{decode}"
    out = write_predictions(batch, name, ev)
    tables, metrics = score_file(out, batch)
    print(tables)
    rprint(f"predict={t_pred:.0f}s -> {out}")
    if log:
        from caselaw_extraction import tracking

        with tracking.run(
            f"{name}-{batch}",
            {
                "extractor": "transformer",
                "model_dir": str(model_dir),
                "decode": decode,
                "eval": batch,
            },
        ) as lg:
            lg.metrics({**metrics, "predict_seconds": t_pred})
            lg.text(tables, "scores.md")
            lg.artifact(str(out))


RUN_MODEL_OPT = typer.Option(
    None, help="gbert: saved token classifier, e.g. models/gbert-base-b13-s0-ner"
)
RUN_OUTCOME_OPT = typer.Option(
    None, help="gbert: saved outcome classifier (default <model-dir> with -outcome)"
)


@app.command(name="run-corpus")
def run_corpus_cmd(
    name: str = typer.Option(..., help="run name -> data/runs/<name>/"),
    extractor: str = typer.Option("regex", help="regex | gbert"),
    limit: int = typer.Option(0, help="only the first N decisions of the corpus (0 = all)"),
    workers: int = typer.Option(0, help="Dask workers for the regex (0 = one per core)"),
    scheduler: str = typer.Option("distributed", help="distributed | processes | sync"),
    model_dir: Path | None = RUN_MODEL_OPT,
    outcome_dir: Path | None = RUN_OUTCOME_OPT,
    decode: str = typer.Option("viterbi", help="gbert: argmax | viterbi"),
    log: bool = typer.Option(True, help="log the run to MLflow"),
) -> None:
    """Week 3: run one extractor and the linking stage over the whole corpus (Dask for the
    regex, one GPU process for gbert) and write decisions/spans/citations Parquet tables."""
    from caselaw_extraction import corpus_run

    if extractor == "gbert" and model_dir is not None and outcome_dir is None:
        cand = model_dir.with_name(model_dir.name.removesuffix("-ner") + "-outcome")
        outcome_dir = cand if cand.exists() else None
    run = corpus_run.run_corpus(
        name,
        extractor,
        limit=limit or None,
        workers=workers or None,
        scheduler=scheduler,
        model_dir=model_dir,
        outcome_dir=outcome_dir,
        decode=decode,
    )
    print(corpus_run.format_run(run))
    if log:
        from caselaw_extraction import tracking

        flat = {k: v for k, v in run.items() if not isinstance(v, dict)}
        with tracking.run(f"corpus-{name}", flat, tags={"stage": "corpus"}) as lg:
            lg.metrics(
                {
                    "n_decisions": run["n_decisions"],
                    "n_spans_before_linking": run["n_spans_before_linking"],
                    "n_spans": run["n_spans"],
                    "wall_seconds": run["wall_seconds"],
                    "extract_seconds": run["extract_seconds"],
                    **{f"dropped_{k}": v for k, v in run["dropped"].items()},
                    **{f"spans_{k}": v for k, v in run["spans_by_label"].items()},
                    **{f"citations_{k}": v for k, v in run["citations_by_kind"].items()},
                }
            )
            lg.text(corpus_run.format_run(run), "run.md")
            lg.artifact(str(corpus_run.RUNS_DIR / name / "run.json"))
        rprint(f"[green]logged[/green] corpus-{name}")


@app.command(name="graph")
def graph_cmd(
    run: str = typer.Option("regex-v0.4", help="run name under data/runs/"),
    html: bool = typer.Option(True, help="also write graph.html (top 150 nodes)"),
) -> None:
    """Week 3: build the citation graph of a run, write its centrality table and print the
    three headline analyses (most-cited statutes, trend by year, most central decisions)."""
    from caselaw_extraction import graph

    a = graph.analyse_run(run, html=html)
    print(graph.format_analyses(a))


@app.command(name="compare-runs")
def compare_runs_cmd(
    a: str = typer.Argument(..., help="run name"),
    b: str = typer.Argument(..., help="run name"),
    examples: int = typer.Option(10, help="differing citations to list per side"),
) -> None:
    """Week 3: how far two runs over the same corpus agree, citation by citation."""
    from caselaw_extraction import graph

    c = graph.compare_runs(a, b, examples=examples)
    print(graph.format_comparison(c))
    out = corpus_run_dir(a) / f"compare-{b}.json"
    out.write_text(json.dumps(c, indent=1, ensure_ascii=False, default=str))
    rprint(f"[green]written[/green] {out}")


def corpus_run_dir(name: str) -> Path:
    from caselaw_extraction.corpus_run import RUNS_DIR

    return RUNS_DIR / name


@app.command(name="db-load")
def db_load_cmd(
    run: str = typer.Option("regex-v0.4", help="run name under the runs directory"),
    dsn: str = typer.Option("", help="Postgres DSN (default: $CASELAW_DSN or the local compose)"),
    runs_dir: str = typer.Option(
        "", help="directory or s3://bucket/prefix holding <run>/ (default data/runs)"
    ),
    statutes: bool = typer.Option(True, help="also fill the statute table from the Fedlex list"),
) -> None:
    """Week 3: load a run (decisions, spans, citations, centrality) and the statute list into
    Postgres (`make db-up` starts it). Week 4: the same command runs as a Fargate task with
    `--runs-dir s3://<bucket>/runs` against RDS."""

    from caselaw_extraction import db
    from caselaw_extraction.corpus_run import RUNS_DIR
    from caselaw_extraction.store import DEFAULT_DSN, dsn_from_env

    dsn = dsn or dsn_from_env() or DEFAULT_DSN
    counts = db.load_run(run, dsn, runs_dir or RUNS_DIR)
    n_statutes = db.load_statutes(load_code_map(), dsn) if statutes else 0
    rprint(f"[green]loaded[/green] run {run}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    rprint(f"  statute table: {n_statutes} acts; database: {db.table_counts(dsn)}")


@app.command(name="api")
def api_cmd(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    backend: str = typer.Option("", help="duckdb | postgres (default: $CASELAW_BACKEND)"),
    run: str = typer.Option("", help="duckdb: run name (default: $CASELAW_RUN or regex-v0.4)"),
) -> None:
    """Week 3: serve the extracted records (FastAPI, OpenAPI at /docs)."""
    import os

    import uvicorn

    if backend:
        os.environ["CASELAW_BACKEND"] = backend
    if run:
        os.environ["CASELAW_RUN"] = run
    uvicorn.run("caselaw_extraction.api:app", host=host, port=port)


@app.command(name="drift")
def drift_cmd(
    a: str = typer.Option("", "--a", help="first period, `2025-09` or `2025` (default: 2nd last)"),
    b: str = typer.Option("", "--b", help="second period (default: the last period)"),
    period: str = typer.Option("month", help="month | year"),
    run: str = typer.Option("", help="run name (default: $CASELAW_RUN or regex-v0.4)"),
    backend: str = typer.Option("", help="duckdb | postgres (default: $CASELAW_BACKEND)"),
    series: bool = typer.Option(False, help="print the period-to-period series instead"),
    kind: str = typer.Option("statute", help="kind for --series: statute | bge | docket | code"),
    top: int = typer.Option(10, help="movers to list per kind"),
    fail_above: float = typer.Option(
        0.0, help="exit 1 if the statute Jensen-Shannon distance exceeds this (0 = never)"
    ),
    out: str = typer.Option("", help="write the report as JSON to this path"),
) -> None:
    """Week 4: compare the entity-frequency distributions of two periods (drift check)."""
    import json

    from caselaw_extraction import drift
    from caselaw_extraction.store import open_store

    store = open_store(backend or None, run or None)
    try:
        if series:
            rows = drift.drift_series(store, period, kind)
            print(drift.format_series(rows, kind))
            if out:
                Path(out).write_text(json.dumps(rows, indent=1))
            return
        if not a or not b:
            periods = sorted(drift.decisions_per_period(store, period))
            a, b = a or periods[-2], b or periods[-1]
        report = drift.drift_report(store, a, b, period, top=top)
    finally:
        store.close()
    print(drift.format_drift(report))
    if out:
        Path(out).write_text(json.dumps(report, indent=1))
    js = report["kinds"]["statute"]["js_distance"]
    if fail_above and js > fail_above:
        rprint(f"[red]drift[/red]: statute JS distance {js:.3f} > {fail_above}")
        raise typer.Exit(1)


@app.command()
def demo(
    n: int = typer.Option(100, help="decisions in the sample"),
    name: str = typer.Option("demo", help="run name"),
) -> None:
    """Run the pipeline on a sample without Postgres or cloud: regex + linking under Dask,
    the citation graph and the three analyses, all from Parquet."""
    from caselaw_extraction import corpus_run, graph

    run = corpus_run.run_corpus(name, "regex", limit=n, scheduler="processes", workers=4)
    print(corpus_run.format_run(run))
    print()
    print(graph.format_analyses(graph.analyse_run(name)))
    rprint(f"\n[green]API over this sample:[/green] caselaw api --backend duckdb --run {name}")


@app.command()
def stats() -> None:
    """Print corpus statistics for the report."""
    con = duckdb.connect()
    p = ingest_mod.CORPUS_PATH
    rprint(
        con.execute(
            f"SELECT count(*) n, min(decision_date), max(decision_date) FROM read_parquet('{p}')"
        ).fetchall()
    )
    rprint(
        con.execute(
            f"SELECT substr(decision_date,1,4) y, count(*) FROM read_parquet('{p}') "
            "GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )
    rprint(
        con.execute(
            f"SELECT outcome, count(*) FROM read_parquet('{p}') GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    )


if __name__ == "__main__":
    app()
