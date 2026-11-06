# Jev 1.14 pilot, subproject 3: outcome

Date: 2026-11-05. Script: `scripts/jev/outcome.py`. Items: `data/gold/outcome/items.jsonl`. Labels of the disputed decisions: `data/gold/outcome/disputed.jsonl`.

## Question

Can Jev 1.14 read the outcome of a decision from the ruling section, and can its probability support a threshold? The planned uses are a third opinion where regex v0.4 and gbert-b13-s0 disagree (rank 3), and a monthly drift check (rank 5).

## Data

| Set | Decisions | Labels |
|---|---|---|
| `gold`, dev | 40 | gold set, random sample, seed 0 |
| `gold`, test | 310 | gold set |
| `disputed`, test | 153 (151 scored) | labelled by `claude-opus-5-5` on 2026-11-05 |

The disputed set holds the 159 decisions where regex v0.4 and gbert-b13-s0 give different outcomes, minus the 6 that are in the gold set. I labelled them from the ruling section without seeing the two outcomes of the extractors. Two decisions are `unclear` and are not scored: one procedural order without a ruling on the appeal, and one text that is only a web page stub.

All three readers see the same text: `dispositiv()` with 1,500 characters.

## Labelling rules for the disputed decisions

The guideline (`docs/annotation-guideline.md`, Outcome) applies. These cases occur in the disputed set and are not in the guideline:

1. Two remedies, the Beschwerde in Zivilsachen inadmissible and the subsidiäre Verfassungsbeschwerde decided: the decided remedy counts.
2. Several appellants, one appeal inadmissible and another decided: the decided appeal counts.
3. Several consolidated appeals with different results that include an approval: `partial_approval`.
4. A part is struck off as moot and the rest is decided: the rest counts. If the matter itself is moot and only costs are decided: `moot`.
5. The main request is a request for revision, interpretation, rectification or restoration of a time limit: the request counts like an appeal.
6. One ruling section omits the ruling on the appeal (`bger_5A_820_2024`). The reasoning says nicht eingetreten, so the label is `inadmissible`. The extractors and Jev 1.14 cannot see this.

The prompt states rules 1, 2 and 4, because they define the task. I wrote them while I labelled the disputed set, which is test data. This favours Jev 1.14 on that set.

## Baselines on test, before any model ran

| Set | regex v0.4 accuracy | gbert-b13-s0 accuracy |
|---|---|---|
| gold test (310) | 0.987 | 1.000 |
| disputed (151) | 0.185 | 0.762 |

Regex v0.4 was tuned on the gold set. gbert-b13-s0 was trained on batches 1 and 3 of it, so only batch 2 is a fair test for it. On the disputed set, regex v0.4 returns `unknown` for 48 decisions. In 8 disputed decisions neither extractor is right.

## Pass rules, fixed before any model ran (2026-11-05)

1. Gold test: Jev 1.14 accuracy ≥ 0.97.
2. Disputed, tie-break: where Jev 1.14 agrees with one of the two extractors, that label is right in ≥ 0.90 of the cases.
3. Disputed, threshold: decisions with a top probability ≥ 0.9 have accuracy ≥ 0.95.

Always reported: accuracy against gbert-b13-s0 on the disputed set, coverage at 0.8, 0.9 and 0.95, mean top probability on gold against disputed, calibration error, cost. The prompt may change only on the 40 dev decisions, once for each error pattern.

## Test results (2026-11-05)

| Set | Jev 1.14 | gbert-b13-s0 | regex v0.4 |
|---|---|---|---|
| gold test (310), accuracy | 0.968 | 1.000 | 0.987 |
| disputed (151), accuracy | 0.974 | 0.762 | 0.185 |

Jev 1.14 cost USD 0.0188 for 463 decisions, about 970 input tokens each, latency p50 0.21 s. ECE 0.027 on gold and 0.043 on disputed. Mean top probability 0.986 on gold and 0.940 on disputed.

Pass rules:

1. Gold test accuracy ≥ 0.97: **fail** (0.968, 300 of 310).
2. Disputed tie-break ≥ 0.90: **pass**. Jev 1.14 agrees with one extractor in 141 of 151 decisions, and that label is right in 140 (0.993).
3. Disputed, top probability ≥ 0.9, accuracy ≥ 0.95: **pass**. 127 decisions (84.1%), all right (1.000).

### Cause of the failure of rule 1: two conventions

8 of the 10 gold errors are not reading errors. The gold guideline takes item 1 of the ruling literally. When item 1 says that the court does not enter into one remedy (for example the subsidiäre Verfassungsbeschwerde) and item 2 dismisses the other remedy, the gold label is `inadmissible`. My labelling rules 1, 2 and 4 for the disputed set count the remedy that the court decided, and the prompt told Jev 1.14 to do the same. Jev 1.14 then answered `dismissed` on 7 such gold decisions and on one partly moot decision.

I wrote the prompt rules without checking them against the gold set. This is my error. Under the gold convention, 15 disputed labels change. Jev 1.14 accuracy on the disputed set then falls to 0.887, gbert-b13-s0 to 0.742 and regex v0.4 to 0.212. Under the convention of the disputed set, 8 gold labels change and Jev 1.14 reaches 0.994 on gold.

The two other gold errors are real: two approvals that Jev 1.14 labelled `partial_approval`.

## Rescored under guideline v0.4 (2026-11-05, decided by Denis: option A)

The user chose the convention of the disputed set: the decided remedy counts. I added the rules to `docs/annotation-guideline.md` (v0.4) and changed 8 gold labels (`data/gold/outcome/gold-relabel-v0.4.jsonl`). No model ran again; the predictions are the same.

| Set | Jev 1.14 | gbert-b13-s0 | regex v0.4 |
|---|---|---|---|
| gold test (310) | 0.994 | 0.974 | 0.961 |
| gold batch 2 test (82) | 1.000 | 0.988 | 0.988 |
| disputed (151) | 0.974 | 0.762 | 0.185 |

On gold, Jev 1.14 now makes 2 errors, both approvals labelled `partial_approval`. With top probability ≥ 0.9 it covers 95.8% of gold at accuracy 0.997, and 84.1% of disputed at 1.000.

Under v0.4, rule 1 would pass (0.994 ≥ 0.97). This is not a pre-registered result: the label convention changed after the test run, and the change helps Jev 1.14, whose prompt already used it. gbert-b13-s0 was trained on the old labels, so v0.4 is a disadvantage for it.
