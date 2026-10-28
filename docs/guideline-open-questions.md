# Open questions for annotation guideline v0.2 / v0.3

**2026-10-23: Denis accepted every proposed rule in this file.** The decisions are guideline v0.3
(`docs/annotation-guideline.md`), applied to both batches in round `v3`. Items 1, 6 and 17
change the gold set; the rest were already applied or are clarifications.

Collected from the 18 labelling agents' reports on batch 2 (2026-10-21). Batch 1 and batch 2
were labelled under guideline v0.1, so every rule below was applied the v0.1 way in both
batches. A decision on each item changes the gold set and must be applied to both batches with
the same toolchain, after which every extractor is re-scored.

| # | Question | How v0.1 was applied | Occurrences in batch 2 | Proposed v0.2 rule |
|---|---|---|---|---|
| 1 | Same-volume short citations: `BGE 140 III 86 E. 2, 115 E. 2`. Is `115` a citation of BGE 140 III 115? | No span (the guideline example calls it a second page number). The agents noted in at least 20 decisions that it is in fact a different decision. | about 20 decisions | **Yes, label `115` as BGE.** It is a separate decision and the citation graph needs it. Needs a regex rule and a relabel pass over both batches. |
| 2 | Side request not in the list: `Fristwiederherstellungsgesuch` (restoration of a time limit) in item 1. | Agents skipped it by analogy and read item 2. Regex v0.2 read item 1 (one outcome error). | 1 | Add to the side-request list (guideline and regex). |
| 3 | Ruling header without `Demnach`: `Das Bundesgericht erkennt:`. | Agents read it as the header. Regex v0.2 returned `unknown` (one outcome error). | 1 | Add to the header pattern. |
| 4 | Decimal comma inside an amount: `Fr. 2,3 Mio.`, `CHF 5,5 Mio.`. | Agents labelled the full amount. Regex v0.2 stopped at the comma. | 2 decisions | Allow `,\d+` before `Mio.`/`Mrd.` in the regex. The guideline already covers it. |
| 5 | `Art` without the dot (`Art 113 BGG`, `Art 271 Abs. 1 Ziff. 2 SchKG`) and `Art. 17SchKG` (missing space). | Labelled as STATUTE (the citation is complete). | 3 | Keep: label as written when the article and a known abbreviation are present. Regex: make the dot and the space optional. |
| 6 | `Artikel 104 BGG`, `Artikeln 35a und 35b VVG` (word written out). | No span (the rule starts at `Art.`). | 2 | **Label it.** Same citation, different spelling. Regex: accept `Artikel(n)?`. |
| 7 | Full title with the abbreviation in brackets: `Art. 19 des Bundesgesetzes ... (AVG; SR 823.11)`. | No span. | 4 | **Decided in v0.2 (2026-10-23):** `Art. 19` becomes a BARE_ARTICLE span (negative class); the citation span stays absent. |
| 8 | Articles of contract terms or general insurance conditions: `Art. 13 Ziff. 2 lit. a AVB`, `Art. 3 Abs. 1 AB`. | No span (not a law). The regex also skips them because `AVB`/`AB` are not Fedlex abbreviations. | 3 decisions | **Decided in v0.2 (2026-10-23):** CONTRACT_ARTICLE span (negative class). |
| 9 | Typos in the source: `BGE 142 IIII 758`, `BGE 140 II 86` (for III), `Art. 90 BG` (for BGG), `Art. 47 Abs. 2 BGG` (for BGBB), `4A_174/ 2019`. | Labelled as written when the abbreviation is a known code; `Art. 90 BG` dropped in adjudication. | 6 | Keep: label as written when the abbreviation is a known code; otherwise no span. The citation graph step may record a resolution note. |
| 10 | `Bst.` as the variant of `lit.` and chains such as `Art. 271a Abs. 1 lit. e i.V.m. Abs. 2 OR` (second element has no `Art.`). | Labelled as one span. Regex v0.2 breaks the chain at `und Abs.` / `i.V.m. Abs.`. | 3 decisions, 8 spans | Guideline already implies one span. Regex: allow `Abs.` as a chain element after a separator. |
| 11 | Treaty abbreviation with a year: `Art. 56 EPÜ 2000`. | Labelled with the year. | 1 decision, 3 spans | Keep the year. Note (2026-10-23): Fedlex lists the abbreviation *with* the year (`EPÜ 2000`); the regex and the linker now look the full form up first. |
| 12 | Courts or authorities listed with a role word (`Beschwerdegegner` for the Obergericht). | Labelled (the rule covers the header block without exception). | 2 | Keep. |
| 13 | Two appeals with different results in one ruling. | First item that rules on an appeal. | 1 | Keep, and record the second result in a comment. |
| 14 | Broken tokens from text extraction: `F r. 30'000.00`, `Fr. 30'0 00.00`. | Kept in adjudication (the amount is stated). | 1 | Keep. The learned extractors should be robust to this; the regex is not. |
| 15 | Old-format numbers of the former Federal Insurance Court: `I 302/96`. | Labelled as DOCKET. | 1 | Keep (the court cites it as its own judgment). |
| 16 | A statute citation in the metadata line before the formal header (`Art. 17SchKG`). | Labelled. | 1 | Keep: the whole text is in scope. |

Items 1 and 6 change the gold set materially and were decided on 2026-10-23 (v0.3). Items 2 to 5 and 10 are regex
fixes that do not change the gold set (done in v0.3). Items 7 and 8 are settled by the negative
classes of guideline v0.2. The rest are clarifications.

Guideline v0.2 (2026-10-23) added four negative classes, CONTRACT_ARTICLE, BARE_ARTICLE,
OTHER_LAW and JOURNAL_REF, without touching the five citation classes. See the guideline.

## Raised by the v0.2 relabel round (2026-10-23)

| # | Question | Decision in v0.2 |
|---|---|---|
| 17 | Spelled-out `Ziffer`/`Artikel` for the negative classes (`Ziffer 9 des Vertrags`, `Artikel 17 der Vereinbarung`; about 30 occurrences in 4 decisions). | v0.2: no span. **v0.3: spans**, together with item 6. |
| 18 | Court-approved settlements, self-regulation agreements (`VSB 2020`), collective tariffs (`GT 9 VI`): private instruments? | Yes, CONTRACT_ARTICLE (clarification in the guideline). |
| 19 | Draft acts (`Art. 93 VE-ZPO`). | No span. |
| 20 | Official gazettes (`BBl`, `AS`, `AB`). | No span. |
| 21 | A ratified treaty given as a title (`Art. 8 des Übereinkommens ... (KRK)`). | BARE_ARTICLE, like every act given as a title. |
| 22 | `Art. 117 GOG/ZH` labelled STATUTE in batch 1 under v0.1. | Relabelled OTHER_LAW in the v0.2 adjudication (one span). |
| 23 | The first v0.2 draft excluded references inside quoted party text; the citation gold labels them. | The sentence was removed; references inside quotes are labelled like any other. |

The agents also listed citation-gold typos that follow the source text (`BGE 142 IIII 758`,
`140 IIII 264`, `Art. 47 Abs. 2 BGG` for BGBB, `Art. 308 BGG` for ZGB, `Art. 74 Abs. 1 Bst. b
ZGB` for BGG, `BGE 140 III 15`). Item 9 covers them: label as written.
