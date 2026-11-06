# Annotation guideline (v0.4)

v0.4 (2026-11-05, decided by Denis) changes only the outcome: the appeal that the court
decides counts, not item 1 taken literally (see "Outcome"). Eight gold labels changed; the list
is in `data/gold/outcome/gold-relabel-v0.4.jsonl`.

v0.2 (2026-10-23) added the four negative classes in the section "Negative classes" and
changed nothing in the five citation classes. v0.3 (2026-10-23, decided by Denis on all open
questions) changes two things in the citation classes and one in the negative classes:

- **Same-volume short BGE citations are BGE spans** (question 1). In
  `BGE 140 III 86 E. 2, 115 E. 2; 264 E. 2.3` the numbers `115` and `264` cite BGE 140 III 115
  and BGE 140 III 264. The span is the page number only. The test is a consideration (`E.`)
  after the number; a number after `S.` or a number followed by nothing is a page of the same
  decision and gets no span (`BGE 133 III 189 E. 5.2.5 S. 197, 201`).
- **`Artikel` and `Artikeln` written out are STATUTE** (question 6): `Artikel 104 BGG`,
  `Artikeln 35a und 35b VVG`, the same span rules as for `Art.`.
- **Spelled-out `Ziffer`, `Artikel`, `Absatz` count for the negative classes** (question 17):
  `Ziffer 9 des Vertrags`, `Artikel 17 der Vereinbarung`, `Ziffer 1 Absatz 2 des Vergleichs`
  and the `Ziffer` clauses of collective tariffs (`Ziffer 6.7 GT 9 VI`) are CONTRACT_ARTICLE;
  `Artikel 242` in a commentary reference is BARE_ARTICLE.

All other items of `docs/guideline-open-questions.md` keep the rule the table proposes.

Label character spans in the decision text. Correct the pre-annotations; do not re-draw a span
that is already right.

General rule: a span covers the **citation key only**. Considerations (`E. 2.1`), page
references (`S. 88`) and dates are never part of a span. The regex parses them as attributes.

## STATUTE
The full citation including the code: `Art. 42 Abs. 1 BGG`, `Art. 8 ZGB`,
`Art. 97 Abs. 1 lit. a OR`, `aArt. 139 Ziff. 2 StGB`. Include `Abs.`, `lit.`, `Ziff.`, `Satz`
and the code. Exclude a leading `gemäss`, `nach`, `von` and trailing punctuation.
A chain of articles that share one trailing code is **one span**:
`Art. 95 und 96 BGG`, `Art. 42 Abs. 1 und 2 BGG`, `Art. 97 Abs. 1 i.V.m. Art. 105 Abs. 2 BGG`.
Two citations that each carry their own code are two spans:
`Art. 42 Abs. 2 BGG` i.V.m. `Art. 106 Abs. 2 BGG`.

## BGE
`BGE 140 III 86` only. Not `E. 2.1`, not `S. 88`. In a chain like
`BGE 140 III 86 E. 2; 139 III 133 E. 1.1` label `BGE 140 III 86` and `139 III 133` as two spans.
A same-volume short citation, a bare page number followed by `E.` (`BGE 140 III 86 E. 2, 115
E. 2`), is a third span `115` (v0.3). A number after `S.` is a page, not a span.

## DOCKET
A BGer docket number cited as a prior decision: `4A_463/2022`, `4C.195/2005`, `9C_12/2020`.
The number only, without `Urteil`, the date, or the consideration.
Do **not** label the docket number of the decision itself in the header.

## AMOUNT
Money amounts with currency: `Fr. 40'000.--`, `CHF 12'500.50`, `Fr. 1'200.-`. Include the
currency token. Exclude `nebst Zins`.

## PARTY_ROLE
Role words that denote a party: `Beschwerdeführer`, `Beschwerdeführerin`, `Beschwerdegegnerin`,
`Beschwerdegegner`, `Gesuchsteller`, `Klägerin`, `Beklagte`. Only in the Rubrum (header) section,
once per role. Do not label every occurrence in the body.

## Outcome (document label)
Read the Dispositiv (section after `Demnach erkennt das Bundesgericht:`).
- approved: `wird gutgeheissen`
- partial_approval: `teilweise gutgeheissen`
- dismissed: `wird abgewiesen` (also `abgewiesen, soweit darauf einzutreten ist`)
- inadmissible: `wird nicht eingetreten`
- moot: `abgeschrieben`, `gegenstandslos`
- consolidated: only if the whole decision does nothing but join proceedings
- "Item 1" means the first item that rules on the appeal itself (Beschwerde, Revisionsgesuch,
  Verfassungsbeschwerde). Skip items that only decide a side request: Sistierung (suspension),
  Vereinigung (joining), Ausstand (recusal), unentgeltliche Rechtspflege (legal aid),
  aufschiebende Wirkung (suspensive effect). Example: item 1 "Das Sistierungsgesuch wird
  abgewiesen", item 2 "Auf die Beschwerde wird nicht eingetreten" → `inadmissible`.
