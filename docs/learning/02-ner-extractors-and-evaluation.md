# NER extractors and their evaluation: what each model does, how we judge it, what we learned

This note explains the extraction models of the caselaw project and the way we score them. It
is written for someone who would build the same thing by hand and wants to understand each
piece before copying it. The code lives in `src/caselaw_extraction/`, the task definition in
`docs/annotation-guideline.md`, and the numbers in sections 5, 6 and 8.4 of `docs/report.md`.
Every number here is copied from the report, with the batch it was measured on. The report
separates development numbers from held-out numbers, and this note keeps that separation.

## 1. The problem extraction solves here

A decision of the Swiss Federal Supreme Court is a German text of 5,000 to 30,000 characters.
It cites federal acts (`Art. 42 Abs. 2 BGG`), leading cases (`BGE 140 III 86`), earlier
decisions by file number (`4A_437/2018`), sums of money and the roles of the parties. It ends
with a ruling that approves, dismisses or refuses the appeal. We want every citation as a
character span with a class, a key for each citation so that a graph can join decisions, one
outcome label per decision, and a measurement of how good each output is.

The text is formal, so hand-written rules reach a high score fast. The question of the
project is whether a learned model can match them, and what that costs in labelled data. The
answer needs four extractors with one output format, one scorer, and an unseen gold batch.

## 2. The vocabulary

**Span.** A `(start, end, label)` triple into the decision text, plus the covered text. Gold
files, prediction files and all extractors use this shape. A span covers the citation key
only; considerations (`E. 2.1`), pages (`S. 88`) and dates stay outside.

**Citation class, negative class.** The five citation classes are STATUTE, BGE, DOCKET, AMOUNT
and PARTY_ROLE. The pipeline links the first three to a key. Guideline v0.2 added four negative
classes: CONTRACT_ARTICLE, BARE_ARTICLE, OTHER_LAW and JOURNAL_REF. They look like citations
and link to nothing. Under v0.1 a clause such as `Art. 13 Ziff. 2 lit. a AVB` had no span, so a
model saw it as background and still labelled it STATUTE. Under v0.2 it has its own class, so
the model can learn the difference and the scorer can report the confusion (report, section
6.10). `gold.LABELS` holds all nine; `gold.CITATION_LABELS` holds the five.

**Outcome.** One label per decision from `gold.OUTCOMES`: `approved`, `partial_approval`,
`dismissed`, `inadmissible`, `moot`, `consolidated`, `unknown`. The values match the dataset's
own `outcome` column.

**Gold, batch, held out.** Gold is the corrected annotation in `data/gold/<batch>.gold.jsonl`.
Batch 1 has 60 decisions, batch 2 has 90, batch 3 has 200. Batch 2 is the held-out batch: no
rule was tuned on it before scoring, and no model trained on it. A number measured on the
data that produced the rules is a development number.

**Window.** A piece of a decision of at most 1,500 characters (spaCy) or 1,200 characters
(transformer), cut at a line break and never inside a span (`gold.windows`). A transformer
reads at most 512 subword pieces, so the learned models train and predict on windows.

**BIO tags.** General NER theory: each token gets `B-X` (begins a span of class X), `I-X`
(inside one) or `O` (outside). `gold.TAGS` lists `O` plus `B-` and `I-` for each of the nine
classes, so 19 tags. `gold.tags_to_spans` merges token tags back into spans.

**Jensen-Shannon distance.** General theory: a symmetric distance between two probability
distributions, in base 2 here, so that it lies in [0, 1]; 0 is identical, 1 is disjoint.

## 3. How the pieces connect

```
 labeling/tasks/<batch>.json          data/gold/<batch>.gold.jsonl
 (decision texts)                     (corrected spans + outcome)
        |                                        |
        v                                        |
 +-----------------------------------------+     |
 | four extractors                         |     |
 |  regex_extractor.py   (rules + Fedlex)  |     |
 |  spacy_extractor.py   (blank "de" NER)  |     |
 |  transformer_extractor.py (gbert, BIO)  |     |
 |  scripts/llm/* (Haiku agents + brief)   |     |
 +-----------------------------------------+     |
        |  data/pred/<batch>/<name>.jsonl        |
        v                                        |
 caselaw link  (linking.py) -> <name>-linked.jsonl
        |                                        |
        v                                        v
 caselaw score (scoring.py, evaluate.py) ----> tables + MLflow (sqlite:///mlflow.db)

 caselaw run-corpus -> data/runs/<run>/*.parquet -> store.py (DuckDB | Postgres)
                                                        |
                                            caselaw drift (drift.py), GET /drift
```

