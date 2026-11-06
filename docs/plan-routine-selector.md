# Plan: selector to hide routine citations (API, then caselaw-explorer)

Status: steps 1 to 5 are built and committed (2026-11-06). The full labelling run is done: 111,619 citations, 52,159 routine (46.7%), USD 5.43, no errors. `caselaw graph` wrote both variants (`no_routine` keeps 44,772 of 86,365 edges). The deploy (step 6) is open. Rewritten 2026-11-06. Decision of the user on 2026-11-06: Jev 1.14 is the only source of the routine label. The "BGG" regex is not used.

Evidence: `docs/jev-treatment.md`. On 150 new random windows, every `routine_standard` prediction of Jev 1.14 was right (68 of 68, lower 95% bound 0.947). Jev 1.14 found 82% of the routine citations.

## Goal

An API client chooses whether citations of routine standard text count. Examples of such text are the arbitrariness test, the duty to give reasons and the review of facts. The default stays as now: all citations count. With `routine=exclude`, a route ignores every citation that Jev 1.14 labelled `routine_standard`.

## Rules

- A citation is routine if and only if its label is `routine_standard`, at any probability.
- A citation without a label counts as not routine. Examples are new decisions before the next batch and citations where the call failed.
- The API never calls the other citations "substantive". The docs say "not labelled routine".
- Phase 1 labels `bge` and `docket` citations only. Statute citations are phase 2 (see below).

## Step 1: labelling job (offline)

1. Move the prompt, the label descriptions and `call_jev` from `scripts/jev/treatment.py` to a new module `src/caselaw_extraction/treatment.py`. The prompt stays frozen (prompt 2).
2. Add a CLI command `caselaw treatment --run regex-v0.4`. It builds the same window as the pilot (400 characters before, 200 after, citation in `[[ ]]`) for each `bge` and `docket` citation.
3. The command writes `data/runs/<run>/treatment.jsonl` as it goes, so a stopped run can resume. At the end it writes `data/runs/<run>/treatment.parquet`.
4. Columns: `span_id`, `label`, `p` (top probability), `probabilities` (JSON), `model` (the snapshot, `typesafe/jev-1.14-20261014`), `labelled_at`.
5. Keep a spending cap (default USD 8) and 8 workers. Expected cost for 111,619 citations: about USD 5.40.
6. Add a Makefile target `treatment`. The user runs it under `op run` in their own terminal.

## Step 2: storage

1. Add a new table to `src/caselaw_extraction/sql/schema.sql`. A separate table keeps `citation` unchanged, and labels can arrive later than the run.

   ```sql
   CREATE TABLE IF NOT EXISTS citation_treatment (
       run_id   text NOT NULL REFERENCES extraction_run(run_id) ON DELETE CASCADE,
       span_id  text NOT NULL,
       label    text NOT NULL,
       p        double precision,
       model    text NOT NULL,
       PRIMARY KEY (run_id, span_id)
   );
   ```

2. Add `citation_treatment` to `_LOADS` in `db.py`. It is optional: if `treatment.parquet` is missing, `db-load` skips it.
3. In `DuckDBStore` (`store.py`), map `citation_treatment` to `treatment.parquet`. If the file is missing, create an empty view, as for `decision_text`. The SQL then works with and without labels.
4. Add a column `variant` to `centrality` (`all` or `no_routine`) and add it to the primary key. Existing rows get `all`.

## Step 3: graph

1. `graph.build_graph(store, exclude_routine=False)`: with `True`, skip edges whose citation span is labelled routine.
2. An edge stays if at least one citation from decision A to node B is not routine. Only fully routine pairs disappear.
3. `caselaw graph` writes both variants to `centrality.parquet`. PageRank is never computed per request.

## Step 4: API (`src/caselaw_extraction/api.py`)

Add one query parameter to the routes below, with the same definition each time:

```python
Routine = Query("include", pattern="^(include|exclude)$",
                description="exclude: ignore citations that Jev 1.14 labelled routine_standard")
```

Add one SQL helper, so that every route uses the same condition:

```python
def _not_routine(alias: str = "c") -> str:
    return (f"NOT EXISTS (SELECT 1 FROM citation_treatment t WHERE t.run_id = {alias}.run_id "
            f"AND t.span_id = {alias}.span_id AND t.label = 'routine_standard')")
```

| Route | Change with `routine=exclude` |
|---|---|
| `/decisions/central` | Read the `no_routine` variant of `centrality`. |
| `/graph/neighbors` | Leave out routine edges in `cites` and `cited_by`. Read degree and PageRank from the `no_routine` variant. |
| `/decisions` | The `bge` and `docket` filters match only non-routine citations (`_decision_where`). |
| `/decisions/facets` | Same as `/decisions`, through `_decision_where`. |
| `/trends/years` | Count only non-routine `bge` and `docket` citations in `bge_per_decision`, `docket_per_decision`, `distinct_bge` and `mean_bge_age`. |
| `/decisions/{id}` | No parameter. Every citation gets two new fields, `treatment` and `treatment_p` (null for statutes and unlabelled citations). The client decides how to show them. |
| `/runs` | New fields: `treatment_model`, `labelled_share` and `routine_share`, so a client can see how much `exclude` removes. |

