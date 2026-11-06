# Jev 1.14 pilot, subproject 2: citation treatment

Date: 2026-11-05. Script: `scripts/jev/treatment.py`. Labels and rules: `docs/citation-treatment-guideline.md` (v0.2). MLflow run: `jev-1.14-treatment`.

## Setup

- 300 citation windows (400 characters before the citation, 200 after), at most one per decision, from decisions outside the pool used to write the guideline.
- 150 windows drawn at random and 150 drawn with a keyword filter for rare classes. 60 windows are dev, 240 are test.
- Labels by `claude-opus-5-5`, written before any model ran. A blind spot check by the user is open (`data/gold/treatment/spotcheck.md`).
- Both models get the same instructions and label descriptions. Haiku 5.5: `/v1/chat/completions`, temperature 0, strict JSON schema, `max_tokens` 200, reasoning off.
- Prompt changed once on dev (routine text about the procedure before the Federal Supreme Court). Prompt 2 is frozen.

## Test results (239 windows; 1 `unclear` left out)

| Model | Accuracy | Macro-F1 | Routine binary F1 | Cost | Latency p50 |
|---|---|---|---|---|---|
| Jev 1.14 | 0.845 | 0.743 | 0.881 | USD 0.0116 | 0.20 s |
| Haiku 5.5 | 0.803 | 0.605 | 0.847 | USD 0.0417 | 0.83 s |
| `regex_bgg` | 0.649 | 0.272 | 0.692 | – | – |
| Majority | 0.561 | 0.144 | 0.718 | – | – |

Random stratum (119 windows):

| Model | Accuracy | Routine binary F1 | Routine binary accuracy |
|---|---|---|---|
| Jev 1.14 | 0.832 | 0.864 | 0.857 |
| Haiku 5.5 | 0.849 | 0.889 | 0.874 |
| `regex_bgg` | 0.756 | 0.821 | 0.824 |
| Majority | 0.580 | 0.734 | 0.580 |

Jev 1.14 minus Haiku 5.5, accuracy on all test windows: +0.042, 95% bootstrap [-0.021, +0.101]. Jev 1.14 alone was right on 34 windows, Haiku 5.5 alone on 24.

## Pass rules

1. Jev 1.14 accuracy is no more than 0.03 below Haiku 5.5: **pass** (+0.042).
2. Random stratum, routine binary F1 ≥ 0.90: **fail** (0.864). Beats the majority on routine binary accuracy: pass (0.857 against 0.580).
3. `negative_treatment` (5 windows): no conclusion. Jev 1.14 found 2 of 5, Haiku 5.5 found 0 of 5.

## Errors and calibration

- Main error of Jev 1.14: routine text labelled `substantive_rule`, 26 of 37 errors. Haiku 5.5 made the same error 25 times. Prompt 2 reduced this error on dev but not on test.
- Jev 1.14 ECE on the top probability: 0.038. With the top probability ≥ 0.9, Jev 1.14 covers 49% of test windows at accuracy 0.957. On the random stratum it covers 52.9% at 0.968.
- Dev accuracy with prompt 2 was 0.983. Test accuracy was 0.845, so the prompt fitted the dev windows.

## Conclusion

Jev 1.14 is at least as accurate as Haiku 5.5 on this task, at about a quarter of the cost and a quarter of the latency. It is not accurate enough to label every citation without review.

### Correction after the first report: routine filter without a threshold

For a routine filter, the precision of the `routine_standard` prediction matters, not the overall accuracy. This analysis was done after the test results were known, so it needs confirmation on new windows.

| Rule for "routine" | Predicted routine | Precision | Recall |
|---|---|---|---|
| Jev 1.14 predicts `routine_standard`, any probability | 109 | 0.982 | 0.799 |
| Same, top probability ≥ 0.8 | 60 | 1.000 | 0.448 |
| Same, top probability ≥ 0.9 | 40 | 1.000 | 0.299 |

On the random stratum the first rule gives precision 0.964 and recall 0.783. Jev 1.14 errs towards `substantive_rule`, so a routine prediction is almost always right. The 0.9 threshold removes most correct routine predictions.

### Limitation: no human spot check

The user decided on 2026-11-05 to skip the spot check. The same model wrote the guideline, the labels and the prompt. A shared bias between these three is not visible in the scores. The boundary between `routine_standard` and `substantive_rule` is where both tested models disagree with the labels most often.

## Confirmation run (150 new random windows, 2026-11-05)

Pass rule, fixed before the run: precision of every `routine_standard` prediction ≥ 0.95. **Pass.**

| Rule for "routine" | Marked | Precision | Recall |
|---|---|---|---|
| Jev 1.14 predicts `routine_standard` | 68 | 1.000 | 0.819 |
| `regex_bgg`: the window contains "BGG" | 67 | 1.000 | 0.807 |
| Either of the two (found after the run) | 74 | 1.000 | 0.892 |

Jev 1.14 accuracy over all labels: 0.892 on 148 windows, ECE 0.024, USD 0.0072. The 95% Wilson lower bound for 68 of 68 is 0.947.

The free regex is almost as good as Jev 1.14 for the routine filter. On the random test windows the regex had precision 1.000 and recall 0.696, and Jev 1.14 had 0.964 and 0.783. The combination "regex or Jev 1.14" had the highest recall in both samples (test random 0.884 at precision 0.968). This combination was chosen after the results, so it is not a pre-registered result.

Possible bias: the labeller may have used "BGG" in the window as a cue for `routine_standard`. Then the regex scores are too high.
