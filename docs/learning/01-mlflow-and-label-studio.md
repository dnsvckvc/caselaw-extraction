# Label Studio and MLflow: what they do, how we use them, what we learned

This note explains the two bookkeeping tools of the project. Label Studio holds the gold set,
the checked labels that every extractor is scored against. MLflow holds the scores, one record
per extractor run. The note is written for someone who would build the same thing by hand and
wants to understand each piece before copying it. The Label Studio setup lives in `labeling/`,
the gold toolchain in `scripts/gold/`, the MLflow wrapper in
`src/caselaw_extraction/tracking.py`. The report discusses the gold set in section 4 and the
scores in sections 5 and 6 of `docs/report.md`.

## 1. The problem the two tools solve here

The project compares five extractors on the same decisions: three regex versions, spaCy,
GBERT and an LLM. A comparison needs two things that the raw data does not give. The first is
a set of decisions where the correct spans and the correct outcome are known, stored with
character offsets. Label Studio stores these texts, pre-annotations and accepted labels, and
shows them in a browser. The second is a record of every scoring run: which prediction file,
which gold batch, which parameters, which numbers came out. MLflow stores each run with its
parameters, metrics and output files, and lets two runs be compared side by side.

## 2. The vocabulary

| term | meaning | here |
|---|---|---|
| **Project** (Label Studio) | one labeling config plus a set of tasks | one project, `BGer civil law - gold set`, id `1` in `labeling/data/project_id` |
| **Labeling config** | XML that defines what the annotator sees and which labels exist | `labeling/label_config.xml`: nine span labels, one choice |
| **Task** | one unit of work: data plus optional predictions | one decision; `labeling/tasks/<batch>.json` from `caselaw tasks` |
| **Prediction**, pre-annotation | a machine-made annotation the annotator corrects; carries `model_version` | regex spans and outcome plus negative-class proposals |
| **Annotation**, ground truth | an accepted result; can be flagged `ground_truth` | `finalize.py --import` posts the gold with that flag |
| **Experiment** (MLflow) | a named group of runs | `caselaw-extraction`, the only one |
| **Run** | one execution with name, params, metrics, tags, artifacts | one scoring of one prediction file against one gold batch |
| **Parameter** | a string input; immutable after logging | `batch`, `seed`, `train`, `eval`, ... |
| **Metric** | a numeric output | `span_f1_exact`, `entity_f1`, `confusion_*`, ... |
| **Tag** | a free key-value label that filters select on | `learning_curve=1`, `stage=corpus` |
| **Artifact** | a file attached to a run | `scores.md` and, in most runs, the prediction file |
| **Backend store** | where the run metadata lives | `sqlite:///mlflow.db`; artifacts under `mlruns/`; git ignores both |
| **Model registry** | named model versions with stages; needs a database backend | available, not used (section 6.5) |

## 3. How the pieces connect

```
 corpus Parquet --caselaw sample--> <batch>.ids.json --caselaw tasks--> labeling/tasks/<batch>.json
                                                                        (text + pre-annotations)
                                                                                 |
   +-- labelling, outside Label Studio -------------------------------------------v-------------+
   | render_task.py  : agent reads the text with numbered pre-annotations                      |
   | agent writes    : data/gold/<batch>/edits/<pass>/<decision_id>.json   (edits by text)     |
   | apply_edits.py  : data/gold/<batch>/ann/<pass>/<decision_id>.json     (spans by offset)   |
   | agreement.py    : data/gold/<batch>/disagreements.json                                    |
   | adjudicator     : data/gold/<batch>/edits/adj/<decision_id>.json                          |
   | finalize.py     : data/gold/<batch>.gold.jsonl                                            |
   +--------------------------------------------|-------------------------------------------------+
                  finalize.py --import          |          caselaw score / train-* / link --log
                           v                    |                         v
   +----------------------------------+         |         +----------------------------------+
   | Label Studio (Docker, :8080)     |         +-------->| MLflow (sqlite:///mlflow.db)     |
   | project 1, nine labels           |   gold vs         | experiment caselaw-extraction    |
   | annotations = ground truth       |   data/pred/...   | runs: params, metrics, scores.md |
   | view for the human spot check    |                   | UI: make mlflow-ui (:5001)       |
   +----------------------------------+                   +----------------------------------+
```

