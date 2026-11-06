# Jev 1.14 and TF-IDF for `legal_area`: results and combination plan

Status 2026-11-05. Subproject 1 of the Jev pilot is finished. The combination in part 2 is planned, not
started and not scheduled. No production table was changed.

## 1. Results of subproject 1

### Task and data

The dataset's `legal_area` is empty for 2,510 of the 7,999 decisions. The task is to choose one area from a
closed list. The labels are the dataset's own values, not gold.

- Classes: the 13 areas with at least 20 labelled decisions. Thirteen decisions in rarer areas are left out.
- Labelled decisions kept: 5,476.
- Split (`data/pred/legal_area/split.json`, stratified by label, seed 0): 1,000 test and 4,476 train.
  The 100 dev decisions are drawn from the 4,476 train decisions.
- Input of Jev 1.14 and `tfidf_window`: the first 6,000 characters of the decision.

### How `tfidf_window` was trained

`scripts/jev/legal_area.py`, functions `tfidf` and `baseline`, scikit-learn.

| Step | Setting |
|---|---|
| Training data | all 4,476 train decisions, including the 100 dev decisions |
| Text | first 6,000 characters, no other cleaning, lower-cased by the vectorizer |
| Features | `TfidfVectorizer`: words and word pairs, `min_df=2`, `sublinear_tf=True`, `max_features=300_000`; 167,809 features after fitting |
| Stop words, stemming | none |
| Classifier | multinomial `LogisticRegression`, solver `lbfgs`, `class_weight="balanced"`, `max_iter=2000`; stopped after 77 iterations |
| Tuning | `GridSearchCV`, 3 folds on the train decisions, scoring macro-F1, `C` in 1, 10, 100 |
| Selected | `C=100`; mean macro-F1 in the folds 0.607, 0.606 and 0.609, so the choice of `C` hardly matters |
| Final model | refitted on all train decisions, then applied once to the test split |
| Confidence | the largest value of `predict_proba` |
| Run time | about 32 s for the grid search, the refit and the prediction |

The window is short enough to contain the header and the `Gegenstand` section, which name the subject. The
strongest features confirm this: `gegenstand internationale` and `internationale schiedsgerichtsbarkeit` for
`Schiedsgerichtsbarkeit`, `gegenstand haftpflichtrecht` and `werkeigentümerhaftung` for `Haftpflichtrecht`.

### How Jev 1.14 was run

`POST /api/alpha/decisions`, model `typesafe/jev-1.14` (the snapshot `typesafe/jev-1.14-20261014` answered).
One `choice` question with a German instruction and one German description per class. No training. One
prompt change on the dev decisions: accuracy rose from 0.85 to 0.88 after the `Zivilprozess` description was
narrowed. The test split ran once, after that change was frozen. Cost of all runs: USD 0.13.

### Test results (1,000 decisions)

| Metric | Jev 1.14 | `tfidf_window` | `tfidf_full` | majority class |
|---|---|---|---|---|
| Accuracy | 0.888 | 0.905 | 0.873 | 0.321 |
| Macro-F1 | 0.751 | 0.717 | 0.688 | 0.037 |
| Calibration error (top probability, 10 bins) | 0.063 | 0.032 | 0.420 | – |
| Training labels | 0 | 4,476 | 4,476 | 4,476 |
| Cost per 1,000 decisions | USD 0.11 | none | none | none |
| Latency per decision | p50 0.21 s, p95 0.27 s | not measured | not measured | – |

Accuracy difference, Jev 1.14 minus `tfidf_window`: -0.017, 95% bootstrap interval -0.038 to +0.004.

Rules fixed before the test run: the interval is entirely above zero, or macro-F1 is at least 0.747. The first
rule failed and the second passed (0.751). The pass is narrow, and macro-F1 is driven by small classes.

| Threshold on top probability | Jev 1.14 coverage | Jev 1.14 accuracy | `tfidf_window` coverage | `tfidf_window` accuracy |
|---|---|---|---|---|
| 0.5 | 0.993 | 0.892 | 0.937 | 0.934 |
| 0.7 | 0.948 | 0.916 | 0.865 | 0.953 |
| 0.8 | 0.915 | 0.931 | 0.791 | 0.977 |
| 0.9 | 0.855 | 0.951 | 0.702 | 0.990 |
| 0.95 | 0.798 | 0.967 | 0.587 | 0.995 |

Jev 1.14 is overconfident below its top bin:

| Jev 1.14 top probability | Decisions | Mean probability | Accuracy |
|---|---|---|---|
| 0.95 to 1.00 | 798 | 0.994 | 0.967 |
| 0.90 to 0.95 | 57 | 0.924 | 0.719 |
| 0.80 to 0.90 | 60 | 0.842 | 0.650 |
| 0.70 to 0.80 | 33 | 0.745 | 0.485 |
| 0.50 to 0.70 | 45 | 0.603 | 0.400 |
| below 0.50 | 7 | 0.431 | 0.286 |

