# caselaw-extraction

Information extraction and a citation graph over Swiss Federal Supreme Court (BGer) decisions.

Project 1 of a four-project portfolio. See `docs/report.md` for the running report.

## Data

Decisions come from the CC0-licensed `voilaj/swiss-caselaw` dataset on Hugging Face
(one Parquet file per court, built by the `opencaselaw` project). Raw data stays out of git.

## Quick start

```bash
make setup      # uv sync
make ingest     # filter the BGer file remotely with DuckDB into data/raw/
make sample     # pick 60 decisions for the gold set
make tasks      # write Label Studio tasks with regex pre-annotations
make labelstudio-up
```

## Extractors and scoring (week 2)

Every extractor writes `data/pred/<batch>/<name>.jsonl` (decision_id, outcome, spans). One
command scores any such file against a gold batch at span level and entity level and logs the
run to MLflow (`sqlite:///mlflow.db`):

```bash
uv run caselaw predict regex --batch batch2            # regex -> data/pred/batch2/regex.jsonl
uv run caselaw score data/pred/batch2/regex.jsonl --batch batch2 --name regex-batch2
uv run caselaw score silver --batch batch2             # the dataset's own citation graph
uv run caselaw train-spacy --train batch1 --eval batch2
uv run caselaw train-transformer --train batch1 --eval batch2   # deepset/gbert-base on MPS/CUDA/CPU
make mlflow-ui                                          # http://127.0.0.1:5001
```

The LLM extractor is run by agents that follow `docs/llm-extractor-brief.md`; their JSON output
is resolved to offsets with `scripts/llm/apply_output.py` and collected with
`scripts/llm/collect.py`. Gold-set tooling is batch-aware through `GOLD_BATCH=batch2
GOLD_PASSES=a,c` (see `scripts/gold/`). Results and caveats: `docs/report.md`, section 6.

## Entity linking and guideline v0.2 (week 3, day 1)

Extraction and linking are two stages. The linking stage (`caselaw link`) resolves every span
of every extractor to a key (Fedlex article, `BGE vol part page`, normalised file number) and
drops the spans that resolve to nothing: a statute whose code is not a Swiss federal act, a BGE
fragment, the decision's own file number. It never moves a boundary. Scores are reported
before and after linking, so a model's learning failures stay visible:

```bash
uv run caselaw link data/pred/batch2/gbert-base-s0.jsonl --batch batch2 --log   # -> *-linked.jsonl
uv run caselaw predict-transformer --model-dir models/gbert-base-s0-ner --decode viterbi
```

Guideline v0.2 adds four negative classes (`CONTRACT_ARTICLE`, `BARE_ARTICLE`, `OTHER_LAW`,
`JOURNAL_REF`) so that a learned model can learn what is *not* a citation and the scorer can
show the confusion (`caselaw score ... --labels all`). The relabel is a round over a finished
batch: `make gold-round BATCH=batch1` builds the task file (previous gold locked + proposals
from `negatives.py`), agents follow `docs/agent-negatives-brief.md`, then
`make gold-round-agreement` and `make gold-round-finalize` with `GOLD_ROUND=v2`. Guideline
v0.3 (short BGE citations as spans, `Artikel` written out) was applied the same way as round
`v3`, with `make gold-round BATCH=batch1 ROUND=v3` building proposals from the current regex
(`--citations`) and brief `docs/agent-v3-brief.md`. Gold files: `data/gold/<batch>.gold.jsonl`
is the current version (v0.3); `*.gold.v0.1.jsonl` and `*.gold.v2.jsonl` are kept.

Batch 3 (200 decisions) was sampled half on purpose: `caselaw sample --n 200 --targeted 100`
draws decisions that contain rare classes or rare outcomes (membership in
`data/gold/<batch>.groups.json`) and fills the rest stratified. `caselaw tasks` pre-annotates
all nine classes. The training commands take several batches: `--train batch1,batch3`.

`scripts/learning_curve.py` trains the span models on 15 to 105 decisions (several seeds) and
logs span F1 per training size to MLflow; `scripts/learning_curve.py table` collects the
results. See `docs/report.md`, section 6.12.