The labelling agents never worked inside Label Studio. They worked on text files, and Label
Studio received the finished gold afterwards. The gold file is the only link between the two
tools. MLflow never reads Label Studio; it reads the gold file through `gold.load_gold`.

## 4. Label Studio in depth

### 4.1 The container

`labeling/docker-compose.yml` runs one service from the image `heartexlabs/label-studio:1.17.0`
on port 8080. The environment sets the user `annotator@local.test`, a password and a token, and
enables local file serving. Two volumes mount `./data` (Label Studio's own database,
`labeling/data/label_studio.sqlite3`) and `./tasks` read-only. The password is in the file on
purpose. A comment says that this is a local, single-user instance, and that the password must
change if the port is ever exposed. Both `labeling/data/` and `labeling/tasks/` are in
`.gitignore`, because the task files hold the full decision texts. `make labelstudio-up` and
`make labelstudio-down` start and stop the container.

### 4.2 The labeling config and the nine labels

`labeling/label_config.xml`, shortened:

```xml
<View>
  <Header value="$docket_number — $decision_date — $chamber"/>
  <Choices name="outcome" toName="text" choice="single" required="true">
    <Choice value="approved"/> ... <Choice value="moot"/> <Choice value="unknown"/>
  </Choices>
  <Labels name="label" toName="text">
    <Label value="STATUTE" background="#1f77b4" hotkey="1"/>   <!-- then BGE, DOCKET, AMOUNT, PARTY_ROLE -->
    <Label value="CONTRACT_ARTICLE" background="#8c564b" hotkey="6"/>  <!-- then BARE_ARTICLE, OTHER_LAW, JOURNAL_REF -->
  </Labels>
  <Text name="text" value="$text" granularity="symbol"/>
  <TextArea name="comment" toName="text" placeholder="Comment (optional)" maxSubmissions="1"/>
</View>
```

Each `$name` reads a field of the task data. `granularity="symbol"` lets a span start and end
at any character, which the citation keys need. The five citation labels are the classes that
the linking stage resolves to a key. The four negative labels came with guideline v0.2.

One difference deserves a note. `gold.py` lists seven outcomes, including `consolidated`; the
config offers six choices without it. The gold files were never produced through this form, so
the difference had no effect, but a human who labels in the browser could not choose it.

### 4.3 Tasks and pre-annotations

`caselaw tasks --name <batch>` reads `data/gold/<batch>.ids.json`, pulls the rows from the
corpus Parquet with DuckDB and calls `labelstudio.write_tasks`. A task's `data` holds
`decision_id`, `docket_number`, `decision_date`, `chamber`, `legal_area`, `dataset_outcome`
and `text`. Its one prediction holds a result list. A span result has type `labels` and a
`value` with `start`, `end`, `text` and `labels`. The outcome result has type `choices`.

`labelstudio.to_prediction` merges two sources into that list. The regex extractor supplies
the citation spans and the outcome. `negatives.propose` supplies wide-recall proposals for the
four negative classes and never overlaps a citation span. Duplicate `(start, end, label)`
triples are written once. An `unknown` outcome is not written. A code comment records the
pre-annotator of each batch: `regex-v0.1` for batch 1, `regex-v0.2` for batch 2,
`regex-v0.4+negatives` for batch 3.

### 4.4 The API client and ground truth

Label Studio 1.17 rejects legacy API tokens by default. `scripts/labelstudio_api.py` therefore
logs in through the HTML login form and sends the session cookie and the CSRF token with each
call. Its command `create-project` posts `label_config.xml` with `show_collab_predictions: true`
and writes the id to `labeling/data/project_id`. `import <file>` posts a task file to
`/api/projects/<id>/import`. `export` downloads the project as JSON.

`scripts/gold/finalize.py --import` uses the same client. For each gold record it posts an
annotation with `ground_truth: true` to the matching task of project 1. With `--replace` it
patches an existing ground-truth annotation. This is how all 350 decisions came to be in Label
Studio as ground truth, and it is the view Denis used for the spot check (section 5.2).

### 4.5 Why the labelling happened outside Label Studio

