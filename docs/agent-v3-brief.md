# Brief for labelling agents: guideline v0.3 round (short BGE citations, written-out forms)

You apply three rule changes of guideline v0.3 to a finished gold batch. Work in
`/Users/dnsvckvc/dev/harness/job-chances/caselaw-extraction`. Do not modify any file outside
`data/gold/<batch>/v3/edits/<pass>/`. Do not read other agents' edits or `data/gold/<batch>/v3/ann/`.

The batch (`batch1`, `batch2`) and the pass (`a`, `c`) are in your assignment. Every command
needs `GOLD_BATCH=<batch> GOLD_ROUND=v3` in front of it, for example
`GOLD_BATCH=batch2 GOLD_ROUND=v3 uv run python scripts/gold/render_task.py 7`.

## What you see

`render_task.py` prints the decision with numbered pre-annotations `«#12 LABEL»text«/12»`.
Most of them are the **finished gold** of the batch (all nine classes). **Leave those alone.**
A few are **new proposals** for the three v0.3 rules below. You cannot tell the two apart by
colour, so check every span that falls under one of the three rules, and nothing else. The
outcome is final; copy it unchanged.

## The three rules

1. **Same-volume short BGE citations are BGE spans.** In `BGE 140 III 86 E. 2, 115 E. 2; 264
   E. 2.3` the numbers `115` and `264` cite BGE 140 III 115 and 140 III 264. The span is the
   page number only, label BGE. The test: a bare number after `,` or `;` that is **followed by
   `E.`**. A number after `S.` (`E. 5.2.5 S. 197, 201`) is a page of the same decision and
   gets no span. A number followed by a roman part (`139 III 133`) is a full citation and is
   already in the gold. Short citations also occur after a full citation that itself lacks the
   word BGE (`139 III 133 E. 1.1, 334 E. 3`): `334` is a span.
2. **`Artikel` and `Artikeln` written out are STATUTE** when a known law abbreviation follows:
   `Artikel 104 BGG`, `Artikeln 35a und 35b VVG`. Same span rules as for `Art.`: from
   `Artikel` to the abbreviation, chains with one trailing abbreviation are one span.
3. **Spelled-out `Ziffer`, `Artikel`, `Absatz` count for the negative classes**:
   `Ziffer 9 des Vertrags`, `Artikel 17 der Vereinbarung`, `Ziffer 1 Absatz 2 des Vergleichs`,
   `Ziffer 6.7 GT 9 VI` (collective tariff), `Ziffer 13 der AGB für Hypothekarkredite` (span
   ends at `AGB`) are CONTRACT_ARTICLE; `Artikel 242` in `N. 3 zu Artikel 242` is
   BARE_ARTICLE. Everything else in the v0.2 rules for these classes stays: numbered points of
   court documents and party briefs (`Dispositiv-Ziffer 2`, `Ziffer 1 des Urteils`, `Ziff. 41
   der Berufung`) are not spans; an act given as a title is BARE_ARTICLE (`Artikel 19 des
   Bundesgesetzes ...` → `Artikel 19`).

## Workflow for each task

1. `GOLD_BATCH=<batch> GOLD_ROUND=v3 uv run python scripts/gold/render_task.py <N>`
2. Search the text for the three patterns: every `, <number> E.` / `; <number> E.` after a BGE
   citation; every `Artikel`/`Artikeln`; every `Ziffer`/`Absatz` written out. Check that each
   occurrence has the right span or correctly has none. Delete wrong proposals, add missing
   spans. Do not touch anything outside the three rules.
3. Write `data/gold/<batch>/v3/edits/<pass>/<decision_id>.json`:

```json
{
  "outcome": "dismissed",
  "delete": [31],
  "add": [
    {"text": "115", "label": "BGE", "occurrence": 3},
    {"text": "Artikel 104 BGG", "label": "STATUTE"},
    {"text": "Ziffer 9 des Vertrags", "label": "CONTRACT_ARTICLE", "all": true}
  ],
  "comment": "optional"
}
```

   A short number such as `115` occurs many times in a text: count the occurrences
   (`apply_edits.py` lists them with context when the text is ambiguous) and give the right
   `occurrence`. Write the file with a Python heredoc or `python -c 'json.dump(...)'`. A task
   with nothing to change still needs the file with the outcome and empty lists.
4. `GOLD_BATCH=<batch> GOLD_ROUND=v3 uv run python scripts/gold/apply_edits.py <pass> <N>`.
   Fix and repeat until it prints `OK`.
5. Next task. One line of notes per task; report them at the end with every case the rules do
   not settle.

## Quality bar

Precision over speed. Change only what the three rules require. Use your own scratchpad
subfolder (`/private/tmp/claude-501/.../scratchpad/<batch>_<pass>_<first task>/`) for rendered
texts, because other agents work in parallel. Report at the end: tasks done, spans added and
deleted per rule, and every open case in one line.