| Class | Test decisions | Jev 1.14 recall | Jev 1.14 precision | `tfidf_window` recall | `tfidf_window` precision |
|---|---|---|---|---|---|
| Schuldbetreibungs- und Konkursrecht | 321 | 0.97 | 0.94 | 0.98 | 0.97 |
| Familienrecht | 269 | 0.99 | 1.00 | 0.99 | 0.93 |
| Vertragsrecht | 202 | 0.77 | 0.94 | 0.95 | 0.82 |
| Sachenrecht | 49 | 0.86 | 0.93 | 0.86 | 0.91 |
| Erbrecht | 30 | 0.90 | 0.96 | 0.70 | 1.00 |
| Obligationenrecht (allgemein) | 30 | 0.20 | 0.43 | 0.30 | 0.50 |
| Gesellschaftsrecht | 24 | 0.75 | 0.86 | 0.62 | 0.83 |
| Immaterialgüter-, Wettbewerbs- und Kartellrecht | 20 | 0.80 | 1.00 | 0.65 | 0.93 |
| Personenrecht | 19 | 0.74 | 0.88 | 0.58 | 1.00 |
| Schiedsgerichtsbarkeit | 16 | 1.00 | 0.94 | 1.00 | 0.84 |
| Haftpflichtrecht | 10 | 0.80 | 0.36 | 0.30 | 0.60 |
| Register | 5 | 1.00 | 0.62 | 0.20 | 1.00 |
| Zivilprozess | 5 | 0.80 | 0.08 | 0.40 | 1.00 |

| Year | Decisions | Jev 1.14 | `tfidf_window` |
|---|---|---|---|
| 2020 | 140 | 0.879 | 0.936 |
| 2021 | 131 | 0.908 | 0.939 |
| 2022 | 141 | 0.908 | 0.901 |
| 2023 | 113 | 0.841 | 0.894 |
| 2024 | 165 | 0.885 | 0.903 |
| 2025 | 216 | 0.880 | 0.880 |
| 2026 | 94 | 0.926 | 0.894 |

A `tfidf_window` model trained only on decisions before 2026 reaches 0.883 and macro-F1 0.707 on the same 94
decisions.

### Reading and limits

- Jev 1.14 needs no labels and reads German rulings well. `tfidf_window` is more accurate overall and has more
  reliable confidence, and it runs free and locally.
- `Zivilprozess` is the main weakness of Jev 1.14. It gives decisions about costs or legal aid this label, but
  the dataset files them under the area of the underlying dispute.
- The labels are not gold, and `tfidf_window` was trained on them, so it also learns the dataset's habits. About
  a third of the 26 errors of Jev 1.14 at confidence 0.95 or above look defensible from their subject lines.
  Example: `bger_4A_14_2019` has the subject "Vertragsrecht" and the label `Obligationenrecht (allgemein)`.
- Missing labels are not random: 530 of 1,046 decisions in 2026 have none, against 1 of 1,347 in 2025. Results
  on the 2,510 unlabelled decisions may differ.
- The class descriptions were written after looking at subject words across all labelled decisions, including
  those that later became the test split. This may favour Jev 1.14 slightly.
- Some classes have about 5 test decisions, so their figures are noisy.

### Exploratory agreement figures

These figures come from the test split above, which has now been read, so they justify the plan but do not prove
the result. The agreement rule has no fitted parameter.

| Rule | Coverage | Accuracy |
|---|---|---|
| Both models give the same class | 0.856 | 0.980 |
| Same class, both at 0.80 or above | 0.726 | 0.997 |
| Same class, both at 0.90 or above | 0.638 | 1.000 |
| For comparison: `tfidf_window` alone at 0.70 | 0.865 | 0.953 |
| For comparison: `tfidf_window` alone at 0.95 | 0.587 | 0.995 |

On the 144 decisions where the models disagree, Jev 1.14 is right on 34%, `tfidf_window` on 46%, and neither on
20%. A rule that chooses between them on these decisions therefore has limited room to gain.

## 2. Plan: combine Jev 1.14 and `tfidf_window`

### Goal

Fill the 2,510 empty `legal_area` values with higher coverage at the same accuracy than either model alone, and
abstain on the rest. The combination must beat `tfidf_window` alone on a test split that no one has read.

### Prerequisites

- The existing 1,000 test decisions are no longer a clean test. They become training data for this plan.
- The Jev 1.14 prompt stays frozen, and the model stays pinned to `typesafe/jev-1.14`. A prompt or model change
  restarts the evaluation.
- `op` works only in the user's own terminal, so the user runs the API steps.

