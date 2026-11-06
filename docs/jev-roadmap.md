# Roadmap: Jev 1.14 in the pipeline

Written 2026-11-05, after the three-part pilot. Not scheduled. Details and numbers: `docs/jev-legal-area.md`, `docs/jev-treatment.md`, `docs/jev-outcome.md`, `docs/plan-routine-selector.md`.

## Findings

| Use | Finding | Decision |
|---|---|---|
| Outcome where regex v0.4 and gbert-b13-s0 disagree | Strongest case. On 151 disputed decisions Jev 1.14 is right in 0.974, gbert-b13-s0 in 0.762, regex v0.4 in 0.185. On gold (guideline v0.4) 0.994. Top probability ≥ 0.9 covers 84% of disputed decisions at 1.000. | Build first. |
| Routine filter for citations | Jev 1.14 `routine_standard` has precision 0.982 (test) and 1.000 (new random windows), with higher recall than the "BGG" regex in both samples (0.783 against 0.696, 0.819 against 0.807). The regex only finds routine text that names the BGG; Jev 1.14 also finds standard text without it, such as the arbitrariness test. Jev 1.14 or regex gives the highest recall (0.892) at precision 1.000. | Build second, as Jev 1.14 or regex. |
| `legal_area` for the 2,510 decisions without it | Jev 1.14 alone is not better than TF-IDF (accuracy 0.888 against 0.905). Where both agree (85.6% of decisions) accuracy is 0.980, an exploratory figure. | Only in combination with TF-IDF, after the whole-text check. |

The outcome run had one failed pre-registered rule (gold accuracy 0.968). The cause was a label convention: the prompt and the gold set counted different items of the ruling. The user resolved it with guideline v0.4. The record is in `docs/jev-outcome.md`.

## Principles for every stage

- Offline batch only. Jev 1.14 is never in the API request path.
- Pin the snapshot (`typesafe/jev-1.14-20261014`) and store it with every label.
- Store the source of every value (`regex`, `gbert`, `jev`, `agree`) and the Jev 1.14 probability, so that the API and the explorer can show and filter it.
- If the alpha endpoint (`/api/alpha/decisions`) changes or fails, the stage is skipped and the pipeline keeps today's values. No view breaks.
- The key comes from 1Password through `op run --env-file scripts/jev/openrouter.op.env`.
- Log each run to MLflow, as the pilot scripts do.
- Before a new snapshot is used, rerun the three frozen test sets: `data/gold/outcome/items.jsonl` (test), `data/gold/treatment/windows.jsonl` (test and confirm), `data/pred/legal_area/split.json` (test). Adopt it only if no score falls by more than 0.02.

## Stage 1: outcome resolver

1. After the regex and gbert runs, select the decisions where the two outcomes differ or the regex returns `unknown` (159 in the current corpus, about 2%).
2. Send their ruling section (`dispositiv()`, 1,500 characters) with the frozen prompt in `scripts/jev/outcome.py`.
3. Rule: if the two extractors agree, keep their outcome. If they disagree, take the Jev 1.14 outcome when its top probability is ≥ 0.9; otherwise take gbert-b13-s0 and mark the decision for review.
4. Columns in `decision`: `outcome` (resolved), `outcome_source`, `outcome_jev_p`. Keep `outcome_regex`, `outcome_gbert` and `outcome_dataset` beside it.
5. Cost: under USD 0.01 for each corpus run. Monthly, the same call on a random sample of 200 decisions gives an independent drift check for the outcome (rank 5 of the first evaluation).
6. Tests: the resolver rule on fixtures; an integration test with a stubbed Jev 1.14 response.

## Stage 2: routine filter and selector

As in `docs/plan-routine-selector.md`: a citation is routine if Jev 1.14 says `routine_standard` or its window contains "BGG". One run on 111,619 citations costs about USD 5.40. The API gets `routine=include|exclude`, PageRank is precomputed for both variants, and caselaw-explorer gets one toggle.

## Stage 3: `legal_area` with TF-IDF

1. Run the whole-text check in `docs/jev-legal-area.md` (under USD 0.10).
2. Run the combination plan in the same file (agreement, weighted log-probabilities, stacking) on a new test split.
3. Fill the 2,510 missing values only if the plan's pass rules hold, with `legal_area_source` and `legal_area_confidence`.

## Open risks

- No human checked the pilot labels (treatment windows, disputed outcomes, the 8 changed gold outcomes).
- The outcome prompt contains rules written while labelling the disputed set.
- TypeSafe states that English gives the best accuracy; all results here are on German text and hold only for this corpus.
