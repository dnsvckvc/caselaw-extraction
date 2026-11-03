# Dask and the full-corpus run: what it does, how we use it, what we learned

This note explains the run that sends every decision of the corpus through one extractor and
the linking stage. It is written for someone who would build the same thing by hand and wants
to understand each piece before copying it. The code is `src/caselaw_extraction/corpus_run.py`.
The commands are `caselaw run-corpus` and `caselaw demo` in `src/caselaw_extraction/cli.py`.
The report discusses the run in section 7 of `docs/report.md`.

## 1. The problem the corpus run solves

The corpus holds 7,999 decisions in one Parquet file, `data/interim/bger_de_zivil_2020.parquet`.
Weeks 1 and 2 scored the extractors on 350 gold decisions. Week 3 needed every decision: the
citation graph needs every edge, the three analyses count over the whole corpus, and the API
serves any decision.

The run must also be the same for every extractor. The posting that this project answers
names Dask for corpus-wide extraction, so the portfolio plan uses Dask for the regex. Section
7.1 of the report adds the real target: a corpus of all courts and all languages, about 100
times this one.

## 2. The vocabulary

The terms in this section describe Dask in general. The next sections say which parts this
repository uses.

**Task, task graph, lazy evaluation.** A task is one Python function call with its arguments.
Dask records the call instead of running it. The task graph is a dictionary of tasks. Each
task names the tasks whose results it needs. The graph is a plan. The work starts when you
call `.compute()`.

**Scheduler.** The part that walks the graph and runs the tasks. The synchronous scheduler
runs every task in the calling thread. The threaded scheduler uses a thread pool. The
multiprocessing scheduler uses a process pool. The distributed scheduler is a separate
process that talks to workers over the network.

**Worker, client, LocalCluster.** A worker is a process that runs tasks for the distributed
scheduler. A `LocalCluster` starts the scheduler and the workers on one machine. A `Client`
connects your program to the scheduler. While a client is open, `.compute()` sends the graph
to it.

**Partition.** One slice of a large collection. A bag with 72 partitions is 72 Python lists
in different tasks. Every partition becomes at least one task.

**Bag, dataframe, delayed.** The bag is the collection for lists of Python objects. It offers
`map`, `map_partitions`, `filter` and `fold`. A Dask dataframe is a list of pandas frames.
`dask.delayed` turns any function call into one task. This repository uses only the bag.

**GIL.** The lock in CPython that lets one thread run Python code at a time. Regex matching
and span bookkeeping are Python code, so two threads would take turns. Two processes do not
share the lock. That is the general reason for processes in CPU-bound Python work.

## 3. How the pieces connect

```
 laptop (18 cores)
 +---------------------------------------------------------------------------------+
 | client process                                                                  |
 |   load_corpus() ---> rows (7,999 dicts) ---> write_partitions()                 |
 |                      data/interim/partitions/n7999-p72/part-0000..0071.parquet  |
 |   bag = from_sequence(files).map(regex_partition_file, corpus_ids, code_map)    |
 |   bag.compute()  ---- task graph: 72 tasks, each carries one path ---->         |
 |   LocalCluster(n_workers=18, threads_per_worker=1, processes=True)              |
 |   +----------+ +----------+        +----------+   each task: read part file,    |
 |   | worker 1 | | worker 2 |  ...   | worker 18|   regex -> dedupe -> link_spans |
 |   +----------+ +----------+        +----------+   -> one Tables object          |
 |         \            |                 /                                        |
 |          +---- 72 Tables objects back to the client ----+                       |
 |   Tables.extend() x 72 ---> _write() ---> data/runs/regex-v0.4/                 |
 |                       decisions.parquet, spans.parquet, citations.parquet, run.json |
 +---------------------------------------------------------------------------------+
                                             |
             +-------------------------------+-------------------------------+
             v                               v                               v
   caselaw graph                     caselaw db-load                   caselaw api --backend duckdb
   DuckDB views over Parquet,        COPY into Postgres                DuckDB views, no database
   NetworkX, centrality.parquet      (local path or s3://)
```

The gbert extractor skips the top half of the box. `run_gbert` runs in one process on the
GPU, 100 decisions at a time, and calls the same `flatten` function. Both extractors write
the same four files, so the consumers in the bottom row do not know which one made a run.

## 4. Dask in this repository

The dependency in `pyproject.toml` is `dask[distributed]>=2024.10`. The lock file pins
`dask` and `distributed` at version 2026.8.0. The import happens inside `run_regex`, so the
API image can load `corpus_run.py` without starting Dask.

