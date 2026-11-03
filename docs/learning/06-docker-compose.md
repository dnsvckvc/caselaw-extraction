# Docker and Docker Compose: the image, the stack on the server, what we learned

This note explains the container layer of the caselaw deployment. It is written for someone
who would build the same thing by hand and wants to understand each piece before copying it.
The files are `Dockerfile` and `.dockerignore` at the repository root,
`infra/hetzner/compose.yml`, `infra/hetzner/cloud-init.yaml` and `scripts/hz.sh`. The report
discusses the deployment in sections 8.1 and 8.2 of `docs/report.md`.

## 1. The problem containers solve here

The server is one Hetzner machine with Ubuntu, 2 vCPUs and 4 GB of memory. On it we need
four programs with different runtimes: Postgres 16, a Python 3.12 API, Caddy for TLS, and
Grafana Alloy for monitoring. Each has its own files, its own user and its own upgrade cycle.

Without containers, each program would be installed with apt or pip on the host. With
containers, each program is one image with a fixed version. Compose starts them in order,
connects them on a private network, restarts them after a crash, and gives them their
secrets as files. The whole stack is one file of 110 lines and one command. The same image
serves the API and the loader `caselaw db-load`, which runs in it as a one-off command.

## 2. The vocabulary

The definitions below describe general Docker and Compose behaviour.

**Image and layer.** An image is a stack of read-only filesystem layers plus metadata. Each
Dockerfile instruction adds a layer. Docker reuses a cached layer while its inputs are unchanged.

**Build context.** The directory that `docker build` sends to the daemon. `COPY` can only read
files from it. `.dockerignore` removes files from the context before it is sent.

**Multi-stage build.** A Dockerfile with more than one `FROM`. A later stage copies files from
an earlier stage with `COPY --from`. Only the last stage becomes the image.

**Service and project.** A service is one entry under `services:`. Compose names containers
after the project, which defaults to the directory of the Compose file. Our file lives in
`infra/hetzner`, so the containers are `hetzner-postgres-1`, `hetzner-api-1` and so on.

**Named volume and bind mount.** A named volume is storage that Docker manages under
`/var/lib/docker/volumes`. A bind mount is a host path mapped into the container, either a
directory or a single file.

**Compose secret.** A file on the host that Compose mounts read-only at `/run/secrets/<name>`.
The content never appears in the container's environment.

**Profile.** A label on a service. Compose starts the service only when the command line
names the profile with `--profile`.

**Health check.** A command that Docker runs inside the container at an interval. The
container is `healthy` when the command exits with 0. Other services can wait for that state.

## 3. How the pieces connect

```
 laptop                                   server (Hetzner cx23, Ubuntu 24.04)
 +------------------+                     +-----------------------------------------------+
 | scripts/hz.sh    |  rsync --inplace    | /opt/caselaw/repo        (the checkout)       |
 |   deploy  -------+-------------------->|   infra/hetzner/compose.yml                   |
 |                  |  ssh: compose build | /etc/caselaw/caselaw.env  (hz.sh secrets)     |
 |                  |       compose up -d | /etc/caselaw/hosts.env    (cloud-init)        |
 +------------------+                     | /etc/caselaw/secrets/*    (cloud-init)        |
                                          |                                               |
   :80 :443                               |  Compose network "hetzner_default"            |
   ----------------------------------------->  caddy  --(api:8000)-->  api                |
                                          |     |  :2020                 |  /run/secrets/ |
                                          |     |                        |  caselaw_dsn   |
                                          |   alloy (profile monitoring) |                |
                                          |     |  /run/secrets/exporter_dsn              |
                                          |     +----------------------> postgres         |
                                          |                               /run/secrets/   |
                                          |                               postgres_password|
                                          |  volumes: pgdata caddy_data caddy_config      |
                                          |           alloy_data                           |
                                          +-----------------------------------------------+
```

Only Caddy publishes ports. The API listens on 8000 inside the network, and Postgres on 5432.
Nothing outside the server can reach them. Each service finds the others by name. Docker's
internal DNS resolves `postgres`, `api` and `caddy` to the current container address. Three
files use these names: the DSN that cloud-init writes contains `@postgres:5432`, the
Caddyfile proxies to `api:8000`, and the Alloy config scrapes `caddy:2020`.