Every extractor writes the same prediction file. The linking stage reads it and writes a
second file next to it. The scorer reads either one and compares it with the gold of the same
batch. The drift check uses no gold; it compares two periods of a full-corpus run.

## 4. The four extractors

### 4.1 The regex extractor (`regex_extractor.py`, v0.1 to v0.4)

The module holds one compiled pattern per class and a procedure for the outcome. `VERSION` is
`regex-v0.4`. It was the pre-annotator for Label Studio and the first extractor of the
comparison. `STATUTE_RE` is built from parts: article number with suffixes, `Abs.`, `Satz`,
`lit.`/`Bst.`/`Ziff.` lists, `f.`/`ff.`, chain separators (`und`, `i.V.m.`, `sowie`) and the
code. `WS` allows a line break inside a citation, because the source wraps citations.

| version | what it added | measured on | span F1 exact |
|---|---|---|---|
| v0.1 | the pre-annotator of batch 1 | batch 1 | 0.901 (6.2) |
| v0.2 | line breaks inside citations, ranges, `f.`/`ff.`, ordinal `Satz`, `SchlT`, `Mio.`/`Mrd.`, old dockets, all header dockets as own numbers, side requests skipped | batch 1 (development) | 0.998 (6.3) |
| v0.2 | the same rules, frozen | batch 2 (held out) | 0.994 (6.4) |
| v0.3 | twelve rules from the 22 misses on batch 2: bare `Abs.` chain elements, `Abs.` ranges, `Art` without dot, `aVVG`, `EPÜ 2000`, decimal comma before `Mio.`, chains past a short citation, `Das Bundesgericht erkennt:`, time-limit restoration as side request | batch 2 (development) | 0.998, later 0.999 (6.6) |
| v0.4 | guideline v0.3: short BGE citations as spans (`_SHORT_CITE_RE`), `Artikel` written out, the `EPÜ 2000` lookup fix | batch 2 (development, v0.3 gold) | 0.999 (6.11) |

The code check is the knowledge the pattern alone lacks. `extract_statutes` calls
`fedlex.resolve_code` and drops a match whose code is not a known act; that keeps the German
noun `Art` out. The outcome procedure takes the last `DISPOSITIV_RE` match, splits the next
1,500 characters into numbered items, skips `_SIDE_REQUEST_RE` items, and applies
`_OUTCOME_RULES` in order; `teilweise gutgeheissen` is tested before `gutgeheissen`.

The report calls v0.4 a development number twice over. The rules saw batch 2, and v0.4 was the
pre-annotator of the round that produced the v0.3 gold. Its 0.999 says that the rules are
consistent with the gold, not that the regex generalises (section 6.11).

### 4.2 The spaCy extractor (`spacy_extractor.py`)

Two small models trained from zero on CPU with spaCy's default architectures (hash embeddings
plus a CNN, transition-based NER; a bag-of-words text classifier). No pretrained weights.

`train_ner` starts from `spacy.blank("de")`, adds the `ner` pipe and one label per entry of
`gold.LABELS`. `ner_examples` cuts each decision with `windows(d.text, d.spans)` and builds one
`Example` per window. spaCy drops an entity that does not align with its tokens (warning
W030); the function counts these as `n_misaligned`. Training runs 20 epochs. Each epoch
shuffles the examples and feeds `minibatch` with `compounding(4.0, 32.0, 1.001)`, so the batch
size grows from 4 towards 32 by a factor of 1.001 per batch. Dropout is 0.2. `random.seed` and
`spacy.util.fix_random_seed` make a run repeatable. Batch 1 gives 631 windows and 2,650 spans
(report, section 5); training took 292 s on CPU.