The annotators were language-model agents. The report records (section 9) that agents cannot
compute character offsets reliably. The toolchain in `scripts/gold/` therefore lets an agent
name a span by its exact text, and a checker turns the text into offsets. `render_task.py <N>`
prints the decision with each pre-annotation as `«#12 STATUTE»Art. 42 Abs. 1 BGG«/12»`. The
agent writes an edits file with `delete` (ids), `relabel` (id and label) and `add` (text,
label, optional `occurrence` or `all`). `apply_edits.py <pass> <N>` resolves each added text,
refuses an ambiguous text, an overlap or an unknown label, and writes nothing on failure. The
report states that this worked on the first try for all 180 agent-decisions.

## 5. The gold-set process across three batches

### 5.1 Two passes, agreement, adjudication

Two independent passes labelled every decision of every batch. Pass `a` used Claude Fable
agents and pass `c` used Claude Opus agents, ten decisions per agent, with the brief
`docs/agent-labelling-brief.md`. A pass `b` existed for batch 1 and was discarded (section 8).

`scripts/gold/agreement.py` compares the two passes. A span counts as agreed when
`(start, end, label)` is identical. The script prints precision, recall and F1 of pass `c`
against pass `a`, the outcome agreement and per-label counts. It writes
`data/gold/<batch>/disagreements.json` with each disputed span, an id such as `a1` or `b3`,
and 60 characters of context.

The adjudicator decides only the disputed spans and any outcome conflict, following
`docs/agent-adjudication-brief.md`. The adjudication file names the ids to keep; unlisted ids
are dropped. It can also override agreed spans with `drop`, `relabel` and `add`, which was
needed when a guideline decision came after both passes. `scripts/gold/finalize.py` merges the
agreed spans, the kept spans and the overrides into `data/gold/<batch>.gold.jsonl`. It refuses
a decision that still has disputes and no adjudication file.

| batch | decisions | pass a vs pass c (report section 4) | result |
|---|---|---|---|
| batch 1 (v0.1) | 60 | 2,650 spans in both, 2 only in c; outcomes 60 of 60 | 2,650 spans |
| batch 2 (v0.1) | 90 | 3,571 in both, 0 only in a, 2 only in c; outcomes 90 of 90 | 3,572 spans |
| batch 3 (v0.3) | 200 | 10,230 in both, 22 only in a, 28 only in c; F1 0.998; outcomes 200 of 200 | 10,259 spans |

For batch 3 Denis adjudicated the 50 disputed spans in 14 decisions himself. In batch 2 the
agents accepted every pre-annotation in 68 of 90 decisions.

### 5.2 The human spot check

On 2026-10-22 Denis read 10 decisions of batch 2 in Label Studio with the gold spans shown.
`scripts/gold/spot_check.py batch2 --pick 10 --seed 7` chose the ids and wrote the table
template. The result in `data/gold/batch2/spot_check.md`: 358 gold spans, 0 wrong, 0 missed,
10 of 10 outcomes right. The report calls this the only quality number that does not come from
a model. It covers about 10% of the spans in batch 2 and bounds the error rate at roughly below
1%. It does not remove the anchoring bias (section 8).

### 5.3 Guideline versions v0.1 to v0.3, and why the gold changed

The guideline is `docs/annotation-guideline.md`. Its header records the versions.

**v0.1** had the five citation classes. Batches 1 and 2 were labelled under it. The agents
raised 16 open questions, listed in `docs/guideline-open-questions.md`.

**v0.2 (2026-10-23)** added the four negative classes and changed nothing in the citation
classes. The reason, from report section 4: the learned models produced false positives on
contract clauses, commentary article numbers, foreign law and journal references. Under v0.1
these had no span, so the models saw them as background and the scorer could only count errors.
With their own classes the model can learn them and the scorer can show the confusion.

**v0.3 (2026-10-23)** changed two citation rules and one negative rule, after Denis decided
every open question. Same-volume short BGE citations (`115` in `BGE 140 III 86 E. 2, 115 E. 2`)
became BGE spans. `Artikel` and `Artikeln` written out became STATUTE. Spelled-out `Ziffer`,
`Artikel` and `Absatz` count for the negative classes.

Each later version was applied to the finished batches as a **round**. `scripts/gold/make_round.py
<batch> <round>` writes `labeling/tasks/<batch>.<round>.json`. Its pre-annotations are the
current gold of the batch, locked, plus new proposals. With `--citations` the current regex
also proposes citation spans that the gold lacks. The round then runs through the same two
passes, agreement and finalize, with `GOLD_ROUND=<round>` in the environment. The round name is
`v2` for guideline v0.2 and `v3` for guideline v0.3. The briefs are
`docs/agent-negatives-brief.md` and `docs/agent-v3-brief.md`.

