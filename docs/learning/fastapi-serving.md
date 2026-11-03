# FastAPI serving: the read-only API, its cache, its container, and how we test it

This note explains the API of the caselaw project. It is written for someone who would build
the same service by hand and wants to understand each piece before copying it. The code is
`src/caselaw_extraction/api.py` and `src/caselaw_extraction/store.py`. The container is the
`api` service in `infra/hetzner/compose.yml`. The report covers the API in sections 7.4 and 8.2.

## 1. The problem the API solves here

The extraction run produces three tables: decisions, spans and citations. The citation graph
adds a centrality table. These tables sit in Postgres on the server, or in Parquet files on a
laptop. Someone who wants a decision with its citations, or the most-cited articles, should
not need SQL. The API answers those questions over HTTPS and documents itself.

Three constraints shaped the design. The data never changes while the service runs. The
server is small: 2 shared vCPU and 4 GB, where one aggregate took 1.1 seconds (report, 8.2).
The same code must run on a laptop without Postgres, for `make demo` and for the tests.

## 2. The vocabulary

**FastAPI.** A Python web framework. You declare a function with typed parameters and a
decorator such as `@app.get("/health")`. FastAPI parses the query string, validates the
types, calls the function and serialises the result as JSON. This is general FastAPI
behaviour.

**Pydantic model.** A class that declares the fields of a JSON object with their types. In
`api.py`, `Health`, `DecisionOut`, `CitationOut` and the others are Pydantic models. A field
without a default is required. `Field(description=...)` adds text that appears in the schema.

**`response_model`.** The Pydantic model that an endpoint returns. FastAPI validates the
return value against it and uses it to build the OpenAPI schema.

**OpenAPI.** A JSON description of every path, parameter, response and schema of an API.
FastAPI generates it at `/openapi.json`. The page at `/docs` is Swagger UI, which renders the
same JSON as an interactive page. Nobody writes this file by hand.

**Lifespan.** An async context manager that FastAPI runs once at startup and once at
shutdown. The code before `yield` runs at startup. The code after `yield` runs at shutdown.

**Dependency.** A function that FastAPI calls to supply a parameter. `get_store` reads the
store from `request.app.state.store`. `StoreDep` is the annotated type that every endpoint
uses for its `store` parameter.

**Store.** The one query interface of this project. It has a `backend` name, a `run_id` and a
`query(sql, params)` method that returns a list of dicts.

**LRU cache.** A dict with a size limit. On each hit the entry moves to the end. When the
dict is full, the oldest entry at the front is removed. `api.py` builds one from an
`OrderedDict`.

**`Cache-Control`.** An HTTP response header that tells a browser or a proxy how long it may
reuse a response. `public` means any cache may store it. `max-age=3600` means the copy is
fresh for 3,600 seconds. This is general HTTP behaviour.

**uvicorn.** The ASGI server that runs the FastAPI app. With `--workers 2` it starts two
processes, each with its own memory and its own cache.

**TestClient.** A FastAPI test helper that calls the app in process, without a network port.
Used as a context manager, it runs the lifespan handler.

## 3. How the pieces connect

```
 laptop in Switzerland                        server (Hetzner cx23)
 curl / browser                               +------------------------------------------------+
   |  https://api.caselaw.inat.io             |  Caddy :443   TLS, zstd/gzip, CORS header       |
   +----------------------------------------->|    reverse_proxy api:8000 (Docker network only)  |
                                              |         |                                        |
                                              |         v                                        |
                                              |  hetzner-api-1   uvicorn, 2 workers, :8000       |
                                              |    each worker:  FastAPI app                     |
                                              |      lifespan -> open_store() -> warm_cache()    |
                                              |      endpoint -> cached() -> _CACHE (LRU, 512)   |
                                              |                      miss -> graph.* / drift.*   |
                                              |                                 |                |
                                              |                          Store.query(sql)        |
                                              |                                 |                |
                                              |                          PostgresStore -> :5432  |
                                              +------------------------------------------------+

 laptop, make demo and tests:  same app, DuckDBStore -> views over data/runs/<run>/*.parquet
```

