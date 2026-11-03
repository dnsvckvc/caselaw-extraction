# GitHub Actions and the AWS design: what the workflows do, what the Terraform would create, why neither runs

This note explains two things that exist in the repository as code but have never run. Part A
covers the two GitHub Actions workflows in `.github/workflows/`. Part B covers the AWS stack in
`infra/terraform/`, which `terraform validate` accepts and nobody has applied. The report
discusses the AWS design in section 8.6 of `docs/report.md`. The note is written for someone
who would build the same thing by hand and wants to understand each piece before copying it.

Both parts share one fact. On 2026-11-03 the repository has no git remote: `git remote -v`
prints nothing. GitHub has never seen `ci.yml` or `deploy.yml`, so no workflow run exists. The
report lists the GitHub repository as the second item of its next steps (section 10).

## Part A: continuous integration

### 1. The problem CI solves here

The project has 13 test files, a linter, a Dockerfile and a Terraform directory. Each of them
can break without anyone noticing, because the laptop runs only what the developer remembers.
CI runs the same five checks on every push to `main` and on every pull request:

- Does `ruff` accept the code, and is it formatted?
- Do the tests pass, including the one that needs Postgres?
- Does the API image still build?
- Is the Terraform formatted, and does it validate?
- After a green run on `main`: can the new image reach the cloud without a stored key?

The last point is the deploy workflow. It targets the AWS stack of Part B, which does not
exist, so it is inert twice: no remote, and no cluster to deploy to.

### 2. The vocabulary

**Workflow.** One YAML file under `.github/workflows/`. It has a name, triggers (`on`) and jobs.
This repository has two: `ci` and `deploy`.

**Job.** A set of steps that runs on one fresh virtual machine, the runner. `ubuntu-latest` is
a GitHub-hosted runner with Docker, Python and the AWS CLI already installed. Each job starts
from an empty machine, which is why every job repeats the checkout.

**Service container.** A Docker container that GitHub starts next to the job before the first
step and stops after the last one. The job declares it under `services:` with an image,
environment and ports. Here the service is `postgres:16-alpine`.

**Cache.** A directory that an action saves at the end of a run and restores at the start of
the next, keyed by a hash. Here `setup-uv` caches the uv download cache.

**Extra.** An optional dependency group in `pyproject.toml`. `uv sync --extra dev` installs the
core dependencies plus the `dev` list. The `ml` extra, with torch, spaCy and MLflow, stays out.

**OIDC.** OpenID Connect. GitHub issues a short-lived signed token to a workflow run. AWS
checks the token's claims against a trust policy and hands back temporary credentials. No
AWS access key is stored in GitHub.

**Repository variable.** A value set in the repository settings and read as `vars.NAME`. It is
not secret. `deploy.yml` reads three: `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION` and `API_URL`.

### 3. How the pieces connect

```
 push to main / pull request                        (nothing of this has run: no remote)
          |
          v
 +-- ci.yml, job "test", runner ubuntu-latest ----------------------------------+
 |                                                                              |
 |  service container postgres:16-alpine  <--- localhost:5433 --- uv run pytest |
 |                                                                              |
 |  checkout -> setup-uv (cache) -> uv sync --extra dev -> ruff -> pytest       |
 |          -> docker build -t caselaw-api . -> setup-terraform -> fmt/validate |
 +------------------------------------------------------------------------------+
          |  workflow_run, conclusion == success, branch main
          v
 +-- deploy.yml, job "deploy" --------------------------------------------------+
 |  OIDC token --> AWS STS --> role caselaw-github-deploy (github.tf)           |
 |  ecr login -> docker build + push :<sha7> and :latest -> ecs update-service  |
 |  -> ecs wait services-stable -> curl $API_URL/health                         |
 +------------------------------------------------------------------------------+
```

### 4. `ci.yml`, step by step

The file is 44 lines. The job is named `test` and runs on `ubuntu-latest`.

