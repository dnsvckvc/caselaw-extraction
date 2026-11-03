# Learning notes

One note per tool or layer of this project. Each note explains what the tool does, how it
works, how this repository uses it, what went wrong while setting it up, how to verify it,
which alternatives were considered, and which questions a reader should be able to answer
afterwards. The notes are written for someone who would build the same system by hand.

Infrastructure and operations:

- [grafana.md](grafana.md): Grafana Cloud and Grafana Alloy, metrics, logs, integrations, alerting.
- [terraform.md](terraform.md): Terraform, the Hetzner, Cloudflare and Njalla providers, state, plan and apply.
- [hetzner-cloud-init-deploy.md](hetzner-cloud-init-deploy.md): the server, cloud-init, hardening, the deploy script.
- [docker-compose.md](docker-compose.md): the image, Compose services, secrets, profiles, health checks, mounts.
- [caddy-tls-dns.md](caddy-tls-dns.md): Caddy, Let's Encrypt certificates, reverse proxy, DNS records.
- [postgres.md](postgres.md): Postgres in a container, tuning, the loader, backups, the exporter, DuckDB beside it.
- [cloudflare-r2-rclone.md](cloudflare-r2-rclone.md): object storage, the S3 API, scoped keys, rclone, pyarrow.
- [secrets-1password.md](secrets-1password.md): where each secret lives, 1Password CLI, what must never be on disk.
- [fastapi-serving.md](fastapi-serving.md): the API, OpenAPI, caching, health checks, measured latency.
- [ci-github-actions-and-aws.md](ci-github-actions-and-aws.md): the CI pipeline, the deploy workflow, the AWS design kept as the second target.

Data and models:

- [dask-corpus-run.md](dask-corpus-run.md): the full-corpus extraction run with Dask and Parquet.
- [mlflow-and-label-studio.md](mlflow-and-label-studio.md): experiment tracking and the gold-set labelling setup.
- [ner-extractors-and-evaluation.md](ner-extractors-and-evaluation.md): regex, spaCy, transformer and LLM extractors, linking, scoring, drift.