`predict_ner` cuts with `windows(d.text, [])`, runs `nlp.pipe` with batch size 32, shifts each
entity by the window offset and calls `gold.dedupe`. `train_textcat` reads `gold.dispositiv`,
the 1,500 characters after the last ruling header, for 30 epochs with minibatch size 8.

### 4.3 The transformer extractor (`transformer_extractor.py`)

A pretrained German encoder, `deepset/gbert-base` (110 M parameters), with a new linear head.
One model does token classification over the BIO tags; a second does sequence classification
over the ruling section. `device()` picks Apple MPS, CUDA or CPU.

**Encoding.** `token_dataset` cuts windows of `WINDOW_CHARS = 1200`. The comment gives the
reason: digit-heavy text tokenises into many pieces, so 1,200 characters stay under
`MAX_LEN = 512`. `_encode_window` derives one tag per token from `gold.char_tags`: the tag of
the first non-space character of the token. Special tokens get `-100`, which the loss ignores.

**Training.** AdamW with learning rate `3e-5` and weight decay 0.01, a linear schedule with 10
percent warm-up, gradient clipping at 1.0, batch size 8, 4 epochs. `seed_all` seeds Python,
NumPy and PyTorch. The outcome classifier uses the same optimiser for 12 epochs. Batch 1 gives
794 windows; fine-tuning took 191 s for spans and 40 s for the outcome on MPS (section 5).

**Tokenizer and config fallbacks.** `load_tokenizer` tries `AutoTokenizer` and falls back to
`BertTokenizerFast` on a `ValueError`; `load_config` does the same with `BertConfig`. The
docstrings and report section 9 (2026-10-21) record the reason: transformers 5 cannot convert
a `vocab.txt`-only checkpoint without `model_type` through the `Auto*` classes.

**Decoding.** `predict_token_classifier` takes `decode="argmax"` or `decode="viterbi"`. Argmax
picks the best tag per token independently, so `O, I-STATUTE` sequences occur.
`bio_transition_mask` builds an `allowed[prev, cur]` table: `I-X` may only follow `B-X` or
`I-X`, and a sequence may only start with `O` or `B-*`. `viterbi_decode` finds the best path
under these hard constraints. The docstring is explicit: this is constrained decoding, not a
CRF. The model's scores are unchanged; only invalid sequences are excluded.
`tests/test_decoding.py` checks that `O, I-X, I-X` becomes `O, B-X, I-X`. `tag_names_of` reads
the tag set from the saved config, so a model trained under an older label set still decodes.

Result on batch 2 (section 6.9): +0.001 to +0.002 span F1 on every seed (s0 0.984 to 0.986,
s1 0.983 to 0.985, s2 0.986 to 0.986). Most fragments the model emits (`Art`, `8`) are valid
BIO sequences, so the constraint rarely fires.

### 4.4 The LLM extractor (`docs/llm-extractor-brief.md`, `scripts/llm/`)

Claude Haiku agents follow the brief. They get plain text only, no pre-annotations, and must
not open the gold, the guideline or the source. The brief defines the five classes, the
boundary rules and the outcome procedure. The procedure per decision has four steps:

1. `render_decision.py <batch> <N>` prints the decision.
2. The agent writes one JSON object: `outcome` and a list of `{"label", "text"}` citations in
   document order.
3. The agent saves it to `data/pred/<batch>/llm_raw/<model>/<decision_id>.json`.
4. `apply_output.py <batch> <N> <model>` resolves the texts to offsets and prints `OK` or
   `CHECK`.

The agent names spans by exact text, not by offsets. Report section 9 (2026-10-21) records
why: agents cannot compute character offsets reliably, and text matching worked on the first
try. `apply_output.py` builds a whitespace-tolerant pattern per text and searches from the end
of the previous match. A text not found there is searched from the start and counted as a
backtrack; a text not found at all is dropped and listed. A BGE text without the leading `BGE`
word gets the prefix back when `BGE ` stands right before it (`_BGE_LEAD_RE`).
`collect.py <batch> <model>` joins the resolved files into `data/pred/<batch>/llm-<model>.jsonl`.