**The service container.** The job declares one service:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    env:
      POSTGRES_USER: caselaw
      POSTGRES_PASSWORD: caselaw
      POSTGRES_DB: caselaw
    ports: ["5433:5432"]
    options: >-
      --health-cmd "pg_isready -U caselaw -d caselaw"
      --health-interval 5s --health-timeout 3s --health-retries 20
```

The port mapping is the link to the tests. `src/caselaw_extraction/store.py` defines
`DEFAULT_DSN = "postgresql://caselaw:caselaw@localhost:5433/caselaw"`. The local Compose file
`infra/docker-compose.yml` publishes the same port, with the same user and database. The
service container copies that file's values, including the health check, so the test code
needs no CI-specific configuration.

How the job reaches the container is general GitHub Actions behaviour. The job's steps run
directly on the runner, not in a container. GitHub then publishes each service port on the
runner's `localhost`. The `options` string is passed to `docker create`, and GitHub waits for
the health check before the first step starts. If the job itself ran inside a container, the
host name would be the service label `postgres` and the port would be 5432.

**Checkout and uv.**

```yaml
- uses: actions/checkout@v4
- uses: astral-sh/setup-uv@v6
  with:
    enable-cache: true
- name: Install (core + dev; the ml extra is not needed by the tests)
  run: uv sync --extra dev
```

`setup-uv` installs uv and, with `enable-cache: true`, saves uv's download cache between runs.
By default the action derives the cache key from the lock file, so a changed `uv.lock`
invalidates it. That is general behaviour of the action, not something this file sets.

`uv sync --extra dev` reads `pyproject.toml` and `uv.lock`. It installs the 14 core
dependencies and the `dev` extra (pytest, pytest-cov, hypothesis, ruff, mypy). The `ml` extra
is not requested. The pyproject comment says why: "The learned extractors and experiment
tracking. The API image installs the core set only." Torch alone is hundreds of megabytes, and
the tests do not need it.

One detail of the pyproject deserves a look. It has an optional-dependency extra named `dev`
and a dependency group named `dev` (the `markdown` package). These are two different uv
concepts with the same name. `uv sync` installs the `dev` dependency group by default. The
flag `--extra dev` adds the extra. The CI step therefore gets both.

**How a test skips torch.** `tests/test_decoding.py` starts with:

```python
torch = pytest.importorskip("torch")  # the `ml` extra; CI installs the core set only
```

`pytest.importorskip` tries the import at collection time. If the module is missing, pytest
marks the whole file as skipped instead of failing. The import of
`caselaw_extraction.transformer_extractor` comes after that line, with `# noqa: E402`, because
that module imports torch too. In CI the two Viterbi tests are therefore skipped, not run.

**How a test skips Postgres.** `tests/test_db.py` uses the other mechanism:

```python
pytestmark = pytest.mark.skipif(not _postgres_available(), reason="no Postgres on :5433")
```

`_postgres_available()` opens a connection to `DEFAULT_DSN` with a two-second timeout. On a
laptop without the Compose database the file skips. In CI the service container answers, so
the loader test runs. That is the purpose of the service container: one test, but the one that
touches the SQL schema and the `COPY` loader.

**Lint.**

```yaml
- name: Lint
  run: |
    uv run ruff check src tests scripts
    uv run ruff format --check src tests scripts
```

The rule set is in `pyproject.toml`: `E, F, I, UP, B, SIM, N`, line length 100, with `E501`
ignored under `tests/` and `scripts/`. The Makefile's `lint` target checks `src tests` only.
CI adds `scripts`.

**Docker build.** `docker build -t caselaw-api .` builds the Dockerfile at the repository root.
The image installs the core dependencies with `uv sync --frozen --no-dev` in a build stage and
copies the virtual environment into `python:3.12-slim-bookworm`. CI builds it and discards it.
There is no layer cache between runs, so each run downloads the wheels again.

**Terraform.**

```yaml
- name: Terraform format and validate
  uses: hashicorp/setup-terraform@v3
  with:
    terraform_wrapper: false
- run: |
    terraform -chdir=infra/terraform fmt -check -recursive
    terraform -chdir=infra/terraform init -backend=false -input=false
    terraform -chdir=infra/terraform validate
```