### 4.1 Three schedulers, one bag

`run_regex(rows, workers, scheduler)` accepts three scheduler names. The `caselaw run-corpus`
option `--scheduler` passes the name through. The default is `distributed`.

| name | what runs | where it is used |
|---|---|---|
| `distributed` | `LocalCluster(n_workers=workers, threads_per_worker=1, processes=True, dashboard_address=None)` and a `Client` | `make run-corpus`, the `regex-v0.4` run |
| `processes` | `bag.compute(scheduler="processes", num_workers=workers)`, a multiprocessing pool, no scheduler process | `caselaw demo`, the integration test |
| `sync` | `dask.config.set(scheduler="synchronous")`, one process, one thread | the test fixtures, the `regex-v0.4-1proc` run |

The worker count is `os.cpu_count()` when `--workers` is 0. On the MacBook that is 18. For
`sync` the count is forced to 1. Each worker has one thread. The module docstring gives the
reason: "one process per core". The GIL paragraph in section 2 explains why.

The gbert extractor does not use Dask. The docstring says that "a token classifier does not
gain from CPU processes". The model runs on the GPU, and the GPU is one device. The run
record of `gbert-b13-s0` therefore says `"scheduler": "single-process"` and `"device": "mps"`.

### 4.2 How the corpus is partitioned

The partition count is `max(1, min(len(rows), workers * 4))`. With 18 workers and 7,999 rows
that is 72. Four partitions per worker is the ratio the code chose. It gives the scheduler
slack to balance uneven partitions.

The `distributed` and `processes` paths do not put the texts into the graph. `write_partitions`
splits the rows into Parquet files under `data/interim/partitions/n<rows>-p<partitions>/`.
The file names are `part-0000.parquet` to `part-0071.parquet`. The chunk size is the ceiling of
7,999 divided by 72, that is 112 rows per file. Compression is zstd. The directory for the
full run holds 29 MB in 72 files. The corpus file itself is 24 MB.

A `manifest.json` next to the files records the row count, the partition count, the first
decision id and the last. If the next run has the same record and the same file count, the
files are reused. Otherwise they are rewritten. The test `test_partition_files_are_reused` checks this.

The docstring of `write_partitions` names the reason: "Dask best practice: the task graph
carries paths, not the texts". A graph with 7,999 texts would be serialised to the scheduler
and again to each worker. A graph with 72 paths is small. Each worker reads its own file.

The `sync` path takes the shortcut. It calls `db.from_sequence(rows, npartitions=4)` with
the rows in memory and `map_partitions(regex_partition, ...)`. Nothing is serialised.

### 4.3 What one task does

Each task in the `distributed` path is one call of `regex_partition_file(path, corpus_ids,
code_map)`. The two extra arguments travel with every task. `corpus_ids` is the set of all
7,999 decision ids. `code_map` is the Fedlex abbreviation table, loaded once in the client by
`load_code_map()`. The function does four things for each row of its file:

1. `rx.extract(decision_id, full_text, code_map)` runs the regex extractor. It returns spans
   and an outcome.
2. `dedupe` sorts the spans and removes duplicates on (start, end, label).
3. `link_spans` from `linking.py` resolves each span to a key. It drops spans that resolve to
   nothing. The four drop reasons are `unknown_code`, `no_article`, `no_bge_key` and
   `own_docket`.
4. `flatten` turns the kept spans into rows for three tables and adds one decision row.

The result of a task is one `Tables` object: the decision rows, the span rows, the citation
rows and a `Counter` of drop reasons. The client merges the 72 objects with `Tables.extend` in
partition order, so the output keeps the corpus order. The linking stage therefore runs inside
the workers, not after them.

### 4.4 The outputs of a run

`_write` writes three Parquet files with explicit `pyarrow` schemas. `run_corpus` adds
`run.json`. `caselaw graph` adds `centrality.parquet`, `graph.html` and `analyses.json` later.

`decisions.parquet`, one row per decision:

| column | type | source |
|---|---|---|
| `decision_id`, `docket_number`, `decision_date`, `legal_area`, `source_url` | string | corpus |
| `year` | int32 | first four characters of `decision_date` |
| `chamber` | string | corpus column `chamber_text` |
| `outcome_dataset` | string | the dataset's own label |
| `outcome` | string | the extractor's prediction |
| `text_length` | int32 | corpus |
| `n_spans`, `n_dropped` | int32 | spans kept and spans dropped by linking |

`spans.parquet`, one row per kept span:

