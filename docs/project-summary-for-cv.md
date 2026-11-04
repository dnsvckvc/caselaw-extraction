# Project summary for CV and cover-letter generation

Audience: an agent that turns this text into CV entries and cover-letter paragraphs. Every
number comes from `docs/report.md` or the repository state on 2026-11-04. Section 11 says
how authorship must be described. Section 12 lists keywords. Do not invent figures that are
not here.

## 1. Identity

| field | value |
|---|---|
| project name | Case-Law Extraction Pipeline |
| one-line description | End-to-end information-extraction system over Swiss Federal Supreme Court decisions: NER and entity linking, a citation graph, a read-only API, infrastructure as code, monitoring, backups and a drift check |
| owner | Denis Vuckovac (GitHub `dnsvckvc`) |
| period | 2026-10-20 to 2026-11-04, planned as four work weeks of about 20 hours each |
| status | complete except a five-minute screen recording |
| repository | https://github.com/dnsvckvc/caselaw-extraction (private at the time of writing; to be made public) |
| live API | https://api.caselaw.inat.io (OpenAPI docs at `/docs`) |
| live report | https://caselaw.inat.io |
| written report | `docs/report.md`, about 1,350 lines, with a management summary, ten numbered sections and a "what did not work" section |
| learning notes | `docs/learning/`, 13 notes, one per tool or layer |
| target roles | Lead Research Engineer, Thomson Reuters Labs (NER, information extraction, data pipelines, MLOps, cloud, tested code); Solution Architect Agentic AI, NVIDIA (secondary) |
| context | first of four planned portfolio projects; the next ones reuse the corpus, the API and the infrastructure |

## 2. Problem and outcome in two sentences

Swiss Federal Supreme Court decisions cite statutes, leading cases and file numbers in free
text, so questions such as "which articles are cited most" or "which decisions are central"
cannot be answered without extraction. The project extracts and links those citations from
7,999 decisions with a measured span F1 of 0.985 to 0.993, builds a citation graph of 19,622
nodes and 86,365 edges, and serves the results through a public API on infrastructure that
costs under EUR 6 per month.

## 3. Data

- Source: the CC0 dataset `voilaj/swiss-caselaw` on Hugging Face, filtered to German-language
  civil decisions of the Federal Supreme Court from 2020-01-06 to 2026-10-07: 7,999 decisions,
  25 MB as zstd Parquet.
- Statute reference data: the Fedlex SPARQL endpoint, cached as JSON, with a hand-checked list
  of 67 core act abbreviations and their SR numbers.
- Data-quality findings documented in week 1: the dataset's outcome column is missing for 27
  percent of decisions, and the extractor's outcome disagrees with the dataset label in 1,179
  of 5,806 decisions where both exist; sampling showed the dataset label to be the wrong one.

## 4. What was built, by week

### Week 1 (2026-10-20): corpus, schema, labelling setup

- Ingest of the corpus into Parquet; a Pydantic schema for decisions, spans and citations.
- Label Studio in Docker with a nine-label configuration and regex pre-annotation.
- A regex pre-annotator covering statute articles, BGE citations, file numbers, amounts and
  party roles, measured on the full corpus (STATUTE spans in 7,998 of 7,999 decisions).
- First gold batch of 60 decisions.

### Week 2 (2026-10-21 to 2026-10-28): gold set, five extractors, evaluation

- Gold set of 350 decisions and 16,783 spans in three batches (60, 90, 200), nine span classes
  (five citation classes and four negative classes such as contract clauses and journal
  references) and five outcome classes. Batch 3 was half targeted sampling toward rare classes
  and outcomes.
- Labelling method: two independent passes by language-model agents (two different model
  families) following a written annotation guideline, automatic agreement check, adjudication
  of the disagreements, a human spot check of 10 decisions with 0 errors in 358 spans. The
  guideline went through three versions; every change was re-applied to all batches.
