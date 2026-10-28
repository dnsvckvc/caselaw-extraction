# Brief for labelling agents (gold set, guideline v0.3 edition)

This edition (2026-10-25) covers all nine classes. Batches 1 and 2 were labelled with the
five citation classes and later extended; batch 3 is labelled with all nine in one pass. The
pre-annotations come from regex v0.4 (citation classes) and from a wide-recall pre-annotator
for the negative classes, so expect the negative proposals to need more correction.

You correct machine pre-annotations on Swiss Federal Supreme Court decisions (German). Work in
`/Users/dnsvckvc/dev/harness/job-chances/caselaw-extraction`. Do not modify any file outside
`data/gold/<batch>/edits/<pass>/`. Do not read other agents' edits or `data/gold/<batch>/ann/`.

The batch (`batch1`, `batch2`) and the pass (`a`, `c`) are given in your assignment. Every
command below needs the environment variable `GOLD_BATCH=<batch>` in front of it, for example
`GOLD_BATCH=batch2 uv run python scripts/gold/render_task.py 7`.

## Workflow for each task

1. `GOLD_BATCH=<batch> uv run python scripts/gold/render_task.py <N>` prints the decision. Pre-annotations appear as
   `«#12 STATUTE»Art. 42 Abs. 1 BGG«/12»`.
2. Read the whole decision. Decide which pre-annotations are wrong, which spans are missing, and
   the outcome from the dispositiv.
3. Write `data/gold/<batch>/edits/<pass>/<decision_id>.json` (decision_id is printed in the header):

```json
{
  "outcome": "dismissed",
  "delete": [3, 7],
  "relabel": [{"id": 5, "label": "BGE"}],
  "add": [
    {"text": "Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG", "label": "STATUTE"},
    {"text": "BGE 140 III 86", "label": "BGE", "occurrence": 2},
    {"text": "Fr. 500.--", "label": "AMOUNT", "all": true}
  ],
  "comment": "optional note on anything odd"
}
```

   Write the `text` of an added span on one line with single spaces. Matching ignores line
   breaks and repeated spaces. Use the exact characters of the text otherwise (`'` apostrophes,
   `--` dashes). Use a Python heredoc or `python -c 'json.dump(...)'` to write the file; do not
   put raw line breaks inside JSON strings.
4. `GOLD_BATCH=<batch> uv run python scripts/gold/apply_edits.py <pass> <N>`. If it lists problems, fix the edits
   file and run it again until it prints `OK`. A new span that overlaps an old one is refused:
   delete the old one first.
5. Move to the next task. Keep a short note per task of what you changed; report the notes at
   the end.

## The rules (same as docs/annotation-guideline.md)

**Boundaries.** A span is the citation key only. Never include `E. 2.1`, `S. 88`, dates,
brackets, the final full stop, or words such as `gemäss`, `vgl.`, `Urteil`, `Urteile`.

**STATUTE.** From `Art.`, `aArt.`, `Artikel` or `Artikeln` up to and including the law abbreviation:
`Art. 42 Abs. 1 BGG`, `Art. 97 Abs. 1 lit. a OR`, `aArt. 139 Ziff. 2 StGB`. Articles that
share one trailing abbreviation form one span: `Art. 95 und 96 BGG`,
`Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG`, `Art. 97 Abs. 1 i.V.m. Art. 105 Abs. 2 BGG`.
Each abbreviation closes a span: `Art. 42 Abs. 2 BGG` i.V.m. `Art. 106 Abs. 2 BGG` is two spans.
The pre-annotator often marks only the last article of a chain; extend it (delete, then add the
full chain). Chains joined by a comma, `bzw.`, `sowie` or `in Verbindung mit` follow the same
rule. Ranges and `f.`/`ff.` forms with an abbreviation are spans: `Art. 113-119 BGG`,
`Art. 95 f. BGG`, `Art. 319 ff. ZPO`, `Art. 121 lit. b-d BGG`. Old-format file numbers such as
`B.101/1991` are DOCKET spans. `§` citations of cantonal law and citations without an abbreviation
("Art. 8 dieser Verordnung") get no span. Also label articles of treaties (`Art. 6 Ziff. 1 EMRK`)
and cantonal codes with abbreviation (`§ 18 ZPO/ZH` is **not** labelled: it has no `Art.`).