`setup-terraform` installs the binary. `terraform_wrapper: false` disables the action's wrapper
script, which otherwise captures stdout into step outputs and can confuse multi-line commands.
`fmt -check` fails on unformatted files without changing them. `init -backend=false` downloads
the providers (`aws >= 5.80`, `random >= 3.6`) but configures no state backend, so no AWS
credentials are needed. `validate` checks types, references and required arguments against the
provider schemas. It does not contact AWS and does not know whether the account exists.

### 5. `deploy.yml`, step by step

The file header states the design: build the image, push it to ECR, restart the Fargate
service. Credentials come from the OIDC role that `github.tf` creates when `github_repo` is set.

**Triggers and gating.**

```yaml
on:
  workflow_dispatch:
  workflow_run:
    workflows: [ci]
    types: [completed]
    branches: [main]
permissions:
  id-token: write
  contents: read
concurrency: deploy
```

`workflow_run` starts this workflow when `ci` finishes on `main`. `completed` includes
failures, so the job has an `if`: it runs on a manual dispatch, or when the `ci` conclusion was
`success`. `id-token: write` lets the job request an OIDC token; without it the AWS step fails.
`concurrency: deploy` lets one deploy run at a time.

The deploy is not gated by an `if` on a variable. It depends on the variable
`AWS_DEPLOY_ROLE_ARN`: `configure-aws-credentials` receives it as `role-to-assume`, and an
empty value makes that step fail. `AWS_REGION` falls back to `eu-central-1`. Only the smoke
test has an explicit gate, `if: vars.API_URL != ''`.

**The steps.**

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
    aws-region: ${{ env.AWS_REGION }}
- id: ecr
  uses: aws-actions/amazon-ecr-login@v2
- run: |
    docker build -t "$REGISTRY/$REPOSITORY:${GITHUB_SHA::7}" -t "$REGISTRY/$REPOSITORY:latest" .
    docker push --all-tags "$REGISTRY/$REPOSITORY"
- run: |
    aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment >/dev/null
    aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