Routes without the parameter in phase 1: `/statutes/top`, `/statutes/codes`, `/trends/code-share`. They count statute citations only, and these have no labels yet. `/drift` and `/drift/series` stay unchanged, because they monitor the extractor and not the reading of the law.

Further changes:

- Add `routine` to every `cached(...)` key.
- In `warm_cache`, also warm `/decisions/central` with the `no_routine` variant.
- Raise `API_VERSION` to `0.2.0`. The default `include` keeps every current response the same.
- Add an index: `CREATE INDEX citation_span_idx ON citation (run_id, span_id)` if the joins are slow on the Hetzner server.

## Step 5: tests (`tests/test_api.py`, `tests/test_graph.py`, `tests/test_db.py`)

1. Without `routine`, and with `routine=include`, every route returns exactly what it returns now.
2. A fixture run has one citation labelled `routine_standard`. With `routine=exclude`, `/decisions?bge=...` no longer finds the decision that only cites it routinely.
3. The `no_routine` centrality variant loses the edge, and `/decisions/central?routine=exclude` reads it.
4. A run without `treatment.parquet` works with both values, and `exclude` then changes nothing.
5. `/decisions/{id}` returns `treatment` and `treatment_p`.

## Step 6: deploy

Warning: the new API code reads `centrality.variant` and `citation_treatment`, so it fails on a database without the new schema. On Hetzner, `hz-load` runs the loader inside the API image, so the new image must be deployed first. Keep the gap between `hz-deploy` and `hz-load` short. The API starts anyway, because a failed cache warm-up does not stop it. `/decisions/central?routine=exclude` returns an empty list until `caselaw graph` has written the `no_routine` variant.

1. Run `make treatment` locally (user terminal, `op run`). `LIMIT=200` makes a trial run first.
2. Run `caselaw graph` again to write both centrality variants.
3. `make hz-sync RUN=regex-v0.4` copies `treatment.parquet` and the new `centrality.parquet` to the server.
4. `make hz-deploy` builds the new image and starts the new API. `hz-load` runs the loader inside this image, so the deploy must come before the load. Until the load ends, `/runs` and the graph routes return errors.
5. `make hz-load RUN=regex-v0.4` migrates the schema and replaces the run in one transaction.
6. `make hz-restart` warms the cache again, then `make hz-smoke`.
7. Check `GET /runs` on the live API: `labelled_share` should be 1.0 and `routine_share` about 0.47.

## Phase 2: statute citations

Statute citations are 138,143 of the citations, and 59% of them cite the BGG. The pilot did not test Jev 1.14 on statute citations. Before Jev 1.14 labels them:

1. Draw 150 random statute windows and label them before any model runs.
2. Run Jev 1.14 with the frozen prompt 2. Pass rule: routine precision ≥ 0.95.
3. If it passes, label all statute citations (about USD 7) and add the parameter to `/statutes/top`, `/statutes/codes` and `/trends/code-share`.

## Phase 3: caselaw-explorer

- One toggle in the header, "Hide routine citations", stored in the URL as `?routine=exclude`. `src/api.ts` passes it to the routes of step 4.
- Decision page: show all citations and mark routine ones in grey, with `treatment_p` in a tooltip.
- A short note next to the toggle: a model wrote the labels, and about 1 in 5 routine citations stays visible.
- API map page (`src/endpoints.ts`): document the parameter.

## Risks

- `typesafe/jev-1.14` is on an alpha endpoint. If it changes or stops, new decisions stay unlabelled. `exclude` then removes less, but no route breaks. `/runs` shows the drop in `labelled_share`.
- A new snapshot needs the 150 `confirm` windows again before it replaces the pinned one.
- The gold labels came from a model, and no human checked them (`docs/jev-treatment.md`).

## Built on 2026-11-06 (steps 1 to 5)

- `src/caselaw_extraction/treatment.py`: prompt 2 (moved from `scripts/jev/treatment.py`, which now imports it), `window`, `call_jev`, `citation_windows`, `label_run`, `write_parquet`. `label_run` stops when an answer comes from another snapshot than `typesafe/jev-1.14-20261014`.
- `caselaw treatment` and `make treatment` (`LIMIT=` for a trial). The real run has 111,619 windows. All 450 pilot windows are identical to the windows the job builds.
- Schema: `citation_treatment`, `centrality.variant` with a migration for existing databases, index `citation_span_idx`. The loader and `DuckDBStore` accept run folders without `treatment.parquet` and old `centrality.parquet` files without `variant`.
- `graph.not_routine()` is the one SQL condition. `caselaw graph` writes both variants.
- API 0.2.0: `routine=include|exclude` on `/decisions`, `/decisions/facets`, `/decisions/central`, `/graph/neighbors`, `/trends/years`. `/decisions/{id}` returns `treatment` and `treatment_p`. `/runs` returns `treatment_model`, `labelled_share`, `routine_share` and now carries a cache header.
- Tests: `tests/test_treatment.py` (new) and `test_routine_selector` in `tests/test_api.py`. The synthetic run is labelled by `fake_jev` in `tests/conftest.py`. 105 tests pass.