### TODO before step 1: does Jev 1.14 improve with the whole text?

Not started. The result decides which input the plan freezes.

- Use the 1,000 old test decisions, which are development data under this plan. Do not use the new test split.
- Run the whole text on the old test decisions that Jev 1.14 got wrong with the 6,000-character window (112 errors).
- Also run the same number of decisions that it got right. Errors alone would be misleading: an error can only stay
  wrong or improve, and random change would look like a gain. Only the correct sample shows what the whole text breaks.
- Skip decisions of 6,000 characters or fewer, because their input does not change, but count them in the totals.
- Rerun a small sample with the same window first, to see whether identical requests give identical answers.
- Report errors fixed, new errors, the net change in accuracy, and the same figures for decisions over 32,000 bytes,
  which run in the slower long-context mode.
- Adopt the whole text only if the net change on the combined sample is clearly positive after weighting the two
  samples back to their test-split shares. Otherwise keep the window.
- Expected cost: under USD 0.10.

### Steps

1. **New split.** Draw a new test split of 1,000 decisions, stratified, seed 1, from the 4,376 labelled decisions
   that Jev 1.14 has not read. Nobody reads its results until step 7. The other 4,476 decisions become the
   development set.
2. **Jev 1.14 predictions.** Run the 3,376 development decisions without a prediction. Cost about USD 0.37.
3. **Fair TF-IDF probabilities.** Produce out-of-fold `tfidf_window` probabilities with 5 folds on the
   development set, because a stacker trained on in-sample probabilities trusts TF-IDF too much.
4. **Candidates**, simplest first, all compared by 5-fold cross-validation on the development set:
   - A. Agreement: accept when both models give the same class and both exceed a threshold.
   - B. Weighted average of the two log-probability vectors, with one fitted weight and one threshold.
   - C. Stacked logistic regression on both probability vectors, on the agreement flag and on the two confidences.
5. **Calibration.** Fit temperature scaling or isotonic regression on the out-of-fold scores of the selected
   candidate. Keep Jev 1.14's raw scores for comparison.
6. **Freeze.** Commit the selected candidate, its threshold and the pass rules below before step 7. A more complex
   candidate must beat a simpler one by more than the fold-to-fold spread, otherwise the simpler one wins.
7. **Final test.** Run Jev 1.14 once on the new test split, refit on all 4,476 development decisions, score once.
8. **Adjudicated check.** Review a sample by hand, because dataset labels favour TF-IDF. Take 150 test decisions:
   50 where the models agree, 50 where they disagree, 50 where the combination abstains. Report these with sampling
   weights. Effort about two hours.
9. **Temporal check.** Repeat steps 3 to 5 with training before 2026 and test on 2026 decisions.
10. **Fill, only if the rules pass.** Run the 2,510 unlabelled decisions (about USD 0.28) and audit a random 100 by
    hand, because this population differs from the labelled one.
11. **Publish.** Add `legal_area_pred`, `legal_area_source` and `legal_area_confidence` beside the dataset column,
    which stays unchanged. Log metrics and the model snapshot to MLflow, then add a section to `docs/report.md`.

### Pass rules (final test split)

The combination passes if all of these hold against `tfidf_window` alone:

- At the same coverage as `tfidf_window` at threshold 0.9, the paired bootstrap interval for the accuracy gain is
  entirely above zero.
- At accuracy 0.98 or above on dataset labels, coverage is at least 5 points higher.
- Calibration error is at most 0.04 on the selected scores.
- On the adjudicated sample, accepted decisions reach at least 0.95 weighted accuracy.
- The temporal check on 2026 decisions loses no more than 0.03 accuracy against the final test.

### Stop rules

- If candidate A already meets the rules, do not build B or C for production.
- If the combination fails, use `tfidf_window` at threshold 0.9 alone, or keep the field empty.
- Do not tune on the new test split. A second test needs new labels.

### Cost and effort

| Item | Estimate |
|---|---|
| Jev 1.14 API: development decisions, new test, fill | about USD 0.75 |
| Code: split, out-of-fold probabilities, candidates, report | about one working day |
| Hand review: 150 test decisions and 100 audited fills | about three to four hours |

### Open risks

- Agreement may partly reflect shared errors, because both models read the same `Gegenstand` text. The hand review
  measures this.
- Jev 1.14 can fail or change. Fills are a batch job, so an outage only delays them, and the API path does not depend
  on them. The endpoint is alpha.
- The gain is modest in absolute terms, because `tfidf_window` at 0.9 already fills 70% at 0.99 accuracy on labelled
  data. The real test is whether the combination covers the hard decisions correctly.
- Reproducing `tfidf_window` needs only local data. Reproducing Jev 1.14 depends on the pinned snapshot staying online,
  so keep the raw `.jsonl` outputs.