```

The image gets two tags: the first seven characters of the commit hash and `latest`. The ECS
task definition in `ecs.tf` references `${repository_url}:${var.image_tag}`, and `image_tag`
defaults to `latest`. A forced new deployment therefore pulls the image that was just pushed.
The `wait services-stable` call blocks until the new task passes the load balancer's health
check or the circuit breaker rolls back. The smoke test calls `/health` and
`/statutes/top?limit=3`.

**Why OIDC instead of a stored key.** A long-lived access key in a GitHub secret is valid until
someone rotates it, and anyone with write access to the repository can exfiltrate it. The OIDC
role in `github.tf` is restricted in three ways:

1. The trust policy accepts tokens with audience `sts.amazonaws.com` only.
2. The subject must match `repo:<owner/name>:ref:refs/heads/main`. A pull request or another
   branch cannot assume the role.
3. The role may call `ecr:GetAuthorizationToken`, push and pull on the one ECR repository, and
   `ecs:UpdateService` and `ecs:DescribeServices` on the one service. Nothing else.

The role exists only when the variable `github_repo` is set in `terraform.tfvars`. Its ARN is
the Terraform output `github_deploy_role_arn`, which the operator copies into the repository
variable `AWS_DEPLOY_ROLE_ARN`.

## Part B: the AWS design that was validated and not applied

### 6. What each file creates

`infra/terraform/` holds ten `.tf` files and a `terraform.tfvars.example`. The provider lock
file `.terraform.lock.hcl` is present, so `terraform init` ran on the laptop on 2026-10-29.
No state file exists, which matches the report: validated, never applied.

| file | resources | notes from the file |
|---|---|---|
| `versions.tf` | provider `aws >= 5.80`, `random >= 3.6`, Terraform `>= 1.6` | every resource is tagged `Project=caselaw`, `ManagedBy=terraform` |
| `main.tf` | data sources for the default VPC and its default subnets, locals `name`, `bucket` | the default VPC is used on purpose: a NAT gateway "would cost more per month than everything else here together" |
| `s3.tf` | bucket `caselaw-runs-<account>`, public access block, SSE-S3 | the run Parquet under `runs/<run_id>/`; the loader reads it |
| `ecr.tf` | repository `caselaw-api`, scan on push, lifecycle rule "keep the last 10 images" | `force_delete = true`, so `destroy` removes images too |
| `rds.tf` | random password, subnet group, security group, Postgres 16 `db.t4g.micro` with 20 GB gp3, SSM SecureString `/caselaw/dsn` | not public by default; one day of backups; `skip_final_snapshot = true` |
| `ecs.tf` | execution role, task role, log group (14 days), cluster, task definitions `api` and `load`, two security groups, ALB, target group, HTTP listener, service | the API task is 0.25 vCPU and 512 MB; the loader task is 1 vCPU and 2 GB; circuit breaker with rollback |
| `cloudwatch.tf` | SNS topic, optional e-mail subscription, eight alarms, one dashboard | metrics from the balancer, ECS and RDS; "the alarms cost ten cents each per month" |
| `github.tf` | OIDC provider, trust policy, role `caselaw-github-deploy`, inline policy | all four with `count = var.github_repo != "" ? 1 : 0` |
| `variables.tf` | region, project, run_id, image_tag, api sizes, desired count, db class and storage, public db flag, allowed CIDRs, alarm e-mail, github repo | `api_desired_count`: "Set 0 on the first apply, before an image exists in ECR" |
| `outputs.tf` | `api_url` (HTTP, no domain), ECR URL, bucket, DB address, DSN parameter, cluster, service, loader family, subnet ids, API security group, log group, dashboard URL, deploy role ARN | the subnet and security group outputs exist so that the loader task can be started by hand |

**How the secret reaches the task.** `rds.tf` builds the connection string from the generated
password and stores it once as an SSM SecureString. `ecs.tf` gives the execution role the right
to read that one parameter and to decrypt with the SSM key. The container definition lists
`CASELAW_DSN` under `secrets`, not `environment`, so the value never appears in the task
definition JSON.

**How the network is cut.** Three security groups form a chain. The balancer accepts port 80
from anywhere. The API tasks accept port 8000 from the balancer's group only. The database
accepts 5432 from the API group only, plus any CIDR in `db_allowed_cidrs`. The tasks get a
public IP because the default VPC has no NAT gateway and the image must be pulled from ECR.

**The dashboard and alarms.** The dashboard has a text header and nine data widgets: requests
per minute, responses by class, p50/p95/p99 response time with the alarm line, healthy and
unhealthy targets, task CPU and memory, database CPU and connections, database free storage,
database read and write latency, and the last twenty log lines. The eight alarms are listed in
report section 8.6. Only `caselaw-api-no-healthy-target` treats missing data as breaching,
because no data from the balancer means no target.

### 7. The cost estimate and the decision

Report section 8.6 prices the stack for `eu-central-1` on 2026-10-29:

| item | monthly estimate (USD) |
|---|---|
| application load balancer, 730 h | 19.7 |
| Fargate, 0.25 vCPU and 0.5 GB, 730 h | about 9 |
| RDS `db.t4g.micro`, 730 h, 20 GB gp3 | about 16.5 |
| 8 alarms | 0.8 |
| S3, ECR, logs, SSM | under 0.5 |
| **total** | **about 47, that is USD 1.60 per day** |

The Hetzner deployment of section 8.5 costs under EUR 6 per month. The report gives two
reasons for the choice. The AWS stack would cost about eight times more for the same public,
read-only API, most of it for the balancer and the managed database. And the project already
ran a second service on Hetzner, Cloudflare and Njalla, so the providers and tokens existed.

**What was lost.** The report names three things: a managed database with snapshots, a load
balancer with its metrics, and the AWS name on the stack. Section 8.3 lists the replacement
for each. Snapshots become a nightly `pg_dump` to Cloudflare R2 with 14 days of retention.
The balancer metrics become Caddy's request histograms, scraped by Grafana Alloy. CloudWatch
becomes Grafana Cloud's free tier. The AWS name has no replacement.

**What was gained.** The live service has HTTPS with a domain. The AWS design serves HTTP only,
because there is no domain and therefore no certificate; the output `api_url` says so. The
live service also has measured numbers. Section 8.2 reports latency per endpoint and resource
use per container. The AWS numbers in the report are estimates from price pages. A "day on
the AWS stack for a measured comparison" is item 5 of the next steps, after four other items.

### 8. How a reader would apply the AWS stack

Nothing below has been run. The report describes a `make aws-bootstrap` target that runs the
sequence in one command, and the `.tf` comments mention `make aws-load` and `make aws-sync`.
Those targets and `scripts/aws.sh` were missing until 2026-11-03 (see section 9) and exist
again now. The sequence from report section 8.6, with the commands that the repository files
contain, and the `make` target that wraps each step:

1. Copy `infra/terraform/terraform.tfvars.example` to `infra/terraform/terraform.tfvars`.
2. Set `alarm_email` and `github_repo` in that file. Both may stay empty.
3. Configure AWS credentials for an account in `eu-central-1`.
4. Run `terraform -chdir=infra/terraform init`.
   The provider lock file already pins the versions.
5. Run `terraform -chdir=infra/terraform apply -var api_desired_count=0`.
   The service starts with zero tasks, because no image exists yet.
6. Build the image for `linux/amd64` and push it to the ECR URL from `terraform output`.
   The `docker build` and `docker push` lines of `deploy.yml` show the tags.
7. Upload `data/runs/regex-v0.4/` to `s3://<runs_bucket>/runs/regex-v0.4/`.
8. Start the task definition `caselaw-load` once with `aws ecs run-task`.
   Use the outputs `subnet_ids` and `api_security_group_id` for the network configuration.
