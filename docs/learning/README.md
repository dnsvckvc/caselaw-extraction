# Learning notes

One note per tool or layer of this project. Each note explains what the tool does, how it
works, how this repository uses it, what went wrong while setting it up, how to verify it,
which alternatives were considered, and which questions a reader should be able to answer
afterwards. The notes are written for someone who would build the same system by hand.

The numbers give the suggested reading order. It follows the order in which the system was
built: first the data and the models, then the serving layer, then the server and its
operation, and last the pipeline that would automate it. Each note stands on its own, so a
reader who only wants one tool can start there.

Part 1, data and models (weeks 1 to 3):

1. [Labelling and experiment tracking](01-mlflow-and-label-studio.md): how the gold set was made in Label Studio, and how MLflow records every extractor run.
2. [Extractors and evaluation](02-ner-extractors-and-evaluation.md): regex, spaCy, the transformer and the LLM extractor, entity linking, the scores, and the drift check.
3. [The corpus run](03-dask-corpus-run.md): the full-corpus extraction with Dask and the Parquet run directories.

Part 2, serving (week 3):

4. [Postgres](04-postgres.md): the schema, the loader, tuning, backups, the exporter, and DuckDB beside it.
5. [The API](05-fastapi-serving.md): FastAPI, OpenAPI, caching, health checks, measured latency.

Part 3, the server and its operation (week 4):

6. [Docker and Compose](06-docker-compose.md): the image, the services, secrets as files, profiles, mounts.
7. [Secrets](07-secrets-1password.md): where each secret lives, the 1Password CLI, what must never be on disk.
8. [Terraform](08-terraform.md): the Hetzner, Cloudflare and Njalla providers, state, plan and apply.
9. [The server](09-hetzner-cloud-init-deploy.md): Hetzner, cloud-init, hardening, the deploy script.
10. [Caddy, TLS and DNS](10-caddy-tls-dns.md): certificates, the reverse proxy, the DNS records.
11. [Object storage](11-cloudflare-r2-rclone.md): R2, the S3 API, scoped keys, rclone, pyarrow.
12. [Monitoring](12-grafana.md): Grafana Cloud and Alloy, metrics, logs, integrations, alerting.

Part 4, automation and the alternative:

13. [CI and the AWS design](13-ci-github-actions-and-aws.md): the GitHub Actions workflows, and the AWS stack kept as the second target.

Part 5, the cheap classifier (pilot of 2026-11-05):

14. [The routine filter explained](14-jev-routine-filter-explained.md): what Jev 1.14 was tested on, and why the regex baseline looks for "BGG".

Two shorter paths:

- For the deployment only, read 6 to 12.
- For the machine-learning work only, read 1 to 3.
