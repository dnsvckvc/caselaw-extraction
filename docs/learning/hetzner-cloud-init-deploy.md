# Hetzner Cloud, cloud-init and the deploy script: how the server is built and updated

This note explains the one server that runs the caselaw API and how code reaches it. It is
written for someone who would build the same thing by hand, without an AI assistant, and
wants to understand each piece before copying it. The files it describes are
`infra/hetzner/main.tf`, `infra/hetzner/cloud-init.yaml`, `scripts/hz.sh` and the `hz-*`
targets in the `Makefile`. The report discusses the design in section 8.1 of `docs/report.md`.

## 1. The problem the server and the deploy flow solve

The API needs a machine with a public address, a database, TLS and a way to update the code.
The AWS design in `infra/terraform/` buys these as managed services for about USD 47 per
month. The Hetzner design buys one virtual server for about EUR 5 per month and does the rest
with Docker Compose. That choice leaves four tasks: prepare the operating system, create the
database password without having it on the laptop, copy the repository and build the image on
the server, and operate the stack from the laptop. cloud-init does the first two tasks once,
at the first boot. `scripts/hz.sh` does the last two, as often as needed.

## 2. The vocabulary

**User data.** A text that a cloud provider hands to a new server at the first boot. The
program cloud-init reads it. Terraform fills the `user_data` attribute of the server from
`cloud-init.yaml` through `templatefile()`, which replaces `${name}` placeholders.

**cloud-init.** The program that runs at the first boot of a cloud server. A file that starts
with `#cloud-config` is a YAML document whose top-level keys select modules: `packages`,
`users`, `write_files`, `runcmd` and others. This is general cloud-init behaviour.

**Compose secret and Compose env file.** A secret is a host file that Compose mounts into a
container under `/run/secrets/<name>`. An env file holds `KEY=value` lines that replace
`${KEY}` in `compose.yml`. The stack reads three secret files from `/etc/caselaw/secrets` and
two env files, `/etc/caselaw/caselaw.env` and `/etc/caselaw/hosts.env`.

**rsync, `--delete`, `--inplace`, inode.** rsync sends only the changed parts of files.
`--delete` removes files on the server that no longer exist on the laptop. `--inplace` writes
into the existing file instead of writing a new file and renaming it. The inode is the
identity of a file on disk, separate from its name. A bind mount of a single file follows the
inode, so after a rename the mount still shows the old file. This is general Linux behaviour.

## 3. How the pieces connect

```
 laptop                                   Hetzner Cloud (nbg1)
 +----------------------------+           +-------------------------------------------+
 | 1Password (op run)         |           | hcloud_firewall "caselaw-web"             |
 | terraform -chdir=infra/    |  create   |   22, 80, 443 tcp, icmp, from anywhere    |
 |   hetzner  --------------------------> | hcloud_ssh_key "caselaw-admin"            |
 |                            |           | hcloud_server "caselaw" cx23 ubuntu-24.04 |
 | ~/.ssh/caselaw-prod        |           |   user_data = cloud-init.yaml (once)      |
 |                            |   ssh     |   first boot: packages, user caselaw,     |
 | scripts/hz.sh  ----------------------> |     ufw, docker, secrets, .provisioned    |
 |   wait, secrets, deploy,   |  rsync    |                                           |
 |   sync, load, status, logs |  scp      |   /opt/caselaw/repo   <- rsync            |
 |                            |           |   /opt/caselaw/site   <- scp              |
 | docs/report.html           |           |   /var/lib/caselaw/runs/<run> <- rsync    |
 | data/runs/<run>/*.parquet  |           |   /etc/caselaw/caselaw.env <- ssh stdin   |
 |                            |  https    |                                           |
 | curl (smoke, measure) ---------------> |   docker compose: postgres, api, caddy,   |
 +----------------------------+           |   alloy (profile monitoring)              |
                                          +-------------------------------------------+
```

Terraform touches the server once, at creation. After that, everything goes over SSH as the
user `caselaw`. The server never pulls from git. The laptop pushes the working tree.

## 4. Terraform: the server, its firewall and its key

`main.tf` creates three Hetzner resources. The R2 bucket and the two Njalla records in the
same file have their own notes.

