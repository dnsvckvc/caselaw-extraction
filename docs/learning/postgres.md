# Postgres: the serving database, its loader, tuning, secrets, backups, and DuckDB beside it

This note explains the database of the caselaw service. It is written for someone who would
build the same thing by hand, without an AI assistant, and wants to understand each piece
before copying it. The schema is `src/caselaw_extraction/sql/schema.sql`, the loader is
`src/caselaw_extraction/db.py`, the query layer is `src/caselaw_extraction/store.py`, the
container is the `postgres` service in `infra/hetzner/compose.yml`, and the report discusses
the database in sections 7.2, 7.4, 8.1 and 8.2 of `docs/report.md`.

## 1. The problem the database solves here

The extraction run writes Parquet files. One run holds 7,999 decisions, 294,884 spans and
249,762 citations (report 7.2). The API must answer two kinds of question over these rows:

- Give me one decision with its spans and its citations.
- Give me an aggregate: the most-cited articles, the trend by year, the most central nodes.

DuckDB can answer both kinds directly from the Parquet files. A single-decision lookup then
scans the Parquet and takes 140 ms on the laptop. The same lookup takes 5 ms on Postgres
(report 7.4). Postgres also lets several runs live side by side in one database, and a reload
replaces a run instead of duplicating it. The decision texts stay in Parquet. The database
holds offsets, span texts, citations and the centrality table (report 7.2).

## 2. The vocabulary

**Run and `run_id`.** One pass of one extractor over the corpus, for example `regex-v0.4`.
Every record row carries its `run_id`. The API reads one run; `CASELAW_RUN` selects it.

**COPY.** The Postgres bulk-load statement. The client streams rows into a table in one
stream, without one `INSERT` per row. The loader uses `COPY ... FROM STDIN` through psycopg.

**ANALYZE.** The statement that refreshes the planner statistics of a table. This is general
Postgres behaviour: after a bulk load the statistics are stale or absent, and the planner then
chooses plans for an empty table.

**Planner.** The part of Postgres that chooses between a sequential scan, an index scan and
the sort or hash strategies. It reads the statistics and four cost parameters, which section
4.3 explains.

**DSN.** The connection string, `postgresql://user:password@host:port/database`. It contains
the password, so it is a secret.

**Compose secret.** A file on the host that Compose mounts into a container under
`/run/secrets/<name>`. The content never becomes an environment variable, so `docker inspect`
does not show it (report 8.1).

**Custom-format dump.** The output of `pg_dump -Fc`. It is compressed, and `pg_restore` can
restore it as a whole or table by table. This is general Postgres behaviour.

**Store layer.** The `Store` class in `store.py` with two implementations: `DuckDBStore` over a
run directory and `PostgresStore` over the loaded database. The graph analyses, the drift
check and the API write their SQL once against this class.

## 3. How the pieces connect

```
 laptop                                 server (Hetzner cx23, 4 GB)
 data/runs/regex-v0.4/*.parquet         /var/lib/caselaw/runs/<run>/          Cloudflare R2
        |  make hz-sync (rsync)  ---->     |                                   caselaw-runs/
        |                                  | ro mount /data/runs                 runs/
        |                                  v                                     backups/
        |                          +--- api container (uid 1000) ---+              ^
        |                          | caselaw db-load  -- COPY ----> |              |
        |                          | uvicorn, 2 workers -- SELECT ->|  postgres    |
        |                          | reads /run/secrets/caselaw_dsn | container    |
        |                          +--------------------------------+  pgdata vol  |
        |                                                                 ^        |
        |                          alloy: postgres_exporter --------------+        |
        |                                 reads /run/secrets/exporter_dsn          |
        |                                                                          |
        |                          cron 03:30: pg_dump -Fc -> /var/lib/caselaw/backups
        |                                        rclone copy ------------------------+
        |
 local: infra/docker-compose.yml, localhost:5433, user caselaw, password caselaw
 CI:    the same image as a GitHub Actions service on port 5433
```

The three secret files live in `/etc/caselaw/secrets` on the host. cloud-init writes them on
the first boot. Compose mounts them into the three containers that need them.