9. Wait until the task stops. Its log stream has the prefix `load` in the API log group.
10. Run `terraform -chdir=infra/terraform apply` with the default `api_desired_count` of 1.
11. Call `http://<api_url>/health`.
12. If `github_repo` was set, copy `github_deploy_role_arn` into the repository variable `AWS_DEPLOY_ROLE_ARN`.

The exact flags of `aws ecs run-task` and `aws s3 sync` are general AWS CLI usage and are not
in the repository. `terraform destroy` removes every resource, the database included, because
`skip_final_snapshot` and `force_destroy` are set.

## 9. What went wrong, and what each gap teaches

The commit history and the report hold little evidence of incidents for this part of the
project. What the files do show is three gaps between description and content.

**The commit message names files that are not in the commit.** Commit `46a1e18` of
2026-10-29 lists "scripts/aws.sh and Makefile targets: push, sync, load, deploy, smoke,
measure, bootstrap". `git log --all -- scripts/aws.sh` prints nothing, and the Makefile at that
commit has no `aws-*` or `tf-*` target. The report (`make aws-bootstrap`, `make tf-destroy`),
`ecs.tf` (`make aws-load`) and `s3.tf` (`make aws-sync`) refer to the same missing targets.
The Hetzner commit `3951571` then added `scripts/hz.sh` and the `hz-*` targets in their place.
On 2026-11-03, while these notes were written, the gap was found and `scripts/aws.sh` with the
`tf-*` and `aws-*` targets were recreated, still unapplied. Lesson: a commit message is a
claim. Check it with `git show --stat` before you cite it.

**The report counts four Postgres tests; the suite has one.** Section 8.6 says the service
container lets "the four Postgres tests" run. `tests/test_db.py` is the only test file that
uses `DEFAULT_DSN`, and it holds one test function under one `skipif` marker. Lesson: a
number in prose drifts away from the code it describes. Derive counts from the tree.

**The step name sits on the wrong step.** In `ci.yml` the name "Terraform format and
validate" belongs to the `setup-terraform` step. The three `terraform` commands run in an
unnamed step. Lesson: in a run log, a wrong name sends you to the wrong line.