## 4. The image

### 4.1 The Dockerfile

The Dockerfile has two stages. The first stage builds the virtual environment. The second
stage copies it into a plain Python image.

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable
```

The build stage starts from an image that already contains `uv` and Python 3.12. The three
environment variables tell `uv` to compile `.pyc` files, to copy packages instead of linking
them, and to never download a Python. The first `uv sync` installs only the dependencies, with
`--no-install-project`, so a change in `src/` does not invalidate this layer. The second
`uv sync` installs the project after `src/` is copied. `--frozen` uses `uv.lock` exactly as
committed. `--no-editable` copies the package instead of linking to `src/`. The cache mount
keeps downloaded wheels between builds. `README.md` is copied because `pyproject.toml`
declares `readme = "README.md"`, which the build backend `hatchling` reads.

```dockerfile
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN useradd --create-home --uid 1000 app
COPY --from=build --chown=app:app /app/.venv /app/.venv
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CASELAW_BACKEND=postgres CASELAW_RUN=regex-v0.4
EXPOSE 8000
CMD ["uvicorn", "caselaw_extraction.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
```

The final stage contains Python, the virtual environment and one user. The process runs as
`app` with uid 1000, not as root. `/app` itself belongs to root, so the working directory is
read-only for the process. The `PATH` puts the environment's `bin` first, so `uvicorn` and
`caselaw` resolve without activation. The two `CASELAW_*` variables are defaults that the
Compose file sets again.

### 4.2 Which dependencies are in the image

`pyproject.toml` has three groups of dependencies:

- `dependencies`: the core set, such as `fastapi`, `uvicorn`, `psycopg`, `pyarrow`, `polars`
  and `duckdb`. The image installs these.
- `[project.optional-dependencies] ml`: `torch`, `spacy`, `transformers`, `mlflow` and the
  other training libraries. `uv sync` installs an extra only with `--extra ml` or
  `--all-extras`. The Dockerfile passes neither, so the image does not contain them.
- `dev` (as an extra and as a dependency group): `pytest`, `ruff`, `mypy`. `--no-dev` leaves
  the dependency group out, and the extra is not requested.

The `ml` extra stays out because the API serves records from Postgres and never runs a
model. The comment at the top of the Dockerfile states this. Locally, `make setup` runs
`uv sync --all-extras` and installs everything.

### 4.3 .dockerignore

```
*
!pyproject.toml
!uv.lock
!README.md
!src/
src/**/__pycache__/
```

The first line excludes everything. The next four lines add back only what the Dockerfile
copies. The build context is the repository root, which holds `data/`, `models/`, `.venv/`
and `mlruns/`. Without the ignore file, every build would send them to the daemon. The
allowlist form is safer than a list of exclusions, because a new directory is excluded by default.

### 4.4 Image size

The report measured the image in section 8.2. The build for x86 on the server is 965 MB. The
build for ARM on the laptop is 211 MB. The difference comes from the x86 wheels of `pyarrow`
(156 MB), `polars` (179 MB) and DuckDB (58 MB), which bundle their native libraries. The API
against Postgres needs neither `polars` nor DuckDB. Report section 10 lists moving them to an
extra as a next step, which would save about 240 MB. This is not fixed yet.

## 5. The Compose file

### 5.1 The four services

| service | image | role | ports published |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | the database, tuned for 4 GB | none |
| `api` | `caselaw-api:latest`, built from `Dockerfile` | uvicorn with 2 workers, and the loader | none |
| `caddy` | `caddy:2-alpine` | TLS, reverse proxy to `api:8000`, static site | 80, 443 |
| `alloy` | `grafana/alloy:v1.10.0` | metrics and logs to Grafana Cloud | none |

All four have `restart: unless-stopped`, so Docker restarts them after a crash and after a
reboot, but not after a manual stop. The `api` service is the only one with a `build` block. `context: ../..` points at the repository root, and `image: caselaw-api:latest` names
the result. `docker compose build api` on the server produces the image. No registry is
involved. The CI workflow in `.github/workflows/ci.yml` builds the image only as a check.

### 5.2 Health checks and start order

```yaml
  api:
    depends_on:
      postgres: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 20s
```

The chain is `postgres`, then `api`, then `caddy`, then `alloy`. `condition: service_healthy`
makes Compose wait until the health check passes. The `alloy` service uses the short form
`depends_on: [caddy]`, which only waits for the container to start. Postgres checks itself
with `pg_isready` every 10 seconds. The API checks itself with a Python one-liner against
`/health`, because the slim Python image has no `curl`. `start_period: 20s` gives the process
time to start before a failed check counts.

### 5.3 Secrets as files, not environment variables

```yaml
secrets:
  postgres_password:
    file: /etc/caselaw/secrets/postgres_password
  caselaw_dsn:
    file: /etc/caselaw/secrets/caselaw_dsn
  exporter_dsn:
    file: /etc/caselaw/secrets/exporter_dsn
```

Each service lists the secrets it may read. Compose mounts each one at `/run/secrets/<name>`.
Postgres reads `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password`. The API reads
`CASELAW_DSN_FILE=/run/secrets/caselaw_dsn`. The function `dsn_from_env` in `store.py` checks
`CASELAW_DSN` first, then reads the file named by `CASELAW_DSN_FILE`. Alloy reads
`exporter_dsn` with `local.file`.

An environment variable is visible in `docker inspect` and in any child process. A file under
`/run/secrets` is visible only to a process that opens it. The report states this as the
reason in section 8.1. cloud-init generates the three files on the first boot with
`openssl rand`, so the password never exists on the laptop.

Not everything is a secret file. The R2 key and the Grafana token are environment variables
from `/etc/caselaw/caselaw.env`, owned by root, group `caselaw`, mode 640, outside the checkout.

### 5.4 Two env files

The `COMPOSE` variable in `scripts/hz.sh` passes two `--env-file` arguments:

```
docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env -f /opt/caselaw/repo/infra/hetzner/compose.yml
```

The two files have two writers. cloud-init writes `hosts.env` once with `SITE_HOST`,
`API_HOST` and `CASELAW_GID`, mode 644, no secret in it. `scripts/hz.sh secrets` writes
`caselaw.env` from `infra/hetzner/runtime.secrets` after resolving 1Password references.
Compose reads both for `${...}` substitution. `${SITE_HOST:?SITE_HOST required}` fails the
whole stack if the variable is missing. `${GCLOUD_RW_API_KEY:-}` falls back to an empty
string. Compose also expands `$` inside values, so `hz.sh secrets` refuses such a value.

### 5.5 The `monitoring` profile

The `alloy` service carries `profiles: [monitoring]`. `docker compose up -d` without
`--profile monitoring` ignores it. The `profile` function in `scripts/hz.sh` looks for a
non-empty `GCLOUD_RW_API_KEY` in `caselaw.env` and adds the flag only then. The stack can
therefore run without a Grafana account. `docs/learning/12-grafana.md`, section 4.1, explains
`privileged: true`, `pid: host` and the host mounts of the `alloy` service.

### 5.6 Named volumes and bind mounts

| mount | kind | used by | why this kind |
|---|---|---|---|
| `pgdata:/var/lib/postgresql/data` | named volume | `postgres` | the container owns the data |
| `caddy_data`, `caddy_config`, `alloy_data` | named volumes | `caddy`, `alloy` | certificates, the running config and Alloy's storage survive a restart |
| `/var/lib/caselaw/runs:/data/runs:ro` | directory bind mount | `api` | `hz.sh sync` writes Parquet here; the loader reads it |
| `/opt/caselaw/site:/srv/site:ro` | directory bind mount | `caddy` | `hz.sh deploy` copies `index.html` and `graph.html` here |
| `./Caddyfile:/etc/caddy/Caddyfile:ro` | single-file bind mount | `caddy` | the config lives in the checkout |
| `./alloy/config.alloy:/etc/alloy/config.alloy:ro` | single-file bind mount | `alloy` | the config lives in the checkout |

A named volume is the right choice when the container owns the data. A bind mount is the
right choice when something on the host writes the data and the container only reads it.
A single-file bind mount has one trap: the kernel mounts the inode, not the path. If a tool
writes a temporary file and renames it over the original, the path has a new inode. The
container still sees the old inode. `rsync` works this way by default. Section 7 describes
how this appeared and how `--inplace` fixes it.

### 5.7 `group_add` and the gid of the secret files

cloud-init creates the secret files with owner root, group `caselaw` and mode 640. Postgres
reads its file as root before it drops privileges, so it needs nothing more. The API runs as
uid 1000. Containers share the kernel's user ids with the host, so the file is checked
against uid 1000 and its groups. The container process must therefore be in group `caselaw`.

The `caselaw` user on the host did not get gid 1000. Docker's own group took 1000 first, so
`caselaw` got 1001. cloud-init therefore writes the real gid into `hosts.env`:

```
sh -c 'printf "CASELAW_GID=%s\n" "$(getent group caselaw | cut -d: -f3)" >> /etc/caselaw/hosts.env'
```

The `api` service adds it with `group_add: ["${CASELAW_GID:-1001}"]`. The process then has the
supplementary group and can open `/run/secrets/caselaw_dsn`.

## 6. Walkthrough of a deployment, as done by hand

`scripts/hz.sh deploy` does these steps. `make hz-deploy` calls it.

1. Run `rsync -az --delete --inplace` from the repository root to `/opt/caselaw/repo/` on the
   server. Exclusions remove `.git`, `.venv`, `data`, `models`, `mlruns`, the Terraform state
   and `runtime.secrets`.
2. Copy `docs/report.html` to `/opt/caselaw/site/index.html` with scp.
3. Copy `data/runs/regex-v0.4/graph.html` to `/opt/caselaw/site/graph.html` with scp.
4. Run `docker compose ... build api` on the server. The build context is the synced checkout.
5. Run `docker compose ... [--profile monitoring] up -d --remove-orphans`. Compose recreates
   only the containers whose image or config changed.
6. Run `caddy reload --config /etc/caddy/Caddyfile` inside the `caddy` container.
7. If the monitoring profile is active, run `docker compose ... restart alloy`.
8. Install the cron line for the nightly backup into `/etc/cron.d/caselaw-backup`.

Steps 6 and 7 exist because `up -d` compares the service definition, not the content of a
bind-mounted file. A changed Caddyfile or `config.alloy` does not trigger a recreate. The loader uses the same image once. `scripts/hz.sh load` runs
`docker compose ... run --rm --no-deps api caselaw db-load --run regex-v0.4 --runs-dir /data/runs`.
`run` starts a fresh container from the `api` service with a different command. `--rm`
removes it afterwards. `--no-deps` skips the wait on Postgres, because the stack is already up.

## 7. What went wrong, and what each mistake teaches

Each problem below is recorded in a commit message, in the report or in a code comment.

**The API container could not read its secret file.** The first deployment on 2026-11-03
found that the host group `caselaw` had gid 1001, because Docker's group took 1000. The
container ran as uid 1000 with no supplementary group, and the file was mode 640. Commit
`1542125` added `group_add` and the `CASELAW_GID` line in cloud-init. Lesson: a container
user is a number, and the number must match the host's files.

**The loader wrote into a read-only working directory.** `load_code_map` in `fedlex.py` wrote
a cache file next to the code. In the image, `/app` belongs to root and the process is
`app`. The same commit wraps the write in `try` and treats a failed write as acceptable.
Lesson: a non-root image makes every write outside a volume fail. Find them before the first
deploy.

**The stack would not start without the monitoring profile.** The `alloy` variables were
written as `${GCLOUD_RW_API_KEY:?}`. Compose substitutes variables for every service in the
file, also for a service in an inactive profile. A missing variable stopped the whole stack.
The same commit changed them to `${...:-}`. Lesson: a profile hides a service from `up`, not
from the parser.

**cAdvisor could not find the container layers.** Docker 29 stores images with the containerd
image store by default. cAdvisor, inside Alloy, looks for layer ids under
`/var/lib/docker/image/overlay2`, which does not exist in that mode. Commit `7c274bf` added
`/etc/docker/daemon.json` to cloud-init with
`{"features": {"containerd-snapshotter": false}, "storage-driver": "overlay2"}`. On the live
server the change was applied by hand, and the named volumes survived. The images did not,
because each storage backend keeps its own image store; this is general Docker behaviour.
Lesson: a tool that reads another tool's internal files depends on that tool's defaults, and
defaults change between major versions.

**Config changes did not reach Caddy and Alloy.** `rsync` replaced `Caddyfile` and
`config.alloy` with new inodes. The containers kept the old inodes. Commit `6a4362f` added
`--inplace` to the rsync call, a `caddy reload` and an Alloy restart to the deploy step.
Lesson: a single-file bind mount follows the inode, and `up -d` does not watch content.

## 8. How to verify

Open a shell on the server with `make hz-ssh`. The `docker` commands below are general Docker
commands and not part of the repository.

1. Run `make hz-status` from the laptop. The four containers should show `Up`, and `postgres`
   and `api` should show `(healthy)`.
2. On the server, run `docker inspect hetzner-api-1 --format '{{.Config.Env}}'`. The output
   must contain `CASELAW_DSN_FILE` and must not contain a password.
3. On the server, run `docker exec hetzner-api-1 id`. The groups must include the value of
   `CASELAW_GID` from `/etc/caselaw/hosts.env`.
4. On the server, run `docker info --format '{{.Driver}}'`. The output must be `overlay2`.
5. From the laptop, run `make hz-smoke`. `/health`, `/runs` and `/statutes/top` must answer.

## 9. Alternatives, and why not

- **One stage, `pip install`.** Simpler to read. The image would carry the build tools and
  the cache. `uv sync --frozen` also guarantees the exact lock file.
- **The `ml` extra in the image.** One image for training and serving. The API never imports
  `torch`, `spacy` or `transformers`, and the x86 image is already 965 MB without them.
- **Secrets as environment variables.** A shorter Compose file. Every `docker inspect` could
  show the connection string. The file form costs one `_FILE` variable and the gid fix.
- **A registry and ECS Fargate, the AWS design.** Report section 8.6 pushes the image to ECR
  and runs it on Fargate. It was validated, not applied. Section 8.5 estimates about USD 47 a
  month against under EUR 6 here. On one server a local build after rsync needs no registry.

## 10. Questions to be able to answer afterwards

- Why does the Dockerfile run `uv sync` twice, and which layer does a change in `src/`
  invalidate?
- Which dependencies of `pyproject.toml` are in the image, and which flag leaves each of the
  other groups out?
- Why does `docker inspect` not show the Postgres password, and where does the API read it?
- Why did `${VAR:?}` on a profiled service break a stack that never started that service?
- Why does the API container need `group_add`, and why is the gid 1001?
- Why does `rsync --inplace` matter for a single-file bind mount, and why does the deploy
  step still reload Caddy?
- What did Docker 29 change in image storage, and which container noticed?

## 11. Files

| file | role |
|---|---|
| `Dockerfile` | the two-stage build, `uv sync` without `dev` and `ml`, the `app` user |
| `.dockerignore` | the allowlist of the build context |
| `pyproject.toml`, `uv.lock` | the core dependencies, the `ml` and `dev` extras, the lock file |
| `infra/hetzner/compose.yml` | the four services, secrets, volumes, profile, health checks |
| `infra/hetzner/cloud-init.yaml` | Docker install, `daemon.json` for overlay2, the secret files, `hosts.env` |
| `infra/hetzner/Caddyfile` | `reverse_proxy api:8000`, the `:2020` metrics site |
| `scripts/hz.sh` | the `COMPOSE` command with two env files, `deploy`, `load`, `status` |
| `src/caselaw_extraction/store.py` | `dsn_from_env`, which reads `CASELAW_DSN_FILE` |
| `src/caselaw_extraction/fedlex.py` | the cache write that tolerates a read-only directory |
| `Makefile` | the `hz-*` targets; `docker-build` and `docker-run` for the image against the local Postgres |
| `docs/report.md`, sections 8.1, 8.2 and 10 | secrets design, image size, the slimming item |