**BGE.** `BGE 140 III 86` only. In a list, later items drop `BGE`: in
`BGE 140 III 86 E. 2; 139 III 133 E. 1.1` both `BGE 140 III 86` and `139 III 133` are spans.
A same-volume short citation, a bare page number followed by `E.` (`BGE 140 III 86 E. 2, 115 E. 2`),
is a span on the number `115` (guideline v0.3). A number after `S.` is a page and not a span.
Also label `BGE` written as `BGE 120 Ia 31` and French/Italian forms `ATF`, `DTF` if they occur.

**DOCKET.** A Federal Supreme Court file number of another case: `4A_437/2018`, `5A_12/2020`,
`4C.195/2005`, `2C_1/2019`. The number only. The decision's own number (header and footer) is
not a span. Cantonal file numbers (`ZV.2021.2`, `NG190010-O/U`, `ZK2 19 51`) are not spans.

**AMOUNT.** A sum of money with its currency token: `Fr. 1'387.--`, `CHF 12'500.50`,
`1'200 Franken`, `EUR 300`. Exclude `brutto`, `nebst Zins`, `pro Monat`. A multiplier belongs inside:
`Fr. 50 Mio.`, `EUR 2 Mio.`, `Fr. 3.241 Mio.`. `Fr` without the dot still counts as a currency token. Bare numbers,
percentages and `Fr.` without a number are not spans.

**PARTY_ROLE.** Each party's role word once, only in the header block between
`Verfahrensbeteiligte` (or `Parteien`) and `Gegenstand`: `Beschwerdeführer`, `Beschwerdeführerin`,
`Beschwerdegegnerin`, `Beschwerdegegner`, `Gesuchsteller`, `Gesuchsgegnerin`, `Klägerin`,
`Beklagter`, `Nebenintervenient`. If both parties have the same role word (two Beschwerdeführer
listed separately), one span is enough. Mentions in the body are not spans; delete them if
pre-annotated. If the role word appears as `Beschwerdeführer 1` keep only the word.

**Outcome.** Find the last header `Demnach erkennt das Bundesgericht:` /
`Demnach erkennt der Präsident:` / `… die Präsidentin:` / `… das präsidierende Mitglied:` /
`verfügt …:` and read **item 1 only**:
- `gutgeheissen` → `approved`; `teilweise gutgeheissen` → `partial_approval`
- `abgewiesen` (also `abgewiesen, soweit darauf einzutreten ist`) → `dismissed`
- `nicht eingetreten` → `inadmissible`
- `abgeschrieben`, `gegenstandslos` → `moot`
- item 1 only joins proceedings (`vereinigt`) → use item 2
- "Item 1" means the first item that rules on the appeal itself (Beschwerde, Revisionsgesuch,
  Verfassungsbeschwerde). Skip items that only decide a side request: Sistierung (suspension),
  Vereinigung (joining), Ausstand (recusal), unentgeltliche Rechtspflege (legal aid),
  aufschiebende Wirkung (suspensive effect). Example: item 1 "Das Sistierungsgesuch wird
  abgewiesen", item 2 "Auf die Beschwerde wird nicht eingetreten" → `inadmissible`.
- A decision that annuls the lower ruling and remands (aufgehoben, zurückgewiesen) without the
  word gutgeheissen counts as `approved`.
- Item 2 about `unentgeltliche Rechtspflege` (legal aid) never counts. The pre-annotated outcome is
  usually right; confirm it against item 1 anyway.
- If two appeals get different results, take the first and write a comment. If there is no
  dispositiv at all, use `unknown` and write a comment.

## The negative classes (guideline v0.2/v0.3)

Four classes mark references that look like citations and link to nothing. Boundary rule as
above: the reference only, no `E.`, `S.`, `Rz.`, `N.`, `vgl.`, `in:`, `publ. in`, brackets,
`ff.` or the final full stop. Written-out `Ziffer`, `Artikel`, `Absatz` count like `Ziff.`,
`Art.`, `Abs.` (v0.3).