| round | what the agents saw | result (report section 4) |
|---|---|---|
| `v2` | v0.1 gold locked; 18 + 40 CONTRACT_ARTICLE, 22 + 40 BARE_ARTICLE, 4 + 7 OTHER_LAW, 13 + 12 JOURNAL_REF proposals for batch 1 + batch 2 | batch 1: 2,649 citation + 64 negative spans; batch 2: 3,572 + 103; one citation span relabelled (`Art. 117 GOG/ZH` to OTHER_LAW) |
| `v3` | v0.2 gold locked; proposals from regex v0.4 and the extended negative proposer; only 30 of 60 and 46 of 90 decisions had a matching pattern | batch 1 gained 42 BGE, 11 CONTRACT_ARTICLE, 1 OTHER_LAW; batch 2 gained 59 BGE, 2 STATUTE, 17 CONTRACT_ARTICLE, 3 BARE_ARTICLE, 1 OTHER_LAW; both passes identical, no adjudication |

Batch 3 was labelled once, under v0.3 with all nine classes. `caselaw sample --n 200
--targeted 100 --seed 3` drew half of it from decisions with rare classes or rare outcomes. The
group membership is in `data/gold/batch3.groups.json`. Its task file carried 10,101 proposals,
about 50 per decision.

### 5.4 The exported gold files under `data/gold`

| file | content |
|---|---|
| `batch1.gold.jsonl`, `batch2.gold.jsonl`, `batch3.gold.jsonl` | the current gold, guideline v0.3; 60, 90 and 200 lines |
| `batch1.gold.v0.1.jsonl`, `batch2.gold.v0.1.jsonl` | the v0.1 gold, kept for the week-2 comparisons |
| `batch1.gold.v2.jsonl`, `batch2.gold.v2.jsonl` | the output of round `v2` |
| `batch1.gold.v3.jsonl`, `batch2.gold.v3.jsonl` | the output of round `v3`; same bytes as the unversioned file |
| `<batch>.ids.json`, `batch3.groups.json` | the sampled ids; the targeted groups of batch 3 |
| `<batch>/edits/<pass>/`, `<batch>/ann/<pass>/` | the agents' edits and the resolved annotations |
| `<batch>/edits/adj/`, `<batch>/disagreements.json` | adjudication files and the dispute list |
| `<batch>/v2/`, `<batch>/v3/` | the same structure for each round |
| `batch2/spot_check.ids.json`, `batch2/spot_check.md` | the human spot check |

One gold line has the shape `{"decision_id", "task_index", "outcome", "spans": [{"start",
"end", "label", "text"}], ...}`. The texts are not in the file. `gold.load_gold` reads them from
`labeling/tasks/<batch>.json`, so the task file must exist for scoring to work.

## 6. MLflow in depth

### 6.1 The backend, the experiment and the wrapper

`src/caselaw_extraction/tracking.py` is the only place that logs to MLflow:

```python
TRACKING_URI = "sqlite:///mlflow.db"
EXPERIMENT = "caselaw-extraction"

@contextmanager
def run(name, params=None, tags=None):
    mlflow = _mlflow()                       # set_tracking_uri, set_experiment
    with mlflow.start_run(run_name=name, tags=tags) as r:
        if params:
            mlflow.log_params({k: str(v)[:500] for k, v in params.items()})
        yield Logger(mlflow, r.info.run_id)  # .metrics(), .artifact(), .text()
```

Every command calls `tracking.run(name, params, tags)` and logs through the `Logger`.
Parameters are cast to strings and cut at 500 characters, which guards against MLflow's limit
on the length of a parameter value. MLflow is in the `ml` extra of `pyproject.toml`, so the API
image does not carry it. `uv.lock` pins `mlflow 3.17.2`.

The SQLite file is 2 MB. The directory `mlruns/1/` holds one folder per run with `scores.md`
and the prediction file, 126 folders at the time of writing. The report counts 127 runs in its
management summary and 125 in its architecture diagram; the counts were written on other dates.

### 6.2 What each command logs