- Five extractors compared on a held-out batch: rules (regex), the dataset's own citation
  graph as a silver baseline, spaCy NER trained from scratch, a fine-tuned German BERT token
  classifier with BIO tags and optional Viterbi decoding, and an LLM extractor with structured
  output.
- Entity-linking stage applied to every extractor: statute spans to Fedlex act and article,
  BGE spans to volume, part and page (with resolution of short same-volume citations from
  context), file numbers normalised and the decision's own number removed. Scores are reported
  before and after linking so that model errors stay visible.
- Learning curve over 15 to 105 training decisions, several seeds, 40 tracked runs.
- Results on the held-out batch: frozen rules span F1 0.985; tuned rules 0.999 (not held out);
  German BERT trained on 260 decisions 0.993, all 90 held-out outcomes correct (macro-F1 1.0);
  spaCy 0.985; LLM 0.985 at span level with the best entity-level score.
- All experiments tracked in MLflow: 127 runs with parameters, metrics and artifacts.

### Week 3 (2026-10-28): full-corpus run, database, graph, API

- Full-corpus extraction with Dask over 72 Parquet partitions: 3.8 seconds with 18 processes,
  9.7 seconds with one; the German BERT run took 30 minutes on the laptop GPU. Output: 294,884
  spans and 249,762 linked citations per run.
- Postgres schema and a bulk loader (COPY, then ANALYZE); the same SQL runs on DuckDB over the
  Parquet files for laptop use, through one store layer.
- Citation graph with NetworkX: 19,622 nodes, 86,365 edges, PageRank centrality, three headline
  analyses (most-cited articles, trend by year, most central decisions), an interactive HTML
  graph.
- Comparison of the rule-based and the model-based graphs: Jaccard 0.994 on statute edges,
  0.991 on BGE edges, identical top-20 lists. Decision documented: the rules go to production
  because the model changes no analysis at 185 times the compute.
- FastAPI service with 11 read-only endpoints, Pydantic models, generated OpenAPI schema,
  in-process cache for aggregate queries with HTTP cache headers and start-up warm-up.
- `make demo`: the whole pipeline on a 100-decision sample without a database or cloud.

### Week 4 (2026-10-29 to 2026-11-04): deployment, operations, drift

- Drift check: entity-frequency distributions per month or year compared with Jensen-Shannon
  and total-variation distance, largest movers, a period-to-period series and thresholds at
  the 95th percentile of that series (statute distance 0.49 over 81 months). Exposed as a CLI
  with a failing exit code and as two API endpoints. First flagged month: September 2026.
- Docker image of the API and loader with uv, core dependencies only; the ML stack lives in an
  optional extra.
- Two infrastructure-as-code targets in Terraform. Applied: one Hetzner Cloud server
  (2 vCPU, 4 GB) with firewall and SSH key, a Cloudflare R2 bucket, DNS records at Njalla,
  cloud-init provisioning. Validated but not applied: an AWS stack with S3, ECR, RDS Postgres,
  ECS Fargate behind a load balancer, CloudWatch dashboard and eight alarms, a GitHub OIDC
  deploy role; estimated at USD 47 per month against under EUR 6 on Hetzner.
- Server stack in Docker Compose: Postgres 16 with tuned memory settings, the API, Caddy with
  automatic Let's Encrypt certificates and HTTP-to-HTTPS redirect, Grafana Alloy under a
  Compose profile. Secrets reach containers as files, not environment variables.
- Secrets model: Terraform credentials only in 1Password, injected per process with the
  1Password CLI; the database password generated on the server; a scoped object-storage key
  with rights on one bucket; nothing secret in git.
- Monitoring with Grafana Cloud: host, container, Postgres and Caddy metrics, container logs
  in Loki, four integration dashboards, eight alert rules kept as a versioned file.
- Nightly backups: pg_dump and the run Parquet to R2 with rclone, 14-day retention; verified.
- Measured on the deployment: about 100 ms per request end to end over HTTPS from
  Switzerland, aggregate queries 0.8 to 1.3 s cold on the small server and under 0.2 s cached.