| column | type | note |
|---|---|---|
| `span_id` | string | `<decision_id>:<start>:<end>:<label>` |
| `decision_id` | string | |
| `start`, `end` | int32 | character offsets into `full_text` |
| `label` | string | `STATUTE`, `BGE`, `DOCKET`, `AMOUNT`, `PARTY_ROLE`, or a negative class from gbert |
| `text` | string | the span text |

`citations.parquet`, one row per linked key. A statute chain span yields one row per article:

| column | type | note |
|---|---|---|
| `span_id`, `decision_id` | string | the span that produced the row |
| `kind` | string | `statute`, `bge` or `docket` |
| `key` | string | `ZGB 8`, `BGE 140 III 86` or `4A_12_2020` |
| `code`, `sr`, `article` | string | filled for `statute` only; `sr` is the Fedlex SR number |
| `target_decision_id` | string | for `docket`: `bger_<key>` when that decision is in the corpus, else null |

`centrality.parquet`, written by `graph.py`, one row per graph node: `node`, `kind`, `key`,
`decision_id`, `in_degree`, `out_degree`, `pagerank`, `rank_pagerank`, `rank_in_degree`.

`run.json` holds the run record. The keys are `name`, `extractor`, `extractor_version`,
`started_at`, `corpus`, `n_decisions`, `n_spans_before_linking`, `n_spans`, `dropped` (one
count per reason), `spans_by_label`, `citations_by_kind`, `docket_targets_in_corpus`,
`outcomes`, `wall_seconds`, `extract_seconds`, `cpu_count`, `machine`, `workers`,
`npartitions` and `scheduler`. The Dask paths add `partition_seconds` and `dashboard`. The
gbert path adds `model_dir`, `outcome_dir`, `decode` and `device`. The command also logs the
record to MLflow as `corpus-<name>`.

### 4.5 Run directory names

The run name is the `--name` option. It becomes the directory under `data/runs/` and the
`run_id` in Postgres. The repository uses these names:

| directory | meaning |
|---|---|
| `regex-v0.4` | regex extractor version `regex-v0.4` (`VERSION` in `regex_extractor.py`), 18 workers, distributed |
| `regex-v0.4-8w`, `regex-v0.4-4w` | the same extractor with 8 and 4 workers, for the timing table |
| `regex-v0.4-1proc` | the same extractor with `--scheduler sync`, one process |
| `gbert-b13-s0` | the model `models/gbert-base-b13-s0-ner`; `b13` is the training batches 1 and 3, `s0` is seed 0 |
| `demo`, `smoke20` | the 100-decision sample of `caselaw demo`; a 20-decision smoke run |

A run name is a fact about the extractor, not about the date.

## 5. Cost and timing of the full run

The numbers come from `run.json` of each run and from report sections 7.1 and 7.5. The machine
is a MacBook with an M5 Pro, 18 cores and 48 GB.

| run | workers | partitions | wall time | extraction time |
|---|---|---|---|---|
| `regex-v0.4` | 18 | 72 | 4.37 s | 3.75 s (partition files 0.27 s) |
| `regex-v0.4-8w` | 8 | | 4.2 s | |
| `regex-v0.4-4w` | 4 | | 5.3 s | |
| `regex-v0.4-1proc` | 1 | 4 | 11.09 s | 9.69 s |
| `gbert-b13-s0` | 1 GPU process | | 1,794.73 s (30 min) | 1,791.36 s |

The report draws one conclusion. The regex is so cheap that Dask does not pay off on this
corpus. Most of the parallel time goes to starting the cluster, not to extracting. Dask stays
in the pipeline for the 100 times larger corpus and for extractors that cost seconds per decision.

Section 7.5 gives cost estimates for AWS. The regex on one Fargate task with 1 vCPU and 2 GB
costs under USD 0.01 per full run. The Dask variant is "not worth a cluster at this size".
The gbert run on one `g5.xlarge` costs about USD 0.63 per run, about USD 0.08 per 1,000
decisions.

## 6. Walkthrough of a run, as done by hand

The corpus must exist first. `make ingest` builds it. Then:

1. Run `make run-corpus`.
   It calls `uv run caselaw run-corpus --name regex-v0.4 --extractor regex`. The command
   prints five summary lines and writes `data/runs/regex-v0.4/`.
2. Run `make graph RUN=regex-v0.4`.
   The command writes `centrality.parquet`, `graph.html` and `analyses.json` into the run
   directory and prints the three analyses.