- A decision that annuls the lower ruling and remands (aufgehoben, zurückgewiesen) without the
  word gutgeheissen counts as `approved`.
If several appeals are decided, label the main one and leave a comment.

Rules added in v0.4 (2026-11-05):
- Two remedies, one inadmissible and the other decided (for example `Auf die Beschwerde in
  Zivilsachen wird nicht eingetreten. 2. Die subsidiäre Verfassungsbeschwerde wird abgewiesen`):
  the decided remedy counts → `dismissed`. This holds in either order of the items.
- Several appellants or joined appeals, one inadmissible and another decided: the decided one
  counts. If the results include an approval and a dismissal: `partial_approval`.
- One proceeding or part is struck off as moot and the rest is decided: the rest counts. If the
  matter itself is moot and only costs are decided: `moot`.
- A request for revision, interpretation, rectification or restoration of a time limit counts
  like an appeal.

## Negative classes (v0.2)

The five classes above are citations that the pipeline links to a key: a Fedlex article, a
BGE, a BGer file number. The text also contains references that look like these citations but
are not. Under v0.1 they got no span, so a learned model saw them only as background. Under
v0.2 they get their own class, so that the model learns the distinction from data and the
evaluation reports the confusion instead of hiding it. None of the four is linked to anything.
The boundary rules are the same as for STATUTE and BGE: the reference only, no `E.`, `S.`,
`Rz.`, `N.`, brackets or final full stop.

### CONTRACT_ARTICLE
A clause of a private instrument: a contract, general terms (`AGB`), general insurance
conditions (`AVB`), statutes of a company or association, a pension-fund or other regulation
(`Reglement`), a collective labour agreement (`GAV`), a tender document. The span runs from
`Art.`, `Ziff.` or `§` to the name or abbreviation of the instrument:
`Art. 13 Ziff. 2 lit. a AVB`, `Ziff. 6 der AGB`, `Art. 22 des Konsortialvertrags`,
`Art. 7 Abs. 2 des Vorsorgereglements`. A chain that shares one trailing instrument name is one
span, as for STATUTE. If the instrument is not named after the number (`Art. 5` alone, the
contract named earlier), the reference is BARE_ARTICLE.

### BARE_ARTICLE
An article or paragraph reference after which no act is named by abbreviation: `Art. 242` in
`N. 6 zu Art. 242`, `Art. 70-72` in `Rz. 169 zu Art. 70-72`, `Art. 8` in
`Art. 8 dieser Verordnung`, `§ 15` in a textbook citation `§ 15 Rz. 12`, and `Art. 19` in
`Art. 19 des Bundesgesetzes über ... (AVG; SR 823.11)` (the act is given as a title, not as the
abbreviation after the number; this settles open question 7). The span covers `Art.`/`§`, the
number and its units (`Abs.`, `Ziff.`, `lit.`, ranges, `f.`/`ff.`) and stops before the next
word. `Art.` without a number and a bare number without `Art.` are not spans.

### OTHER_LAW
A citation of law that is not Swiss federal law and that names the act by an abbreviation
after the number: cantonal law (`§ 18 ZPO/ZH`, `Art. 46 KV/BE`, `§ 66 Abs. 1 EG ZGB`), foreign
law (`§ 133 BGB`, `Art. 1382 CC`, `§ 823 BGB`), supranational law that Fedlex does not list
(`Art. 101 AEUV`). The span runs from `Art.`/`§` to the abbreviation. Treaties that Switzerland
has ratified are in Fedlex and stay STATUTE (`Art. 6 Ziff. 1 EMRK`, `Art. 56 EPÜ 2000`). A
cantonal act given as a title (`§ 29 Abs. 1 der Verordnung über ...`) is BARE_ARTICLE.

### JOURNAL_REF
A decision or an article cited by its place in a journal or a case collection other than the
BGE: `SVR 1998 IV Nr. 13`, `FamPra.ch 2018 S. 595`, `BlSchK 1976 S. 141`, `Pra 2005 Nr. 12`,
`SJ 2010 I 123`, `ZR 100 Nr. 1`, `sic! 2004 S. 11`, `AJP 2019 S. 1230`. The span runs from the
journal abbreviation to the page or number. Exclude `publ. in`, `in:`, `ff.`, `E. 2` and a
following consideration. A BGE cited with its journal publication keeps the BGE span, and the
journal part becomes a separate JOURNAL_REF span. Author names and titles of books or articles
are never part of the span.