## 4. Postgres in depth

### 4.1 The schema

`schema.sql` creates six tables and six indexes with `CREATE ... IF NOT EXISTS`, so the loader
can run it on every load without harm.

| table | key | content |
|---|---|---|
| `extraction_run` | `run_id` | one row per run: extractor, version, counts, wall time, workers, `loaded_at` |
| `decision` | `(run_id, decision_id)` | metadata of one decision, no text |
| `span` | `(run_id, span_id)` | `start_char`, `end_char`, `label`, `text` |
| `citation` | `citation_id bigserial` | linked citation: `kind` in `statute`, `bge`, `docket`; `key`, `code`, `sr`, `article`, `target_decision_id` |
| `centrality` | `(run_id, node)` | in-degree, out-degree, PageRank and the two ranks |
| `statute` | `sr` | SR number, abbreviation, title; filled from the Fedlex list, not per run |

Every record table has `run_id ... REFERENCES extraction_run(run_id) ON DELETE CASCADE`. One
`DELETE FROM extraction_run WHERE run_id = ...` therefore removes a whole run. Every index
starts with `run_id`, because every query of the API starts with `WHERE run_id = ?`. The
`citation` table has three indexes: by `(run_id, kind, key)`, by `(run_id, decision_id)` and
by `(run_id, target_decision_id)`. These serve the filters `?statute=`, `?bge=`, `?docket=`
and the lookup of one decision.

### 4.2 The loader

`caselaw db-load --run <name> [--dsn ...] [--runs-dir ...] [--no-statutes]` calls
`db.load_run` and then `db.load_statutes`. The DSN comes from `--dsn`, else from
`CASELAW_DSN`, else from the file named by `CASELAW_DSN_FILE`, else from `DEFAULT_DSN`, which
is the local Compose database. `load_run` does these things inside one connection:

1. It runs `schema.sql`.
2. It deletes the row of this `run_id` from `extraction_run`. The cascade removes the old rows.
3. It inserts the run metadata from `run.json`.
4. For each of `decisions.parquet`, `spans.parquet`, `citations.parquet` and `centrality.parquet`,
   it reads the needed columns with pyarrow and streams the rows with `COPY <table> (...) FROM STDIN`.
   The Parquet columns `start` and `end` become `start_char` and `end_char`.
5. It commits.
6. It runs `ANALYZE` and commits again.

The code comment on step 6 gives the reason: "Fresh statistics after a bulk COPY; without them
the planner scans the citation table sequentially for the aggregate endpoints (seen on the
first deployment)." Section 6 has the details.

`open_run` accepts a local directory or an `s3://bucket/prefix`. With `AWS_ENDPOINT_URL_S3`
set, pyarrow talks to an S3-compatible store such as Cloudflare R2. The Compose file passes
the R2 key to the `api` service for this reason. On the server, `scripts/hz.sh load` runs the
loader inside the API image:

```
docker compose ... run --rm --no-deps api caselaw db-load --run <run> --runs-dir /data/runs
```

The report measured the local load: 6 seconds for the regex run, 130 MB for one run, 276 MB
with two runs on the server (report 7.2 and 8.1). `load_statutes` deletes and refills the
`statute` table with 1,505 acts from the Fedlex code map; the first abbreviation of an SR
number wins, and the core codes are inserted first.

### 4.3 The four tuning parameters

The `postgres` service starts with this command:

```
postgres -c shared_buffers=512MB -c work_mem=32MB -c effective_cache_size=2GB -c random_page_cost=1.1
```

The Compose comment says: "Tuned for a 4 GB server (the defaults assume 128 MB); the aggregate
endpoints sort 140,000 citation rows per request." What follows about each parameter is
general Postgres behaviour, applied to this server.