- GitHub Actions CI: ruff, pytest against a Postgres service container, image build,
  Terraform format and validate; green on the first push after two fixes. A deploy workflow
  to ECS is in place and skips until the AWS stack exists.
- 96 tests passing; coverage on the parsers and normalisers 85 to 100 percent.
- Thirteen learning notes documenting each tool, the setup by hand, the problems met and
  their lessons.

## 5. Technology stack

| layer | technologies |
|---|---|
| language and tooling | Python 3.12, uv, ruff, pytest with coverage, Makefile, typer CLI |
| data | Parquet, pyarrow, polars, DuckDB, Dask (distributed, local cluster), httpx, SPARQL (Fedlex) |
| NLP and ML | regex-based extraction, spaCy NER, Hugging Face transformers (German BERT, token classification, BIO tagging, Viterbi decoding), PyTorch, scikit-learn, LLM extraction with structured output (Claude), entity linking |
| labelling and experiments | Label Studio (Docker, REST API), MLflow (SQLite backend, 127 runs) |
| storage and serving | PostgreSQL 16 (COPY loader, tuning, pg_dump), FastAPI, Pydantic, uvicorn, OpenAPI |
| graph | NetworkX (PageRank), pyvis |
| containers | Docker (multi-stage image with uv), Docker Compose (secrets, profiles, health checks, named volumes) |
| infrastructure as code | Terraform with the Hetzner Cloud, Cloudflare and Njalla providers; an AWS stack (S3, ECR, RDS, ECS Fargate, ALB, CloudWatch, IAM OIDC) validated |
| cloud and operations | Hetzner Cloud, cloud-init, ufw, unattended upgrades, Caddy (ACME, reverse proxy), Cloudflare R2 (S3 API), rclone, Grafana Cloud (Mimir, Loki), Grafana Alloy (node_exporter, cAdvisor, postgres_exporter), healthchecks.io |
| security | 1Password CLI (`op run`, `op inject`, secret references), scoped API tokens, Compose file secrets, SSH keys, no secrets in git |
| CI/CD | GitHub Actions (service containers, uv cache, terraform validate), GitHub OIDC to AWS (designed) |
| statistics | Jensen-Shannon and total-variation distance, quantile thresholds, Jaccard agreement, precision, recall, F1 at span and entity level, macro-F1, Cohen-style agreement between annotation passes |

## 6. Quantified achievements, ready for CV bullets

Each line is one fact with its source section in `docs/report.md`.

- Built an extraction pipeline over 7,999 Swiss Federal Supreme Court decisions that links 249,762 citations to canonical statute, case and file-number keys (7.1).
- Reached span F1 0.993 held out with a fine-tuned German BERT trained on 260 gold decisions, and 0.985 with a frozen rule-based extractor; the two produce citation graphs that agree on 99 percent of edges (6.13, 7.6).
- Created a gold set of 350 decisions and 16,783 spans in nine classes with a two-pass labelling protocol, automatic agreement, adjudication and a human spot check with 0 errors in 358 spans (4).
- Compared five extraction approaches on a held-out set and chose the one that met the analysis goal at 185 times less compute, with the evidence written down (6.5, 7.6).
- Measured a learning curve from 15 to 105 training decisions to estimate the labelling budget for model parity with the rules (6.12).
- Tracked 127 experiment runs in MLflow with parameters, metrics and artifacts (management summary).
- Ran the full corpus under Dask in 3.8 seconds on 18 processes and loaded it into Postgres with the same SQL serving DuckDB on a laptop (7.1, 7.2).
- Built a citation graph of 19,622 nodes and 86,365 edges with PageRank centrality and three headline analyses (7.3).
- Served the results through a FastAPI service with 11 read-only endpoints, OpenAPI schema, caching and start-up warm-up; about 100 ms per request over HTTPS (7.4, 8.2).
- Designed a statistical drift check with Jensen-Shannon distance and p95 thresholds over 81 months that flagged the first anomalous month (8.4).
- Deployed with Terraform on Hetzner Cloud for under EUR 6 per month, with automatic TLS, nightly backups to object storage and Grafana Cloud monitoring with eight alert rules; also wrote and validated the equivalent AWS stack at about USD 47 per month (8.1, 8.3, 8.5, 8.6).
- Set up a secrets model with no credential on disk or in git: 1Password CLI injection for Terraform, server-generated database passwords, scoped object-storage keys (8.1, `docs/learning/07-secrets-1password.md`).
- Wrote 96 tests with CI on GitHub Actions against a Postgres service container; coverage on parsers and normalisers 85 to 100 percent.
- Documented the system in a 1,350-line report with a management summary and a "what did not work" section, plus 13 learning notes.