On batch 2 the raw texts scored span F1 0.936, because 177 BGE spans lacked the prefix. With
the resolver restoring it, 0.985. Entity F1 0.996 and outcome 90/90 were the best of any
extractor in week 2 (section 6.5). The resolver, not the agent, owns the boundary.

## 5. The entity-linking stage (`linking.py`, `fedlex.py`)

A span model reads only the text. Two facts that decide whether a span is a citation are not
in the text: the list of Swiss federal acts and the decision's own file numbers. The linking
stage holds both for every extractor alike. It resolves each span to a key and drops the spans
that resolve to nothing. It never changes a boundary and never adds a span.

| label | key | dropped when (`REASONS`) |
|---|---|---|
| STATUTE | `{code, sr, article}` per article of the chain | no digit in the span (`no_article`); no code is a federal act (`unknown_code`) |
| BGE | `BGE <volume> <part> <page>` | no volume, part and page (`no_bge_key`) |
| DOCKET | `4A_12_2020` from `norm_docket` | it is an own file number (`own_docket`) |
| AMOUNT, PARTY_ROLE | none | never |

**Fedlex keys.** `fedlex.load_code_map` reads a cache of abbreviations from the Fedlex SPARQL
endpoint (`data/interim/fedlex_abbreviations.json`). `CORE_CODES`, a hand-checked dictionary of
about seventy acts, overrides it. `resolve_code` tries forms in a fixed order: the full code,
the code without a trailing year, the code without an `a` prefix, the last token of a
multi-word code. The docstring names the case that set the order: Fedlex lists the European
Patent Convention as `EPÜ 2000`, so the full form must be tried before the year is stripped.

**BGE keys and dockets.** `evaluate.bge_key` parses `vol part page`. A bare page number
inherits volume and part from the nearest full citation in the 150 characters before it, so
`115` after `BGE 140 III 86 E. 2,` resolves to `BGE 140 III 115` (`tests/test_entities.py`).
`norm_docket` removes whitespace and replaces `/` and `.` with `_`: `4C.195/2005` becomes
`4C_195_2005`. `docket_of` derives the own number from the decision id (`bger_4A_12_2020`);
`regex_extractor.own_dockets` adds the header numbers of joined proceedings.

**Why linking must not be presented as learning.** The report is explicit (sections 6.7, 6.8
and 9). On batch 2 the stage raised gbert s0 from span F1 0.984 to 0.994 and entity F1 from
0.989 to 0.996. It dropped 13 own dockets, 55 unknown codes, 9 spans without an article and 7
BGE spans without a key. Those are failures the model still has after linking; the table
merely stops counting them. The regex and the LLM lose nothing in the stage, because they
carry the knowledge already. Hence the rule: report before and after side by side, and give
the hidden failures their own classes. By section 6.13, gbert trained on 260 decisions loses 4
spans to `unknown_code` instead of 62.

## 6. The evaluation (`evaluate.py`, `scoring.py`)

`scoring.score_file` scores one prediction file against one gold batch and returns the tables
and a metrics dictionary. A decision missing from the prediction file counts as empty.

**Span F1, exact and overlap.** `_exact` works on sets of `(start, end, label)`: the
intersection is true positives, each difference is false positives or false negatives.
`_overlap` walks the sorted predictions, and each one claims the first unclaimed gold span of
the same label that it overlaps. Both are summed per label to a micro average. Exact is the
headline number. `Scores(labels=...)` filters both sides to one label set first. The default is
the five citation classes, so that every extractor is comparable; `caselaw score --labels all`
scores nine.

**Entity F1.** `entity_keys` turns the spans of one decision into sets of keys per entity label
(STATUTE, BGE, DOCKET). `statute_keys` expands `Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG` into
`BGG 42` and `BGG 106`. The dataset's silver graph has no offsets, so `caselaw score silver`
compares it at this level only.

**Outcome accuracy and macro-F1.** `score_decision` counts correct outcomes and fills a
confusion counter `(gold, pred)`. `scoring.macro_f1` takes the mean F1 over the classes that
occur in the gold. Batch 2 holds four outcome classes (dismissed 43, inadmissible 43, approved
2, moot 2; no partial approval). A classifier that only gets the two common classes right
scores 85 of 90 in accuracy and about 0.59 in macro-F1. That gap is why the report quotes both.