| parameter | value here | Postgres default | what it does on a 4 GB server |
|---|---|---|---|
| `shared_buffers` | 512 MB | 128 MB | The cache of table and index pages inside Postgres. 512 MB holds the whole 276 MB database, so a warm query reads no disk. The memory is reserved at start, but the container showed 178 MB in use (report 8.2), because only touched pages count. |
| `work_mem` | 32 MB | 4 MB | The memory one sort or hash step may use before it spills to disk. The top-statutes aggregate sorts about 140,000 citation rows for `count(DISTINCT)`; 4 MB spills, 32 MB does not. The limit applies per step, not per connection, so two uvicorn workers with a few steps each stay far below 1 GB. |
| `effective_cache_size` | 2 GB | 4 GB | A hint to the planner about how much of the data the kernel and Postgres together keep in memory. It allocates nothing. The value is lowered to 2 GB because the API, Caddy and Alloy share the 4 GB. |
| `random_page_cost` | 1.1 | 4.0 | The planner's cost of one random page read relative to a sequential read of 1.0. The default assumes spinning disks. On the SSD of the server a random read is nearly as cheap as a sequential one, so 1.1 makes the planner prefer index scans over sequential scans. |

The parameters are passed on the command line, not in a `postgresql.conf`, so the committed
Compose file is the only place to read them. `SHOW shared_buffers;` inside the container
confirms the running value.

### 4.4 Why the password is generated on the server

Nobody types the database password, and it is never on the laptop. cloud-init runs these
commands on the first boot (`infra/hetzner/cloud-init.yaml`):

```
install -d -m 0750 -o root -g caselaw /etc/caselaw/secrets
openssl rand -hex 24 > /etc/caselaw/secrets/postgres_password
printf "postgresql://caselaw:%s@postgres:5432/caselaw" "$(cat .../postgres_password)" > .../caselaw_dsn
printf "postgresql://caselaw:%s@postgres:5432/caselaw?sslmode=disable" "$(cat .../postgres_password)" > .../exporter_dsn
chmod 0640 /etc/caselaw/secrets/*
chgrp caselaw /etc/caselaw/secrets/*
```

The Compose file maps the three files to secrets. The `postgres` service gets
`POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password`. The official image reads the
password from that file when it creates the database cluster. The `api` service gets
`CASELAW_DSN_FILE=/run/secrets/caselaw_dsn`, and `store.dsn_from_env` reads the file. The
host name in the DSN is `postgres`, the Compose service name, which Docker's DNS resolves
inside the Compose network. The database port is never published on the host.

Two file permissions matter. Postgres reads its password as root before it drops privileges,
so mode 0640 with group `caselaw` is enough for it. The API image runs as uid 1000 (the `app`
user in the `Dockerfile`). The host group `caselaw` has gid 1001, because Docker took 1000.
The `api` service therefore has `group_add: ["${CASELAW_GID:-1001}"]`, and cloud-init writes
`CASELAW_GID` into `/etc/caselaw/hosts.env`. Section 6 tells how this was found.

The test `tests/test_store_env.py` pins the order: `CASELAW_DSN` wins over
`CASELAW_DSN_FILE`, and the file content is stripped of its trailing newline.

### 4.5 The exporter DSN

The Alloy container runs `postgres_exporter` in process. It reads
`/run/secrets/exporter_dsn` through `local.file` with `is_secret = true`, so Alloy's own UI
and logs mask it (`infra/hetzner/alloy/config.alloy`). The file holds the same user
`caselaw` and the same password as the API; there is no separate monitoring role in this
repository. The one difference is `?sslmode=disable`. The container Postgres has no TLS, and
the Go driver of the exporter would otherwise try to negotiate it. The exporter gives the
PostgreSQL dashboard its connections, transactions, cache hit ratio and database size
(report 8.3). `docs/learning/grafana.md` covers the dashboard side.

### 4.6 Backups

`infra/hetzner/backup.sh` runs from `/etc/cron.d/caselaw-backup` at 03:30 as the `caselaw`
user; `scripts/hz.sh deploy` installs that cron line. The script does five things:

```
docker compose ... exec -T postgres pg_dump -U caselaw -Fc caselaw > /var/lib/caselaw/backups/caselaw-<stamp>.dump
rclone copy  <dump>                r2:caselaw-runs/backups/ --s3-no-check-bucket --s3-no-head
rclone sync  /var/lib/caselaw/runs r2:caselaw-runs/runs/    --s3-no-check-bucket --s3-no-head
rclone delete r2:caselaw-runs/backups/ --min-age 14d
find /var/lib/caselaw/backups -name '*.dump' -mtime +3 -delete
```

`pg_dump` runs inside the container over the Unix socket, so the script needs no password.
`-Fc` is the custom format: compressed, and restorable with `pg_restore` as a whole or per
table. The retention is 14 days in R2 and 3 days on the server. rclone is configured through
environment variables from `/etc/caselaw/caselaw.env`, so no `rclone.conf` holds the R2 key.
If `BACKUP_HEALTHCHECKS_URL` is set, the script pings healthchecks.io at start, success and
failure. The repository contains no restore script and no restore test. A restore would be
`pg_restore -U caselaw -d caselaw <dump>` into an empty database, which is general Postgres
usage, not something this project has exercised.

### 4.7 The local database and CI

`infra/docker-compose.yml` runs `postgres:16-alpine` as `caselaw-postgres` with user, password
and database all `caselaw`, on host port 5433. The comment gives the reason for 5433: port
5432 is often taken by another Postgres. `make db-up` runs `docker compose up -d --wait`, which
returns when the `pg_isready` health check passes. `make db-load` loads `RUN` (default
`regex-v0.4`). `DEFAULT_DSN` in `store.py` points at this database.

`.github/workflows/ci.yml` starts the same image as a service container on port 5433. It uses
the same credentials and a `pg_isready` health command, then runs `uv run pytest`.
`tests/test_db.py` tries to connect to `DEFAULT_DSN` with a two-second timeout and skips
when no database answers. When it runs, it loads a synthetic run. It compares the top statutes, the central nodes and
the trend by year between `PostgresStore` and `DuckDBStore`. It loads the run a second time
and asserts that the row count stays at 3. Then it deletes the run. The report
lists a GitHub repository as the next step (section 10), so the workflow is written but has
not run yet.

### 4.8 One SQL, two backends

`store.py` is the reason the same analyses work with and without a database.

`DuckDBStore` opens an in-memory DuckDB and creates one view per Parquet file:

```sql
CREATE VIEW span AS SELECT '<run_id>' AS run_id, span_id, decision_id,
  "start" AS start_char, "end" AS end_char, label, text FROM read_parquet('<path>')
```

The view adds the `run_id` literal and renames two columns, so the table and column names
match the Postgres schema. `extraction_run` is a one-row view with `run_id` and `extractor`.
Nothing is copied.

`PostgresStore` connects with psycopg, `dict_row` and `autocommit=True`. Its `query` method
runs `sql.replace("?", "%s")` and passes the parameters through. DuckDB uses `?` as the
placeholder and psycopg uses `%s`; the callers write `?`. The replacement is a plain string
replace, so a SQL statement must not contain a literal question mark. None does today.

`open_store` picks the backend from the argument, else from `CASELAW_BACKEND`, else
`postgres` when a DSN is present and `duckdb` otherwise. The run comes from `CASELAW_RUN`
(default `regex-v0.4`), the runs directory from `CASELAW_RUNS_DIR`. The SQL in `graph.py`,
`drift.py` and `api.py` stays in the common dialect: `count(DISTINCT ...)`, `round`, `cast(...
AS varchar)`, `substr`, `GROUP BY 1, 2`.

The trade-offs as the report states them (7.3, 7.4, 8.2, 10):

- DuckDB needs no server and no load step; `make demo` runs on Parquet only.
- A single-decision lookup takes 140 ms on DuckDB and 5 ms on Postgres.
- The aggregates took 10 to 100 ms on either backend on the laptop. On the 2 vCPU server the
  top-statutes aggregate took 1.1 s on Postgres, so the API caches aggregates in process.
- The smoke run returned identical numbers on both backends.
- Postgres holds several runs side by side; a DuckDB store sees one run directory.
- The API image carries DuckDB and polars although the Postgres backend needs neither.
  Moving them to an extra would cut about 240 MB; this is open in report section 10.