## 7. Engineering decisions worth a cover-letter sentence

- Rules in production, model in reserve: the held-out comparison and the graph agreement
  showed the learned model changed no analysis, so the cheaper extractor ships and the model
  is kept for citation forms without rules and for other languages.
- One SQL layer, two backends: the same queries run on DuckDB over Parquet on a laptop and on
  Postgres in production, so every analysis is reproducible without cloud access.
- Entity linking as a separate stage: it carries the world knowledge (which abbreviations are
  federal acts, which file number is the decision's own) for every extractor alike, and the
  before-and-after scores keep model failures visible.
- Gold set with negative classes: four classes of near-misses (contract clauses, bare article
  numbers, cantonal law, journal references) were added after the first models confused them
  with citations, and the models were retrained.
- Cost-driven cloud choice: the AWS design was written and validated, then a single-server
  deployment was chosen with the numbers in the report, and the AWS design kept as the
  documented second target.
- Operations before features: backups, monitoring, alert rules, a drift check and a secrets
  model were part of the four weeks, not a later phase.

## 8. Problems met and solved (evidence of debugging depth)

- R2 object storage returned HTTP 501 to rclone's post-upload check because of a version id
  header; diagnosed with request dumps, fixed with one flag, documented.
- cAdvisor could not read containers under Docker 29's containerd image store; switched the
  server to the overlay2 driver through cloud-init.
- Grafana integrations select by fixed job labels; relabelled all targets so dashboards and
  tests match.
- Compose bind mounts of single files follow the inode; rsync replaced the file and the
  containers kept the old one; fixed with in-place writes and reloads in the deploy script.
- Container could not read a secret file because the host group id differed from the image's;
  fixed with `group_add` and a gid passed from the host.
- Slow aggregate queries on a 2 vCPU server; fixed with ANALYZE after bulk load, Postgres
  memory tuning, an in-process cache with HTTP cache headers and start-up warm-up (2.9 s to
  0.3 s on the drift endpoint).
- networkx's PageRank needed scipy, which only the ML extra had installed; found by the first
  CI run, fixed in the dependency list.
- A credential was printed by a debug flag during troubleshooting; the key was rolled the same
  hour and the incident is written into the learning notes.

## 9. What did not work or is limited (keep the CV honest)

- The gold set was labelled by language-model agents under a written guideline, not by legal
  professionals; one human check covers 10 of 350 decisions. The agents corrected proposals
  from the rules, which favours the rules in every comparison.
- The learned models did not beat the frozen rules until 260 training decisions were available.
- The deployment is one server without a load balancer or managed database; recovery is a
  nightly dump plus a six-second rebuild from Parquet.
- The AWS stack is validated, not applied; its costs are estimates from price pages.
- The LLM extractor was evaluated on the held-out batch, not run over the corpus (estimated
  USD 140 per run).
- Only German-language civil decisions are covered.

## 10. Skills demonstrated, grouped as a CV would group them

- Machine learning and NLP: named-entity recognition, token classification with transformers,
  BIO decoding, entity linking, evaluation design (span versus entity level, held-out sets,
  learning curves), LLM extraction with structured output, drift detection.
- Data engineering: Parquet pipelines, Dask parallelism, DuckDB and Postgres, bulk loading,
  schema design, graph analysis with NetworkX.
- MLOps: experiment tracking (MLflow), labelling operations (Label Studio, agreement,
  adjudication), reproducible runs, model-versus-rules decision with evidence.
- Backend: FastAPI, Pydantic, OpenAPI, caching, health checks, performance measurement.
- Cloud and infrastructure: Terraform (three providers plus an AWS design), Hetzner Cloud,
  cloud-init, Docker Compose, Caddy with ACME, object storage with the S3 API, backups.
- Observability: Prometheus-style metrics, Loki logs, Grafana dashboards and alert rules,
  exporters, relabelling, cardinality.
- Security: secrets management with 1Password CLI, scoped tokens, file-based secrets, key
  rotation, least privilege on tokens.
- Software engineering: tests with CI, coverage targets, linting, Makefile workflows,
  documentation (report, learning notes, runbook-style READMEs).
- Domain: Swiss federal law citation conventions, Fedlex, BGE and file-number formats.

## 11. How to describe authorship

The project was built by Denis Vuckovac with an AI coding assistant (Claude) as pair
programmer. Denis set the goals and constraints, chose between options at every decision
point (extractor choice, guideline rules, cloud provider, secrets model, what to cut),
performed the human spot check of the gold set, operated all external accounts (Hetzner,
Cloudflare, Njalla, Grafana Cloud, GitHub, 1Password) and verified the results. The
assistant wrote most of the code and prose under that direction. The gold set was labelled
by language-model agents under a written guideline and checked by Denis.

Acceptable phrasings: "built with AI-assisted development", "designed and directed; code
produced with an AI pair programmer and reviewed", "AI-assisted labelling with human
adjudication and spot check". Do not claim hand-written code or professional legal
annotation. Do claim the design decisions, the evaluation discipline, the operations work
and the documented reasoning, which are the parts a reviewer can verify in the repository.

## 12. Keywords for matching

NER, named-entity recognition, information extraction, entity linking, token classification,
BERT, German BERT, transformers, PyTorch, spaCy, LLM, structured output, Claude, evaluation,
F1, held-out, learning curve, annotation guideline, Label Studio, gold set, inter-annotator
agreement, MLflow, experiment tracking, MLOps, Dask, Parquet, pyarrow, polars, DuckDB,
PostgreSQL, SQL, FastAPI, Pydantic, OpenAPI, REST API, NetworkX, PageRank, citation graph,
drift detection, Jensen-Shannon, Terraform, infrastructure as code, Hetzner, AWS, ECS
Fargate, RDS, S3, ECR, CloudWatch, IAM OIDC, Docker, Docker Compose, Caddy, TLS, Let's
Encrypt, Cloudflare R2, rclone, backups, Grafana Cloud, Grafana Alloy, Prometheus, Loki,
observability, alerting, cloud-init, Linux, SSH, 1Password CLI, secrets management, GitHub
Actions, CI/CD, pytest, ruff, uv, Python 3.12, legal tech, Swiss law, Federal Supreme Court,
Fedlex, BGE, regulated domain, documentation.

## 13. Links and files for a reviewer

| what | where |
|---|---|
| report with management summary | `docs/report.md`, or https://caselaw.inat.io |
| API documentation | https://api.caselaw.inat.io/docs |
| extractor comparison table | `docs/report.md` section 6.5 and 6.13 |
| gold-set method | `docs/report.md` section 4, `docs/annotation-guideline.md` |
| infrastructure | `infra/hetzner/` (applied), `infra/terraform/` (AWS, validated) |
| monitoring and alert rules | `infra/hetzner/alloy/config.alloy`, `infra/hetzner/grafana/` |
| CI | `.github/workflows/ci.yml` |
| learning notes | `docs/learning/README.md` |
| demo without cloud | `make demo` |
