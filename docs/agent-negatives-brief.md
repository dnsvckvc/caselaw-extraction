# Brief for labelling agents: guideline v0.2 round (negative classes)

You add the four **negative classes** of guideline v0.2 to a finished gold batch. Work in
`/Users/dnsvckvc/dev/harness/job-chances/caselaw-extraction`. Do not modify any file outside
`data/gold/<batch>/v2/edits/<pass>/`. Do not read other agents' edits or `data/gold/<batch>/v2/ann/`.

The batch (`batch1`, `batch2`) and the pass (`a`, `c`) are in your assignment. Every command
needs `GOLD_BATCH=<batch> GOLD_ROUND=v2` in front of it, for example
`GOLD_BATCH=batch2 GOLD_ROUND=v2 uv run python scripts/gold/render_task.py 7`.

## What you see

`render_task.py` prints the decision with numbered pre-annotations `«#12 LABEL»text«/12»`.
Two kinds are mixed:

- **Citation gold** (STATUTE, BGE, DOCKET, AMOUNT, PARTY_ROLE): the finished, human-checked
  gold of the batch. **Leave these alone.** Do not delete, relabel or re-draw them. If one is
  clearly wrong, write it in `comment` and move on.
- **Negative proposals** (CONTRACT_ARTICLE, BARE_ARTICLE, OTHER_LAW, JOURNAL_REF): machine
  proposals with wide recall. These you correct: delete the wrong ones, fix boundaries by
  delete + add, relabel between the four negative classes, and add the ones the machine missed.

The outcome is already final; copy the pre-annotated outcome into the edits file unchanged.

## Workflow for each task

1. `GOLD_BATCH=<batch> GOLD_ROUND=v2 uv run python scripts/gold/render_task.py <N>`
2. Read the whole decision. Check every negative proposal, and search the text for references
   of the four classes that have no proposal. They are rare: a decision usually has 0 to 5.
3. Write `data/gold/<batch>/v2/edits/<pass>/<decision_id>.json`:

```json
{
  "outcome": "dismissed",
  "delete": [31],
  "relabel": [{"id": 44, "label": "OTHER_LAW"}],
  "add": [
    {"text": "Art. 7 Abs. 2 des Vorsorgereglements", "label": "CONTRACT_ARTICLE"},
    {"text": "Pra 2005 Nr. 12", "label": "JOURNAL_REF", "occurrence": 1}
  ],
  "comment": "optional"
}
```

   Write the `text` of an added span on one line with single spaces; matching ignores line
   breaks. Use the exact characters otherwise. Write the file with a Python heredoc or
   `python -c 'json.dump(...)'`. A decision with nothing to change still needs the file, with
   the outcome and empty lists.
4. `GOLD_BATCH=<batch> GOLD_ROUND=v2 uv run python scripts/gold/apply_edits.py <pass> <N>`.
   Fix and repeat until it prints `OK`. A new span may not overlap an existing one.
5. Next task. Keep one line of notes per task; report them at the end, with any case where
   the guideline did not tell you what to do.

## The four classes (from docs/annotation-guideline.md, section "Negative classes")

Boundary rule for all four: the reference only. No `E.`, `S.`, `Rz.`, `N.`, `vgl.`, `in:`,
`publ. in`, brackets, `ff.` or the final full stop.

**CONTRACT_ARTICLE.** A clause of a private instrument: contract, `AGB`, `AVB`, statutes of a
company or association, a `Reglement`, a `GAV`, a tender document. From `Art.`, `Ziff.` or `§`
to the name or abbreviation of the instrument: `Art. 13 Ziff. 2 lit. a AVB`, `Ziff. 6 der AGB`,
`Art. 22 des Konsortialvertrags`, `Art. 7 Abs. 2 des Vorsorgereglements`. A chain with one
trailing instrument name is one span. If no instrument is named after the number, it is
BARE_ARTICLE.

**BARE_ARTICLE.** An `Art.`/`§` reference after which no act is named by abbreviation:
`Art. 242` in `N. 6 zu Art. 242`; `Art. 70-72` in `Rz. 169 zu Art. 70-72`; `Art. 8` in
`Art. 8 dieser Verordnung`; `§ 15` in `§ 15 Rz. 12` (textbook); `Art. 19` in
`Art. 19 des Bundesgesetzes über ... (AVG; SR 823.11)` (act given as a title). The span is
`Art.`/`§` + number + units (`Abs.`, `Ziff.`, `lit.`, ranges, `f.`/`ff.`), and stops before the
next word. `Art.` alone or a number alone is not a span.

**OTHER_LAW.** Law that is not Swiss federal law, with the act named by an abbreviation after
the number: cantonal (`§ 18 ZPO/ZH`, `Art. 46 KV/BE`, `§ 66 Abs. 1 EG ZGB`), foreign
(`§ 133 BGB`, `Art. 1382 CC`), supranational not in Fedlex (`Art. 101 AEUV`). From `Art.`/`§`
to the abbreviation. Ratified treaties are STATUTE and already in the gold (`EMRK`, `EPÜ 2000`,
`LugÜ`, `CISG`); do not touch them. A cantonal act given as a title is BARE_ARTICLE.

**JOURNAL_REF.** A decision or article cited by journal or by a case collection other than
BGE: `SVR 1998 IV Nr. 13`, `FamPra.ch 2018 S. 595`, `BlSchK 1976 S. 141`, `Pra 2005 Nr. 12`,
`SJ 2010 I 123`, `ZR 100 Nr. 1`, `sic! 2004 S. 11`, `AJP 2019 S. 1230`. From the journal
abbreviation to the page or number. Not author names, not titles, not `in:`/`publ. in`.
A BGE cited with its journal publication keeps its BGE span; the journal part is a separate
JOURNAL_REF.

**Still no span.** Bare numbers, `Art.` without a number, `SR 823.11` alone, titles of acts
and articles, references inside text the court quotes as the appellant's own words. If a
reference fits none of the nine classes, leave it and note it in `comment`.

## Typical pre-annotator errors

- `Art. 5 des Vertrags` proposed as BARE_ARTICLE although the instrument follows: delete and
  add as CONTRACT_ARTICLE with the full span.
- A proposal that cuts a chain short (`Art. 13 Ziff. 2 lit. a` without `und Art. 13 Ziff. 3 lit. a AVB`).
- A journal proposal that is in fact a BGE in a list, or that swallowed `S.` of a page range.
- A `§` from a textbook citation proposed as OTHER_LAW because a capitalised word follows.
- Missing: `Ziff.`-only clauses (`Ziff. 4.2 des Vertrags`), journal names not in the list.

## Quality bar

Precision over speed. The citation gold is not yours to change. A wrong negative span is worse
than a missing one. Report at the end: the number of tasks, how many proposals you deleted,
added and relabelled, and every guideline gap you hit.
