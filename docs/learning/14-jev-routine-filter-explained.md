# The routine filter: what Jev 1.14 was tested on, and why the regex looks for "BGG"

This note answers two questions that an outsider asks about the Jev 1.14 pilot of 2026-11-05. The full results are in `docs/jev-treatment.md`. The labels and rules are in `docs/citation-treatment-guideline.md`.

## 1. What was Jev 1.14 tested on?

Jev 1.14 was tested on citations of earlier court decisions, not on citations of law articles.

### Short explanation for an outsider

> Swiss Federal Supreme Court decisions cite two kinds of sources: articles of laws, such as "Art. 42 BGG", and earlier court decisions, such as "BGE 140 III 86". We tested the model only on citations of earlier court decisions.
>
> For each citation, the model saw about 600 characters of the surrounding text. It had to answer one question: why does the court cite this decision here? About 60% of these citations are routine. The court repeats the same standard paragraph in almost every judgment, for example on how an appeal must be argued. The other 40% matter more. There the court uses the earlier decision as authority on the legal question in dispute.
>
> We labelled 450 such citations and compared the model with these labels. On a final set of 150 new citations, each one that the model called routine was really routine (68 of 68). The model found about 82% of all routine citations.
>
> We did not test citations of law articles. That is a separate test.

### An example of each kind

- **Routine:** "In der Beschwerde ist in gedrängter Form darzulegen, inwiefern der angefochtene Akt Recht verletzt (BGE 140 III 86 E. 2)." The court cites the same decision in hundreds of judgments only to restate how an appeal must be argued.
- **Substantive:** "Glaubhaft gemacht ist eine Tatsache dann, wenn für deren Vorhandensein gewisse Elemente sprechen (BGE 138 III 232 E. 4.1.1)." Here the court uses the decision to define the legal standard in the dispute about an asset freeze.

### Caveats

- **The model wrote the labels.** Claude (`claude-opus-5-5`) wrote the 450 labels, not a lawyer, and no human checked them. An outsider should hear this.
- **The sample is small.** "68 of 68" means that the precision is probably above 95%. The lower end of the 95% interval is 0.947. It does not mean that the model never makes a mistake.

## 2. If only decision citations were tested, why was the regex based on "BGG"?

The regex does not look at the citation itself. It looks at the text around a decision citation. "BGG" in that text is a sign that the paragraph is about the procedure before the Federal Supreme Court.

### Why "BGG" is a good cue

Routine paragraphs usually name a BGG article and an earlier decision side by side. An example from the test windows:

> "In der Beschwerde ist in gedrängter Form darzulegen, inwiefern der angefochtene Akt Recht verletzt (Art. 42 Abs. 2 BGG; BGE 140 III 86 E. 2)."

The labelled citation is `BGE 140 III 86`. The regex marks it as routine because "Art. 42 Abs. 2 BGG" is in the same window. The BGG is the law on the procedure before the Federal Supreme Court, so its articles appear mostly in routine paragraphs. Substantive paragraphs usually cite other laws, such as the ZGB, the OR or the SchKG.

### Why it was used

The pilot needed a free and simple baseline to compare against Jev 1.14. A model is worth its cost only if it is better than such a rule. The regex was fixed before any model ran. It was one of two baselines, together with the majority class.

### What it means

- **For the test:** All the labelled items were decision citations. The regex was only a different way to classify them, based on the surrounding text.
- **For statute citations:** The same regex would not work. A citation of a BGG article always has "BGG" in its window, so the regex would mark all of them as routine.
- **For the selector:** The user decided on 2026-11-06 to use Jev 1.14 only, not the regex (`docs/plan-routine-selector.md`).

### Caveat

The labeller may have used "BGG" in the window as a cue. If so, the regex scores are too high. No human checked the labels, so this cannot be ruled out.

## Numbers at hand

| Rule for "routine", 150 new random windows | Marked | Precision | Recall |
|---|---|---|---|
| Jev 1.14 predicts `routine_standard` | 68 | 1.000 | 0.819 |
| The window contains "BGG" | 67 | 1.000 | 0.807 |

- Statute citations in the corpus: 138,143. Of these, 81,806 (59%) cite the BGG.
- Decision citations in the corpus (BGE and file numbers): 111,619. Labelling all of them with Jev 1.14 costs about USD 5.40.