## 5. Walkthrough of the setup, as done by hand

Precondition: Docker runs on the laptop, and `data/runs/regex-v0.4/` exists.

1. Run `make db-up`. Postgres 16 answers on `localhost:5433`.
2. Run `make db-load`. The command prints the row count per table and the database size.
3. Run `make api BACKEND=postgres`. The API serves `http://127.0.0.1:8000/docs`.
4. Run `uv run pytest tests/test_db.py`. The test runs instead of skipping.
5. On a new server, run `make hz-apply`. cloud-init writes the three secret files.
6. Run `make hz-deploy`. Compose starts `postgres`, then `api`, then `caddy`.
7. Run `make hz-sync RUN=regex-v0.4`. The run directory arrives under `/var/lib/caselaw/runs`.
8. Run `make hz-load RUN=regex-v0.4`. The loader runs once inside the API image.
9. Run `make hz-smoke`. The API answers over HTTPS.
10. If the R2 key is in `/etc/caselaw/caselaw.env`, run `scripts/hz.sh backup-now`. A dump appears under `backups/` in the bucket.

`make hz-bootstrap` runs steps 5 to 9 in one command.

## 6. What went wrong, and what each mistake teaches

The evidence for this section is the commits of 2026-11-03, the code comments and report
sections 8.1 and 8.2. Four problems are documented; nothing else is on record.

**The aggregates were slow on the server.** Commit `b82bdd0` and report 8.2. On the laptop
the top-statutes aggregate answered in 10 to 100 ms. On the server the first measurement,
before any `ANALYZE` had run, was 1.3 s. After `ANALYZE` it was 1.1 s in `EXPLAIN ANALYZE`:
an index scan over 138,143 citation rows followed by a sort for `count(DISTINCT)`. Three
changes followed. The loader runs `ANALYZE` after every load. The Compose command sets the
four memory and cost parameters of section 4.3. The API keeps aggregate results in a 512-entry
LRU, sends `Cache-Control: public, max-age=3600` and fills the four default views at startup.
The warm latency fell to about 100 ms, which is the network floor. Lesson: a bulk `COPY`
leaves the planner without statistics, and a 2 vCPU server exposes a sort that a laptop hides.

**The API could not read its secret file.** Commit `1542125` and report 8.1. The secret files
have mode 0640 and group `caselaw`. The host group got gid 1001, because Docker had taken
1000, and the API runs as uid 1000. The fix is `group_add` with `CASELAW_GID` from
`hosts.env`, which cloud-init fills with the real gid. Lesson: a file mounted into a
container keeps the host's numeric ids, and nothing maps the container's user to them.

**The loader wrote into a read-only directory.** Same commit. `caselaw db-load` loads the
Fedlex code map, and the cache write failed inside the container. The cache write is now
optional. Lesson: a command that worked on the laptop may assume a writable working directory.

**The backup upload was reported as failed although the object was stored.** Commit `4860de7`
and the comment in `backup.sh`. R2 returns a version id on `PUT`. rclone 1.60 then sends
`HEAD ?versionId=...`, and R2 answers that call with 501. rclone therefore retried every upload. The flag
`--s3-no-head` skips that check, and `Content-MD5` still verifies the upload. Lesson: an
S3-compatible store is compatible for the common calls, and a client's extra checks find the
gaps.

## 7. How to verify

On the laptop, after `make db-up` and `make db-load`:

```sql
-- the loaded runs and their sizes
SELECT run_id, extractor, n_decisions, n_spans, loaded_at FROM extraction_run;
SELECT pg_size_pretty(pg_database_size('caselaw'));

-- the statistics exist after the load
SELECT relname, n_live_tup, last_analyze FROM pg_stat_user_tables ORDER BY relname;

-- the plan of the heavy aggregate uses the index and does not spill
EXPLAIN (ANALYZE, BUFFERS)
SELECT c.key, count(*) AS mentions, count(DISTINCT c.decision_id) AS decisions
FROM citation c WHERE c.kind = 'statute' AND c.run_id = 'regex-v0.4'
GROUP BY c.key ORDER BY decisions DESC LIMIT 20;

-- the running parameters
SHOW shared_buffers; SHOW work_mem; SHOW effective_cache_size; SHOW random_page_cost;
```

