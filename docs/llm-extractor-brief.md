# Brief for the LLM extractor (structured output, no pre-annotations)

You extract citations and the outcome from Swiss Federal Supreme Court decisions written in
German. Work in `/Users/dnsvckvc/dev/harness/job-chances/caselaw-extraction`. You get plain text
only. Nothing is pre-marked. Write only to `data/pred/<batch>/llm_raw/<model>/`. Do not open
`data/gold/`, `docs/annotation-guideline.md`, `docs/agent-labelling-brief.md` or anything under
`src/`. Your assignment names the batch, the model tag and the decision indices.

## Procedure per decision

1. `uv run python scripts/llm/render_decision.py <batch> <N>` prints the decision and its
   `decision_id`.
2. Read it once from top to bottom and produce the JSON object described below. List every
   occurrence of every citation in the order in which it appears in the text.
3. Write the object to `data/pred/<batch>/llm_raw/<model>/<decision_id>.json` with
   `json.dump` from Python (no raw line breaks inside strings).
4. `uv run python scripts/llm/apply_output.py <batch> <N> <model>` maps your texts onto the
   decision. It prints `OK` or `CHECK` with a list of texts it could not find. Fix typos in your
   own copy of a text and run it again. If a text really is not in the decision, remove it.

## Output schema

```json
{
  "outcome": "dismissed",
  "citations": [
    {"label": "STATUTE", "text": "Art. 42 Abs. 2 BGG"},
    {"label": "BGE", "text": "BGE 140 III 86"},
    {"label": "BGE", "text": "139 III 133"},
    {"label": "DOCKET", "text": "4A_437/2018"},
    {"label": "AMOUNT", "text": "Fr. 1'387.--"},
    {"label": "PARTY_ROLE", "text": "Beschwerdeführerin"}
  ]
}
```

`outcome` is one of `approved`, `partial_approval`, `dismissed`, `inadmissible`, `moot`,
`consolidated`, `unknown`.

## What each label means

Give the citation key exactly as the text writes it, character for character, without the
words around it, without considerations (`E. 2.1`), page references (`S. 88`), dates, brackets or
the sentence's full stop.

- **STATUTE**: a reference to an article of a Swiss federal act, ordinance or treaty that ends
  with the act's abbreviation: `Art. 42 Abs. 1 BGG`, `aArt. 139 Ziff. 2 StGB`,
  `Art. 97 Abs. 1 lit. a OR`, `Art. 6 Ziff. 1 EMRK`, `Art. 319 ff. ZPO`, `Art. 113-119 BGG`.
  When several articles are followed by one abbreviation, the whole group is one text:
  `Art. 95 und 96 BGG`, `Art. 42 Abs. 2 und Art. 106 Abs. 2 BGG`,
  `Art. 97 Abs. 1 i.V.m. Art. 105 Abs. 2 BGG`. When each article has its own abbreviation,
  each is its own text. Do not include `§` references, articles of cantonal law, articles of a
  contract or of general insurance conditions, or an article whose act is named in full words
  instead of an abbreviation.
- **BGE**: a published leading decision: `BGE 140 III 86`. Inside a list such as
  `BGE 140 III 86 E. 2; 139 III 133 E. 1.1` the second item `139 III 133` is its own text even
  though the word `BGE` is not repeated. A bare page number after a comma that belongs to the
  same volume and part followed by `E.` (`BGE 140 III 86 E. 2, 115 E. 2`) **is** a text: `115`
  (guideline v0.3). A number after `S.` is a page, not a text.
- **DOCKET**: the file number of another Federal Supreme Court case: `4A_437/2018`,
  `5A_12/2020`, `4C.195/2005`, `2C_1/2019`, `B.101/1991`. Not the number of the decision you
  are reading (it stands in its header and may be repeated in the body), and not cantonal or
  foreign file numbers.
- **AMOUNT**: a sum of money with its currency: `Fr. 1'387.--`, `CHF 12'500.50`, `1'200 Franken`,
  `EUR 300`, `Fr. 50 Mio.`. Not percentages, not bare numbers, not `Fr.` without a number.
- **PARTY_ROLE**: the role word of each party in the header block that lists the parties
  (between `Verfahrensbeteiligte` or `Parteien` and `Gegenstand`): `Beschwerdeführer`,
  `Beschwerdeführerin`, `Beschwerdegegner`, `Beschwerdegegnerin`, `Gesuchsteller`, `Klägerin`,
  `Beklagter`, `Nebenintervenient` and the like. Each distinct role word once. Role words in
  the body of the decision are not texts.

## Outcome

Go to the last ruling header (`Demnach erkennt das Bundesgericht:`, `... erkennt die
Präsidentin:`, `Demnach verfügt ...:`, `Das Bundesgericht erkennt:`). Take the first numbered item
that rules on the appeal itself. Skip items that only decide a side matter (joining of cases,
suspension, recusal, legal aid, suspensive effect, restoration of a time limit).

- `gutgeheissen` → `approved`; `teilweise gutgeheissen` → `partial_approval`
- a ruling that sets the lower judgment aside and sends the case back → `approved`
- `abgewiesen`, also `abgewiesen, soweit darauf einzutreten ist` → `dismissed`
- `nicht eingetreten` → `inadmissible`
- `abgeschrieben`, `gegenstandslos` → `moot`
- several appeals with different results → the first one
- no ruling section → `unknown`

## Report

One line per decision: index, decision_id, number of citations listed, the `apply_output.py`
status line, and any case where you were unsure.
