# Project memory for agents

Facts that later sessions need and that the code does not show. The report (`docs/report.md`) holds the full history.

## Jev 1.14 (cheap classifier on OpenRouter), pilot of 2026-11-05

- Roadmap: `docs/jev-roadmap.md`. Order: outcome resolver, routine filter, `legal_area` with TF-IDF. Only the routine filter is built (2026-11-06).
- Outcome is the strongest case: on decisions where regex v0.4 and gbert-b13-s0 disagree, Jev 1.14 is right in 0.974, gbert in 0.762, regex in 0.185. Do not keep "regex wins" for these decisions.
- Routine filter: Jev 1.14 `routine_standard` only (user decision 2026-11-06; the "BGG" regex is not used). Selector plan for the API: `docs/plan-routine-selector.md`. Steps 1 to 5 built and the full labelling run done on 2026-11-06 (`caselaw treatment`, `routine=include|exclude`). On Hetzner the order is hz-sync, hz-deploy, hz-load, hz-restart (step 6).
- `legal_area`: Jev 1.14 alone is not better than TF-IDF. Use it only in combination, after the whole-text check (`docs/jev-legal-area.md`).
- Outcome guideline is v0.4: the remedy that the court decides counts, not item 1 taken literally. Eight gold labels changed (`data/gold/outcome/gold-relabel-v0.4.jsonl`).
- A single outcome label is too coarse for decisions with several rulings (two remedies, several appellants, joined proceedings, partly moot). Ideally they get one outcome per ruling item and a derived document outcome. When, why and the open design: `docs/guideline-open-questions.md`, last section.
- Jev 1.14 runs offline only, with the snapshot `typesafe/jev-1.14-20261014` pinned. Prompts in `scripts/jev/*.py` are frozen; change them only on dev data.
- Haiku 5.5 on OpenRouter needs reasoning off and `max_tokens` ≥ 200 for one-label answers.

## Running API calls

- `op` (1Password CLI) does not work inside the Claude Code session. The user runs `op run --env-file scripts/jev/openrouter.op.env -- uv run python scripts/jev/<script>.py ...` in a separate terminal, and the agent reads the result files.
- Never print the key.

## Labels

- The pilot labels (treatment windows, disputed outcomes) were written by `claude-opus-5-5`, and no human checked them. The user accepted this on 2026-11-05.