**CONTRACT_ARTICLE.** A clause of a private instrument: contract, `AGB`, `AVB`, statutes of a
company, a `Reglement` without an SR number, a `GAV`, a court-approved settlement
(`Vergleich`), a self-regulation agreement (`VSB 2020`), an approved collective tariff
(`GT 9 VI`). From `Art.`, `Ziff.`, `Ziffer` or `§` to the name or abbreviation of the
instrument: `Art. 13 Ziff. 2 lit. a AVB`, `Ziffer 9 des Vertrags`, `Art. 22 des
Konsortialvertrags`, `Art. 3 der zwischen den Parteien geltenden Allgemeinen Bedingungen für
die Kollektiv-Krankentaggeldversicherung` (stop before a bracketed abbreviation). A qualifier
after an abbreviation (`AGB für Hypothekarkredite`) is not included. If no instrument is named
after the number, it is BARE_ARTICLE.

**BARE_ARTICLE.** An `Art.`/`Artikel`/`§` reference after which no act is named by
abbreviation: `Art. 242` in `N. 6 zu Art. 242`; `Art. 70-72` in `Rz. 169 zu Art. 70-72`;
`§ 15` in a textbook citation `§ 15 Rz. 12`; and **any act given as a title**, federal,
cantonal, foreign or a treaty: `Art. 19` in `Art. 19 des Bundesgesetzes über ... (AVG;
SR 823.11)`, `§ 25` in `§ 25 des Einführungsgesetzes zur ZPO [EG ZPO/AG]`, `Art. 8` in
`Art. 8 des Übereinkommens über die Rechte des Kindes (KRK)`. A `Reglement` or `Verordnung`
with an SR number is an act, never CONTRACT_ARTICLE. Span: `Art.`/`§`, number, units; stop
before the next word. `Art.` alone, a number alone, a lone `Absatz 2` or `Ziffer 3` without
`Art.`/`§`: no span.

**OTHER_LAW.** Law that is not Swiss federal law, named by an abbreviation after the number:
cantonal (`§ 18 ZPO/ZH`, `Art. 117 GOG/ZH`, `§ 66 Abs. 1 EG ZGB/BL`), foreign (`§ 133 BGB`,
`Art. 1382 CC`), supranational not in Fedlex (`Art. 101 AEUV`). Ratified treaties with a
Fedlex abbreviation are STATUTE (`EMRK`, `EPÜ 2000`, `LugÜ`, `KRK` when cited as `Art. 8 KRK`).

**JOURNAL_REF.** A decision or article cited by journal or by a case collection other than
BGE: `SVR 1998 IV Nr. 13`, `FamPra.ch 2018 S. 595`, `BlSchK 1976 S. 141`, `Pra 2005 Nr. 12`,
`MRA 2014, S. 90` (comma inside), `Anwaltsrevue 8/2020 S. 315` (full names count). From the
journal name to the first page or number; a second page after a comma or `und` is left out;
`f.`/`ff.` excluded; author names and titles never.

**No span, for all classes:** numbered points of court or authority documents and party
briefs (`Dispositiv-Ziffer 2`, `Ziffer 1 des Urteils`, `Ziff. 41 der Berufung`, `Randziffer
26`); official gazettes and collections (`BBl`, `AS`, `AB`, `SR 823.11`, `LS 212.51`); draft
acts (`Art. 93 VE-ZPO`); administrative guidelines (`Ziff. 4.10 der IGE-Richtlinien`); patent
numbers; foreign, cantonal and ECtHR file numbers; a typo that makes a federal code unknown
(`Art. 90 BG`); book citations with `Rz.` only. References inside text the court quotes from
a party are labelled like any other.

## Quality bar

- Precision over speed. A wrong box in the gold set is worse than a missing one.
- Check every pre-annotation, not only the suspicious ones. Typical pre-annotator errors:
  a chain cut short; `Franken` amounts missed; `BGE` list items without the `BGE` word missed;
  `lit.` or `Ziff.` cut off; a `DOCKET` that is the decision's own number; a `PARTY_ROLE`
  in the body.
- Do not invent spans for things that are not in the nine categories. When a reference fits
  none of them, leave it and note it in `comment`.