### Clarifications from the v0.2 relabel round (2026-10-23)
The 20 labelling agents of the round raised these cases. The decisions below are now part of
v0.2 and were applied to both batches.

- **Any act given as a title is BARE_ARTICLE**, whether federal, cantonal, foreign or a
  ratified treaty, and whether or not an abbreviation follows in brackets:
  `Art. 19 Abs. 1 lit. b der Verordnung ... (VMWG; SR 221.213.11)` → `Art. 19 Abs. 1 lit. b`;
  `Art. 8 des Übereinkommens ... (KRK; SR 0.107)` → `Art. 8`; `§ 25 des Einführungsgesetzes
  zur ZPO [EG ZPO/AG]` → `§ 25`; `Art. 51 der spanischen Zivilprozessordnung` → `Art. 51`.
  A `Reglement` or `Verordnung` with an SR number is an act, never a CONTRACT_ARTICLE.
- **Spelled-out `Ziffer`, `Artikel`, `Absatz`**: no span in v0.2; **spans in v0.3** (see the
  top of this file). `Ziffer 9 des Mortgage Loan Agreement`, `Artikel 17 der Vereinbarung` and
  the `Ziffer` clauses of collective tariffs (GT 8, GT 9) and court settlements are
  CONTRACT_ARTICLE.
- **Private instruments** include a court-approved settlement (`Vergleich`), a self-regulation
  agreement of an industry (`VSB 2020`), and approved collective tariffs of collecting
  societies (`GT 9 VI`). The span ends at the abbreviation or the last word of the instrument
  name; a qualifier after an abbreviation (`AGB für Hypothekarkredite`) is not included, and a
  bracketed abbreviation after a long name is not included:
  `Art. 3 der zwischen den Parteien geltenden Allgemeinen Bedingungen für die
  Kollektiv-Krankentaggeldversicherung` (span ends before `(AB)`).
- **Numbered points of court documents and party briefs are not spans**: `Dispositiv-Ziff. 1`,
  `Ziff. 1 des Urteils`, `Ziff. 3.1 der prozessleitenden Verfügung`, `Ziff. 41 der Berufung`,
  `Rz. 151 der Beschwerde`.
- **Official gazettes and collections are not spans**: `BBl 2017 5089`, `AS 2016 2317`,
  `AB 2014 N 1967`, `RB 211.24`, `LS 212.51`, `SR 823.11`.
- **Not covered by any class, no span**: draft acts (`Art. 93 VE-ZPO`), administrative
  guidelines and directives cited by `Ziff.` (`Ziff. 4.10 der IGE-Richtlinien`), patent
  numbers, foreign and cantonal file numbers, ECtHR application numbers, book citations with
  `Rz.` only, and a typo that makes a federal code unknown (`Art. 90 BG`).
- **JOURNAL_REF details**: a comma between year and page is inside the span
  (`MRA 2014, S. 90`); a single `f.` is excluded like `ff.`; a second page after a comma or
  `und` is not part of the span and gets no span of its own (`BlSchK 1981 S. 133, 137` →
  `BlSchK 1981 S. 133`); a journal written out in full counts (`Anwaltsrevue 8/2020 S. 315`,
  `Revue de l'Arbitrage, 2008, S. 768`).
- **`§` in a textbook citation** (`KOLLER, § 6 Rz. 179`) is BARE_ARTICLE.
- **`Art. 117 GOG/ZH`** and similar cantonal codes are OTHER_LAW even where batch 1 had labelled
  them STATUTE under v0.1; the one such span was relabelled in adjudication.

### Clarifications from batch 3 (2026-10-25, adjudication of the first 100 decisions)

- A bracketed correction or year **inside** a reference stays inside the span:
  `Art. 233 [recte: 232] Abs. 2 ZPO` (STATUTE), `Art. 16 Abs. 2 [recte: 3] AVB`
  (CONTRACT_ARTICLE), `ZBJV 147 [2011], S. 551`, `Pra 107 [2018] Nr. 86`,
  `Entscheidungen des Bundesgerichtshofes in Zivilsachen [BGHZ] 185 133` (JOURNAL_REF).
  Brackets **around** a reference or **after** it stay outside.
- A bracketed remark that is not part of the reference breaks a chain:
  `Art. 42 Abs. 2 und (in Bezug auf ...) Art. 106 Abs. 2 BGG` is BARE_ARTICLE `Art. 42 Abs. 2`
  plus STATUTE `Art. 106 Abs. 2 BGG`. A STATUTE span always contains its code.