The brief for this note mentions two further incidents: workflow files first written into a
wrong directory, and a denied `gh repo create`. Neither appears in a commit message, the
report or a code comment, so this note cannot confirm them. The absence of a remote is the
only verifiable trace.

## 10. How to verify

These checks are read-only or local. None needs GitHub or AWS.

1. Run `git remote -v`.
   The output is empty: no workflow has ever run on GitHub.
2. Run `uv sync --extra dev`.
   The environment has pytest and ruff, and `uv pip list` shows no torch.
3. Run `uv run pytest -rs`.
   The skip summary lists `tests/test_decoding.py` and `tests/test_db.py` ("no Postgres on :5433").
4. Run `make db-up`.
5. Run `uv run pytest -rs` again.
   `tests/test_db.py` no longer skips; the loader test runs against `localhost:5433`.
6. Run `terraform -chdir=infra/terraform init -backend=false`.
7. Run `terraform -chdir=infra/terraform validate`.
   The command prints "Success! The configuration is valid." without AWS credentials.
8. Run `terraform -chdir=infra/terraform fmt -check -recursive`.
   An empty output means every file is formatted.

The OIDC trust, the alarm thresholds and the cost cannot be verified locally. They need a
GitHub run, real traffic and a month of billing.

## 11. Alternatives, and why not

- **A stored AWS access key** in a GitHub secret instead of the OIDC role. Simpler to set up.
  The key never expires on its own and can be copied by anyone with repository write access.
  The report's reason for OIDC is one line: "no long-lived AWS key in GitHub".
- **A NAT gateway and private subnets** for the tasks. Correct for a service with secrets to
  hide, but the API is public and read-only. The NAT gateway alone would exceed the rest of
  the bill (comment in `main.tf`).
- **A Fargate task without the load balancer.** It would save USD 19.7 per month and change
  its public address at every deployment. The report keeps the balancer for the stable URL
  and the health checks.
- **Deploying to Hetzner from GitHub Actions over SSH** instead of `make hz-deploy` from the
  laptop. This is the report's next step 2 and is not written yet.

## 12. Questions to be able to answer afterwards

- Why does the test code reach the service container at `localhost:5433` and not at `postgres:5432`?
- What is the difference between `pytest.importorskip` and `pytest.mark.skipif`, and why does each file use the one it uses?
- Why does `uv sync --extra dev` install two different things called `dev`?
- Why does `terraform init -backend=false` need no AWS credentials, and what does `validate` not check?
- Which three conditions limit the OIDC role, and which branch can assume it?
- How does `docker push :latest` plus `--force-new-deployment` change the running task?
- Where does the database password live after `apply`, and which role may read it?
- Which three things did the Hetzner deployment give up, and what replaces each?

## 13. Files

| file | role |
|---|---|
| `.github/workflows/ci.yml` | the five checks, the Postgres service container |
| `.github/workflows/deploy.yml` | ECR push, ECS restart, smoke test; OIDC through `AWS_DEPLOY_ROLE_ARN` |
| `pyproject.toml` | the `dev` and `ml` extras, the ruff and pytest settings |
| `tests/test_decoding.py` | `pytest.importorskip("torch")` |
| `tests/test_db.py` | `skipif` on `localhost:5433`, the one Postgres test |
| `infra/docker-compose.yml` | the local Postgres that the service container copies |
| `Dockerfile` | the image that CI builds and `deploy.yml` pushes |
| `infra/terraform/*.tf` | the AWS stack: S3, ECR, RDS, ECS Fargate, ALB, CloudWatch, GitHub OIDC |
| `infra/terraform/terraform.tfvars.example` | `alarm_email`, `github_repo`, the public-database option |
| `scripts/hz.sh`, Makefile `hz-*` | the deployment in use |
| `scripts/aws.sh`, Makefile `tf-*` and `aws-*` | the AWS helpers, recreated on 2026-11-03, never run |
| `docs/report.md`, sections 8.5, 8.6 and 10 | cost, the AWS design, the GitHub repository as next step |
