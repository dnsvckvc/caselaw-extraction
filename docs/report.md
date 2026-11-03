# Project 1: Case-Law Extraction Pipeline — report

Status: weeks 1 to 4 complete except the recording. Week 1: corpus of 7,999 decisions, schema, Label Studio, first gold batch. Week 2: gold set of 350 decisions over three batches (guideline v0.3, nine classes), five extractors compared, entity-linking stage, learning curve, models retrained on 260 decisions. Week 3 (2026-10-28): full-corpus run under Dask, Postgres, citation graph with the three headline analyses, FastAPI service, regex graph compared with the gbert graph. Week 4 (2026-11-03): drift check, API image, deployment on one Hetzner server with Terraform (API at `https://api.caselaw.inat.io`, this report at `https://caselaw.inat.io`), monitoring and backups prepared; the AWS stack validated as the second target (section 8). Last updated 2026-11-03.

## Management summary

This section is for readers who need the result and the decision, not the method. Every number in it appears again in the numbered sections, with its caveats.

### What was built

The pipeline reads the 7,999 German-language civil decisions that the Swiss Federal Supreme Court published from January 2020 to October 2026. For each decision it extracts the cited statute articles, the cited leading cases (BGE), the cited file numbers, the amounts in dispute, the party roles and the outcome. It links each citation to a canonical key (the Fedlex act and article, the BGE volume and page, the normalised file number). The linked citations form a citation graph of 19,622 nodes and 86,365 edges. A read-only API serves the decisions, the citations and the three headline analyses (most-cited articles, trend by year, most central decisions) from Postgres. The same code runs on a laptop without a database in under two seconds on a 100-decision sample.

### Results

| question | answer | where |
|---|---|---|
| How good is the extraction? | The rules reach span F1 0.985 on a held-out batch and 0.999 after tuning. A fine-tuned German BERT trained on 260 gold decisions reaches 0.993 held out and gets all 90 held-out outcomes right. | 6.4, 6.11, 6.13 |
| Does the choice of extractor change the result? | No. The rule-based graph and the model-based graph agree on 97 to 99 percent of edges, and their top-20 lists are identical. | 7.6 |
| What does the full run cost? | The rules take 10 seconds on one core, under one cent. The model takes 30 minutes on a GPU, about USD 0.63. An LLM would cost about USD 140 per run. | 7.1, 7.5 |
| What does it cost to serve? | Under EUR 6 per month on one Hetzner server with HTTPS, against about USD 47 for the equivalent AWS stack, which was written and validated but not applied. | 8.5, 8.6 |
| What does the graph show? | The court cites its own procedure act in every decision. Three leading cases on the duty to substantiate an appeal are cited in four of ten decisions. The share of decisions citing the Civil Procedure Code fell from 35 to 25 percent in 2025 and 2026. | 7.3 |
| Does the extraction drift over time? | The month-to-month distance of the statute distribution has a median of 0.45 and a 95th percentile of 0.49 over 81 months. September 2026 is the first month the check flags: shorter decisions, three quarters of them inadmissibility rulings, half the usual number of distinct articles. | 8.3 |
| How reliable is the gold set? | 350 decisions and 16,783 spans, labelled by two different language models and adjudicated. A human check of 10 decisions found 0 errors in 358 spans. | 4 |

### Decision

The rule-based extractor goes to AWS in week 4. On this corpus the learned model buys no change in any analysis at 185 times the compute. The model is kept for the cases where the rules stop: citation forms nobody has written a rule for, cantonal file numbers, and the French and Italian decisions.

### Key figures

