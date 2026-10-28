# Project 1: Case-Law Extraction Pipeline — report

Status: week 2 complete (batch 2 held-out gold set, five extractors compared); 2026-10-23/24 addendum: entity-linking stage, guideline v0.2 (negative classes) and v0.3 (short BGE citations, written-out forms), gold relabelled twice, all extractors re-scored; 2026-10-28: batch 3 (200 decisions, half targeted) labelled, gold set 350 decisions, models retrained on 260. Week 3 (full-corpus run, graph, API) not started. Last updated 2026-10-28.

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

_Diagram TBD._ Ingest (DuckDB over HTTPS → Parquet) → extractors → MLflow → Postgres → API → graph.

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

### 6.10 Guideline v0.2: negative classes (relabel in progress, 2026-10-23)

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

## 7. Full-corpus run and citation graph

_Dask run, cost table, headline analyses. TBD week 3._

## 8. Deployment and monitoring

_AWS, Terraform, CloudWatch, drift check. TBD week 4._

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

## 10. Next steps (week 3)

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