| command | run name | parameters | metrics beyond the scorer's | artifacts |
|---|---|---|---|---|
| `caselaw score <pred> --name <n>` | `<n>` | `batch`, `pred`, `labels` | none | `scores.md`, the prediction file (not for `silver`) |
| `caselaw link <preds> --log` | `<pred>-linked-<batch>` | `batch`, `pred`, `stage=linked`, `source` | `dropped_<reason>` | `scores.md`, the linked file |
| `caselaw train-spacy` | `<name>-<eval>` | `extractor=spacy`, `train`, `eval`, `epochs`, `seed`, `n_windows`, `n_misaligned`, `n_labels` | `train_seconds`, `ner_train_seconds`, `predict_seconds`, `final_ner_loss` | `scores.md`, predictions |
| `caselaw train-transformer` | `<name>-<eval>` | `extractor=transformer`, `model`, `train`, `eval`, `epochs`, `outcome_epochs`, `seed`, `n_windows`, `n_truncated`, `n_labels` | `train_seconds`, `predict_seconds`, `outcome_train_seconds`, `final_loss` | `scores.md`, predictions |
| `caselaw predict-transformer` | `<name>-<batch>` | `extractor`, `model_dir`, `decode`, `eval` | `predict_seconds` | `scores.md`, predictions |
| `caselaw run-corpus` | `corpus-<name>`, tag `stage=corpus` | the flat fields of the run record | `n_decisions`, `n_spans`, `wall_seconds`, `dropped_*`, `spans_*`, `citations_*` | `run.md`, `run.json` |
| `scripts/learning_curve.py` | `lc-<model>-<curve>-n<N>-s<seed>`, tag `learning_curve=1` | `extractor`, `curve`, `n_train_decisions`, `n_train_spans`, `seed`, `eval` | `train_seconds` | `scores.md` |

The scorer's own metrics come from `scoring.score_file`: `span_f1_exact`, `span_f1_overlap`,
`entity_f1`, `outcome_acc`, `outcome_macro_f1`, one `f1_<LABEL>` per class, and one
`confusion_<gold>_as_<pred>` per off-diagonal pair of the label confusion. The confusion
metrics are the source of report table 6.10. `caselaw score` without `--name` logs nothing.

Two things are not logged. The trained models go to `models/`, which git ignores, and no
command calls `mlflow.log_model`. The gold version is not logged either; a run records the
batch name, and the gold version must be inferred from the run date.

### 6.3 The learning-curve runs

`scripts/learning_curve.py` trains the span models on growing subsets and logs 40 runs. Each
run carries the tag `learning_curve=1` and the parameters `curve` (`main` or `extended`),
`n_train_decisions` and `seed`. The `table` subcommand calls `mlflow.search_runs` with
`filter_string="tags.learning_curve = '1'"`, drops duplicate run names, groups by model, curve
and training size, and prints mean, minimum and maximum of `span_f1_exact` over the seeds.
Report table 6.12 is this output. The tag makes the query cheap; without it the script would
have to parse run names. The 40 prediction files are in `data/pred/batch2/lc/`, not in MLflow.

### 6.4 The UI and how to compare two extractor runs

`make mlflow-ui` runs `uv run mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5001`.
The UI reads the same SQLite file and serves `http://127.0.0.1:5001`. The filter box accepts
the same syntax as `search_runs`, for example `tags.learning_curve = '1'`.

1. Start the UI with `make mlflow-ui`.
2. Open the experiment `caselaw-extraction`.
3. Filter with `params.eval = 'batch2'`.
4. Tick two runs, for example `regex-v0.2` and `gbert-base-b13-s0-batch2`.
5. Click **Compare**.

The compare page shows the parameters side by side and every metric of both runs. The
`confusion_*` metrics tell where the two differ by class. The `scores.md` artifact holds the
full per-label tables. Do not confuse this with `caselaw compare-runs <a> <b>`. That command
compares two **corpus runs** under `data/runs/` citation by citation and does not read MLflow.

### 6.5 The model registry

The docstring of `tracking.py` says: "Local SQLite store so the model registry works." This is
a general MLflow fact: the registry needs a database backend. Nothing in `src/` or `scripts/`
calls `register_model` or `log_model`, so the registry is empty. It would add a name such as
`gbert-ner` with versions 1, 2, 3, each pointing at a saved model and a run, with an alias such
as `production`. The corpus run instead takes `--model-dir models/gbert-base-b13-s0-ner` on the
command line. For one person this is enough. A team that deploys models would want the registry.

