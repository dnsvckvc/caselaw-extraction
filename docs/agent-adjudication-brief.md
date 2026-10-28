# Brief for adjudication agents (gold set)

Two annotators (pass a and pass c; the pass names are given in your assignment) corrected the same decisions independently. Spans they both
produced are already accepted. You decide the spans only one of them produced, and the outcome
when they disagree. Work in `/Users/dnsvckvc/dev/harness/job-chances/caselaw-extraction`.
Write only to `data/gold/<batch>/edits/adj/`.

Every command below needs `GOLD_BATCH=<batch> GOLD_PASSES=<pass1>,<pass2>` in front of it, for
example `GOLD_BATCH=batch2 GOLD_PASSES=a,c uv run python scripts/gold/agreement.py bger_4A_1_2024`.

## Workflow for each decision

1. `GOLD_BATCH=<batch> GOLD_PASSES=<p1>,<p2> uv run python scripts/gold/agreement.py <decision_id>` prints the dispute record:
   `outcome_a`, `outcome_b` (b here means the second pass), comments, and a `disputed` list. Each disputed item has an `id`
   (`a1`, `b3`, ...), a `label`, the span `text`, and 60 characters of context on each side.
2. If the context is not enough, `GOLD_BATCH=<batch> uv run python scripts/gold/render_task.py <task_index>` prints
   the full decision with the original pre-annotations.
3. Apply the rules in `docs/agent-labelling-brief.md` (section "The rules") to each disputed
   item. Keep it if it is a correct span under the rules. Drop it otherwise. Typical cases:
   - Two overlapping versions of one citation (one annotator extended a chain, the other did not):
     keep the one with the correct boundaries, drop the other.
   - A span only one annotator found (for example `1'200 Franken` or a `BGE` list item): keep it
     if it is correct.
   - A `PARTY_ROLE` in the body text or a `DOCKET` that is the decision's own number: drop.
4. Write `data/gold/<batch>/edits/adj/<decision_id>.json`:

```json
{"keep": ["a1", "b3"], "outcome": "dismissed", "comment": "a2 dropped: own docket number"}
```

   `outcome` is required only when `outcome_a` and `outcome_b` differ; then read item 1 of the
   dispositiv yourself and decide. Use a Python heredoc with `json.dump` to write the file.
5. `GOLD_BATCH=<batch> GOLD_PASSES=<p1>,<p2> uv run python scripts/gold/finalize.py --check <decision_id>` must print `OK`. If it reports
   overlapping kept spans, you kept two versions of the same citation; drop one.

## Report

One line per decision: decision_id, number kept / number disputed, outcome decision if any, and
the rule you applied for anything non-obvious.