3. Run `make db-up`.
   Postgres 16 starts in Docker on port 5433.
4. Run `make db-load RUN=regex-v0.4`.
   The loader creates the schema and copies the four tables. The report gives 6 seconds.
5. Run `make api BACKEND=postgres`.
   FastAPI serves the run at `http://127.0.0.1:8000/docs`.

For the gbert run, replace step 1 with `make run-corpus-gbert`. That target passes
`--model-dir models/gbert-base-b13-s0-ner`. The command finds the outcome classifier by
replacing the `-ner` suffix with `-outcome`.

## 7. The 100-decision demo

`caselaw demo --n 100` runs the whole pipeline from Parquet alone. It calls
`run_corpus("demo", "regex", limit=100, scheduler="processes", workers=4)`, then
`graph.analyse_run("demo")`. It needs no Postgres and no cloud. The recorded demo run took
1.07 s with 4 workers and 16 partitions.

The demo still uses Dask. The `processes` scheduler starts a multiprocessing pool but no
`LocalCluster`. The first command below runs the sample in one process. The second runs it
with the distributed cluster:

```bash
uv run caselaw run-corpus --name smoke --limit 100 --scheduler sync
uv run caselaw run-corpus --name smoke --limit 100 --workers 4
```

Both forms write the same four files. The `scheduler` field in `run.json` tells them apart.
After either of them, `caselaw api --backend duckdb --run smoke` serves the sample.

## 8. How the output feeds DuckDB and Postgres

`store.py` defines one query interface with two backends. The graph analyses and the API
write their SQL once against the table names `decision`, `span`, `citation`, `centrality` and
`extraction_run`.

`DuckDBStore(run_dir)` creates one view per Parquet file with `read_parquet`. Nothing is
copied. Each view adds a constant `run_id` column equal to the directory name. The `span`
view renames `start` and `end` to `start_char` and `end_char`, the Postgres column names.
`graph.analyse_run` opens this store, builds the NetworkX graph from `decision` and
`citation`, writes `centrality.parquet`, then reopens the store to see the new file.

`db.load_run(name, dsn, runs_dir)` reads the same directory into Postgres. It reads `run.json`
first and inserts one `extraction_run` row with the extractor, the version, the counts, the
wall time, the worker count and the scheduler. Then it copies each Parquet table with `COPY
... FROM STDIN`, prefixing every row with the `run_id`. A load deletes the earlier rows of the
same `run_id` first, so a run can be reloaded. The `runs_dir` can be a local path or an
`s3://` prefix; `pyarrow.fs` reads both. After the copy the loader runs `ANALYZE`.

`open_store(backend, run)` chooses the backend from the arguments or from `CASELAW_BACKEND`,
`CASELAW_RUN` and `CASELAW_DSN`. Without any of them it opens DuckDB over `data/runs/regex-v0.4`.

## 9. What went wrong, and what each finding teaches

The commit log, the report and the code comments record no Dask failure. Section 9 of the
report has no Dask entry. The evidence is thin, so this section holds only the measured
results and the design notes that the files contain.

**Cluster start dominates a cheap workload.** The one-process run extracts in 9.7 s. The
18-worker run needs 3.8 s from partitioning to results, and the report attributes most of
that to starting the cluster. Eight workers (4.2 s) are almost as fast as eighteen (4.4 s).
Lesson: measure the single-process time first. Parallelism pays only when the work per task
is much longer than the start-up of the workers.

**Paths in the graph, not texts.** The docstring of `write_partitions` records this as a Dask
best practice. Lesson: keep the task graph small. Let the workers read their own input.

**The dashboard link in `run.json` points to nothing.** The cluster is created with
`dashboard_address=None`, which in Dask turns the dashboard off. `run.json` of `regex-v0.4`
still records `"dashboard": "http://127.0.0.1:8787/status"`, because `client.dashboard_link`
builds the string from the configuration. Lesson: a recorded link is not a running service.

## 10. How to verify a run

1. Run `cat data/runs/regex-v0.4/run.json`.
   The fields `n_decisions`, `n_spans`, `workers`, `npartitions` and `scheduler` show what ran.
2. Run `ls data/interim/partitions/n7999-p72 | wc -l`.
   The count is 73: 72 partition files and the manifest.
3. Run the count query below.
   The span count must equal `n_spans` in `run.json`. The per-decision sum must match it.
4. Run `uv run pytest tests/test_corpus_run.py`.
   The tests use a synthetic corpus with `sync`, plus 20 real decisions with `processes`.