- A bare `mit` is not a chain joiner: `N. 77 zu Art. 134 mit Art. 315a/b ZGB` is BARE_ARTICLE
  `Art. 134` plus STATUTE `Art. 315a/b ZGB`.
- A currency word in another language is a currency token: `15 million dollars`,
  `DM 300'000.--`, `JPY 3'091'220'814.--`, `R$ 84'894.--`, `RUB 2.95 Mio.` are AMOUNT. An
  exchange rate (`CHF 1.1114`, `DM 1,95583`) is not a sum and gets no span.
- A yearbook (`Jahrbuch zum Strassenverkehrsrecht 2011, S. 111`) and an administrative case
  collection (`VPB 64/2000 Nr. 134`, `BGHZ 99 274`) count as JOURNAL_REF. Conference volumes
  (`Baurechtstagung 2019, S. 169`) and anthologies (`Aktuelle Anwaltspraxis 2007, S. 26`) are
  books: no span. A journal cited by date and margin number only (`Jusletter vom 7. November
  2011, Rz. 10`) has no page or number: no span.
- The instrument of a CONTRACT_ARTICLE may follow with a preposition: `Ziff. 1, 4 und 5 in den
  AVB`. Quote marks around an instrument name are part of the name: both quotes inside the span
  (`Art. 14 der einschlägigen "Allgemeinen Vertragsbedingungen"`). A year that belongs to the
  instrument name stays (`Zusätzlichen Versicherungsbedingungen 2014`). The clause-chain rule of
  STATUTE applies to CONTRACT_ARTICLE (`Ziff. 3.4 i.V.m. Ziff. 7.1 ZVB` is one span).
- A clause heading inside a quoted contract (`"§ 14 Maklercourtage ..."`) is a label, not a
  reference: no span.
- A typo that still names a known federal code is labelled as written (`Art. 99 BBG`, item 9);
  a typo inside a file number keeps the DOCKET span (`4A_540/2 019`, `5F_37 /2020`); a decision's
  own number written with a typo is still its own number (no span). An earlier file number of
  the same proceeding after renumbering is the own number too.
- Ratified treaties with an SR number are STATUTE even when the pre-annotator says OTHER_LAW:
  `CISG`, `KRK`, `LugÜ`, `aLugÜ`, `LugÜ 1988`. A qualifier between number and abbreviation
  stays inside the span: `§ 732 dt. ZPO` (OTHER_LAW), `Art. 57 rev. LugÜ` (STATUTE). A
  repealed federal act (`Art. 8 NAG`) is STATUTE. A cantonal abbreviation without a canton
  suffix is OTHER_LAW when the text defines it as cantonal (`GerG`, `VRPG`).
- A BARE_ARTICLE chain (act given as a title) follows the STATUTE chain rule: one span when one
  title follows (`Art. 10 Abs. 1, Art. 12 Abs. 1 und Art. 13 Abs. 1` of the HKsÜ), one span per
  article when the court omits the code (`Art. 74 Abs. 1 Bst. b` and `Art. 51 Abs. 1 und 4`).
- Outcome: a granted Eventualbegehren with annulment and remand is `approved`; the nominal
  form `In teilweiser Gutheissung` is `partial_approval`; `nicht eingetreten, soweit nicht
  gegenstandslos` is `inadmissible`; a Fristwiederherstellungsgesuch in item 1 is a side request.
- From the second half of batch 3: `und/oder` and `wie auch` are chain joiners; a treaty named
  by a short title that is not a Fedlex abbreviation (`Vollstreckungsabkommen CH/FL`) follows
  the title rule (BARE_ARTICLE); an online newsletter or Jusletter cited with a page is
  JOURNAL_REF; a German law with a country suffix keeps it (`§ 133 BGB/D`); `dZPO`, `EuGVVO`,
  `Brüssel I-VO` are abbreviations (OTHER_LAW); `in fine` stays inside a STATUTE span; a
  federal ordinance cited by its abbreviation (`GebV SchKG`) is STATUTE; an association's or
  foundation's regulation or statutes without an SR number is a private instrument; a contract
  annex named after the clause (`Ziffer 14 Anlage 1`) counts as the instrument; paragraphs of
  an ECtHR judgment (`§ 193`) are points of a court document: no span; `Millionen` written out
  is a multiplier inside an AMOUNT.

### What is still not a span
Bare numbers, `Art.` without a number, SR numbers alone (`SR 823.11`), and the title of an act
or a journal article are not spans. A reference inside text that the court quotes from a party
is labelled like any other (this matches the citation gold of both batches). When a reference
fits none of the nine classes, leave it.