**Label confusion.** `_label_confusion` records `(gold label, predicted label)` for every
overlapping pair over all nine labels. A gold span with no overlapping prediction counts as
`(gold, O)`, a prediction over no gold span as `(O, pred)`. The docstring names the purpose:
this is where a STATUTE predicted on a CONTRACT_ARTICLE becomes visible. Each off-diagonal cell
is logged to MLflow as `confusion_<gold>_as_<pred>`. In week 2 gbert s0 labelled 32 of 38
contract clauses STATUTE; trained on 260 decisions, 0 of 55 (sections 6.10 and 6.13).

**Held-out batches and the anchoring caveat.** Batch 2 is the only batch that no rule and no
model touched before scoring. One caveat applies to every batch: the gold was made by
correcting regex pre-annotations, accepted unchanged in 68 of 90 decisions of batch 2. The
gold is anchored on the regex, so precision near 1.000 is partly a consequence. The human spot
check of 358 spans (0 errors) bounds the gold error rate, not the anchoring bias (6.8).

### 6.1 The headline numbers

All on batch 2 (90 decisions). Span F1 is exact match over the five citation classes.

Week 2, v0.1 gold (section 6.5):

| extractor | span F1 | entity F1 | outcome | macro-F1 |
|---|---|---|---|---|
| regex v0.2, frozen before batch 2 | 0.994 | 0.994 | 88/90 | 0.991 |
| spaCy seed 0, trained on batch 1 | 0.982 | 0.989 | 82/90 | 0.596 |
| gbert-base seed 0, trained on batch 1 | 0.984 | 0.989 | 85/90 | 0.586 |
| LLM Haiku, resolver keeps `BGE` prefix | 0.985 | 0.996 | 90/90 | 1.000 |
| opencaselaw silver graph | – | 0.948 | – | – |

Seed spread: the span models vary by at most 0.003 (spaCy 0.982, 0.979, 0.980; gbert 0.984,
0.983, 0.986). The outcome heads swing by up to nine decisions (gbert 85, 87, 79, 87, 82 over
five seeds), so the report says a single-seed outcome number should not be quoted.

Re-scored on v0.3 gold, which adds 59 short BGE citations and 2 written-out statutes to batch 2
(section 6.11): regex v0.2 falls to 0.985, regex v0.3 0.990, regex v0.4 0.999 (development).
spaCy v3 s0 0.978 and gbert v3 s0 0.979, both with BGE F1 above 0.998. The LLM with the v0.3
prompt reaches 0.985 span and 0.999 entity F1; with the week-2 prompt, which called short
citations pages, it scored 0.978.

Trained on 260 decisions, batches 1 and 3, still against batch 2 (section 6.13):

| model | span F1 | after linking | outcome | macro-F1 | CONTRACT_ARTICLE | BARE_ARTICLE | OTHER_LAW | JOURNAL_REF |
|---|---|---|---|---|---|---|---|---|
| gbert s0 | 0.993 | 0.996 | 90/90 | 1.00 | 0.85 | 0.89 | 0.86 | 0.97 |
| gbert s1 | 0.991 | 0.994 | 90/90 | 1.00 | 0.84 | 0.85 | 0.75 | 0.90 |
| spaCy s0 | 0.985 | 0.989 | 89/90 | 0.95 | 0.47 | 0.69 | 0.67 | 0.89 |
| regex v0.2, frozen | 0.985 | 0.985 | 88/90 | 0.99 | – | – | – | – |
| regex v0.4, tuned on all batches | 0.999 | 0.999 | 90/90 | 1.00 | – | – | – | – |

gbert on 260 decisions passes the frozen regex on the held-out batch without the linking
stage. The remaining 0.006 to regex v0.4 is a development number. Data alone fixed the outcome
head: 260 labels with 46 approved, 19 partial approvals and 11 moot.

### 6.2 The learning curve and what it says about data needs

