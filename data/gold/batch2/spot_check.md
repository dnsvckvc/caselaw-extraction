# Human spot check of the model-labelled gold set

For each decision: read it with the gold spans inline, count wrong spans (should not be
there or wrong boundary), missed spans, and say whether the outcome is right.

| # | decision_id | gold spans | gold outcome | wrong spans | missed spans | outcome ok? |
|---|---|---|---|---|---|---|
| 1 | bger_4D_40_2026 | 20 | inadmissible | 0 | 0 | yes |
| 2 | bger_4A_37_2020 | 12 | moot | 0 | 0 | yes |
| 3 | bger_5A_193_2021 | 44 | dismissed | 0 | 0 | yes |
| 4 | bger_5A_98_2025 | 62 | dismissed | 0 | 0 | yes |
| 5 | bger_4A_153_2025 | 12 | inadmissible | 0 | 0 | yes |
| 6 | bger_4A_172_2020 | 12 | inadmissible | 0 | 0 | yes |
| 7 | bger_5A_601_2025 | 38 | dismissed | 0 | 0 | yes |
| 8 | bger_4A_29_2022 | 45 | dismissed | 0 | 0 | yes |
| 9 | bger_5A_133_2019 | 98 | dismissed | 0 | 0 | yes |
| 10 | bger_5A_680_2021 | 15 | inadmissible | 0 | 0 | yes |

Notes:

- Checked by Denis on 2026-10-22 in Label Studio (project 1, tasks 146, 74, 92, 134, 130, 68, 135, 94, 69, 81).
- Result: 358 gold spans in 10 decisions, 0 wrong, 0 missed; 10 of 10 outcomes right.
- No correction to apply to the gold set.

