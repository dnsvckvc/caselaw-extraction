# Citation treatment: label guideline (v0.2, 2026-11-05; rule 4 added while labelling, before any model ran)

Subproject 2 of the Jev pilot. One label per citation of a BGE or a file number. The citation is marked `[[...]]` in a
window of 400 characters before and 200 characters after. Label only what the window shows, from the point of view of
the Federal Supreme Court writing this decision.

| Label | Use it when |
|---|---|
| `routine_standard` | The court's own standard text on how an appeal to it works: admissibility, duty to give reasons, `Rügeprinzip`, review of facts, arbitrariness formula, costs and party compensation before it. The rule would fit almost any appeal, even when applied to this appeal. |
| `substantive_rule` | The court's own reasoning cites it as authority for a rule on the legal question in dispute. This includes civil procedure and debt collection rules that the lower court had to apply. |
| `party_or_lower_court` | The citation reports what a party, the lower court or another body said or relied on, without the court adopting it in this sentence. |
| `negative_treatment` | The court distinguishes, limits, questions, departs from or changes the cited decision, says it does not apply here, or leaves open whether it still holds. Saying that a lower court departed from it is `substantive_rule`: the cited decision is still good law. |
| `case_history` | The citation names an earlier decision in this same dispute or the decision under review, for example the judgment subject to revision or an earlier remand. |

Rules for conflicts:

1. `case_history` goes first: a decision in this dispute is history even when its rule is applied.
2. `party_or_lower_court` applies only when attribution is visible in the window. A later sentence that adopts the rule does not change the label of a citation inside the party's statement.
3. A citation in a list takes the label of the statement the list supports.
4. If a party or a lower court invokes the citation and the court says in the window that it does not help or does not apply, use `negative_treatment`. If a lower court itself says this and the Federal Supreme Court only reports it, use `party_or_lower_court`.
5. If the window does not allow a decision, use `unclear`. These windows are counted and left out of the scores. The models do not get this option.

## Pass rules, fixed before any model ran (2026-11-05)

All on the test windows, without `unclear`. Labels: Claude Opus 5.5, blind to both models; a human spot check is still open.

1. Jev 1.14 accuracy is no more than 0.03 below Haiku 5.5, over all test windows.
2. On the random stratum, Jev 1.14 reaches `routine_binary_f1` of at least 0.90 and beats the majority baseline on `routine_binary_accuracy`.
3. `negative_treatment` has only 5 windows in all, so no conclusion is drawn on this class.

Calibration, per-class results and cost are reported in any case. The prompt may change only on the 60 dev windows, once per error pattern.

### Prompt change on dev (2026-11-05)

Prompt 1 on 54 dev windows: Jev 1.14 accuracy 0.815, Haiku 5.5 accuracy 0.833. Both models labelled routine text about the procedure before the Federal Supreme Court (Art. 90 ff. BGG, Rechtsbegehren, Revision, review of Ermessen and Beweiswürdigung) as `substantive_rule`. Jev 1.14 made this error 10 times, Haiku 5.5 8 times. I added these topics to `routine_standard` and excluded them from `substantive_rule`. Both models get the same text. The prompt-1 results are in `data/pred/treatment/*-dev-prompt1.jsonl`.

### Prompt 2 on dev and frozen settings (2026-11-05)

Prompt 2 on 59 dev windows: Jev 1.14 accuracy 0.983. Haiku 5.5 answered 58 of 59 windows and was right on 55. Haiku 5.5 sometimes used all 50 output tokens on hidden reasoning and sent no label. I set `max_tokens` to 200 and `reasoning.enabled` to false for Haiku 5.5. The prompt is now frozen. On test, a window without an answer after three runs counts as wrong for that model. The prompt was fitted to these dev windows, so the dev accuracy is optimistic.

### Confirmation of the routine filter, fixed before the run (2026-11-05)

150 new random windows, part `confirm`, from decisions that the first 300 windows did not use. I labelled them before any model ran: routine 83, substantive 56, case history 7, negative 2, unclear 2. Only Jev 1.14 runs, with the frozen prompt 2. Pass rule: the precision of every `routine_standard` prediction, at any probability, is at least 0.95. Recall is reported, with no pass rule.