| resource | name | detail |
|---|---|---|
| `hcloud_ssh_key.admin` | `caselaw-admin` | the content of `~/.ssh/caselaw-prod.pub`; Hetzner installs it for root |
| `hcloud_firewall.web` | `caselaw-web` | four inbound rules: tcp 22, tcp 80 (Let's Encrypt challenge and redirect), tcp 443, icmp; each from `0.0.0.0/0` and `::/0` |
| `hcloud_server.app` | `caselaw` | type `cx23` (2 shared vCPUs, 4 GB, 40 GB), image `ubuntu-24.04`, location `nbg1` (Nuremberg), IPv4 and IPv6 |

**`user_data` is a rendered template.** `templatefile()` replaces three placeholders in
`cloud-init.yaml`: `ssh_public_key`, `site_host` (`caselaw.inat.io`) and `api_host`
(`api.caselaw.inat.io`). The key reaches root through `hcloud_ssh_key` and `caselaw` through cloud-init.

**`lifecycle { ignore_changes = [user_data] }`.** cloud-init runs once. Without this rule, a
change of `cloud-init.yaml` would make Terraform destroy and recreate the server. The
consequence: a change to `cloud-init.yaml` affects only the next server. The live server must
get the same change by hand. Commit `7c274bf` records one such case for `daemon.json`.

The outputs in `outputs.tf` feed the deploy script: `ipv4` for SSH, `api_url` and `site_url`
for the smoke test. Report section 8.5 lists the `cx23` with an IPv4 address at about EUR 5
per month and a total under EUR 6. The header comment of `main.tf` says about EUR 4.50. The
report names the Hetzner console as the source, because the line was repriced.

## 5. cloud-init in depth

### 5.1 The order of execution

cloud-init runs its modules in stages. In the default Ubuntu configuration, `write_files` and
`users` run in the init stage, package installation in the config stage, and `runcmd` in the
final stage. This is general cloud-init behaviour, not something the YAML states. The order
matters for one file: `daemon.json` exists before `apt` installs `docker.io`, so Docker starts with overlay2.

The effective order for this server: `write_files` writes three files (section 5.3). `users`
creates `caselaw` (section 5.2). `apt` updates, upgrades and installs `docker.io`,
`docker-compose-v2`, `ufw`, `unattended-upgrades`, `rclone`, `rsync`, `curl` and `jq`.
`runcmd` runs 18 shell commands as root, in the order written (section 5.4).
`ssh_pwauth: false` turns off password login over SSH.

### 5.2 The user

```yaml
users:
  - name: caselaw
    groups: [sudo, docker]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - "${ssh_public_key}"
```

The user has no password and can run any command with `sudo` without one. The group `docker`
lets the user talk to the Docker daemon without `sudo`. Membership in `docker` is
root-equivalent on the host, because the daemon can mount any path into a container. The
group id of `caselaw` is not fixed in the YAML. On the first server it became 1001, because
the `docker` group had taken 1000 (commit `1542125`). Section 7 explains why that matters.

### 5.3 The three written files

| path | mode | content |
|---|---|---|
| `/etc/docker/daemon.json` | 0644 | `{"features": {"containerd-snapshotter": false}, "storage-driver": "overlay2"}` |
| `/etc/caselaw/hosts.env` | 0644 | `SITE_HOST=caselaw.inat.io` and `API_HOST=api.caselaw.inat.io`; `runcmd` appends `CASELAW_GID=<gid>` later |
| `/etc/apt/apt.conf.d/52caselaw-unattended` | 0644 | remove unused dependencies, automatic reboot, reboot time 04:30 |

The Docker setting exists for cAdvisor inside Grafana Alloy, which reads container layer ids
under `/var/lib/docker/image/overlay2`. The default containerd image store of Docker 29 lacks it (commit `7c274bf`).

### 5.4 The runcmd block, command by command

The first seven commands build the host firewall and start Docker: `ufw default deny
incoming`, `ufw default allow outgoing`, `ufw allow 22/tcp`, `ufw allow 80/tcp`,
`ufw allow 443/tcp`, `ufw --force enable` and `systemctl enable --now docker`. `--force`
answers the confirmation prompt, which has no terminal.

The next six commands generate the database secrets on the server:

```yaml
  - install -d -m 0750 -o root -g caselaw /etc/caselaw/secrets
  - sh -c 'umask 022; openssl rand -hex 24 > /etc/caselaw/secrets/postgres_password'
  - sh -c 'umask 022; printf "postgresql://caselaw:%s@postgres:5432/caselaw" "$(cat /etc/caselaw/secrets/postgres_password)" > /etc/caselaw/secrets/caselaw_dsn'
  - sh -c 'umask 022; printf "postgresql://caselaw:%s@postgres:5432/caselaw?sslmode=disable" "$(cat /etc/caselaw/secrets/postgres_password)" > /etc/caselaw/secrets/exporter_dsn'
  - chmod 0640 /etc/caselaw/secrets/*
  - chgrp caselaw /etc/caselaw/secrets/*
```

`openssl rand -hex 24` writes 48 hexadecimal characters. The two connection strings embed that
password. `caselaw_dsn` is for the API. `exporter_dsn` adds `?sslmode=disable` for
`postgres_exporter` inside Alloy. The host `postgres` is the Compose service name. `chmod` and
`chgrp` then narrow each file to mode 0640, owner root, group `caselaw`.

The last five commands prepare the rest of the layout:

```yaml
  - install -m 0640 -o root -g caselaw /dev/null /etc/caselaw/caselaw.env
  - install -d -m 0755 -o caselaw -g caselaw /opt/caselaw /opt/caselaw/site /var/lib/caselaw /var/lib/caselaw/runs /var/lib/caselaw/backups
  - dpkg-reconfigure -f noninteractive unattended-upgrades
  - sh -c 'printf "CASELAW_GID=%s\n" "$(getent group caselaw | cut -d: -f3)" >> /etc/caselaw/hosts.env'
  - touch /etc/caselaw/.provisioned
```

`install ... /dev/null` creates an empty `caselaw.env` with the right owner and mode, which
`hz.sh secrets` fills later. The `install -d` line creates the five directories that the
deploy script writes into, all owned by `caselaw`. `dpkg-reconfigure` activates
unattended-upgrades. The `getent` line appends the real group id of `caselaw` to
`hosts.env`, so Compose can pass it to the API container. The last line creates the marker
`/etc/caselaw/.provisioned`, which `hz.sh wait` polls for.

### 5.5 The directory layout after the first boot

| path | mode | owner:group | written by | read by |
|---|---|---|---|---|
| `/etc/caselaw/hosts.env` | 0644 | root:root | cloud-init | Compose (second env file) |
| `/etc/caselaw/caselaw.env` | 0640 | root:caselaw | cloud-init (empty), then `hz.sh secrets` | Compose (first env file), `backup.sh` |
| `/etc/caselaw/secrets/` | 0750 | root:caselaw | cloud-init | Compose secrets |
| `/etc/caselaw/secrets/{postgres_password,caselaw_dsn,exporter_dsn}` | 0640 | root:caselaw | cloud-init | the Postgres, API and Alloy containers |
| `/etc/caselaw/.provisioned` | default | root:root | cloud-init | `hz.sh wait` |
| `/opt/caselaw/repo/` | rsync default | caselaw:caselaw | `hz.sh deploy` | `docker compose build`, `compose.yml`, `backup.sh` |
| `/opt/caselaw/site/` | 0755 | caselaw:caselaw | `hz.sh deploy` (scp) | the Caddy container at `/srv/site` |
| `/var/lib/caselaw/runs/<run>/` | rsync default | caselaw:caselaw | `hz.sh sync` | the API container at `/data/runs`, `backup.sh` |
| `/var/lib/caselaw/backups/` | 0755 | caselaw:caselaw | `backup.sh` | the operator |
| `/etc/cron.d/caselaw-backup` | 0644 | root:root | `hz.sh deploy` | cron |
| `/etc/docker/daemon.json` | 0644 | root:root | cloud-init | the Docker daemon |

`/opt/caselaw/repo` is not created by cloud-init. rsync creates it at the first `deploy`.

## 6. The deploy script `scripts/hz.sh` in depth

The script runs on the laptop. Each command either runs Terraform, runs a command over SSH as
`caselaw`, or copies files. Lines 2 to 13 of the script are also the help text, which
`scripts/hz.sh` without an argument prints.

### 6.1 The helpers at the top

| helper | what it does | where it runs |
|---|---|---|
| `KEY` | `$CASELAW_SSH_KEY` or `~/.ssh/caselaw-prod` | laptop |
| `tf()` | `op run --env-file infra/hetzner/terraform.op.env -- terraform -chdir=infra/hetzner "$@"`; 1Password injects the provider tokens into this one process | laptop |
| `out()` | `terraform output -raw <name>`; reads the local state file, needs no token | laptop |
| `ip()` | `out ipv4` | laptop |
| `SSH_OPTS` | `-i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10` | laptop |
| `sshc()` | `ssh $SSH_OPTS caselaw@<ip> "$@"` | the command runs on the server |
| `COMPOSE` | `docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env -f /opt/caselaw/repo/infra/hetzner/compose.yml` | sent over SSH |
| `profile()` | over SSH: if `GCLOUD_RW_API_KEY` has a value in `caselaw.env`, print `--profile monitoring` | server |

`StrictHostKeyChecking=accept-new` accepts the host key of a new server at the first
connection and rejects a changed key later. This is general SSH behaviour. After Terraform
recreates the server, the old line in `~/.ssh/known_hosts` must be removed by hand.

### 6.2 `init`, `plan`, `apply`, `destroy`, `ip`, `ssh`, `wait`

The four Terraform commands call `tf` with `-input=false`, so Terraform never prompts. `ip`
prints the IPv4 address. `ssh` replaces the script with an interactive `ssh` session as
`caselaw` and passes further arguments as the remote command, for example
`scripts/hz.sh ssh sudo cloud-init status --long`.

`wait` runs `sshc -o BatchMode=yes 'test -f /etc/caselaw/.provisioned'` up to 60 times at
10-second intervals, so 10 minutes in total. `BatchMode=yes` makes SSH fail instead of asking
a question. The marker is necessary because SSH as `caselaw` works as soon as the `users`
module has run, minutes before `runcmd` finishes. Report section 8.1 says cloud-init takes about two minutes.

### 6.3 `secrets`

1. The script reads `infra/hetzner/runtime.secrets`. The file is ignored by git.
2. If the file contains `op://` references, `op inject` replaces them with the values from
   1Password. Plain values pass unchanged.
3. The script refuses if any `op://` reference remains unresolved.
4. The script refuses if a non-comment line contains `$`, because Compose would expand it.
5. The rendered text goes over SSH to standard input of
   `sudo install -m 0640 -o root -g caselaw /dev/stdin /etc/caselaw/caselaw.env`.
6. The script prints how many `KEY=value` lines have a value.

The rendered values exist only in the memory of the script and in the SSH stream (commit
`625a9a9`). `runtime.secrets.example` lists the keys: R2, `GCLOUD_*`, healthchecks, `CASELAW_RUN`.

### 6.4 `deploy`

**Step 1: rsync the repository.**

```bash
rsync -az --delete --inplace -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .venv --exclude data --exclude models --exclude mlruns --exclude mlflow.db \
  --exclude labeling/data --exclude labeling/tasks --exclude '__pycache__' --exclude .pytest_cache \
  --exclude .ruff_cache --exclude 'infra/terraform/.terraform' --exclude 'infra/hetzner/.terraform' \
  --exclude 'infra/hetzner/*.tfstate*' --exclude 'infra/hetzner/runtime.secrets' --exclude 'infra/hetzner/terraform.env' \
  "$ROOT/" "caselaw@$(ip):/opt/caselaw/repo/"
```

`-a` keeps modes and times, `-z` compresses. `--delete` makes the server copy equal to the
laptop copy. `--inplace` keeps the inode of every file, which the bind mounts of `Caddyfile`
and `config.alloy` need (commit `6a4362f`). The excludes fall into three groups. Secrets and
state: `runtime.secrets`, `terraform.env`, `*.tfstate*`, `.terraform`. Large data: `data`,
`models`, `mlruns`, `mlflow.db`, `labeling/data`, `labeling/tasks`. Caches: `.git`, `.venv`,
`__pycache__`, `.pytest_cache`, `.ruff_cache`. The Parquet of a run travels by `sync` (section 6.5).

**Steps 2 and 3: the site files.** Two `scp` calls copy `docs/report.html` to
`/opt/caselaw/site/index.html` and `data/runs/regex-v0.4/graph.html` to
`/opt/caselaw/site/graph.html`. Each copy runs only if the source exists. Caddy serves
`/opt/caselaw/site` as `/srv/site`. `make report-html` on the laptop renders the report HTML.

**Step 4: build and start.** `sshc "$COMPOSE build api && $COMPOSE $(profile) up -d
--remove-orphans"`. The API image is built on the server, because the build context in
`compose.yml` is `../..` relative to `infra/hetzner`, so `/opt/caselaw/repo`. There is no
registry. `up -d` recreates the services whose definition or image changed. `--remove-orphans`
stops containers of services that the file no longer defines. `$(profile)` adds Alloy.

**Steps 5 and 6: reload what `up -d` does not notice.** Compose does not look at the content
of a bind-mounted file. The script therefore runs `caddy reload --config /etc/caddy/Caddyfile`
inside the Caddy container, and restarts Alloy if the profile is active.

**Step 7: the backup cron.**

```bash
sshc 'sudo install -m 0644 /dev/stdin /etc/cron.d/caselaw-backup' <<< "30 3 * * * caselaw /opt/caselaw/repo/infra/hetzner/backup.sh >> /var/lib/caselaw/backups/backup.log 2>&1"
```

A file in `/etc/cron.d` has a sixth field, the user. The line runs `backup.sh` as `caselaw`
at 03:30 every night and appends both output streams to `backup.log`. `backup.sh` dumps the
database with `pg_dump` and copies the dump and `/var/lib/caselaw/runs` to R2 with rclone.

### 6.5 `sync` and `load`

`sync` runs `rsync -az --include '*.parquet' --include 'run.json' --exclude '*'` from
`data/runs/<run>/` to `/var/lib/caselaw/runs/<run>/`, default run `regex-v0.4`. Only Parquet
files and `run.json` pass the filter. There is no `--delete`. The destination is bind-mounted
read-only into the API container as `/data/runs`. `load` then runs `$COMPOSE run --rm
--no-deps api caselaw db-load --run <run> --runs-dir /data/runs` over SSH. `--rm` removes
the one-off container afterwards. `--no-deps` skips the dependency start, because Postgres
already runs. The loader writes into Postgres through the same secret file as the API.

### 6.6 `smoke`, `measure`, `status`, `logs`, `backup-now`, `bootstrap`

`smoke` reads `api_url` and `site_url` from the Terraform outputs. It calls `/health`,
`/runs` and `/statutes/top?limit=3` with `curl -fsS`, which fails on any non-2xx status. It
then fetches the site root and prints the status code and size. `measure` fetches one decision
id from `/decisions?limit=1`. For each of seven paths it sends 30 requests, sorts the total
times, and prints the p50 and p95 in milliseconds with `awk`. Each request opens a new TLS
connection, which report section 8.2 names as the 100 ms floor.

`status` runs `docker compose ps` on the server. `logs` runs
`docker compose logs -f --since 10m`, with an optional service name as the first argument.
`backup-now` runs `backup.sh` on the server once, outside cron. `bootstrap` runs `apply`,
`wait`, `secrets`, `deploy`, `sync`, `load` and `smoke` in that order. `set -e` stops the
chain at the first failure. Report section 8.1 gives the timing: `apply` about 30 seconds,
the server ready in 24 seconds, cloud-init about two minutes.

### 6.7 The Makefile wrappers

Each `hz-*` target in the `Makefile` calls the script with the same word: `hz-init`,
`hz-plan`, `hz-apply`, `hz-destroy`, `hz-secrets`, `hz-deploy`, `hz-sync`, `hz-load`,
`hz-smoke`, `hz-measure`, `hz-status`, `hz-ssh`, `hz-bootstrap`. The targets `hz-sync`,
`hz-load` and `hz-bootstrap` pass `$(RUN)`, which defaults to `regex-v0.4`. Example from the
README: `make hz-sync RUN=gbert-b13-s0 && make hz-load RUN=gbert-b13-s0`.

## 7. What went wrong, and what each mistake teaches

The evidence is the commit history of 2026-11-03 and report section 8.1. The commits record
four problems. No log or incident file exists beyond them.

**The API container could not read its secret file.** The image runs as uid 1000. The
cloud-init comment assumed that uid 1000 would also be the `caselaw` group on the host. On
the real server the `docker` group took gid 1000, and `caselaw` got 1001 (commit `1542125`).
The secret files are mode 0640, group `caselaw`, so uid 1000 could not read them. The fix:
cloud-init appends `CASELAW_GID` to `hosts.env`, and `compose.yml` gives the API service
`group_add: ["${CASELAW_GID:-1001}"]`. Lesson: never assume a numeric id across two systems.

**The loader failed in a read-only working directory.** `load_code_map` in `fedlex.py` wrote
the Fedlex abbreviation cache under the working directory. In the image, `/app` belongs to
root and the process runs as `app`. The write failed (commit `1542125`). The fix ignores
`OSError` on that write. Lesson: a program run only from a checkout assumes writable paths.

**Docker stored images where cAdvisor could not see them.** Docker 29 on Ubuntu 24.04 uses
the containerd image store by default. cAdvisor inside Alloy needs the overlay2 layout
(commit `7c274bf`). The fix is `daemon.json` in `write_files`. The live server got the file
by hand, with a Docker restart; the commit says all volumes were kept. Lesson: a setting in
cloud-init reaches only new servers.

**Edited config files did not reach the containers.** `Caddyfile` and `config.alloy` are
bind-mounted as single files. The old rsync wrote a new file and renamed it, so the containers
kept the old inode. Caddy reported an unchanged config (commit `6a4362f`). The fix is
`--inplace` on the rsync, plus `caddy reload` and `restart alloy` in `deploy`. Lesson: `up -d` is not a full reload.

## 8. How to do each step by hand

This section is for a reader without `scripts/hz.sh`. Replace `<ip>` with the server address.
In the steps, `SSH` stands for `ssh -i ~/.ssh/caselaw-prod caselaw@<ip>`, and `COMPOSE`
stands for `docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env`
run in `/opt/caselaw/repo/infra/hetzner` on the server.

### 8.1 Create the server and wait for cloud-init

1. Run `op run --env-file infra/hetzner/terraform.op.env -- terraform -chdir=infra/hetzner init`.
2. Run the same line with `apply -input=false` instead of `init`.
3. Run `terraform -chdir=infra/hetzner output -raw ipv4`. The output is `<ip>`.
4. Run `SSH test -f /etc/caselaw/.provisioned`. An exit code of 0 means the first boot is complete.
5. If the exit code is not 0, wait 10 seconds and repeat step 4.
6. If the marker is still missing after 10 minutes, run `SSH sudo cloud-init status --long`. The output names the stage and any error.

### 8.2 Write the runtime env file

Precondition: `infra/hetzner/runtime.secrets` exists and contains no `$` in a value.

1. If the file contains `op://` references, run `op inject -i infra/hetzner/runtime.secrets`
   and pipe its output into step 2. Otherwise pipe the file itself.
2. Pipe into `SSH 'sudo install -m 0640 -o root -g caselaw /dev/stdin /etc/caselaw/caselaw.env'`.
3. Run `SSH ls -l /etc/caselaw/caselaw.env`. The output shows `-rw-r-----`, `root`, `caselaw`.

### 8.3 Deploy the code

1. Run the rsync command of section 6.4 with `<ip>` in place of `$(ip)`.
2. Run `scp -i ~/.ssh/caselaw-prod docs/report.html caselaw@<ip>:/opt/caselaw/site/index.html`.
3. Run `scp -i ~/.ssh/caselaw-prod data/runs/regex-v0.4/graph.html caselaw@<ip>:/opt/caselaw/site/graph.html`.
4. Run `SSH`. A shell on the server opens.
5. Run `cd /opt/caselaw/repo/infra/hetzner`.
6. Run `COMPOSE build api`.
7. If `GCLOUD_RW_API_KEY` has a value in `/etc/caselaw/caselaw.env`, add `--profile monitoring` before `up` in step 8.
8. Run `COMPOSE up -d --remove-orphans`.
9. Run `COMPOSE exec -T caddy caddy reload --config /etc/caddy/Caddyfile`.
10. If Alloy runs, run `COMPOSE restart alloy`.
11. Run `echo '30 3 * * * caselaw /opt/caselaw/repo/infra/hetzner/backup.sh >> /var/lib/caselaw/backups/backup.log 2>&1' | sudo install -m 0644 /dev/stdin /etc/cron.d/caselaw-backup`.

### 8.4 Upload a run, load it, test

1. On the laptop, run `rsync -az -e 'ssh -i ~/.ssh/caselaw-prod' --include '*.parquet' --include 'run.json' --exclude '*' data/runs/regex-v0.4/ caselaw@<ip>:/var/lib/caselaw/runs/regex-v0.4/`.
2. On the server, run `COMPOSE run --rm --no-deps api caselaw db-load --run regex-v0.4 --runs-dir /data/runs`.
   The loader exits with code 0.
3. Run `curl -fsS https://api.caselaw.inat.io/health`. The output is the health JSON.
4. Run `curl -fsS https://api.caselaw.inat.io/runs`. The output lists the loaded runs.
5. Run `curl -fsS -o /dev/null -w '%{http_code}\n' https://caselaw.inat.io/`. The output is `200`.

## 9. How to verify the server state

Run these on the server as `caselaw`.

```bash
sudo cloud-init status --long          # "status: done" after the first boot
sudo ufw status verbose                # deny incoming, allow outgoing, 22 80 443 allowed
docker info --format '{{.Driver}}'     # overlay2
id caselaw                             # groups sudo and docker; note the gid
grep CASELAW_GID /etc/caselaw/hosts.env   # the same gid
sudo ls -l /etc/caselaw/secrets        # three files, -rw-r-----, root caselaw
ls -ld /opt/caselaw /opt/caselaw/site /var/lib/caselaw/runs /var/lib/caselaw/backups
cat /etc/cron.d/caselaw-backup
tail -3 /var/lib/caselaw/backups/backup.log   # "backup ok <stamp> <size>" lines
```

One check catches the permission problem of section 7: `COMPOSE exec api cat
/run/secrets/caselaw_dsn` must print the connection string, not "Permission denied".

## 10. Alternatives, and why not

- **Ansible or another configuration tool** instead of cloud-init plus a shell script. It
  would apply one playbook to the live server and to a new one. It adds a tool and an inventory for one server.
- **A container registry and `docker pull`** instead of building on the server. The GitHub
  Actions workflow for AWS does that with ECR. A registry needs a credential on the server and
  a push step on the laptop. The build on the 2 vCPU server is slow but needs nothing else.
- **The AWS stack** in `infra/terraform/`. Written and validated, not applied, for cost.
  Report section 8.6 keeps it as the second target.

## 11. Questions to be able to answer afterwards

- Why does a change to `cloud-init.yaml` not change the live server?
- In which order do `write_files`, `users`, `packages` and `runcmd` run, and why does that
  matter for `/etc/docker/daemon.json`?
- Why does the API container need `group_add`, and where does the number come from?
- What does `--inplace` change about rsync, and which two files depend on it?
- Why does `wait` poll for a marker file instead of waiting for SSH to answer?
- Which rights does the user `caselaw` have, and which of them are root-equivalent?

## 12. Files

| file | role |
|---|---|
| `infra/hetzner/main.tf` | the SSH key, the firewall, the server with `user_data` and `ignore_changes` |
| `infra/hetzner/variables.tf`, `outputs.tf` | `cx23`, `nbg1`, `ubuntu-24.04`, the key path; `ipv4`, `api_url`, `site_url` |
| `infra/hetzner/cloud-init.yaml` | packages, the user, the three written files, the 18 `runcmd` lines |
| `infra/hetzner/compose.yml` | the four services, the three secret files, `group_add`, the bind mounts |
| `infra/hetzner/runtime.secrets.example`, `terraform.op.env` | the runtime keys; the 1Password references for the provider tokens |
| `scripts/hz.sh` | every command of sections 6 and 8 |
| `Makefile`, targets `hz-*` | one wrapper per command; `RUN` defaults to `regex-v0.4` |
| `Dockerfile`; `src/caselaw_extraction/fedlex.py`, `load_code_map` | `USER app` with uid 1000, the cause of two problems in section 7; the `OSError` guard |
| `docs/report.md`, sections 8.1 and 8.5 | what runs where, the two problems of the first run, the cost |