5. If both runs exist, run `make compare-runs A=regex-v0.4 B=gbert-b13-s0`.
   The report gives a Jaccard index of 0.974 to 0.994 per citation kind.

```bash
uv run python -c "import duckdb; print(duckdb.sql(\"\"\"
SELECT (SELECT count(*) FROM 'data/runs/regex-v0.4/spans.parquet') AS spans,
       (SELECT sum(n_spans) FROM 'data/runs/regex-v0.4/decisions.parquet') AS span_sum,
       (SELECT count(*) FROM 'data/runs/regex-v0.4/citations.parquet') AS citations
\"\"\"))"
```

## 11. Scaling to more cores or a cluster

This section describes general Dask behaviour and names the code that would change. None of
it has been run in this repository.

**More cores on one machine.** Nothing changes. `--workers 0` takes `os.cpu_count()`. The
partition count follows at four per worker, and a new count writes a new partition directory.

**A cluster of machines.** The `distributed` path already speaks to a `Client`. Replace the
`LocalCluster` with a client to a remote scheduler, for example through `SSHCluster` or the
`dask-kubernetes` package. Three things in the code then matter:

- The partition files must sit where every worker can read them. `write_partitions` writes
  to a local path. A cluster needs S3 or another shared store. The loader already reads
  `s3://` through `pyarrow.fs`, so the same layer would serve the partitions.
- `corpus_ids` and `code_map` travel with each of the 72 tasks. Across a network,
  `client.scatter` would send each of them once and pass a future instead.
- Each task returns a `Tables` object with all rows of its partition. The client holds all 72
  in memory before writing. For a corpus 100 times larger, each task should write its own
  Parquet part and return only counts.

**The gbert run.** `run_gbert` is one process on one GPU. A faster gbert run needs more GPUs,
each with its own copy of the model. The partition files are the natural unit for that split.

**Ray as the fallback.** The portfolio plan, `../PLAN.md` in the parent directory, states:
"Scale-out: Dask (named in the posting) for corpus-wide extraction. Ray is the fallback." The
repository itself does not mention Ray. The regex path would move with little change:
`regex_partition_file` would become a Ray remote function and the 72 paths its arguments.

## 12. Alternatives, and why not

- **One process, no Dask.** It is faster on this corpus once cluster start is counted, with
  no second process to debug. The report keeps Dask because the posting names it and because
  the target corpus is 100 times larger. The `sync` scheduler keeps this option one flag away.
- **Threads instead of processes.** The regex and the span bookkeeping are Python code under
  the GIL. Threads would take turns and gain nothing.
- **A Dask dataframe instead of a bag.** The items are dicts with long texts and nested span
  lists. A dataframe wants flat columns. The bag returns any Python object per partition.

## 13. Questions to be able to answer afterwards

- Why does `bag.compute()` start the work, and what did the lines before it do?
- Why does the task graph carry 72 paths and not 7,999 texts?
- Why is `threads_per_worker=1`? When would more threads per worker help?
- Where does the linking stage run, and why is it not a separate pass over the spans?
- Why does the regex run not gain from eighteen workers, and which extractor would?
- Which three things would you change to run the same graph on a remote cluster?

## 14. Files

| file | role |
|---|---|
| `src/caselaw_extraction/corpus_run.py` | `run_corpus`, `run_regex`, `run_gbert`, `write_partitions`, the Parquet schemas, `run.json` |
| `src/caselaw_extraction/linking.py` | `link_spans`, the four drop reasons |
| `src/caselaw_extraction/graph.py` | `analyse_run`, the NetworkX graph, `centrality.parquet`, `compare_runs` |
| `src/caselaw_extraction/store.py`, `db.py`, `sql/schema.sql` | `DuckDBStore`, `PostgresStore`, `open_store`; `load_run` with COPY; the Postgres tables |
| `src/caselaw_extraction/cli.py` | `run-corpus`, `graph`, `compare-runs`, `db-load`, `api`, `demo` |
| `Makefile`, `pyproject.toml` | the `run-corpus`, `graph`, `db-load`, `demo` targets; `dask[distributed]>=2024.10` |
| `tests/test_corpus_run.py` | the partition reuse test, the 20-decision integration test |
| `data/runs/<name>/`, `data/interim/partitions/n7999-p72/` | the run directories of section 4.5; the 72 partition files and `manifest.json` |
| `docs/report.md`, sections 7.1 and 7.5 | the timing table, the conclusion on Dask, the cost estimates |
| `../PLAN.md` | the portfolio plan that names Dask and Ray |