`scripts/learning_curve.py` trains the span models only, on growing subsets of v0.3 gold, and
scores the five citation classes on batch 2. The main curve takes the first 15, 30, 45 or 60
decisions of a seeded shuffle of batch 1, three seeds, against all 90 decisions of batch 2.
The extended curve splits batch 2 once (seed 7) into a 45-decision pool and a 45-decision test
half. It trains on batch 1 plus 0 to 45 pool decisions, two seeds, and scores the test half
only (`score_file(..., only_ids=...)`).

| training decisions | spaCy, full batch 2 | gbert, full batch 2 | spaCy, 45-decision half | gbert, 45-decision half |
|---|---|---|---|---|
| 15 | 0.954 | 0.922 | – | – |
| 30 | 0.970 | 0.962 | – | – |
| 45 | 0.976 | 0.977 | – | – |
| 60 | 0.977 | 0.979 | 0.976 | 0.977 |
| 75 | – | – | 0.976 | 0.980 |
| 90 | – | – | 0.983 | 0.982 |
| 105 | – | – | 0.977 | 0.983 |

The report reads it in three sentences. The steep part ends at 45 decisions. Beyond 60, gbert
gains about 0.002 per 15 decisions with non-overlapping seed ranges, so parity with regex v0.2
at 0.985 was expected at 150 to 250 decisions. spaCy does not improve beyond 60 in a way the
curve can resolve. The extended points are not held out in the week-2 sense, because they
train on half of batch 2. Section 6.13 confirmed the forecast at 260 decisions.

## 7. The drift check (`drift.py`)

The drift check asks whether the distribution of what decisions cite has changed between two
periods. It needs no gold. A period is a month (`2025-09`) or a year (`2025`) of decision
dates. `KINDS` names six distributions:

| kind | the distribution of a period |
|---|---|
| `statute`, `bge`, `docket` | decisions that cite each key (`count(DISTINCT decision_id)`) |
| `code` | decisions that cite each act |
| `outcome` | decisions per outcome class |
| `label` | spans per span class |

`_counts_sql` builds one SQL statement per kind. Every query goes through `Store`, so the
check runs on DuckDB over a run directory and on Postgres with the same SQL. With two period
values as parameters the query restricts itself to those periods, which cut the two-period
report from 2.9 s to 0.3 s (commit of 2026-11-03).

`js_distance` returns the square root of the Jensen-Shannon divergence in base 2, so the value
lies in [0, 1]. `total_variation` is half the L1 distance of the shares. `compare` adds the
keys whose share of decisions moved most (`movers`). `drift_report` runs `compare` for every
kind between two periods; `drift_series` runs the distance between each period and the one
before it. `quantile` is linearly interpolated; `format_series` prints the median, the p95 and
the maximum. `tests/test_drift.py` checks the identities: equal shares give 0, disjoint keys
give 1, `{a:1, b:1}` against `{a:1}` gives total variation 0.5.

**Thresholds from the series.** A threshold needs a noise level, so the series over the 81
month-to-month steps of the corpus comes first (report, section 8.4):

| kind | median JS | p95 | max | usable month to month |
|---|---|---|---|---|
| statute article | 0.448 | 0.491 | 0.515 | yes, with a high level |
| act (`code`) | 0.227 | 0.278 | 0.322 | yes, the most stable signal |
| BGE | 0.620 | 0.669 | 0.682 | marginal |
| outcome | 0.140 | 0.225 | 0.273 | yes |
| file number | about 0.93 | – | – | no |

The proposed rule is one alarm per kind at the 95th percentile of its own series: statute
0.49, act 0.28, outcome 0.23. The last complete step, August to September 2026, stays under
every threshold (statute 0.445, act 0.230, outcome 0.169). The movers still name the month: the
distinct articles halve from 230 to 134, inadmissibility rises from 67 to 76 percent of
decisions, the ZPO share falls from 31 to 7 percent. The mean text length of a September 2026
decision is 6,900 characters against 10,700 in August. The report leaves two explanations open:
a short month, or a dataset month that is not complete yet.