Port 8000 is not published: the `api` service has no `ports:` entry. Only Caddy, in the same
Compose network, reaches it. `EXPOSE 8000` in the Dockerfile is documentation and opens nothing.

## 4. The API in depth

### 4.1 The models

`SpanOut` holds `start`, `end`, `label` and `text`. `CitationOut` holds the citation fields
and one `SpanOut`. Its required fields are `kind`, `key` and `span`, because the others have
`None` as default. `DecisionOut` extends `DecisionSummary` with `citations` and `spans`.
`DecisionPage` wraps a list of summaries with `total`, `limit` and `offset`. The two drift
endpoints return `dict[str, Any]`, so their schema is a free-form object.

### 4.2 The lifespan handler

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.store = open_store()
    warm_cache(app.state.store)
    yield
    app.state.store.close()
```

The store is opened once per process and kept on `app.state`. Every request reuses the same
connection. At shutdown the connection is closed. With two uvicorn workers, this runs twice,
once in each process. That is general uvicorn behaviour.

### 4.3 The endpoints

| path | returns | cached |
|---|---|---|
| `GET /health` | `status`, `backend`, `run_id`, `api_version` | no |
| `GET /runs` | every row of `extraction_run`: `run_id`, `extractor` | no |
| `GET /decisions` | a page of decision summaries, newest first, with `total` | no |
| `GET /decisions/{decision_id}` | one decision, its citations with spans, all spans | no |
| `GET /decisions/central` | most central nodes by PageRank or in-degree | yes |
| `GET /statutes/top` | most-cited statute articles, optional `year` and `code` filter | yes |
| `GET /statutes/codes` | most-cited acts | yes |
| `GET /trends/years` | citations per decision and BGE age, per year | yes |
| `GET /trends/code-share` | share of decisions per year that cite six main acts | yes |
| `GET /drift` | distributions of period `a` against period `b` | yes |
| `GET /drift/series` | distance between each period and the one before | yes |

Three details of the endpoints deserve attention.

**Route order.** `/decisions/central` is declared before `/decisions/{decision_id}`. FastAPI
matches routes in declaration order. In the reverse order, the word `central` would be read
as a decision id and the endpoint would answer 404. This is general FastAPI behaviour.

**Validation produces 422.** `limit` is declared as `Query(50, ge=1, le=500)`. The parameter
`by` has `pattern="^(pagerank|in_degree)$"`. A value outside these rules gets status 422
before the function runs. The tests check `limit=0` and `by=degree`.

**The filters on `/decisions`.** Each of `statute`, `bge` and `docket` adds an `EXISTS`
subquery on the `citation` table. A docket value has `/` and `.` replaced with `_`, so
`4A_12/2020` and `4A_12_2020` find the same rows. The query computes `count(*) OVER ()` so
that one statement returns the page and the total.

### 4.4 The in-process cache

```python
_CACHE: OrderedDict[tuple, Any] = OrderedDict()
CACHE_MAX = 512
CACHE_CONTROL = "public, max-age=3600"
```

The key of an entry is `(store.backend, store.run_id, *key)`. The endpoint supplies the rest
of the key from its parameters, for example `("statutes_top", limit, year, code)`. Two
requests with the same parameters share one entry. When the dict holds more than 512 entries,
`popitem(last=False)` removes the oldest. The limit protects the memory of the process. The
`/drift` endpoint takes two free-text periods, so a client could create many distinct keys.

The function `cached()` does two things. It sets the `Cache-Control` header on the response.
It then returns the cached value or computes it. Only the aggregate endpoints call `cached()`.
`/decisions` and `/decisions/{decision_id}` do not, so they send no `Cache-Control` header.

### 4.5 What `Cache-Control: public, max-age=3600` does here

A browser that fetches `/statutes/top?limit=20` keeps the response for one hour. A second
visit to the same URL within the hour does not reach the server. Caddy, in this
configuration, does not cache. Its `reverse_proxy` passes the header through unchanged. The
word `public` would allow a shared cache between Caddy and the browser to store the response.
No such cache exists in this stack, so the header matters for browsers only. This paragraph
describes general HTTP and Caddy behaviour.

The header is correct only because a run never changes while the service runs. A new run is
loaded with `make hz-load` and selected with `CASELAW_RUN` at the next container start.

### 4.6 The warm-up at startup

`warm_cache()` runs inside the lifespan handler. It fills four entries:

- `("statutes_top", 20, None, None)`, the default view of `/statutes/top`
- `("codes", 20)`, the default view of `/statutes/codes`
- `("trend_years",)`, the only view of `/trends/years`
- `("central", 20, "pagerank", None)`, the default view of `/decisions/central`

The keys match the default parameters of the endpoints exactly. A warm-up with
`("central", 20)` would compute the data and never be hit. Each job runs inside
`contextlib.suppress(Exception)`, so a failing warm-up does not stop the service. The
switch `CASELAW_WARM=0` turns the warm-up off. The tests do not set it, so the warm-up runs
on the synthetic run too.

`/trends/code-share`, `/drift` and `/drift/series` are not warmed.

### 4.7 The two backends behind one store

`store.py` defines `Store` and two implementations.

`DuckDBStore` opens an in-memory DuckDB connection. For each Parquet file of the run directory
it creates a view with the Postgres column names (`start_char`, `end_char`) and a constant
`run_id` column. Nothing is copied. The view `extraction_run` reads the extractor name from
`run.json`.

`PostgresStore` opens one `psycopg` connection with `dict_row` and `autocommit=True`. Its
`query()` replaces every `?` with `%s`, because psycopg uses `%s` as placeholder. The `run_id`
comes from the constructor and selects the run inside the loaded database.

`open_store()` picks the backend from `CASELAW_BACKEND`. Without that variable, it picks
Postgres when a DSN exists, else DuckDB. The DSN comes from `CASELAW_DSN`, else from the file
named by `CASELAW_DSN_FILE`, which on the server is the Compose secret
`/run/secrets/caselaw_dsn`. `CASELAW_RUNS_DIR` moves the Parquet runs, which the tests use.

Every SQL statement in `api.py`, `graph.py` and `drift.py` is written once and runs on both
backends. The report, section 7.4, states that the smoke run returned identical numbers on
both.

### 4.8 uvicorn in the container

The last line of the Dockerfile is:

```
CMD ["uvicorn", "caselaw_extraction.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

The host `0.0.0.0` makes the process reachable from other containers. Two workers mean two
processes, two store connections and two caches. The Grafana note observes one Postgres
connection per worker. The image runs as user `app` with uid 1000. It sets
`CASELAW_BACKEND=postgres` and `CASELAW_RUN=regex-v0.4` as defaults.

Caddy in `infra/hetzner/Caddyfile` forwards the API host with `reverse_proxy api:8000`. It
adds `encode zstd gzip`, `Strict-Transport-Security`, `X-Content-Type-Options nosniff` and
`Access-Control-Allow-Origin *`. The last header lets a page on another origin call the API.

### 4.9 The Compose health check

```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 20s
```

The check is written in Python because the image has no `curl`. The base image is
`python:3.12-slim-bookworm` and the Dockerfile installs no system packages. The check runs
inside the container, so `localhost:8000` is correct even though the port is not published.
`caddy` has `depends_on: api: { condition: service_healthy }`, so Caddy starts only after
this check passes. The 20-second `start_period` gives the warm-up time before failures count.

## 5. Walkthrough by hand

### 5.1 On the laptop

1. Run `make api`. The default backend is DuckDB over `data/runs/regex-v0.4`.
2. Open `http://127.0.0.1:8000/docs`. Swagger UI shows the eleven paths.
3. Open `http://127.0.0.1:8000/openapi.json`. This is the JSON that the contract test reads.
4. Request `/statutes/top?limit=3` twice. The second answer should come from the cache.
5. If you want Postgres, run `make db-up`, then `make db-load`, then `make api BACKEND=postgres`.
   The field `backend` of `/health` should then read `postgres`.

### 5.2 Against the server

1. Run `make hz-smoke`. It requests `/health`, `/runs` and `/statutes/top?limit=3`, then the site.
2. Run `make hz-measure`. It sends 30 requests per path and prints p50 and p95 in ms.

`hz.sh measure` reads one decision id from `/decisions?limit=1` first. It then measures seven
paths: `/health`, `/decisions/<id>`, `/statutes/top?limit=20`, `/trends/years`,
`/decisions/central?limit=20`, `/decisions?statute=BGG 42&limit=50` and
`/drift?a=2026-08&b=2026-09`. Both commands read the URL from `terraform output`.

## 6. What went wrong, and what each mistake teaches

The evidence for this section is the commit `b82bdd0` of 2026-11-03, the report section 8.2
and the comments in `api.py`. The code has no incident log beyond these.

**The aggregates were slow on the small server.** On the laptop the aggregate endpoints
answered in 10 to 100 ms (report, section 7.4). On the 2 vCPU server, `/statutes/top` took
1.1 seconds in `EXPLAIN ANALYZE`: an index scan over 138,143 citation rows, then a sort for
`count(DISTINCT)`. Before `ANALYZE` had run, the first measurement was 1.3 seconds. Lesson: a
query that is fast on a laptop with many cores behaves differently on a shared 2 vCPU server.
Measure on the target.

**Three fixes went in together.** Commit `b82bdd0` added the in-process cache, the
`Cache-Control` header and the warm-up. The same commit tuned Postgres for 4 GB
(`shared_buffers=512MB`, `work_mem=32MB`) and added `ANALYZE` after every load. Lesson: when
the data is static, caching the result is cheaper than making the query fast. The cache also
removes the load from Postgres for the common views.

**The drift report counted every month.** The first version counted all 81 months and then
compared two. Counting only the two periods under comparison took it from 2.9 seconds to 0.3
(report, section 8.2; `drift._counts_sql` takes `n_periods`). Lesson: an endpoint with two
parameters should read only the rows those parameters select.

**Two deployment faults touched the API container.** Commit `1542125` records them. The
secret file was unreadable until `group_add` joined the group with gid 1001. The Fedlex cache
write failed in a read-only directory. Neither fault is in `api.py`.

## 7. How to verify

### 7.1 The measured latencies

The report, section 8.2, measured from a laptop in Switzerland over HTTPS. Each request opened
a new TLS connection. "First" is the first request after a restart. "Warm" is the median of
nine more.

| endpoint | first | warm |
|---|---|---|
| `/health` | 177 ms | 101 ms |
| `/decisions/{id}` | 123 ms | 104 ms |
| `/decisions?statute=BGG 42&limit=50` | 262 ms | 174 ms |
| `/statutes/top?limit=20` | 1,267 ms | 101 ms |
| `/statutes/codes` | 883 ms | 102 ms |
| `/trends/years` | 843 ms | 101 ms |
| `/decisions/central?limit=20` | 110 ms | 100 ms |
| `/drift?a=2026-08&b=2026-09` | 322 ms | 103 ms |
| `/drift/series?kind=code` | 1,042 ms | 119 ms |

How to read the table. The 100 ms floor is the network. The TLS handshake alone took 50 to
500 ms in the samples. The server answers `/health` in under a millisecond. The "first" column
of the aggregates shows the cost of a cache miss. The "warm" column shows a cache hit, which
is the network floor. `/decisions?statute=...` is not cached and stays at 174 ms. The report
does not say whether the "first" column was measured with the warm-up on.

On the laptop, section 7.4 gives 5 ms for one decision on Postgres and 140 ms on DuckDB (the
Parquet scan).

### 7.2 The tests

`tests/test_api.py` runs the app over the DuckDB backend on a synthetic run of three
decisions. The fixture sets `CASELAW_BACKEND=duckdb`, `CASELAW_RUN=synthetic` and
`CASELAW_RUNS_DIR`, then imports the app and enters `TestClient(app)`. The context manager
runs the lifespan, so `open_store()` reads the variables at that moment. No database and no
real data are needed. Run them with `uv run pytest tests/test_api.py`.

The seven tests check:

- `/health` and `/runs` return the synthetic run with the `regex` extractor.
- `/decisions/bger_4A_1_2021` returns citations of all three kinds, each with a span. An
  unknown id returns 404.
- The filters `statute`, `bge`, `docket`, `year` and `outcome` return the expected totals.
  `limit=0` returns 422.
- The aggregate endpoints return the expected first rows. `by=degree` returns 422.
- The OpenAPI document has exactly the eleven paths and the named schemas.
- `/drift` returns 200 for two known years and 404 for an unknown year. `period=week` is 422.
- `/statutes/top?limit=5` carries `cache-control: public, max-age=3600`, and a second call
  returns the same body. `/decisions?limit=1` has no `cache-control` header.

### 7.3 The contract test idea

A contract test checks the shape of the API, not the data. Clients depend on the shape: the
paths, the field names, which fields are always present. `test_openapi_contract` reads
`/openapi.json` and asserts three things.

The set of paths is equal to a fixed set of eleven. A renamed, removed or added endpoint
fails the test until someone changes the set on purpose. A change of the contract must be
visible in the test diff.

The schemas `DecisionOut`, `CitationOut`, `SpanOut`, `StatuteCount`, `YearTrend` and
`CentralNode` exist. A model removed from a `response_model` disappears from the schema.

`CitationOut.required` is exactly `["kind", "key", "span"]`. Pydantic marks a field as
required when it has no default. Removing the `None` default from `sr` would tell clients that
`sr` is always present. Giving `key` a default would let it disappear. The assertion protects
both directions.

## 8. Alternatives, and why not

- **Redis or another external cache.** One more container on a 4 GB server, for 512 entries
  that fit in a dict. The in-process cache has one cost: two workers hold two copies.
- **Materialised views in Postgres.** They would make the aggregates fast on every parameter
  combination. The cache is one function and needs no schema change.
- **Caching in Caddy.** Caddy's standard build has no response cache; a plugin would be
  needed. The header is already set, so a cache could be added later without touching the API.
- **Flask or Django REST.** FastAPI generates the OpenAPI document from the type hints. The
  contract test and `/docs` come with it. The week-3 commit names the OpenAPI schema as a
  feature of the service.

## 9. Questions to be able to answer afterwards

- What happens if `/decisions/{decision_id}` is declared before `/decisions/central`?
- Why is the cache key prefixed with `store.backend` and `store.run_id`?
- Why must the warm-up keys match the endpoint defaults exactly?
- Where does `Cache-Control: public, max-age=3600` take effect in this stack, and where not?
- Why does the lifespan handler run twice on the server?
- Why is the health check written in Python, and why does `localhost:8000` work inside it?
- What does the assertion on `CitationOut.required` protect a client from?

## 10. Files

| file | role |
|---|---|
| `src/caselaw_extraction/api.py` | the app, the models, the endpoints, the cache, the warm-up |
| `src/caselaw_extraction/store.py` | `Store`, `DuckDBStore`, `PostgresStore`, `open_store` |
| `src/caselaw_extraction/graph.py` | `top_statutes`, `top_codes`, `trend_by_year`, `central_decisions`, `code_share_by_year` |
| `src/caselaw_extraction/drift.py` | `drift_report`, `drift_series`, the two-period counting |
| `src/caselaw_extraction/cli.py`, command `api` | `uvicorn.run` for `make api` |
| `tests/test_api.py` | the contract test over the synthetic run |
| `tests/conftest.py`, fixture `synthetic_run` | the three-decision run the tests read |
| `Dockerfile` | the image, user `app`, the uvicorn command with two workers |
| `infra/hetzner/compose.yml`, service `api` | environment, secret file, the Python health check |
| `infra/hetzner/Caddyfile` | `reverse_proxy api:8000`, compression, CORS header |
| `scripts/hz.sh`, commands `smoke` and `measure` | the checks against the live URL |
| `Makefile` | `api`, `db-up`, `db-load`, `hz-smoke`, `hz-measure` |
| `docs/report.md`, sections 7.4 and 8.2 | the endpoint table and the measured latencies |