## 7. Walkthrough of the setup, as done by hand

1. Run `make labelstudio-up`. Label Studio answers on `http://localhost:8080`.
2. Run `make labelstudio-project`. The script writes the project id to `labeling/data/project_id`.
3. Run `uv run caselaw sample --n 60 --seed 1 --name batch1`. The ids land in `data/gold/batch1.ids.json`.
4. Run `uv run caselaw tasks --name batch1`. The task file lands in `labeling/tasks/batch1.json`.
5. Run `make labelstudio-import`. The output names the task, annotation and prediction counts.
6. Give each labelling agent a batch, a pass and ten task indices with `docs/agent-labelling-brief.md`.
7. After both passes, run `GOLD_BATCH=batch1 GOLD_PASSES=a,c uv run python scripts/gold/agreement.py`.
8. Give the disputed decisions to an adjudicator with `docs/agent-adjudication-brief.md`.
9. Run `GOLD_BATCH=batch1 GOLD_PASSES=a,c uv run python scripts/gold/finalize.py --import`. The gold file and the ground truth exist.
10. Run `uv run caselaw predict regex --batch batch1 --name regex-v0.4`.
11. Run `uv run caselaw score data/pred/batch1/regex-v0.4.jsonl --batch batch1 --name regex-v0.4-batch1`. The run is in `mlflow.db`.
12. Run `make mlflow-ui`. Open `http://127.0.0.1:5001` and find the run.

For a guideline round, replace steps 3 to 5 with `make gold-round BATCH=batch1 ROUND=v3
CITATIONS=--citations`. Then prefix every gold command with `GOLD_ROUND=v3`.

## 8. What went wrong, and what each mistake teaches

Each item below is recorded in `docs/report.md` section 4 or section 9, or in a code comment.
No problem with MLflow itself is recorded anywhere in the repository.

**Label Studio rejected the API token.** Version 1.17 disables legacy API tokens by default.
The client logs in through the login form and carries the session cookie and the CSRF token.
Lesson: read the authentication notes of the exact version before writing a client.

**Agents could not compute character offsets.** The fix was to name a span by its text and let
`apply_edits.py` resolve the offsets, refuse ambiguity and refuse overlaps. Lesson: let the
machine do the arithmetic and the annotator do the judgement.

**Two passes of the same model were one pass.** Pass `a` and pass `b` of batch 1, both Claude
Fable with the same brief, produced byte-identical edits on all 60 decisions. Pass `b` was
discarded and pass `c` used a different model. Lesson: a second annotator adds information only
if it is a different annotator.

**The second pass was still anchored.** Pass `a` and pass `c` agreed on 3,571 of 3,573 spans in
batch 2. The report's own reading: two models with the same brief and the same pre-annotations
are not independent, because the pre-annotation anchors both. Every gold boundary is one the
regex can produce, which favours the regex in every comparison. Lesson: agreement measures
consistency, not truth. The human spot check is the only independent signal.

**The guideline example was wrong.** v0.1 said that `115` in `BGE 140 III 86 E. 2 S. 89, 115
E. 2` is a page number. Every agent followed the example and flagged it. Both batches missed
these citations until round `v3` added 42 and 59 spans. Lesson: an example shapes labels more
than a rule does, so examples must be checked against the corpus.

**A credit cut-off stopped ten agents.** In the second window of batch 3, ten pass-`a` agents
stopped part-way. Three fresh agents finished the 27 missing decisions two days later. Nothing
was lost, because every finished decision is its own file. Lesson: one file per decision makes
a labelling job resumable.

## 9. How to verify

```
wc -l data/gold/*.gold.jsonl                     # 60, 90, 200 lines for the current files
GOLD_BATCH=batch3 GOLD_PASSES=a,c uv run python scripts/gold/agreement.py
                                                 # agree=10230 only_a=22 only_b=28
GOLD_BATCH=batch2 GOLD_PASSES=a,c uv run python scripts/gold/finalize.py --check bger_4A_37_2020
sqlite3 mlflow.db "select count(*) from runs"    # the run count of the backend store
uv run python scripts/learning_curve.py table    # 40 runs grouped by model, curve and size
```