Connect with `psql postgresql://caselaw:caselaw@localhost:5433/caselaw`. On the laptop the
`SHOW` statements return the defaults, because the local Compose file passes no `-c` options.
On the server, `scripts/hz.sh ssh` and then `docker compose ... exec postgres psql -U caselaw`
reaches the tuned instance. `pg_restore --list <dump>` prints the table of contents of a dump
without restoring it; that is the cheapest check that a backup file is complete.

The two tests that cover this layer are `tests/test_db.py` (loader, reload, Postgres against
DuckDB) and `tests/test_store_env.py` (DSN resolution, S3 endpoint).

## 8. Alternatives, and why not

- **RDS Postgres**, as in `infra/terraform/rds.tf`: engine 16, `backup_retention_period = 1`,
  the DSN built from a random password in Terraform. It is the design of report 8.6, written
  and validated, not applied. The whole AWS stack would cost about USD 47 per month; the
  Hetzner server costs under EUR 6. What is lost: managed snapshots and a database that
  outlives the server. What replaces them: the nightly `pg_dump` to R2.
- **DuckDB alone**, no database: works for `make demo` and for the tests. The single-decision
  lookup is 28 times slower, and one store sees one run. The API keeps this backend as an
  option, not as the deployment.
- **Postgres installed on the host** instead of a container. This is a general alternative,
  not one the report weighs. The container gives a pinned version, a named volume and a health
  check that Compose uses to order the start of the API.

## 9. Questions to be able to answer afterwards

- Why does a reload of a run not duplicate rows, and which SQL feature makes that one statement?
- What does `ANALYZE` change, and why did the first measurement on the server differ from the second?
- Which of the four parameters allocates memory, which one only informs the planner, and what does `random_page_cost=1.1` tell the planner about the disk?
- Why is `work_mem` not a per-connection limit, and what is the worst case with two workers?
- Where does the Postgres password exist, who can read each copy, and why does the API need `group_add`?
- Why does the exporter DSN carry `?sslmode=disable` and the API DSN not?
- What does `-Fc` give over a plain SQL dump, and how would you check a dump without restoring it?
- How does one SQL statement run on DuckDB and on Postgres, and what breaks the `?` rewrite?

## 10. Files

| file | role |
|---|---|
| `src/caselaw_extraction/sql/schema.sql` | six tables, six indexes, cascade on `run_id` |
| `src/caselaw_extraction/db.py` | `load_run` with COPY and ANALYZE, `load_statutes`, `open_run` for local and S3 paths |
| `src/caselaw_extraction/store.py` | `DuckDBStore`, `PostgresStore`, `dsn_from_env`, `open_store`, `DEFAULT_DSN` |
| `src/caselaw_extraction/cli.py`, command `db-load` | the loader command and its DSN resolution |
| `src/caselaw_extraction/api.py` | the aggregate cache and the warm-up that answer the slow aggregates |
| `infra/hetzner/compose.yml`, services `postgres` and `api` | tuning command, `POSTGRES_PASSWORD_FILE`, `CASELAW_DSN_FILE`, `group_add`, secrets |
| `infra/hetzner/cloud-init.yaml` | generation of the password and the two DSN files, their modes |
| `infra/hetzner/alloy/config.alloy` | `local.file "exporter_dsn"` and `prometheus.exporter.postgres` |
| `infra/hetzner/backup.sh` | nightly `pg_dump -Fc`, rclone to R2, 14-day retention |
| `scripts/hz.sh` | `load`, `backup-now`, the cron line |
| `infra/docker-compose.yml` | the local database on port 5433 |
| `.github/workflows/ci.yml` | the Postgres service container for the tests |
| `tests/test_db.py`, `tests/test_store_env.py` | loader and DSN tests |
| `docs/report.md`, sections 7.2, 7.4, 8.1, 8.2 | measured sizes, latencies and the deployment decisions |