| figure | value |
|---|---|
| corpus | 7,999 decisions, 2020-01-06 to 2026-10-07 |
| gold set | 350 decisions, 16,783 spans, 9 span classes, 5 outcome classes |
| extractors compared | 5 (rules, the dataset's own graph, spaCy, German BERT, LLM) |
| best held-out span F1 | 0.993 (German BERT on 260 decisions); frozen rules 0.985 |
| full-corpus run | 294,884 spans, 249,762 linked citations |
| citation graph | 19,622 nodes, 86,365 edges |
| agreement of the two graphs | Jaccard 0.994 (statutes), 0.991 (BGE), 0.974 (file numbers) |
| API | 11 read-only endpoints; 5 ms per decision on the laptop, about 100 ms end to end over HTTPS from Switzerland |
| deployment | `https://api.caselaw.inat.io`, one Hetzner server, Terraform, under EUR 6 per month |
| tests | 87, all passing |
| experiment runs tracked | 127 in MLflow |

### Risks and limits

- The gold set was labelled by language-model agents, not by legal professionals. One human check covers 10 of 350 decisions. The agents corrected proposals from the rules, so the gold set favours the rules in every comparison.
- The dataset's own outcome label disagrees with the extractor in 1,179 of 5,806 decisions. Sampling shows the dataset label is the one in error. The analyses use the extractor's outcome.
- The AWS costs are estimates from local run times and public price pages. Week 4 measures them.
- The deployment is one server without a load balancer or a managed database. A nightly dump to object storage and a six-second rebuild from Parquet are the recovery path. Monitoring and the backup cron are configured and start when the Grafana Cloud and R2 credentials are set.
- The corpus is one language, one court and one branch of law. The rules do not cover French or Italian.

### Next step

Switch on monitoring and backups with the two remaining credentials, record the five-minute demo. Then Project 2, which builds on this API and corpus.

## 1. Problem

Legal professionals need to know which statutes and prior decisions a court relies on.
This project extracts statute citations, prior-decision citations, header facts, amounts and
outcomes from Swiss Federal Supreme Court (BGer) decisions, evaluates several extractors
against a hand-labelled gold set, runs the best one over the corpus, and builds a citation graph.

## 2. Data

- Source: `voilaj/swiss-caselaw` on Hugging Face, CC0-1.0, built by the `opencaselaw` project
  from entscheidsuche.ch. Court decisions are official works and not subject to copyright
  (URG Art. 5).
- Scope for this project: BGer, German, civil-law branch (`branch = 'zivil'`),
  decisions from 2020-01-01 with full text. Corpus size: **7,999 decisions**
  (2020-01-06 to 2026-10-07), about 1,100 per year, 25 MB as zstd Parquet.
- Ingest: the 920 MB `bger.parquet` is downloaded once, then filtered with DuckDB.

### Data-quality findings (week 1)

- 13 rows tagged `language = 'de'` are French or Italian (all from 2026). The ingest filter
  now checks the text header (`Arrêt du`, `Sentenza del`) and drops them.
- 12 rows carry `chamber = 'II. Öffentlich-rechtliche Abteilung'` although the text header
  says a civil chamber. The corpus derives `chamber_text` from the header instead.
- The dataset's `outcome` column is missing for 2,193 of 7,999 decisions (27%).
- Where the dataset has an outcome, the regex extractor disagrees in 1,117 of 5,806 cases.
  The largest group (951 cases) is `dataset = dismissed`, `regex = inadmissible`. In every
  sampled case the first dispositiv item reads "Auf die Beschwerde wird nicht eingetreten" and a
  later item rejects a legal-aid request ("wird abgewiesen"). The dataset label appears to pick
  up the later item. The gold set will settle this; the working assumption is that the silver
  outcome label has an error rate near 16%.
- The dataset ships its own citation graph (`graph/citations.parquet`,
  `graph/statute_references.parquet`). This project treats it as a **silver baseline**
  and measures it against the gold set like any other extractor.

## 3. Architecture

```
 Hugging Face (CC0)        ingest (DuckDB)           gold set (Label Studio, agents, adjudication)
 bger.parquet 920 MB  -->  corpus Parquet 7,999  -->  350 decisions, guideline v0.3, nine classes
                                 |                               |
                                 |              train / evaluate (MLflow, 125 runs)
                                 v                               v
                     corpus run (Dask or GPU)  <--  extractor: regex v0.4 | gbert-b13 | spaCy | LLM
                       + entity linking (Fedlex, BGE key, file number)
                                 |
                                 v
                  data/runs/<name>/  decisions | spans | citations  (Parquet)
                        |                    |                   |
                        v                    v                   v
                   Postgres (COPY)     citation graph       make demo (DuckDB only)
                        |             (NetworkX: centrality,
                        v              trend, top statutes)
                  FastAPI (/decisions, /statutes, /trends, /decisions/central)
```

Two stages are deliberately separate: extraction reads only the text; linking holds the
knowledge that is not in the text (the Fedlex list, the decision's own file number) and
applies to every extractor alike (section 6.8). Week 4 moves the Parquet to S3, the
database to RDS and the API to Fargate without changing the tables.

## 4. Gold set

- Target: 150 decisions (60 in week 1, 150 by end of week 2). Stratified by year and chamber.
- Batch 1: 60 decisions, 4 or 5 per (year x chamber) stratum over 2020-2026 and the two civil
  chambers, text length 5,000 to 30,000 characters (ids in `data/gold/batch1.ids.json`).
  The length cap is a known bias: very long decisions are under-represented in the gold set.
- Tool: Label Studio 1.17 in Docker with regex pre-annotation (`model_version = regex-v0.1`).
  The annotator corrects rather than draws. The first task carries 59 pre-annotations.

### How batch 1 was labelled (model-labelled, three passes, adjudicated)

Batch 1 was labelled by language-model agents, not by a human. This is a weaker form of gold
than human labels, and the numbers below must be read with that in mind.

- Each agent received a decision with numbered regex pre-annotations
  (`scripts/gold/render_task.py`), wrote an edits file (delete, relabel, add by exact text), and
  ran a checker that refuses overlaps and unmatched text (`scripts/gold/apply_edits.py`).
  Agents never computed character offsets themselves.
- Pass a and pass b: six Claude Fable agents each, ten decisions per agent, independent.
  Result: identical edits on all 60 decisions (2,650 spans, 60 outcomes). Two runs of the same
  model with the same brief are not independent evidence. Pass b was discarded.
- Pass c: six Claude Opus agents, same brief. Agreement with pass a: 2,650 of 2,650 pass-a spans
  reproduced, 2 extra spans in pass c, outcomes 60 of 60. The two extra spans
  (`Art. 27 Abs. 3 VSB`, a banking self-regulation; `Art. 93 VE-ZPO`, a draft code) were dropped
  under the rule that STATUTE requires a law in force.
- Rules clarified during labelling and added to the guideline: a chain of articles sharing one
  abbreviation is one span (also with commas, `bzw.`, `sowie`, `in Verbindung mit`); ranges and
  `f.`/`ff.` forms are spans; `Mio.` belongs to the amount; a second own docket number in joined
  proceedings is not a DOCKET; the outcome comes from the first dispositiv item that rules on the
  appeal itself, skipping side requests (Sistierung, Ausstand, legal aid); annul-and-remand and
  Berichtigung count as approved.
- Final gold: `data/gold/batch1.gold.jsonl`, also imported into Label Studio as ground truth so
  that any decision can be spot-checked in the browser.
- **Batch 1 is the development set.** The regex extractor was improved against it (section 6.3).
  Batch 2 (90 decisions, week 2) is the held-out test set. Regex v0.2 and every learned model
  were frozen before anyone looked at it; only regex v0.3 (section 6.6) was tuned after.

### Batch 2 (week 2, held out)

- 90 decisions, same stratification (`caselaw sample --n 90 --seed 2 --name batch2`), no
  overlap with batch 1. Pre-annotations from regex v0.2.
- Labelled with the same toolchain: pass a (nine Fable agents), pass c (nine Opus agents),
  ten decisions each. Agreement a vs c: 3,571 spans in both, 0 only in a, 2 only in c;
  outcomes 90 of 90. Adjudication dropped `Art. 90 BG` (typo, unknown abbreviation) and kept
  `F r. 30'000.00` (a sum whose currency token the text extraction broke). Final: 3,572 spans
  (STATUTE 1,594, BGE 1,056, DOCKET 344, AMOUNT 414, PARTY_ROLE 164); outcomes: dismissed 43,
  inadmissible 43, approved 2, moot 2. **No partial approval occurs in batch 2**, so that class
  is untested.
- The agents changed little: in 68 of 90 decisions they accepted every pre-annotation. Where
  they edited, the causes were BGE list items after a same-volume short citation, chains with a
  bare `Abs.` element, amounts with a decimal comma, and typos in the source.
- The agents raised 16 points the guideline does not settle. They are listed with a proposed
  v0.2 rule in `docs/guideline-open-questions.md`. Two of them change the gold set: same-volume
  short citations (`BGE 140 III 86 E. 2, 115 E. 2`, where `115` is a different decision) and
  `Artikel` written out. Both batches were labelled the v0.1 way, so the comparison below is
  consistent, but the citation graph (week 3) must resolve short citations separately.
- Gold: `data/gold/batch2.gold.jsonl`, also in Label Studio project 1 as ground truth.
- Human spot check (2026-10-22): Denis read 10 batch-2 decisions (seed 7 sample, ids in
  `data/gold/batch2/spot_check.ids.json`) in Label Studio with the gold spans shown. Result: 358
  gold spans, 0 wrong, 0 missed; 10 of 10 outcomes right (`data/gold/batch2/spot_check.md`).
  This is the first quality number for the gold set that does not come from a model. It covers
  10% of the spans in batch 2, so it bounds the error rate at roughly below 1% rather than
  proving zero.
- Labels: STATUTE, BGE, DOCKET, AMOUNT, PARTY_ROLE spans; outcome as a document label.

### Guideline v0.2 round (2026-10-23): four negative classes on both batches

- Why: the learned models' false positives were references that look like citations and are
  not (contract clauses, commentary article numbers, foreign law, journal references). Under
  v0.1 these had no span, so the models saw them only as background and the scorer could only
  count them as errors. v0.2 gives them classes CONTRACT_ARTICLE, BARE_ARTICLE, OTHER_LAW and
  JOURNAL_REF (`docs/annotation-guideline.md`, section "Negative classes"), so the models can
  learn them from data and the scorer can show the confusion. None of the four is linked.
- How: a *round* over the finished batches. The task file carries the v0.1 gold as locked
  pre-annotations plus proposals from a wide-recall pre-annotator (`negatives.py`:
  18 + 40 CONTRACT_ARTICLE, 22 + 40 BARE_ARTICLE, 4 + 7 OTHER_LAW, 13 + 12 JOURNAL_REF
  proposals for batch 1 + batch 2). Ten Fable agents (pass a) and ten Opus agents (pass c)
  corrected the proposals, 15 decisions each, following `docs/agent-negatives-brief.md`. The
  citation gold was not theirs to change, and no agent changed it.
- Agreement on the negative spans: batch 1, 69 agreed, 5 only in pass a (one decision);
  batch 2, 100 agreed, 1 only in each pass (one decision). All citation spans and all outcomes
  identical in both passes.
- Adjudication (five files under `data/gold/<batch>/v2/edits/adj/`): the five disputed spans
  of batch 1 and six agreed spans of another decision were spelled-out `Ziffer ...` clauses,
  which v0.2 leaves unlabelled until open question 6 (`Artikel`/`Ziffer` written out) is
  decided for all classes; the batch-2 dispute went to CONTRACT_ARTICLE with the long
  instrument name; two references inside a quoted party title were added as BARE_ARTICLE after
  a contradictory sentence in the first v0.2 draft was removed; one batch-1 span,
  `Art. 117 GOG/ZH`, was relabelled from STATUTE to OTHER_LAW (cantonal law). That relabel is
  the only change to the citation gold.
- Result: `data/gold/batch1.gold.jsonl` (2,649 citation spans + 64 negative spans in 17
  decisions) and `data/gold/batch2.gold.jsonl` (3,572 + 103 in 24 decisions). The v0.1 files
  are kept as `data/gold/<batch>.gold.v0.1.jsonl`. Label Studio project 1 holds the v0.2
  ground truth (nine labels). The 23 guideline gaps the agents raised, and the decision on
  each, are in the guideline and in `docs/guideline-open-questions.md` (items 17 to 23).
- Scores on the five citation classes are unchanged by the round, except that every extractor
  gains one span on batch 1 (the relabelled `GOG/ZH` is no longer a STATUTE miss).

### Guideline v0.3 round (2026-10-23/24): short BGE citations and written-out forms

- Why: Denis accepted every proposed rule in `docs/guideline-open-questions.md`. Two of them
  change the citation gold: same-volume short BGE citations (`BGE 140 III 86 E. 2, 115 E. 2`
  → `115` is a span, question 1) and `Artikel`/`Artikeln` written out (question 6). A third
  extends the written-out forms to the negative classes (question 17).
- How: the same round mechanism as v0.2 (`GOLD_ROUND=v3`), with proposals from regex v0.4
  (which implements the two citation rules) and from the extended negative pre-annotator, on
  top of the locked v0.2 gold. Only decisions whose text contains one of the three patterns
  went to the agents: 30 of 60 in batch 1 and 46 of 90 in batch 2; the other 74 received an
  identity edit from the orchestrator. Five Fable agents (pass a) and five Opus agents (pass c),
  brief `docs/agent-v3-brief.md`.
- Agreement: identical in both passes on every span and outcome of both batches (2,767 and
  3,757 spans). The agents changed three proposals in total: one boundary (`Ziffer 2 der
  Vergleichsvereinbarung`), one missed short citation (`155` in `BGE 141 III 554, E. 2.5.1,
  155 E. 4.3`, found by both passes), and nothing else. No adjudication was needed.
- Result: batch 1 gained 42 BGE, 11 CONTRACT_ARTICLE and 1 OTHER_LAW spans; batch 2 gained
  59 BGE, 2 STATUTE (`Artikel 104 BGG`, `Artikeln 35a und 35b VVG`), 17 CONTRACT_ARTICLE,
  3 BARE_ARTICLE and 1 OTHER_LAW. Nothing was removed. The gold is now
  `data/gold/<batch>.gold.jsonl` = v0.3 (2,767 and 3,757 spans); v0.1 and v0.2 are kept
  beside it (`*.gold.v0.1.jsonl`, `*.gold.v2.jsonl`). Label Studio holds the v0.3 ground truth.
- Open cases the agents raised and the rule now applied: a lone `Absatz 2` referring back to a
  statute, a lone `Ziffer 1 Absatz 2` of a settlement named earlier, `Randziffer 26` of a
  brief, `Dispositivziffer 1-4` of an authority's order: no span (a reference needs `Art.`,
  `Artikel` or `§` for BARE_ARTICLE, and points of court or authority documents and briefs are
  never spans).
- Entity level: a short citation's key is resolved from the nearest full citation before it
  (`evaluate.bge_key`), both in the scorer and in the linking stage, so `115` after
  `BGE 140 III 86` links to `BGE 140 III 115`.

### Batch 3 (2026-10-25 to 2026-10-28): 200 decisions, half of them targeted

- Why: the learning curve (6.12) said the span models gain about 0.002 F1 per 15 random
  decisions beyond 60, and the negative classes and rare outcomes have too few examples to be
  learned at all. Denis asked for 200 more decisions. Random sampling would supply contract
  clauses at about 0.6 per decision and partial approvals at 2 per 100, so half of the batch
  was drawn on purpose.
- Sampling (`caselaw sample --n 200 --targeted 100 --seed 3`, `sample.pick_targeted`): 100
  decisions from the unused civil-chamber pool (4,101 decisions of 5,000 to 30,000 characters)
  that match a rare-class pattern or a rare outcome, with quotas filled from the rarest group
  up: foreign law 15, partial approval 15, moot 8, approved 27, contract clauses 36, journal
  references 36 (a decision can count for several groups; `data/gold/batch3.groups.json`). The
  other 100 are stratified by year and chamber like batches 1 and 2.
- Pre-annotation: regex v0.4 for the citation classes and the negative-class pre-annotator in
  one task file (`labelstudio.to_task`), 10,101 proposals, about 50 per decision.
- Labelling: two windows of 100 decisions, each with ten Fable agents (pass a) and ten Opus
  agents (pass c), ten decisions per agent, brief `docs/agent-labelling-brief.md` (v0.3
  edition, nine classes). The windows were separated by a usage-limit reset; a credit cut-off
  stopped ten Fable agents of the second window part-way, and three fresh agents finished the
  27 missing decisions two days later. Nothing was lost: every finished decision is a file.
- Agreement over the 200 decisions: 10,230 spans agreed, 22 only in pass a, 28 only in pass c
  (F1 0.998); outcomes 200 of 200 identical. The 50 disputed spans in 14 decisions were
  adjudicated by me (`data/gold/batch3/edits/adj/`); the new rules they needed are in the
  guideline under "Clarifications from batch 3" (bracketed corrections inside a reference,
  `und/oder` as a joiner, foreign currency words, yearbooks and newsletters, quoted clause
  headings, treaties named by a short title).
- What the targeted half exposed in the pre-annotator: cantonal abbreviations cut after `EG`
  (`EG ZPO/GL`), contract clauses cut at the first number (`Art. 36` for `Art. 36.2 AVB`), the
  revised judgment's file number missed in revision cases (`5A_89/2020`, 20 mentions), amounts
  cut inside the number (`Fr. 100` for `Fr. 1000.--`), and `Reglement`/`Verordnung` with an SR
  number proposed as CONTRACT_ARTICLE. The agents corrected all of these.
- Result: `data/gold/batch3.gold.jsonl`, 10,259 spans (STATUTE 4,161, BGE 2,672, AMOUNT 1,462,
  DOCKET 1,059, PARTY_ROLE 376, CONTRACT_ARTICLE 223, BARE_ARTICLE 124, JOURNAL_REF 98,
  OTHER_LAW 84), outcomes dismissed 75, inadmissible 70, approved 29, partial approval 17,
  moot 9. The gold set is now 350 decisions. Label Studio project 1 holds all 350 as ground
  truth.
- Regex v0.4 against batch 3 (its own pre-annotations corrected): span F1 0.991, recall 0.983,
  outcome 194 of 200. This is the lowest regex number in the report, because the targeted
  half contains the forms the rules do not cover (`5D_` dockets, `lit a` without the dot,
  `GebV SchKG`, line breaks inside citations) and because batch 3 is not a random sample.
- Annotation guideline: `docs/annotation-guideline.md`.

## 5. Extractors compared

| Extractor | Type | Training data | Notes |
|---|---|---|---|
| regex v0.2 | hand-written rules + Fedlex abbreviation list | none (tuned on batch 1) | also the batch-2 pre-annotator; `src/caselaw_extraction/regex_extractor.py` |
| regex v0.3 | same, 12 more rules | tuned after seeing batch 2 | not a held-out number |
| regex v0.4 | same, plus guideline v0.3 (short BGE citations as spans, `Artikel` written out) and the `EPÜ 2000` lookup fix | tuned on both batches | not a held-out number; the pre-annotator of the v0.3 round |
| opencaselaw silver graph | third-party rules | none | `graph/*.parquet` shipped with the dataset; entity level only (no offsets) |
| spaCy NER + textcat | hash embeddings + CNN, transition-based NER; bag-of-words textcat | batch 1 (631 windows, 2,650 spans; 60 rulings) | trained from zero on CPU; `spacy_extractor.py` |
| gbert-base token + sequence classifier | `deepset/gbert-base` (110 M) fine-tuned, BIO tags; second head on the ruling section | batch 1 (794 windows of 1,200 characters; 60 rulings) | PyTorch on Apple MPS; `transformer_extractor.py` |
| LLM structured output | Claude Haiku agents, zero-shot prompt with a JSON schema, no pre-annotations | none | different model and prompt than the labelling agents; texts resolved to offsets by `scripts/llm/apply_output.py` |

Since 2026-10-23 every extractor's output goes through one more stage, **entity linking**
(`caselaw link`, `src/caselaw_extraction/linking.py`): STATUTE spans are resolved to a Fedlex
act and article, BGE spans to `BGE volume part page`, DOCKET spans to a normalised file number;
a span that resolves to nothing (a code that is not a federal act, a BGE fragment, the
decision's own file number) is dropped. The stage holds the two facts no span model can read
from the text, the Fedlex list and the own file number, and it applies to the regex and the
LLM exactly as to the learned models. It never moves a boundary and never adds a span. Scores
are reported **before and after** linking (section 6.8), so that a learning failure that the
linking removes stays visible in the "before" column.

All extractors write the same prediction format (`data/pred/<batch>/<name>.jsonl`) and are
scored by one command (`caselaw score <file> --batch batch2 --name <run>`), which also logs
parameters, metrics and the prediction file to MLflow (`sqlite:///mlflow.db`, experiment
`caselaw-extraction`). Every number below is in MLflow.

## 6. Results

### 6.1 Regex extractor coverage on the full corpus (week 1, not yet scored against gold)

Runtime: 5.5 s for 7,999 decisions on a laptop (about 1,450 decisions per second).

| Label | Spans | Decisions with at least one span |
|---|---|---|
| STATUTE | 121,232 | 7,998 / 7,999 |
| BGE | 51,436 | 6,854 / 7,999 |
| DOCKET | 31,960 | 4,523 / 7,999 |
| AMOUNT | 43,190 | 7,036 / 7,999 |
| PARTY_ROLE | 14,470 | 7,993 / 7,999 |

Header fields found: docket 7,998; date 7,985; chamber 7,997; appealed court 1,425 (the
appeal sentence has more variants than the current pattern covers).

Outcome: the regex assigns an outcome to 7,943 of 7,999 decisions (56 unknown). It agrees with
the dataset label in 4,672 of 5,806 cases and fills 2,154 of the 2,193 missing ones.
See the data-quality note in section 2 for the disagreements.

Most-cited codes by raw span count: BGG 70,182; ZPO 12,374; ZGB 9,935; BV 6,872; OR 6,318;
SchKG 6,274; IPRG 2,213; EMRK 1,103.

### 6.2 Regex v0.1 (the pre-annotator) against batch 1 gold

| Label | Gold | Pred | P (exact) | R (exact) | F1 (exact) | F1 (overlap) |
|---|---|---|---|---|---|---|
| STATUTE | 1,098 | 1,056 | 0.917 | 0.882 | 0.899 | 0.981 |
| BGE | 759 | 516 | 1.000 | 0.680 | 0.809 | 0.809 |
| DOCKET | 328 | 332 | 0.985 | 0.997 | 0.991 | 0.991 |
| AMOUNT | 353 | 352 | 0.957 | 0.955 | 0.956 | 0.999 |
| PARTY_ROLE | 112 | 112 | 1.000 | 1.000 | 1.000 | 1.000 |
| **all (micro)** | 2,650 | 2,368 | 0.954 | 0.853 | **0.901** | 0.942 |

Outcome accuracy 57/60. Errors: approved labelled moot (legal-aid item), approved labelled
unknown (Berichtigung), inadmissible labelled dismissed (Sistierungsgesuch in item 1).

Causes, in order of size: BGE list items without the word `BGE` after a line break (243 missed);
statute chains cut to the last article because the source wraps citations onto new lines
(130 missed, 88 partial spans counted as wrong); `Mio.` cut off amounts (16); a second own docket
number in joined proceedings (5).

### 6.3 Regex v0.2 against batch 1 gold (development set, tuned on it)

Changes: whitespace inside citations may include line breaks; article ranges, `f.`/`ff.`,
ordinal `Satz`, `SchlT` prefix; `Mio.`/`Mrd.` multipliers and `Fr` without dot; old-format
dockets; all header dockets count as own numbers; side-request items skipped in the dispositiv;
annul-and-remand and Berichtigung count as approved.

| Label | Gold | Pred | P (exact) | R (exact) | F1 (exact) |
|---|---|---|---|---|---|
| STATUTE | 1,098 | 1,095 | 1.000 | 0.997 | 0.999 |
| BGE | 759 | 752 | 1.000 | 0.991 | 0.995 |
| DOCKET | 328 | 328 | 1.000 | 1.000 | 1.000 |
| AMOUNT | 353 | 353 | 1.000 | 1.000 | 1.000 |
| PARTY_ROLE | 112 | 112 | 1.000 | 1.000 | 1.000 |
| **all (micro)** | 2,650 | 2,640 | 1.000 | 0.996 | **0.998** |

Outcome accuracy 60/60. These numbers are optimistic because the rules were written while
looking at these decisions. The honest number comes from batch 2.

### 6.4 Regex v0.2 on batch 2 (held out)

The first honest number. Nothing in v0.2 had seen these decisions.

| Label | Gold | Pred | P (exact) | R (exact) | F1 (exact) | F1 (overlap) |
|---|---|---|---|---|---|---|
| STATUTE | 1,594 | 1,576 | 0.999 | 0.987 | 0.993 | 0.994 |
| BGE | 1,056 | 1,045 | 1.000 | 0.990 | 0.995 | 0.995 |
| DOCKET | 344 | 342 | 1.000 | 0.994 | 0.997 | 0.997 |
| AMOUNT | 414 | 413 | 0.990 | 0.988 | 0.989 | 0.999 |
| PARTY_ROLE | 164 | 164 | 1.000 | 1.000 | 1.000 | 1.000 |
| **all (micro)** | 3,572 | 3,540 | 0.998 | 0.989 | **0.994** | 0.996 |

Outcome 88/90 (macro-F1 0.991). The two errors: a ruling header `Das Bundesgericht erkennt:`
without `Demnach` (unknown), and a request to restore a time limit in item 1 that the
side-request list did not know (dismissed instead of inadmissible). The drop from 0.998 on
batch 1 to 0.994 on batch 2 is the development-set optimism; it is small because the citation
forms are highly regular.

Caveat: batch 2 was labelled by correcting regex v0.2 pre-annotations. The agents accepted every
pre-annotation in 68 of 90 decisions, so the gold set is anchored on the regex. Precision near
1.000 is partly a consequence of that anchoring; the recall number is the informative one.

### 6.5 All extractors on batch 2 (held out)

Span level: exact match of (start, end, label). Entity level: normalised keys
(`BGG 42`, `BGE 140 III 86`, `4A_12_2020`) per decision, which is what the citation graph
needs. Outcome: accuracy over 90 decisions and macro-F1 over the four classes present.

| Extractor | span F1 exact | span F1 overlap | entity F1 | outcome | outcome macro-F1 | train | predict (90 dec.) |
|---|---|---|---|---|---|---|---|
| regex v0.2 | **0.994** | 0.996 | 0.994 | 88/90 | 0.991 | – | < 1 s |
| opencaselaw silver graph | – | – | 0.948 | – | – | – | – |
| spaCy (seed 0) | 0.982 | 0.991 | 0.989 | 82/90 | 0.596 | 292 s CPU | 7 s |
| gbert-base (seed 0) | 0.984 | 0.987 | 0.989 | 85/90 | 0.586 | 191 s + 40 s MPS | 12 s |
| LLM Haiku, raw texts | 0.936 | 0.987 | **0.996** | **90/90** | **1.000** | – | about 25 min wall (9 agents) |
| LLM Haiku, resolver keeps `BGE` prefix | 0.985 | 0.987 | 0.996 | 90/90 | 1.000 | – | same |
| regex v0.3 (tuned on batch 2, not held out) | 0.998 | 0.999 | 0.999 | 90/90 | 1.000 | – | < 1 s |

Per label, span F1 exact:

| Extractor | STATUTE | BGE | DOCKET | AMOUNT | PARTY_ROLE |
|---|---|---|---|---|---|
| regex v0.2 | 0.993 | 0.995 | 0.997 | 0.989 | 1.000 |
| spaCy (seed 0) | 0.982 | 0.998 | 0.961 | 0.956 | 0.997 |
| gbert-base (seed 0) | 0.978 | 0.996 | 0.962 | 0.995 | 0.991 |
| LLM Haiku (resolved) | 0.994 | 0.996 | 0.958 | 0.989 | 0.885 |

Seed variance (same data, different random seed; the tables above show seed 0):

| Model | seeds | span F1 exact | outcome accuracy (of 90) | outcome macro-F1 |
|---|---|---|---|---|
| spaCy | 0, 1, 2 | 0.982, 0.979, 0.980 | 82, 81, 88 | 0.60, 0.55, 0.67 |
| gbert-base spans | 0, 1, 2 | 0.984, 0.983, 0.986 | – | – |
| gbert-base outcome head | 0, 1, 2, 3, 4 | – | 85, 87, 79, 87, 82 | 0.59, 0.74, 0.61, 0.74, 0.59 |

The span models are stable to within 0.003 F1. The outcome classifiers swing by up to nine
decisions between seeds, which is what 60 training labels buy; a single-seed outcome number
from either model should not be quoted.

**Reading the table.**

- The regex wins span-level extraction, as expected for a formal citation language, and it is
  the only extractor that knows which abbreviations are laws (through the Fedlex list). Both
  learned models label articles of general insurance conditions (`Art. 13 Ziff. 2 lit. a AVB`)
  and commentary references (`N. 17 zu Art. 109`) as statutes, and both label the decision's
  own file number when a joined proceeding repeats it in the body. Those are the three largest
  false-positive classes of spaCy and gbert. A learned model cannot know the own number or the
  Fedlex list; a hybrid (model spans, regex-style post-filters) would remove most of them.
- gbert has the highest recall of all extractors (0.997 at span level) with 60 training
  decisions and three minutes of fine-tuning. Its precision (0.972) is the problem. spaCy is
  close behind at a hundredth of the parameters and no GPU.
- The LLM is the best extractor at entity level (0.996) and on the outcome (90/90, including
  both moot cases), and the worst at exact span boundaries in its raw form. 177 of its BGE
  spans lacked the leading `BGE` because the agents wrote list items in the bare form the
  prompt showed for continuation items. That is a prompt and resolver matter, not an extraction
  failure; with the resolver restoring the prefix the span F1 rises to 0.985. Its remaining
  misses are repeated docket mentions it listed once and role words it matched in the body.
- The dataset's own silver graph reaches entity F1 0.948: BGE 0.994 and DOCKET 0.987, but
  STATUTE recall only 0.826. Our regex finds about 17% more statute references than the
  dataset authors' extractor on the same decisions.
- Outcome: the two learned classifiers trained on 60 rulings cannot separate the rare classes.
  spaCy confuses dismissed/inadmissible when a legal-aid item precedes the ruling item; gbert
  predicts the common classes well (85/90) but misses both moot cases. The regex procedure
  (last ruling header, skip side requests, ordered rules) and the LLM, which reads the ruling,
  are the only ones with a usable macro-F1. More outcome labels, not a bigger model, is the fix.

### 6.6 Regex v0.3: what batch 2 taught the rules (not held out)

After scoring, the 22 misses and 2 false positives of v0.2 on batch 2 were read one by one.
Twelve rules were added or widened: a chain element may be a bare `Abs. 2` after `und` or
`i.V.m.`; `Abs.` ranges (`Abs. 1-3`); `Ziff.`/`Bst.` may repeat inside a letter list; the
`i.Vm.` typo; `Art` without the dot and a missing space before the code; `lit. gbis`; an `a`
prefix on the code (`aVVG`) and a year after it (`EPÜ 2000`); a decimal comma before `Mio.`;
a space after the slash in a docket; BGE chains continue past a same-volume short citation
(`E. 1.2, 333 E. 1.2; 137 III 324`); the header `Das Bundesgericht erkennt:`; and restoration
of a time limit as a side request.

Result on batch 2: span F1 0.998, outcome 90/90. On batch 1 it stays at 0.998/0.999 and 60/60,
so nothing regressed. **This is a development number**: v0.3 has now seen both batches. The
six remaining misses are source typos (`BGE 142 IIII 758`, `F r.`, a garbled `BGE 141 III 1 .2`)
and one old Federal Insurance Court number (`I 302/96`); none is worth a rule.

Addendum 2026-10-23: the three `EPÜ 2000` citations in batch 2 were a v0.3 miss too, for a
reason worth recording. Fedlex lists the European Patent Convention under the abbreviation
*with* the year (`EPÜ 2000`), the regex stripped the year before the lookup, and the code
pattern tried a single trailing digit before a four-digit year, so the match ended at `EPÜ 2`.
Both are fixed (`fedlex.resolve_code` tries the full form first; the pattern tries the year
first). v0.3 now scores span F1 0.999 / entity 0.999 on batch 2 and 0.999 / 0.999 on batch 1.
The week-2 table above keeps the 0.998 it reported at the time.

### 6.7 What the learned models would need to beat the rules

- Labels: 60 decisions give 2,650 spans but only 60 outcome labels in four classes. The outcome
  classifiers are data-starved; 500 agent-labelled outcomes would cost about an hour.
- Knowledge the text does not contain: the Fedlex abbreviation list and the decision's own
  file number. These now live in the entity-linking stage (section 6.8), which every extractor
  passes through. They are architecture, not a model improvement, and the report does not
  count them as one.
- Learning failures that the linking stage must not hide: commentary references
  (`N. 6 zu Art. 242`), contract clauses (`Art. 13 Ziff. 2 lit. a AVB`) and fragments (`Art`,
  `8`). Guideline v0.2 gives the first two their own classes so the model can learn them and the
  scorer can show the confusion (section 6.10); the fragments are a decoding matter (6.9).
- Where they could win: text the regex has not seen (new citation forms, broken tokens such as
  `F r. 30'000.00`, which gbert found and the regex did not) and languages (the French and
  Italian decisions are out of scope of every rule written so far).

### 6.8 Entity linking: every extractor before and after (batch 2, held out)

The linking stage is applied to every prediction file of section 6.5 with one command. The
"before" column is the number from 6.5; "after" is the same spans minus the unlinkable ones.
The drop columns say *why* spans went: the own file number, a code that is not a federal act,
a span without an article number, a BGE without volume/part/page.

| Extractor | span F1 before | span F1 after | entity F1 before | entity F1 after | own docket | unknown code | no article | no BGE key |
|---|---|---|---|---|---|---|---|---|
| regex v0.2 | 0.994 | 0.994 | 0.994 | 0.994 | 0 | 0 | 0 | 0 |
| regex v0.3 (not held out) | 0.999 | 0.999 | 0.999 | 0.999 | 0 | 0 | 0 | 0 |
| spaCy s0 | 0.982 | 0.988 | 0.988 | 0.994 | 17 | 21 | 0 | 4 |
| spaCy s1 | 0.979 | 0.986 | 0.981 | 0.993 | 16 | 33 | 0 | 1 |
| spaCy s2 | 0.980 | 0.984 | 0.986 | 0.992 | 15 | 17 | 0 | 3 |
| gbert-base s0 | 0.984 | **0.994** | 0.989 | **0.996** | 13 | 55 | 9 | 7 |
| gbert-base s1 | 0.983 | 0.994 | 0.988 | 0.995 | 15 | 61 | 8 | 6 |
| gbert-base s2 | 0.986 | 0.995 | 0.989 | 0.996 | 15 | 57 | 5 | 2 |
| LLM Haiku (resolved) | 0.985 | 0.985 | 0.996 | 0.996 | 0 | 2 | 0 | 2 |

Reading the table honestly:

- The regex and the LLM lose nothing, because they already carry the knowledge (the regex has
  the list; the LLM has read a lot of Swiss law). The learned models gain 0.004 to 0.010 span
  F1 and reach the regex's entity F1 at 0.995/0.996. **This is not learning.** The "unknown
  code" column is the model labelling `AVB` clauses, `§ 133 BGB` and commentary references as
  statutes; the "no article" column is fragments (`Art`). Both are failures the model still
  has after linking; the table merely stops counting them.
- What the linked number *is* good for: it is the quality of the citation graph input,
  because the graph is built from linked keys. For that purpose gbert after linking and the
  regex are now within 0.003 of each other on a held-out batch.
- The linking rules were written from the schema (a STATUTE links to Fedlex; a DOCKET is not
  the own number; a BGE has three numbers), not from batch-2 errors. The gold set, however,
  was anchored on regex pre-annotations in both batches, so every gold span boundary is one
  the regex can produce. That anchoring favours the regex in every comparison in this report
  and is a larger threat to the comparison than any linking rule. The human spot check
  (section 4) bounds the gold error rate, not the anchoring bias.

### 6.9 Decoding: argmax vs BIO-constrained Viterbi (gbert, batch 2)

The token classifier predicts each token independently, so `O, I-STATUTE` sequences occur.
A Viterbi pass over the same logits with hard BIO constraints (no learned transitions, no
retraining; `transformer_extractor.viterbi_decode`) is the principled fix for invalid
sequences. Result: +0.001 to +0.002 span F1 on every seed (s0 0.984 → 0.986, s1 0.983 → 0.985,
s2 0.986 → 0.986), DOCKET gains most (0.962 → 0.963/0.969). Most fragments the model emits
(`Art`, `8`) are *valid* BIO sequences, so the constraint rarely fires. A CRF head or more
training data would be the next step; neither is done.

### 6.10 Guideline v0.2: do the models learn the negative classes? (batch 2, one seed)

Both learned models were retrained from zero on batch 1 under v0.2 (nine classes, same
hyper-parameters and seed 0 as in 6.5) and evaluated on batch 2. The training set holds
16 CONTRACT_ARTICLE, 29 BARE_ARTICLE, 4 OTHER_LAW and 15 JOURNAL_REF spans, against 2,649
citation spans. Batch 2 holds 38, 44, 6 and 15.

| Model | citation span F1, v0.1 gold (6.5) | citation span F1, v0.2 training | after linking | CONTRACT_ARTICLE F1 exact / overlap | BARE_ARTICLE | OTHER_LAW | JOURNAL_REF |
|---|---|---|---|---|---|---|---|
| spaCy s0 | 0.982 | 0.978 | 0.986 | 0.13 / 0.35 | 0.24 / 0.24 | 0.00 / 0.50 | 0.48 / 0.48 |
| gbert-base s0 | 0.984 | 0.980 | 0.995 | 0.03 / 0.29 | 0.17 / 0.60 | 0.00 / 0.25 | 0.31 / 0.75 |

What the confusion table (overlapping spans, logged with every run) shows for the two
classes that matter most:

| gold class → predicted as | regex v0.3 | LLM Haiku | spaCy v0.1 | spaCy v0.2 | gbert v0.1 | gbert v0.2 |
|---|---|---|---|---|---|---|
| CONTRACT_ARTICLE (38) → STATUTE | 0 | 0 | 13 | 25 | 32 | 35 |
| CONTRACT_ARTICLE → own class | – | – | – | 11 | – | 9 |
| BARE_ARTICLE (44) → STATUTE | 0 | 0 | 5 | 20 | 22 | 37 |
| BARE_ARTICLE → own class | – | – | – | 6 | – | 25 |

(Cells count overlapping span pairs, so a gold span split into two predictions counts twice;
the v0.2 models produce more such splits, which is why their rows add up to more than the
gold count.)

Reading:

- **The classes are measurable now, and they are not learned yet.** With 16 and 29 training
  examples, gbert recognises a quarter of the contract clauses and about half of the bare
  articles at the overlap level, and almost none at exact boundaries. spaCy is similar. The
  model has started to put the right label on the right place, and still labels most of these
  references STATUTE as well. More labels, not a different model, is the fix: the corpus has
  thousands of such references, and the v0.2 pre-annotator finds candidate decisions cheaply.
- **Citation-class F1 fell by 0.004 for both models.** This is one seed and the seed spread in
  6.5 was 0.003, so it may be noise. The mechanism is plausible, though: the new classes take
  probability mass from `O`, and a model that is unsure between STATUTE and CONTRACT_ARTICLE
  now emits more STATUTE spans on contract clauses than one that never saw the class.
- **The linking stage removes the same errors as before** (62 unknown codes, 30 spans without
  an article for gbert), and the linked numbers are unchanged at 0.995 and 0.986. That is the
  point of reporting both: the linked column says what the citation graph receives; the
  confusion table says what the model has not learned.
- The regex and the LLM have no row in the own-class columns because neither predicts the
  negative classes. Their zero confusion is the Fedlex list and world knowledge respectively.

Not done: more seeds, a batch 3 aimed at the negative classes, and a CRF head. Each is a
measured gap, not a guess, which is what the v0.2 round was for.

### 6.11 Everything re-scored on gold v0.3 (batch 2, 2026-10-24)

Gold v0.3 adds 59 short BGE citations and 2 written-out statutes to batch 2, so every
extractor that does not produce them loses recall. The table shows each extractor against the
v0.3 gold on the five citation classes; the models marked v3 were retrained on the v0.3 gold of
batch 1 (one seed).

| Extractor | trained / tuned on | span F1 exact | BGE F1 | entity F1 | after linking | outcome |
|---|---|---|---|---|---|---|
| regex v0.2 (frozen before batch 2) | v0.1 rules | 0.985 | 0.968 | 0.989 | 0.985 | 88/90 |
| regex v0.3 | v0.1 rules, batch-2 fixes | 0.990 | 0.971 | 0.993 | 0.990 | 90/90 |
| regex v0.4 | v0.3 rules | 0.999 | 0.998 | 0.999 | 0.999 | 90/90 |
| spaCy s0 (week 2) | gold v0.1 | 0.974 | 0.971 | – | – | 82/90 |
| spaCy v3 s0 | gold v0.3 | 0.978 | 0.999 | 0.984 | 0.986 | 83/90 |
| gbert s0 (week 2) | gold v0.1 | 0.977 | 0.972 | 0.983 | – | 85/90 |
| gbert v3 s0 | gold v0.3 | 0.979 | 0.998 | 0.982 | 0.993 | 85/90 |
| LLM Haiku (week 2 prompt) | – | 0.978 | 0.969 | – | – | 90/90 |
| LLM Haiku, v0.3 prompt (re-run, 9 agents) | – | 0.985 | 0.999 | 0.999 | 0.985 | 90/90 |

Reading:

- **The short citations are learnable, and were learned.** Batch 1 holds 42 of them. Both
  models trained on v0.3 find the 59 in batch 2 almost completely (BGE F1 0.998 and 0.999,
  from 0.971). The week-2 models, which never saw a labelled short citation, miss 56 of 59.
  This is the clearest case in the report of a rule that a learned model picks up from a few
  dozen examples, because the pattern is local and regular.
- **The negative classes are still not learned, with one exception.** On v0.3 gold spaCy
  reaches BARE_ARTICLE F1 0.72 (exact) and finds 6 of 7 OTHER_LAW spans at the overlap level;
  gbert stays at 0.17 to 0.19 exact on CONTRACT_ARTICLE and BARE_ARTICLE and 0.41 on
  JOURNAL_REF. The confusion tables (in every run) still show 29 to 35 contract clauses
  predicted as STATUTE. Training data for these classes is 27, 29, 5 and 15 spans.
- **Regex v0.4 is a development number twice over**: it implements the v0.3 rules and it was
  the pre-annotator of the round that produced the v0.3 gold. Its 0.999 says the rules are
  consistent with the gold, not that the regex generalises.
- The LLM with the week-2 prompt drops to 0.978 because the prompt told it that short
  citations are not citations. With one sentence changed in the prompt it finds all 59
  (BGE F1 0.999) and is back at span F1 0.985 and entity F1 0.999, the best entity-level
  number of any extractor except regex v0.4, which is not held out. Its remaining misses are
  the same as in week 2: amounts it skipped (27) and role words in the header block it did not
  list (25). The LLM needs no training data for a new rule, only the rule.

The anchoring caveat from 6.8 holds for all of this, now three rounds deep: every round
corrected machine proposals, and both passes agreed on every span in the v0.3 round. Two
models agreeing on proposals they did not generate is consistency, not independent truth.

### 6.12 Learning curve: how much gold do the span models need? (2026-10-24/25)

`scripts/learning_curve.py` trains the span models (no outcome head) on growing subsets of
gold v0.3 and scores the five citation classes on batch 2. Main curve: the first N decisions of
a seeded shuffle of batch 1, evaluated on all 90 decisions of batch 2, three seeds. Extended
curve: all of batch 1 plus the first K decisions of a fixed 45-decision pool from batch 2,
evaluated on the other 45 decisions of batch 2 only, two seeds; the 60-point is in both curves
to connect them. 40 runs, all in MLflow with tag `learning_curve`.

| training decisions | spaCy, full batch 2 | gbert, full batch 2 | spaCy, 45-decision half | gbert, 45-decision half |
|---|---|---|---|---|
| 15 | 0.954 (0.946 to 0.970) | 0.922 (0.917 to 0.931) | – | – |
| 30 | 0.970 (0.965 to 0.973) | 0.962 (0.953 to 0.971) | – | – |
| 45 | 0.976 (0.973 to 0.979) | 0.977 (0.975 to 0.980) | – | – |
| 60 | 0.977 (0.973 to 0.981) | 0.979 (0.978 to 0.980) | 0.976 (0.972 to 0.980) | 0.977 (0.977 to 0.977) |
| 75 | – | – | 0.976 (0.975 to 0.977) | 0.980 (0.979 to 0.980) |
| 90 | – | – | 0.983 (0.982 to 0.983) | 0.982 (0.981 to 0.982) |
| 105 | – | – | 0.977 (0.976 to 0.978) | 0.983 (0.982 to 0.984) |

Span F1 exact, mean over seeds with the range in brackets. Reference on the same gold: regex
v0.2 (frozen before batch 2) 0.985, regex v0.4 0.999 (development number).

Reading:

- **The steep part ends at 45 decisions.** From 15 to 45 both models gain 0.02 to 0.05. From
  45 to 60 they gain 0.001 to 0.002, within the seed spread. gbert needs more data than spaCy
  at the small end (0.922 against 0.954 at 15 decisions) and overtakes it at 45.
- **Beyond 60, gbert gains about 0.002 per 15 decisions**, 0.977 → 0.983 from 60 to 105 on the
  half set, with non-overlapping seed ranges at each step. Extrapolated at that rate, parity
  with regex v0.2 at 0.985 would come at roughly 120 to 150 decisions, and the rate is
  falling, so the estimate of 300 to 400 decisions given before the curve was run is too
  pessimistic for the citation classes as a whole and the true figure is probably 150 to 250.
  The curve cannot say where the gain stops, and the remaining gap is concentrated in the error
  classes of 6.8, which more decisions of the same kind feed only slowly.
- **spaCy does not improve beyond 60 in a way the curve can resolve.** 0.976, 0.976, 0.983,
  0.977: the 90-point is the only one above the 60-point by more than the seed spread, and the
  105-point falls back. spaCy's hash-embedding model has less capacity to absorb more examples
  than the transformer, which is the expected shape.
- **The extended points are not held out in the week-2 sense.** They train on half of batch 2
  and test on the other half, 45 decisions, so each point rests on about 1,900 gold spans and
  the test half was chosen once with seed 7. They are comparable with each other, not with the
  full-batch numbers above them.

What the curve does not measure: the negative classes (5 to 29 training examples in total; the
curve would be noise), the outcome classifier (60 labels, discussed in 6.5), and the own-docket
errors, which no amount of windowed training data removes.

### 6.13 Trained on 260 decisions: batches 1 and 3 against batch 2 (2026-10-28)

Both span models were retrained from zero on batches 1 and 3 together (260 decisions, 13,026
spans, 260 outcome labels with 46 approved, 19 partial approvals and 11 moot) and evaluated on
batch 2, which stays held out. Same hyper-parameters as in 6.5; gbert with two seeds.

| Model | training decisions | citation span F1 | after linking | outcome | outcome macro-F1 | CONTRACT_ARTICLE F1 | BARE_ARTICLE | OTHER_LAW | JOURNAL_REF |
|---|---|---|---|---|---|---|---|---|---|
| spaCy s0 | 60 (v0.3 gold) | 0.978 | 0.986 | 83/90 | 0.62 | 0.11 | 0.72 | 0.00 | 0.50 |
| spaCy s0 | 260 | 0.985 | 0.989 | 89/90 | 0.95 | 0.47 | 0.69 | 0.67 | 0.89 |
| gbert s0 | 60 (v0.3 gold) | 0.979 | 0.993 | 85/90 | 0.59 | 0.19 | 0.17 | 0.00 | 0.41 |
| gbert s0 | 260 | **0.993** | **0.996** | **90/90** | **1.00** | 0.85 | 0.89 | 0.86 | 0.97 |
| gbert s1 | 260 | 0.991 | 0.994 | 90/90 | 1.00 | 0.84 | 0.85 | 0.75 | 0.90 |
| regex v0.2, frozen before batch 2 | – | 0.985 | 0.985 | 88/90 | 0.99 | – | – | – | – |
| regex v0.4, tuned on all batches | – | 0.999 | 0.999 | 90/90 | 1.00 | – | – | – | – |

Reading:

- **gbert on 260 decisions passes the frozen regex on the held-out batch**: 0.993 and 0.991
  against 0.985 for regex v0.2, without the linking stage. After linking it reaches 0.996. The
  learning curve of 6.12 predicted parity at 150 to 250 decisions; the targeted half of batch 3
  got it there at 260, and the remaining 0.006 to regex v0.4 is the development number of rules
  that saw every batch, including the one they were scored on.
- **The negative classes are learned now.** Contract clauses go from 0.19 to 0.85 (0.95 at the
  overlap level), bare articles from 0.17 to 0.89, journal references from 0.41 to 0.97, with 150
  to 220 training examples each instead of 16 to 29. The confusion table shows **0 of 55
  contract clauses labelled STATUTE** by gbert s0, down from 32 in week 2. The linking stage
  now drops 4 unknown-code spans from gbert instead of 62: the model has absorbed most of what
  the Fedlex list used to supply.
- **The outcome classifier is fixed by data alone.** 260 labels with 46 approved, 19 partial
  approvals and 11 moot decisions take gbert from 85 of 90 with a macro-F1 of 0.59 to 90 of 90
  on both seeds, and spaCy to 89 of 90. The week-2 diagnosis (data-starved, not model-limited)
  holds.
- spaCy gains less (0.978 → 0.985) and stays at the frozen-regex level; its outcome head gains
  as much as gbert's. The gap between the two models on the negative classes is capacity.

What this does and does not show. Batch 2 was never used for training or tuning of these
models, so the comparison with regex v0.2 is held out on both sides. Batch 3 is not a random
sample: half of it was chosen because it contains the rare classes, which is why the negative
classes rise so much. The anchoring caveat still holds for every batch, and more strongly for
batch 3, whose pre-annotator was regex v0.4 plus the negative pre-annotator, both corrected by
model agents. Two seeds are the minimum; the spread between them (0.002 on spans, 0.11 on
OTHER_LAW with 7 test spans) is the uncertainty to keep in mind.

## 7. Full-corpus run and citation graph (week 3, 2026-10-28)

### 7.1 The run

`caselaw run-corpus` sends every decision of the corpus through one extractor and the
entity-linking stage and writes three tables, `decisions`, `spans` and `citations`, as Parquet
into `data/runs/<name>/` (`src/caselaw_extraction/corpus_run.py`). A statute chain span yields
one citation row per article; a docket citation whose file number is a decision of this corpus
carries that decision's id as `target_decision_id`. The regex runs under Dask: the client
splits the corpus into partition files once (72 files for 18 workers), each task reads its own
file in the worker, and the task graph carries paths, not texts. The gbert model runs in one
process on the GPU, because a token classifier gains nothing from CPU processes. Both
extractors write the same tables, so the graph, the database loader and the API never know
which extractor made a run.

| run | extractor | decisions | spans before linking | spans after | dropped | wall time |
|---|---|---|---|---|---|---|
| `regex-v0.4` | regex v0.4, Dask, 18 worker processes | 7,999 | 294,885 | 294,884 | 1 own file number | 4.4 s (3.8 s from partitioning to results; partition files 0.3 s, the rest mostly cluster start) |
| `regex-v0.4-8w` | same, 8 workers | 7,999 | 294,885 | 294,884 | 1 | 4.2 s |
| `regex-v0.4-4w` | same, 4 workers | 7,999 | 294,885 | 294,884 | 1 | 5.3 s |
| `regex-v0.4-1proc` | same, one process, no cluster | 7,999 | 294,885 | 294,884 | 1 | 11.1 s (9.7 s extraction) |
| `gbert-b13-s0` | gbert on 260 decisions, Viterbi decoding, outcome head, one process on Apple MPS | 7,999 | 310,538 | 307,075 | 3,463 (2,264 unknown code, 810 own file number, 285 BGE without key, 104 no article) | 1,795 s (30 min) |

The regex is cheap enough that Dask does not pay off on this corpus: 9.7 seconds in one
process, 3.8 seconds with 18 workers, and most of the parallel time is spent starting the
cluster, not extracting. Dask is in the pipeline for the corpus that
the posting has in mind (all courts, all languages, about 100 times this one) and for the
extractors that cost seconds per decision; the gbert run below is the case in point.

Spans of the regex run by class: STATUTE 125,566, BGE 80,703, AMOUNT 43,229, DOCKET 30,916,
PARTY_ROLE 14,470; 36.9 spans per decision on average (median 22, maximum 437); one decision
has no span at all. Linked citations: 138,143 statute citations to 3,413 distinct articles of
145 acts, 80,703 BGE citations to 4,758 distinct leading cases, 30,916 file-number citations
to 9,996 distinct decisions, of which 12,753 citations (3,131 distinct) point at decisions
inside the corpus. The linking stage dropped one span in 294,885: the regex already removes
the own file number and only emits codes from the Fedlex list, so there was nothing left to
drop; the stage matters for the learned models (section 6.8).

Outcomes of the regex run: dismissed 2,515, inadmissible 4,644, approved 256, partial approval
196, moot 336, unknown 52. Where the dataset ships its own label (5,806 decisions), the two
agree in 4,627 cases and disagree in 1,179; 975 of the disagreements are `dataset = dismissed`,
`regex = inadmissible`, the pattern found in week 1 (section 2): the first ruling item is
"nicht eingetreten" and a later item dismisses a legal-aid request. On the 350 gold decisions
the regex outcome is right in 97 to 100 percent of the cases (sections 6.4, 6.11, 6.13), so
the regex column is the one the graph uses, and the dataset column is kept beside it.

### 7.2 Postgres

`make db-up` starts Postgres 16 in Docker (port 5433; `infra/docker-compose.yml`), `make
db-load` creates the schema (`src/caselaw_extraction/sql/schema.sql`: `extraction_run`, `decision`, `span`,
`citation`, `centrality`, `statute`) and loads a run with COPY. Every record row carries its
`run_id`, so several runs live side by side and a reload replaces a run instead of
duplicating it. The regex run loads in 6 seconds: 7,999 decisions, 294,884 spans, 249,762
citations, 19,622 centrality rows, 1,505 acts from the Fedlex list; the database is 130 MB.
Decision texts stay in Parquet; the database holds offsets and span texts.

### 7.3 The citation graph and the three headline analyses

`caselaw graph` builds the decision-to-decision graph with NetworkX (`graph.py`): the nodes
are the 7,999 corpus decisions, the 4,758 cited BGE and the 6,865 cited file numbers that are
not in the corpus; an edge is "A cites B", one per pair. The regex graph has 19,622 nodes and
86,365 edges. The centrality table (in-degree = number of citing decisions, PageRank) is
written next to the run tables and loaded into Postgres, and `graph.html` shows the 150 most
central nodes (pyvis). The analyses are SQL over the run tables through one store layer
(`store.py`) that serves DuckDB over Parquet and Postgres with the same statements, which is
what makes `make demo` work without a database.

**Most-cited statute articles** (by number of citing decisions; `GET /statutes/top`):

| article | decisions | mentions | | article | decisions | mentions |
|---|---|---|---|---|---|---|
| Art. 66 BGG (costs) | 7,791 | 8,020 | | Art. 97 BGG (facts, appeal ground) | 2,374 | 2,793 |
| Art. 42 BGG (form of the appeal) | 5,325 | 7,438 | | Art. 95 BGG (law, appeal ground) | 2,158 | 3,323 |
| Art. 106 BGG (application of law, duty to substantiate) | 4,528 | 7,412 | | Art. 100 BGG (deadline) | 2,027 | 2,128 |
| Art. 108 BGG (summary inadmissibility) | 4,030 | 4,419 | | Art. 90 BGG (final decisions) | 2,010 | 2,090 |
| Art. 68 BGG (party costs) | 3,980 | 4,311 | | Art. 76 BGG (standing) | 1,767 | 2,078 |
| Art. 75 BGG (previous instance) | 2,926 | 3,425 | | Art. 64 BGG (legal aid) | 1,745 | 1,950 |
| Art. 74 BGG (minimum amount) | 2,880 | 3,879 | | Art. 29 BV (procedural guarantees) | 1,733 | 3,340 |
| Art. 72 BGG (civil matters) | 2,715 | 2,856 | | Art. 99 BGG (new facts) | 1,502 | 1,819 |
| Art. 105 BGG (facts, binding) | 2,614 | 4,315 | | Art. 9 BV (arbitrariness) | 1,319 | 2,108 |

The first substantive article outside the court's own procedure act and the constitution is
Art. 18 OR (interpretation of contracts, 158 decisions), then Art. 257d OR (rent default, 50)
and Art. 42 OR (damages, 45). By act: BGG is cited in 7,994 of 7,999 decisions (81,806
mentions, 138 distinct articles), ZPO in 2,490 (365 articles), BV in 2,399, ZGB in 2,039 (687
articles), SchKG in 1,172, OR in 1,037 (606 articles), EMRK in 552, StGB in 301, BZP in 287,
IPRG in 238. The counts are what a reader of civil appeals expects: the court cites its own
procedure in every decision, and the two civil chambers split between family and debt
enforcement law (II) and contract law (I).

**Trend by year** (`GET /trends/years`, `GET /trends/code-share`):

| year | decisions | statute citations per decision | BGE per decision | file numbers per decision | distinct BGE cited | mean age of cited BGE volume (years) | share citing ZPO | share citing OR |
|---|---|---|---|---|---|---|---|---|
| 2020 | 1,165 | 17.3 | 9.5 | 3.9 | 1,735 | 10.8 | 35.0 % | 15.3 % |
| 2021 | 1,084 | 17.7 | 10.2 | 4.4 | 1,809 | 11.4 | 34.6 % | 14.6 % |
| 2022 | 1,139 | 17.6 | 10.2 | 4.1 | 1,749 | 11.2 | 35.2 % | 13.4 % |
| 2023 | 1,143 | 17.2 | 10.1 | 3.5 | 1,719 | 12.0 | 31.3 % | 13.5 % |
| 2024 | 1,075 | 19.6 | 12.2 | 4.1 | 1,788 | 11.9 | 32.8 % | 14.0 % |
| 2025 | 1,347 | 16.4 | 9.4 | 3.5 | 1,606 | 12.2 | 25.0 % | 10.2 % |
| 2026 | 1,046 | 15.3 | 9.3 | 3.7 | 1,428 | 12.8 | 24.7 % | 10.0 % |

Three readings. The citation density is stable at about 17 statute and 10 BGE citations per
decision; 2024 is the one denser year. The cited BGE volumes age by about two years over the
period (volume 146 is 2020; the mean cited volume sits around 2009 to 2013), that is, the
court keeps citing the same leading cases while the years pass. The share of decisions that
cite the ZPO or the OR drops by ten and five points in 2025 and 2026, together with a jump in
the number of decisions (1,347 in 2025) and a lower citation density: the last two years hold
more short inadmissibility rulings, in which only the BGG is cited. The 2026 row covers
January to early October.

**Most central decisions** (`GET /decisions/central`; PageRank over the whole graph,
in-degree in brackets):

| rank | node | cited by | topic (from the court's standard formulas) |
|---|---|---|---|
| 1 | BGE 140 III 115 | 3,335 | duty to substantiate an appeal (Art. 42 Abs. 2 BGG) |
| 2 | BGE 142 III 364 | 3,167 | duty to substantiate constitutional complaints (Art. 106 Abs. 2 BGG) |
| 3 | BGE 140 III 86 | 2,750 | requirements on the statement of grounds |
| 4 | BGE 140 III 264 | 1,900 | arbitrary assessment of facts |
| 5 | BGE 133 II 396 | 584 | constitutional complaints, substantiation |
| 6 | BGE 140 III 16 | 1,926 | arbitrariness standard |
| 7 | BGE 134 II 244 | 1,156 | substantiation of appeal grounds |
| 8 | BGE 135 II 38 | 341 | (topic not checked) |
| 9 | BGE 139 II 233 | 349 | (topic not checked) |
| 10 | BGE 143 II 283 | 995 | (topic not checked) |
| 19 | 4A_20/2011 (not in the corpus) | 210 | the only file number in the top 20 |

The top of the list is the court's own procedural case law, cited in roughly four of ten
decisions; it is the list any Swiss litigator would predict, which is the point of the check.
PageRank and in-degree disagree where a node is cited by decisions that are themselves much
cited (BGE 133 II 396 is 9th by in-degree and 5th by PageRank). Inside the corpus, the most
cited decisions are `5F_36/2022` (56 citing decisions) and `5F_12/2022` (49), two revision
rulings of the II. chamber that a chain of later revision requests by the same party cites;
`5A_85/2021` (46) and `5A_176/2023` (39) follow. The dataset's own citation graph covers the
same decisions with 2,170 fewer BGE edges and 453 fewer file-number edges than the regex run
(BGE: 59,687 edges in both, 2,994 regex only, 824 silver only; file numbers: 22,382 in both,
1,302 regex only, 849 silver only; plus 4,040 silver edges to cantonal decisions outside this
corpus). On the gold set the regex was the more precise of the two at entity level (section
6.5, 0.994 against 0.948), so the differences are mostly the silver graph's.

### 7.4 The API

`caselaw api` serves the run through FastAPI (`api.py`; OpenAPI at `/docs`), read-only:

| endpoint | what it returns |
|---|---|
| `GET /health`, `GET /runs` | backend, run id, loaded runs |
| `GET /decisions/{id}` | one decision with its linked citations (kind, key, Fedlex SR number, article, target decision, span) and all spans |
| `GET /decisions?statute=ZGB 8&bge=BGE 140 III 86&docket=4A_12/2020&year=&outcome=&chamber=` | decisions filtered by what they cite and by metadata, paginated |
| `GET /statutes/top?limit=&year=&code=`, `GET /statutes/codes` | the most-cited articles and acts |
| `GET /trends/years`, `GET /trends/code-share` | the trend tables above |
| `GET /decisions/central?by=pagerank|in_degree&kind=` | the centrality table |

The same app runs on Postgres (`CASELAW_BACKEND=postgres`) and on DuckDB over a run directory
(`CASELAW_BACKEND=duckdb`, the default for `make demo`); the smoke run returned identical
numbers on both. Single-decision lookups answer in 5 ms on Postgres and 140 ms on DuckDB
(the Parquet scan); the aggregate endpoints answer in 10 to 100 ms on either. The contract
test (`tests/test_api.py`) pins the set of paths, the response schemas and the filters on a
synthetic three-decision corpus, so it runs without data and without a database.

### 7.5 Cost of the full-corpus run

Measured on the MacBook (M5 Pro, 18 cores, 48 GB). AWS prices, checked on 2026-10-28 on
third-party price pages: Fargate Linux/x86 USD 0.04048 per vCPU-hour and 0.004445 per GB-hour
in us-east-1 (the Frankfurt rate is a few percent higher; the AWS page shows it per region),
g5.xlarge (one A10G) USD 1.258 per hour in eu-central-1. The AWS costs are estimates from the
local times; week 4 measures them on the real deployment.

| extractor | local time for 7,999 decisions | AWS target | estimated AWS cost per full run | cost per 1,000 decisions |
|---|---|---|---|---|
| regex v0.4 (one process) | 9.7 s | 1 Fargate task, 1 vCPU, 2 GB | < USD 0.01 | < USD 0.01 |
| regex v0.4 (Dask, 18 processes) | 3.8 s | not worth a cluster at this size | | |
| gbert-b13-s0 (GPU) | 1,795 s | 1 g5.xlarge (A10G), assumed as fast as the laptop GPU | about USD 0.63 | about USD 0.08 |
| LLM extractor (Claude Haiku, section 6.5) | not run on the corpus | API | about 100 M input tokens and 8 M output tokens at USD 1 / 5 per M: about USD 140 | about USD 17 |

The regex is free at any corpus size that fits a laptop; the learned model costs about eight
cents per thousand decisions on a rented GPU, plus the half hour of wall time; the LLM costs dollars per thousand and is, on the
held-out batch, the least exact of the three at span level (section 6.5). Week 4 adds the
monthly cost of keeping the API and the database up.

### 7.6 Regex graph against gbert graph: what the rules lose

The question behind the week-2 and week-3 model work was whether a learned extractor would
change the result. Both runs cover the same 7,999 decisions, so the answer is an edge-level
comparison (`caselaw compare-runs`, `data/runs/regex-v0.4/compare-gbert-b13-s0.json`); an
edge is one (decision, linked key) pair.

| kind | in both runs | regex only | gbert only | Jaccard |
|---|---|---|---|---|
| statute article | 90,116 | 243 | 346 | 0.994 |
| BGE | 62,679 | 2 | 577 | 0.991 |
| file number | 23,498 | 186 | 433 | 0.974 |

The two graphs are the same graph for every question this report asks. The 20 most-cited
articles are the same 20 in the same order. The 20 most central nodes are the same 20 (the
first two swap places: PageRank puts BGE 142 III 364 first in the gbert graph and BGE 140
III 115 first in the regex graph, with 3,170 against 3,348 citing decisions). The trend
tables differ in the second decimal. The outcomes agree on 7,840 of 7,999 decisions; the
model fills the 52 decisions the rules leave `unknown`, and the largest disagreement (65
decisions, rules `dismissed`, model `inadmissible`) is the same formula problem as between
the rules and the dataset label. Against the dataset label the two extractors agree equally
often (4,627 and 4,611 of 5,806).

Where they differ, the samples show both sides. The gbert-only BGE citations are real
citations written without the `BGE` prefix or across a line break that the regex does not
accept (`BGE 119 II 249`, `BGE 137 III 4`). The gbert-only file numbers include cantonal and
foreign numbers that the regex pattern excludes on purpose (`13Y_2_2021`, `O2017_025`,
`B25_96`): the linking stage normalises a file number but does not know which courts exist,
which is a week-4 item for the `statute`-like lookup table of courts. The regex-only file
numbers are mostly `5D_` numbers of joined proceedings, rare in the training data even after
the targeted batch. The regex-only statute citations are the long chains where the model
cut a span short (`BGG 66` at the end of a costs chain) and codes the model never saw
(`BauAV`, `FINMAG`). The linking stage dropped 3,463 model spans and one regex span: 2,264
model spans named a code that is not a federal act (contract clauses and cantonal acts the
model still labels STATUTE in a small share of cases, see 6.13), and 810 were the decision's
own file number, which no span model can know (section 6.8). The model also labelled 10,119
spans in the four negative classes (contract clauses 2,693, bare article numbers 3,539,
other law 1,504, journal references 2,383), which the regex does not produce; they are kept
in the `spans` table and are not citations.

The deployment decision follows: the rules go to AWS. On this corpus the learned model buys
an agreement of 0.99 with itself at 185 times the single-process compute (30 minutes on a GPU against 10 seconds on one core) and no change in any analysis. The
model's value is elsewhere: it is the extractor that reads the forms the rules do not list
(the prefix-less BGE, the cantonal file numbers), it measures the rules on 7,999 decisions
instead of 350, and it is what the pipeline will need for the languages and courts for which
nobody has written the rules yet.

## 8. Deployment and monitoring (week 4, 2026-11-03)

The service is live: the API at `https://api.caselaw.inat.io` (OpenAPI at `/docs`), this
report and the graph at `https://caselaw.inat.io`. It runs on one Hetzner server for under
EUR 6 per month. The AWS stack of the first design (8.6) was written and validated on
2026-10-29 and not applied: it would have cost about USD 47 per month for the same public,
read-only API, most of it for the load balancer and the managed database, and the project
already runs a second service on the same providers (Hetzner, Cloudflare, Njalla). What the
cheaper design gives up is a managed database with snapshots, a load balancer with its
metrics, and the AWS name on the stack; what replaces each of them is listed in 8.3.

### 8.1 What runs where

Terraform (`infra/hetzner/`, three providers) creates everything outside the server, and the
server's first boot (cloud-init) prepares it for Docker Compose:

| layer | resource | detail |
|---|---|---|
| server | Hetzner `cx23` (2 shared vCPU, 4 GB, 40 GB), Nuremberg, Ubuntu 24.04 | cloud-init creates the `caselaw` user, installs Docker, ufw (22, 80, 443), unattended upgrades with a nightly reboot window, rclone |
| network | Hetzner firewall: 22, 80, 443 and ping inbound | ufw repeats the rule on the host |
| DNS | two A records at Njalla, `caselaw.inat.io` and `api.caselaw.inat.io`, TTL 300 | the community provider `Sighery/njalla`; the zone stays where the domain is registered |
| object storage | Cloudflare R2 bucket `caselaw-runs`, Western Europe | run Parquet and the nightly dumps; 8 MB per run, inside the free tier |
| database | Postgres 16 container, `shared_buffers` 512 MB, `work_mem` 32 MB | the schema of 7.2, loaded with `caselaw db-load` from the run directory; 276 MB with two runs |
| API | the image of the week-4 Dockerfile, built on the server, 2 uvicorn workers | `CASELAW_BACKEND=postgres`, the connection string from a secret file |
| TLS and routing | Caddy, Let's Encrypt, HTTP redirected to HTTPS with code 308 | one host for the API, one for the static site; the metrics endpoint of Caddy stays inside the Docker network |
| monitoring | Grafana Alloy container under a Compose profile | 8.3 |
| backups | cron 03:30, `pg_dump` and the run directory to R2, 14 days retention | 8.3 |

Secrets. The Postgres password and the connection string are generated on the server by
cloud-init and never leave it; they reach the containers as Compose secret files
(`POSTGRES_PASSWORD_FILE`, `CASELAW_DSN_FILE`), not as environment variables, so they appear
in no `docker inspect` output. The Terraform tokens for Hetzner, Cloudflare and Njalla live in
1Password; `op run` injects them into the single Terraform process from a committed file of
references (`terraform.op.env`), and no token is written to disk on the laptop. The runtime
values that come from other providers (the R2 key for the backups, the Grafana Cloud key) go
to `/etc/caselaw/caselaw.env` on the server, owned by root, group `caselaw`, mode 640, outside
the repository checkout.

Deployment. `make hz-bootstrap` runs the sequence once: `terraform apply` (30 seconds, the
server in 24), wait for cloud-init (about two minutes), write the env file, rsync the
repository and build the image on the server, upload the run Parquet, run the loader inside
the API image, smoke-test the URL. Later changes are `make hz-deploy`. Two things were found
and fixed on the first run: the host group `caselaw` had gid 1001 (Docker took 1000), so the
API container joins that group to read its secret file; and the loader wrote the Fedlex
cache into a read-only working directory. Both are in git with the reason.

### 8.2 Measured on the deployment

Latency from a laptop in Switzerland over HTTPS, each request a new TLS connection; "first"
is the first request after a restart, "warm" the median of nine more:

| endpoint | first | warm |
|---|---|---|
| `/health` | 177 ms | 101 ms |
| `/decisions/{id}` | 123 ms | 104 ms |
| `/decisions?statute=BGG 42&limit=50` | 262 ms | 174 ms |
| `/statutes/top?limit=20` | 1,267 ms | 101 ms |
| `/statutes/codes` | 883 ms | 102 ms |
| `/trends/years` | 843 ms | 101 ms |
| `/decisions/central?limit=20` | 110 ms | 100 ms |
| `/drift?a=2026-08&b=2026-09` | 322 ms | 103 ms |
| `/drift/series?kind=code` | 1,042 ms | 119 ms |

The 100 ms floor is the network: the TLS handshake alone took 50 to 500 ms in the samples,
and the server answers `/health` in under a millisecond. The aggregate endpoints are the
story. On the laptop they answered in 10 to 100 ms (7.4); on the 2 vCPU server the
top-statutes aggregate took 1.1 seconds in `EXPLAIN ANALYZE`, an index scan over 138,143
citation rows followed by a sort for `count(DISTINCT)`, and the first measurement before
`ANALYZE` had run was 1.3 seconds. A run never changes while the service runs, so the API
now keeps the aggregate results in the process (a 512-entry LRU keyed by backend, run and
parameters), sends `Cache-Control: public, max-age=3600`, and fills the four default views
at startup; the warm column is the result. The drift report dropped from 2.9 seconds to 0.3
by counting only the two periods under comparison instead of all 81 months.

Resources after the load: the API container uses 213 MB, Postgres 178 MB, Caddy 19 MB; the
server has 980 MB of 3.8 GB in use and 7 GB of 38 GB on disk. The image built for x86 is
965 MB against 211 MB on the laptop's ARM build, because the x86 wheels of pyarrow (156 MB),
polars (179 MB) and DuckDB (58 MB) bundle their libraries; polars and DuckDB are not needed
by the API against Postgres and are a slimming item in section 10.

### 8.3 Monitoring, alarms and backups

What the AWS design got from the load balancer, ECS and RDS, the server gets from one Grafana
Alloy container that ships to Grafana Cloud's free tier: host CPU, memory, disk and network
(`node_exporter` collectors), container CPU and memory (cAdvisor), Postgres connections,
transactions, cache hits and database size (`postgres_exporter`, reading the DSN from a secret
file), and Caddy's request counts, status codes and latency histograms per host, which is
exactly the role of the balancer metrics. Every container's log goes to Loki. The agent is
configured (`infra/hetzner/alloy/config.alloy`) and starts with `--profile monitoring` as
soon as the Grafana Cloud credentials are in the env file; at the time of writing the
account is not created yet, so the dashboard and the alert rules below are the plan, not a
screenshot.

| alert | condition | from |
|---|---|---|
| API down | Caddy reports no 2xx for 3 minutes, or the probe of `/health` fails | Caddy metrics, Grafana synthetic check |
| 5xx | 5 or more 5xx responses in 5 minutes | Caddy metrics |
| latency | p95 of the API host above 1 s in 2 of 3 five-minute windows | Caddy histogram |
| disk | root filesystem above 85 percent | node collectors |
| memory | less than 300 MB available for 15 minutes | node collectors |
| database | `pg_up` 0, or connections above 40 | postgres exporter |
| backup | healthchecks.io ping missing after 03:30 | the backup cron |

Without the agent the server still has: Compose health checks on Postgres and the API with
`restart: unless-stopped`, Caddy's own certificate renewal, unattended security upgrades, and
the nightly backup cron, which needs the scoped R2 key and runs as soon as it is set. The
backup copies the dump and the run Parquet with rclone configured from environment variables,
so no rclone configuration file holds a key.

### 8.4 Drift check

`caselaw drift` (`drift.py`; `GET /drift`, `GET /drift/series`) compares the
entity-frequency distributions of two periods of decision dates, months or years. For the
citation kinds the distribution is the number of decisions that cite each key (article,
BGE, file number, act); for the outcome, decisions per class; for the span labels, spans per
class. Two periods are compared with the Jensen-Shannon distance (0 identical, 1 disjoint)
and the total variation distance, and the keys whose share of decisions moved most are
listed. The check runs on DuckDB and on Postgres with the same SQL, so it works on a laptop
against a run directory and in the cloud against RDS.

A threshold needs a noise level, so the series over the 81 month-to-month steps of the corpus
comes first (`caselaw drift --series`):

| kind | median JS distance | 95th percentile | maximum | usable month to month? |
|---|---|---|---|---|
| statute article | 0.448 | 0.491 | 0.515 | yes; about 250 distinct articles per month of 100 to 150 decisions, so the tail is noisy and the level is high |
| act (`code`) | 0.227 | 0.278 | 0.322 | yes, the most stable citation signal |
| BGE | 0.620 | 0.669 | 0.682 | marginal; 300 to 450 distinct leading cases per month |
| outcome | 0.140 | 0.225 | 0.273 | yes |
| file number | about 0.93 | – | – | no; file numbers rarely repeat between months |

The proposed rule is one alarm per kind at the 95th percentile of its own series (statute
0.49, act 0.28, outcome 0.23), with `caselaw drift --fail-above` as the check. The last
complete step, August to September 2026, stays under every threshold (statute 0.445, act
0.230, outcome 0.169), and it is still the step the check points at: the number of distinct
articles halves (230 to 134), the share of inadmissibility rulings rises from 67 to 76
percent, the share of decisions citing the ZPO falls from 31 to 7 percent, and BGE 140 III
115 and 142 III 364, the two substantiation precedents, gain 9 and 12 points. The decisions
themselves explain it: the mean text length of a September 2026 decision is 6,900 characters
against 10,700 in August and 11,000 to 13,000 in spring, and spans per decision drop from 30
to 20. Either the court's September output was unusually short, or the dataset's most recent
month is not complete yet and the long decisions arrive later; the next dataset release will
tell. This is what the check is for: it names the month and the keys, and a reader with the
texts can decide.

| month | decisions | mean text length | spans per decision | inadmissible |
|---|---|---|---|---|
| 2026-05 | 130 | 11,833 | 35.8 | 61.5 % |
| 2026-06 | 128 | 10,979 | 32.1 | 56.3 % |
| 2026-07 | 104 | 9,166 | 28.6 | 61.5 % |
| 2026-08 | 94 | 10,716 | 30.5 | 67.0 % |
| 2026-09 | 95 | 6,901 | 20.3 | 75.8 % |
| 2026-10 (7 days) | 7 | 6,705 | 17.0 | 85.7 % |

The year-to-year check (2024 against 2025) repeats the trend of section 7.3 in one table:
Art. 108 BGG, the summary-inadmissibility article, gains 11 points of decisions, every
substantive BGG article loses 8 to 10, the ZPO loses 8 and BGE 150 III 248, a 2024 decision,
enters at 6 percent. What is not built: a schedule that runs the check on the server. It would be one cron line
running `caselaw drift --fail-above 0.49` in the API image and one healthchecks.io ping; the
JSON output (`data/runs/regex-v0.4/drift-*.json`) is ready for it.

### 8.5 Cost

| item | per month |
|---|---|
| Hetzner `cx23` with an IPv4 address | about EUR 5 (the list price at creation; Hetzner's shared Intel line was renamed and repriced in 2025 and 2026, so the console is the source) |
| Cloudflare R2, 20 MB stored, a few hundred requests | EUR 0, inside the free tier (10 GB) |
| Njalla DNS | included in the domain |
| Grafana Cloud free tier, Let's Encrypt | EUR 0 |
| **total** | **under EUR 6** |

The AWS design would have cost about USD 47 for the same service (8.6). The full-corpus
extraction itself stays under one cent per run (7.5). `make hz-destroy` removes the server,
the bucket and the two records; the state file on the laptop is the only trace.

### 8.6 The AWS design (written and validated, not applied)

Kept as the second target in `infra/terraform/`, with `terraform validate` in CI. It is the
stack to apply if a reader wants the managed variant.

`infra/terraform/` describes the deployment; `terraform validate` passes and the CI job
checks it on every push.

| component | resource | why this one |
|---|---|---|
| run tables | S3 bucket `caselaw-runs-<account>`, private, SSE-S3; `runs/<run_id>/*.parquet` and `run.json` | the Parquet of a run is the handover between the pipeline and the database; 9 MB per run |
| image | ECR repository `caselaw-api`, scan on push, keep 10 images | one image for the API and the loader, 211 MB, core dependencies only (torch, spaCy and MLflow moved to the `ml` extra) |
| database | RDS Postgres 16, `db.t4g.micro`, 20 GB gp3, single AZ, not public, security group admits the API tasks only | the schema of section 7.2 unchanged; the connection string lives in one SSM SecureString and reaches the tasks as a secret |
| API | ECS Fargate service, 1 task of 0.25 vCPU and 512 MB, behind an application load balancer on port 80, health check `/health`, circuit breaker with rollback | the FastAPI app of 7.4 with `CASELAW_BACKEND=postgres`; Fargate because the API is one container with no state |
| loader | ECS task definition `caselaw-load`, 1 vCPU and 2 GB, same image, command `caselaw db-load --runs-dir s3://...` | the database is private, so the load runs inside the VPC; the loader reads the Parquet from S3 through pyarrow's filesystem layer and COPYs into RDS |
| logs and metrics | CloudWatch log group (14 days), dashboard with nine widgets, eight alarms on an SNS topic (optional e-mail) | section 8.2 |
| deploy | GitHub OIDC provider and a role that may push the image and restart the service, nothing else | no long-lived AWS key in GitHub |

Decisions worth stating. The stack uses the default VPC and public subnets, and the tasks get
a public IP: a NAT gateway would cost more per month than everything else together, and the
API is public and read-only. The load balancer serves HTTP only, because there is no domain
and therefore no certificate; the report says so instead of pretending. The Terraform state is
local to the laptop (a second operator would need an S3 backend). Every resource is tagged
`Project=caselaw`, and `make tf-destroy` removes all of them, the database included.

The first deployment runs in one command, `make aws-bootstrap`: apply with zero API tasks
(the image does not exist yet), build and push the image for `linux/amd64`, upload the run,
run the loader task and wait for it, apply again with one task, smoke-test the URL. Later
image changes go through GitHub Actions (`.github/workflows/deploy.yml`): after a green `ci`
run on `main`, build, push with the commit hash and `latest`, force a new deployment, wait
until the service is stable, call `/health`. `ci.yml` runs ruff, the test suite against a
Postgres service container (so the four Postgres tests no longer skip), the image build and
`terraform validate`.


#### Dashboard and alarms

The dashboard shows, from the load balancer, requests per minute, responses by class (2xx,
4xx, 5xx from the target and from the balancer) and the p50, p95 and p99 response time with
the alarm line; from ECS, the task's CPU and memory; from RDS, CPU, connections, free storage
and read and write latency; and the last twenty log lines. The alarms:

| alarm | metric | condition |
|---|---|---|
| `caselaw-api-5xx` | target 5xx count | 5 or more in 5 minutes |
| `caselaw-api-latency-p95` | target response time p95 | above 1 s in 2 of 3 five-minute windows |
| `caselaw-api-unhealthy-target` | unhealthy targets | 1 or more for 3 minutes |
| `caselaw-api-no-healthy-target` | healthy targets | below 1 for 3 minutes (missing data counts as breaching) |
| `caselaw-api-cpu`, `caselaw-api-memory` | ECS service CPU, memory | above 80 percent for 15 minutes |
| `caselaw-db-cpu` | RDS CPU | above 80 percent for 15 minutes |
| `caselaw-db-free-storage` | RDS free storage | below 2 GB |

The thresholds are starting points. The latency threshold of 1 s is ten times the local p95
of the slowest endpoint; the first week of real traffic will say whether it is right.

#### Cost estimate

Prices for eu-central-1 on 2026-10-29 from third-party price pages where the AWS page did
not show the region in the search results: load balancer USD 0.027 per hour, RDS
`db.t4g.micro` USD 0.019 per hour, gp3 storage about USD 0.14 per GB-month; Fargate at the
us-east-1 rates of section 7.5 (Frankfurt is a few percent higher); alarms USD 0.10 each; the
dashboard, SSM, the log volume and the ECR storage are inside the free allowances at this size.

| item | monthly estimate (USD) |
|---|---|
| application load balancer, 730 h | 19.7 |
| Fargate, 0.25 vCPU and 0.5 GB, 730 h | about 9 |
| RDS `db.t4g.micro`, 730 h, 20 GB gp3 | about 16.5 |
| 8 alarms | 0.8 |
| S3, ECR, logs, SSM | under 0.5 |
| **total, API up all month** | **about 47, that is USD 1.60 per day** |

The load balancer is the largest item and buys a stable URL and the health checks; a task
without it would be cheaper and would change its address at every deployment. The full-corpus
extraction itself stays under one cent (section 7.5). `make tf-destroy` stops the cost
entirely; the run Parquet and the image are rebuilt in minutes.

## 9. What did not work

_Running log._

- 2026-10-20: `timeout` is not available on macOS by default; use the tool timeout instead.
- 2026-10-20: Label Studio 1.17 rejects legacy API tokens by default. The helper in
  `scripts/labelstudio_api.py` logs in through the session form instead.
- 2026-10-20: DuckDB Python UDFs need numpy; chamber normalisation moved into SQL.
- 2026-10-21: two independent passes of the same model (Fable) with the same brief produced
  byte-identical edits on all 60 decisions. A second pass only adds information with a different
  model.
- 2026-10-21: agents cannot compute character offsets reliably. Letting them name spans by exact
  text and resolving offsets in a checker worked on the first try for all 180 agent-decisions.
- 2026-10-20: the first dispositiv pattern only matched "Demnach erkennt das Bundesgericht"
  and left 54% of outcomes unknown. Single-judge rulings use "der Präsident", "die Präsidentin",
  "das präsidierende Mitglied", "der Einzelrichter", and short rulings drop "Demnach" entirely.

- 2026-10-21: transformers 5 cannot load `deepset/gbert-base` through `AutoTokenizer` or
  `AutoConfig` (vocab.txt-only checkpoint without `model_type`). `BertTokenizerFast` and
  `BertConfig` load it; the extractor falls back to them.
- 2026-10-21: the dataset's silver graph stores BGE citations under `match_type = docket_norm`;
  only the `target_decision_id` prefix (`bge_`, `bger_`) tells the two apart. Reading it by match
  type gave a docket precision of 0.42; reading it by target prefix gives 0.996.
- 2026-10-21: the guideline example "a second page number is not a span"
  (`BGE 140 III 86 E. 2 S. 89, 115 E. 2`) is factually wrong in most occurrences: `115` is
  BGE 140 III 115, a different decision. Every agent followed the example and flagged it. Both
  batches are therefore consistent and both miss these citations. Logged as question 1 in
  `docs/guideline-open-questions.md`.
- 2026-10-21: the LLM agents wrote BGE list items in the bare form (`140 III 86`) even where the
  text has `BGE 140 III 86`, because the prompt showed the bare form for continuation items.
  The resolver now restores the prefix. A prompt example shapes output form more than a rule does.
- 2026-10-23: a post-filter on model output (Fedlex list, own docket, BGE shape) raised gbert
  from 0.984 to 0.992 in an afternoon. It was not added as a model improvement, because it
  hides learning failures and because its rules were designed by reading the batch-2 errors.
  It became the entity-linking stage that every extractor passes through (section 6.8), with
  before/after reported, and the hidden failures became classes (guideline v0.2).
- 2026-10-23: Fedlex keys the European Patent Convention as `EPÜ 2000`, with the year. The
  regex, the entity-key parser and the first draft of the linker all stripped the year before
  the lookup, and the regex's code pattern tried a single digit before a four-digit year. Three
  gold spans were lost to this in every extractor that uses the list.
- 2026-10-21: pass a (Fable) and pass c (Opus) agreed on 3,571 of 3,573 spans in batch 2, as in
  batch 1. Two different models with the same brief and the same pre-annotations are not two
  independent annotators either; the pre-annotation anchors both. The human spot check (section
  4) is the only independent signal available; it found no error in 358 spans.

## 10. Next steps

1. Switch on what is configured: the scoped R2 key for the backup cron and the loader, the
   Grafana Cloud credentials for the Alloy agent (`make hz-secrets`, `make hz-deploy`), then
   the dashboard and the seven alert rules of 8.3.
2. A GitHub repository, so that `ci.yml` runs and a deploy job over SSH replaces
   `make hz-deploy` from the laptop.
3. Record the five-minute demo (`docs/recording-script.md`).
4. Slim the x86 image: the API against Postgres needs neither polars nor DuckDB; moving them
   to an extra cuts about 240 MB.
5. If time remains: the scheduled drift check (8.4); a day on the AWS stack (8.6) for a
   measured comparison; a third gbert seed; a CRF head; a human spot check of batch 3; French
   and Italian decisions.

### Previous next steps (week 4 plan of 2026-10-28)

1. Done 2026-10-28 (week 3): full-corpus run under Dask with regex v0.4 and the linking stage,
   the same run with gbert on 260 decisions on the GPU, Postgres schema and loader, the
   citation graph with the three headline analyses, the FastAPI service on both backends,
   `make demo`, 19 new tests (section 7).
2. Done 2026-10-29 except the apply: Terraform for S3, RDS Postgres, ECS Fargate, CloudWatch
   dashboard and alarms, GitHub Actions for test and deploy, the drift check between months
   (section 8).
3. Open from week 3: the cost table (7.5) holds estimates for AWS; the deployment replaces
   them with measured numbers.

### Previous next steps (week 3, done)

1. Done 2026-10-22: human spot check of 10 batch-2 decisions, 0 errors in 358 spans
   (`data/gold/batch2/spot_check.md`).
2. Done 2026-10-23: entity-linking stage for every extractor, before/after scores (6.8);
   BIO-constrained decoding measured (6.9); guideline v0.2 with four negative classes, relabel
   round over both batches, retrained models with confusion tables (6.10).
3. Done 2026-10-24: Denis decided all open guideline questions; v0.3 round over both batches
   (short BGE citations, written-out forms), regex v0.4, every extractor re-scored, both models
   retrained (6.11). No guideline question is open.
4. Done 2026-10-28: learning curve (6.12); batch 3 with 200 decisions, half targeted; models
   retrained on 260 decisions (6.13). gbert now beats the frozen regex on the held-out batch and
   gets every outcome right.
5. Full-corpus run with Dask, load into Postgres, citation graph and the three headline
   analyses, FastAPI service (plan week 3). Extractor choice for the run: regex v0.4 remains the
   cheapest at under a second per 90 decisions; gbert on 260 is the better model on held-out
   data and costs about 12 seconds per 90 decisions on the GPU. The report will run both and
   compare the graphs.
6. If time remains: a third seed for gbert on 260; a CRF head; a human spot check of batch 3.

### Previous next steps (week 2, done)

1. Sample batch 2 (90 decisions, `caselaw sample --n 90 --seed 2 --name batch2`) and label it
   with the same toolchain: pass a (Fable), pass c (Opus), adjudication. Keep it held out.
2. Score regex v0.2 and the opencaselaw silver graph (`graph/*.parquet`) on batch 2.
3. Train spaCy NER and a German transformer on batch 1, evaluate on batch 2.
4. LLM structured-output extractor with a different prompt and a different model than the
   labelling agents, evaluated on batch 2.
5. A human spot check of 10 batch-2 decisions, to put a number on the model-labelled gold.