In Label Studio, open project 1 and a task of batch 2; the ground-truth annotation shows the
gold spans. In the MLflow UI, filter with `tags.learning_curve = '1'` and count 40 runs.

## 10. What a reader would do differently by hand

**A spreadsheet instead of MLflow.** Each scoring run would be one row: date, prediction file,
gold batch, parameters, the headline metrics. This works for ten runs. At 125 runs with 30 to
60 metrics each, the confusion metrics need their own sheet, and nobody records which file
produced which row. MLflow stores the file with the row, and one query produces the
learning-curve table. The cost is one 40-line wrapper module and one `--name` flag per command.

**One annotator instead of two passes.** One agent, or one person, would label each decision
once, in half the time. What would be missing is the agreement number. Without it there is no
way to tell a hard decision from an easy one, and no list of disputed spans to read. The
dispute lists of this project were the source of the 23 guideline questions. The two-pass
design also found its own limit: two passes with the same pre-annotations agree on almost
everything. The design therefore needs an independent check, here the human spot check.

**Labelling in the browser instead of text edits.** A human would use Label Studio directly:
coloured pre-annotations, hotkeys 1 to 9, an export with offsets. The text-edit toolchain
exists only because the annotators were agents, and a reader with human annotators can skip it.

## 11. Alternatives, and why not

The repository does not record a comparison of tools. The reasons below are general.

- **Prodigy, doccano, brat** instead of Label Studio. All three label spans. Label Studio has
  predictions as a first-class object and an HTTP API for import and ground truth, which the
  pre-annotation workflow needs. Prodigy is paid. A plain JSONL file without a viewer would
  have made the spot check of 358 spans impractical.
- **Weights and Biases or a hosted MLflow** instead of local SQLite. A hosted service shares
  runs with a team and survives the laptop. For one person the SQLite file does the same work
  with no account and no network.
- **A CSV written by the scorer.** Cheaper than MLflow for metrics alone. It loses the
  artifacts, the tags and the compare view, and it needs a second convention for parameters.

## 12. Questions to be able to answer afterwards

- Why does a Label Studio task carry `predictions` and not `annotations`, and what turns one into the other?
- Which file links Label Studio and MLflow, and in which direction does the data flow?
- Why does `gold.load_gold` need `labeling/tasks/<batch>.json`, and what happens when that file is missing?
- What does an agreement F1 of 0.998 between pass `a` and pass `c` prove, and what does it not prove?
- Why did round `v3` touch only 76 of 150 decisions, and what did the other 74 receive?
- How does `learning_curve.py table` find its 40 runs, and why is a tag better than a run-name pattern?
- What would the model registry add, and why does the project not need it yet?

## 13. Files

| file | role |
|---|---|
| `labeling/docker-compose.yml` | Label Studio 1.17.0, port 8080, local credentials, two volumes |
| `labeling/label_config.xml` | nine span labels, six outcome choices, comment field |
| `labeling/tasks/<batch>.json`, `<batch>.<round>.json` | tasks with pre-annotations; git ignores them |
| `scripts/labelstudio_api.py` | session-login client: create-project, import, export |
| `src/caselaw_extraction/labelstudio.py`, `negatives.py`, `gold.py` | task and prediction format; the negative-class proposals; the gold record shape and `load_gold` |
| `scripts/gold/*.py` | render, apply edits, agreement, finalize, make round, spot check |
| `docs/annotation-guideline.md`, `docs/guideline-open-questions.md` | the rules and their history |
| `docs/agent-*-brief.md` | the briefs for labelling, adjudication and the two rounds |
| `data/gold/` | ids, gold files per version, edits, annotations, disputes, spot check |
| `src/caselaw_extraction/tracking.py`, `scoring.py` | the MLflow wrapper; the metrics every run logs |
| `src/caselaw_extraction/cli.py`, `scripts/learning_curve.py` | the commands that log runs; the tagged runs and the `table` query |
| `Makefile` | `labelstudio-*`, `tasks`, `score`, `train-*`, `gold-*`, `learning-curve`, `mlflow-ui` |
| `mlflow.db`, `mlruns/` | the backend store and the artifacts; git ignores both |
| `docs/report.md`, sections 4, 5, 6 and 9 | the gold-set history, the extractor table, the results, the log of problems |