**CLI and API.** `caselaw drift --a 2026-08 --b 2026-09` prints the two-period report; without
`--a` and `--b` it takes the last two periods. `--series --kind code` prints the series with
its quantiles. `--fail-above 0.49` exits with code 1 when the statute JS distance exceeds the
value, which is the hook for a scheduled check. `--out` writes JSON. The API serves the same
functions: `GET /drift?a=2026-08&b=2026-09&period=month&top=10` and
`GET /drift/series?period=month&kind=statute`; an unknown period returns 404. The Makefile wraps
the two forms as `make drift A=... B=...` and `make drift-series KIND=...`.

## 8. Walkthrough by hand

These steps reproduce the results of section 6 with the Makefile and the CLI. Each step is
here so that the reader knows which command made which number. `BATCH` defaults to `batch2`.

1. Predict with the regex: `make predict-regex`. The file is `data/pred/batch2/regex.jsonl`.
2. Score it: `make score PRED=data/pred/batch2/regex.jsonl NAME=regex-batch2`. The span,
   entity, outcome and confusion tables print, and MLflow stores the run.
3. Score the dataset's silver graph at entity level: `make score-silver`.
4. Train spaCy on batch 1 and score on batch 2: `make train-spacy`.
5. Train gbert the same way: `make train-transformer`. The models land in
   `models/gbert-base-s0-ner` and `models/gbert-base-s0-outcome`.
6. Decode a saved model with Viterbi:
   `make predict-transformer MODEL=models/gbert-base-s0-ner DECODE=viterbi`.
7. Link prediction files and log the linked scores:
   `make link PRED="data/pred/batch2/gbert-base-s0.jsonl data/pred/batch2/spacy-s0.jsonl"`.
   The drop table prints one row per file with the four reasons.
8. Score nine classes instead of five:
   `uv run caselaw score data/pred/batch2/gbert-base-s0.jsonl --batch batch2 --labels all`.
9. Train on 260 decisions: `uv run caselaw train-transformer --train batch1,batch3 --eval batch2`.
10. Collect the LLM output after the agents finished: `make llm-collect`. The file is
    `data/pred/batch2/llm-haiku.jsonl`; score it with step 2.
11. Run the learning curve: `make learning-curve MODEL=gbert CURVE=main`, then
    `uv run python scripts/learning_curve.py table`.
12. Print the drift series of a corpus run: `uv run caselaw drift --series --kind statute`.
13. Compare two months: `uv run caselaw drift --a 2026-08 --b 2026-09 --fail-above 0.49`.
14. Open MLflow: `make mlflow-ui`, then `http://127.0.0.1:5001`.

```
# the prediction format every step above reads or writes (one line per decision)
{"decision_id": "bger_4A_12_2020", "outcome": "dismissed",
 "spans": [{"start": 1203, "end": 1221, "label": "STATUTE", "text": "Art. 42 Abs. 2 BGG"}]}
```

## 9. What went wrong, and what each mistake teaches

Each item is recorded in the report (section 9 or the results sections) or in a code comment.
The tokenizer fallback of section 4.3 is a further item of the same kind.

**The first ruling pattern left 54 percent of outcomes unknown** (2026-10-20). It matched only
`Demnach erkennt das Bundesgericht`. Single-judge rulings use `der Präsident`, `die
Präsidentin`, `das präsidierende Mitglied`, and short rulings drop `Demnach`. The comment
above `DISPOSITIV_RE` lists the variants. Lesson: test a header pattern on the whole corpus.

**The guideline's own example was wrong** (2026-10-21). It said that `115` in
`BGE 140 III 86 E. 2 S. 89, 115 E. 2` is a page. In most occurrences it is BGE 140 III 115, a
different decision. Every agent followed the example, so both batches missed these citations.
This became guideline v0.3 and 59 new gold spans in batch 2. Lesson: an example in a brief
shapes output more than a rule does.

**The LLM agents wrote BGE items in the bare form** (2026-10-21). The prompt showed the bare
form for continuation items, and 177 spans lost their prefix. `apply_output.py` restores it;
raw span F1 was 0.936, resolved 0.985. Lesson: separate what the model extracts from how the
resolver draws the boundary, and report both.

**A post-filter looked like a model improvement** (2026-10-23). It raised gbert from 0.984 to
0.992 in an afternoon. It was not counted as learning, because it hides failures and its rules
came from the batch-2 errors. It became the linking stage with before and after columns, and
the hidden failures became the four negative classes. Lesson: report a stage that uses
knowledge the model cannot read separately from the model.

**Fedlex keys the European Patent Convention as `EPÜ 2000`** (2026-10-23). The regex, the key
parser and the first linker all stripped the year before the lookup, and the code pattern
matched `EPÜ 2`. Three gold spans were lost in every extractor that uses the list. Lesson: a
lookup key is data too; test the order of the forms you try.

**Two annotation passes were not two annotators** (2026-10-21). Pass a and pass c agreed on
3,571 of 3,573 spans of batch 2, because both corrected the same pre-annotations. The human
spot check is the only independent signal. Lesson: agreement between models on shared
proposals is consistency, not truth.

## 10. How to verify

1. Run `make test`. The three test files of section 13 cover the Viterbi mask, the key
   functions, the scorer's label filter, the macro-F1 and the distance identities.
2. Score a prediction file against its batch and read the micro row of the span table. The
   value must match the MLflow run of the same name.
3. Compare a `-linked.jsonl` file with its source. The span count must fall by the sum of the
   drop table, and no `start` or `end` may change.
4. Run `caselaw drift --series --kind outcome` and compare the p95 with 0.225 in the report.

## 11. Alternatives, and why not

- **A CRF head on the transformer** instead of constrained Viterbi. It learns transition
  scores and would stop fragments that are valid BIO. The report lists it as a next step that
  is not done (sections 6.9 and 6.10).
- **The dataset's silver graph** as the only extractor. It reaches entity F1 0.948 with STATUTE
  recall 0.826; the regex finds about 17 percent more statute references (section 6.5).
- **The LLM for everything.** It scores best on entity F1 and the outcome and needs no
  training data for a new rule. It took about 25 minutes of wall time for 90 decisions with
  nine agents, against under a second for the regex and 12 s for gbert, on a 7,999-decision corpus.

## 12. Questions to be able to answer afterwards

- What does the linking stage know that no span model can read from the text?
- Why does the report refuse to count the linking gain of gbert as learning?
- Which number on batch 2 is held out and which is a development number, for regex v0.2,
  v0.3 and v0.4?
- Why can accuracy be 85 of 90 while the macro-F1 is 0.586?
- What does Viterbi decoding under BIO constraints change, and why does it rarely fire here?
- Why does the drift threshold come from the p95 of the series, and why is the file-number
  kind unusable for it?

## 13. Files

| file | role |
|---|---|
| `src/caselaw_extraction/regex_extractor.py` | the rule-based extractor, `VERSION = regex-v0.4`, outcome procedure |
| `src/caselaw_extraction/spacy_extractor.py` | spaCy NER and textcat trained from zero |
| `src/caselaw_extraction/transformer_extractor.py` | gbert token and sequence classifiers, BIO mask, Viterbi, tokenizer fallbacks |
| `src/caselaw_extraction/gold.py`, `linking.py`, `fedlex.py` | labels, tags, windows, prediction files; the entity-linking stage, its drop reasons, the Fedlex map |
| `src/caselaw_extraction/evaluate.py`, `scoring.py` | span, entity, outcome and confusion scores; `score_file`, `macro_f1` |
| `src/caselaw_extraction/drift.py` | period counts, the two distances, report, series, quantile |
| `src/caselaw_extraction/cli.py`, `api.py` | the commands of section 8; `GET /drift`, `GET /drift/series` |
| `scripts/llm/apply_output.py`, `scripts/llm/collect.py` | resolve LLM texts to offsets; join them into one prediction file |
| `scripts/learning_curve.py` | the two learning curves and the MLflow table |
| `docs/llm-extractor-brief.md`, `docs/annotation-guideline.md` | the brief the agents follow; the nine classes and the outcome rule |
| `tests/test_decoding.py`, `tests/test_entities.py`, `tests/test_drift.py` | the unit tests named in section 10 |
| `docs/report.md`, sections 5, 6 and 8.4 | every number quoted in this note |
