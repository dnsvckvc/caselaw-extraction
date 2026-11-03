# Secrets and 1Password: where each secret lives, how it moves, what must never be on disk

This note explains the secrets model of the caselaw deployment. It is written for someone who
would build the same thing by hand. For every credential it says where the value is kept and
how it reaches the process that needs it. The files it describes are
`infra/hetzner/terraform.op.env`, `infra/hetzner/runtime.secrets.example`,
`infra/hetzner/cloud-init.yaml`, `infra/hetzner/compose.yml` and `scripts/hz.sh`. The report
discusses the design in section 8.1 of `docs/report.md`, paragraph "Secrets".

## 1. The problem

The deployment talks to five providers and runs four containers. Each link needs a credential.
Terraform needs API tokens. The backup needs a storage key. Alloy needs a Grafana token. The API
needs the database password. A credential has to be somewhere. The question is where, for how
long, and who can read it.

Three bad places are common: a committed file, a shell history, and a `docker inspect` output.
The design here avoids all three with one rule. A secret lives in exactly one of three places:
1Password, the server, or a gitignored file on the laptop. Each place has a reason, and each
secret has exactly one place.

## 2. The vocabulary

**Vault.** A 1Password container for items, with its own sharing rules. The deployment uses one
vault, `caselaw`.

**Item.** One record in a vault, for example a login or an API credential. The items here are
`hetzner-api`, `cloudflare-api`, `njalla-api` and `caselaw-server` (named in
`terraform.op.env` and in commit `625a9a9`).

**Field.** One named value inside an item. The references here use the fields `credential` and
`account_id`.

**Secret reference.** A URI of the form `op://vault/item/field` that names a field without
containing its value. A file of references is not secret and can be committed. This is a
general 1Password concept.

**`op run`.** The 1Password CLI command that reads an env file of references and resolves them.
It then starts a child process with the values in its environment. The values exist only inside
that process. `op run` also masks the values if the child prints them (general CLI behaviour).

**`op inject`.** The CLI command that reads a template file, replaces every reference with its
value, and prints the result. The result is secret text and must go somewhere safe.

**Compose secret.** A file that Docker Compose mounts into a container under
`/run/secrets/<name>`. The file is not an environment variable, so it does not appear in
`docker inspect` or in `/proc/<pid>/environ` (general Compose behaviour).

**Interpolation.** Compose replaces `${VAR}` and `$VAR` in its files with environment values.
A `$` inside a secret value is therefore not safe (general Compose behaviour).

**DSN.** The Postgres connection string, `postgresql://user:password@host:port/db`. It contains
the password, so it is a secret in its own right.

## 3. How the pieces connect

```
 laptop                                   1Password (vault caselaw)
 +------------------------------------+   +-------------------------------+
 | terraform.op.env (committed)  -----+-->| hetzner-api/credential        |
 |   op run --env-file ... terraform  |<--| cloudflare-api/credential     |
 |                                    |   | cloudflare-api/account_id     |
 | runtime.secrets (gitignored)  -----+-->| njalla-api/credential         |
 |   op inject -i ...                 |<--| caselaw-server/*              |
 |        | rendered text, in memory  |   +-------------------------------+
 |        v                           |
 |   ssh ... sudo install /dev/stdin -+------------------------------------+
 | ~/.ssh/caselaw-prod (private key)  |                                    |
 | terraform.tfstate (gitignored)     |                                    v
 +------------------------------------+   server (Hetzner cx23)
                                          +-------------------------------------------+
                                          | /etc/caselaw/caselaw.env  root:caselaw 640 |
                                          |   R2_*, GCLOUD_*, BACKUP_HEALTHCHECKS_URL  |
                                          |   --env-file --> Compose --> environment   |
                                          |                                           |
                                          | /etc/caselaw/secrets/      root:caselaw 750|
                                          |   postgres_password  (openssl rand)        |
                                          |   caselaw_dsn        (built from it)       |
                                          |   exporter_dsn       (built from it)       |
                                          |   secrets: --> /run/secrets/<name>         |
                                          +-------------------------------------------+
```

Two arrows never exist. No secret goes from the server to the laptop. No Postgres secret goes
from the laptop to the server, because cloud-init generates it on the server.

## 4. The inventory

| secret | used by | lives in | reaches the process as |
|---|---|---|---|
| Hetzner API token | Terraform, `hcloud` provider | 1Password, `hetzner-api/credential` | `HCLOUD_TOKEN` through `op run` |
| Cloudflare API token | Terraform, `cloudflare` provider | 1Password, `cloudflare-api/credential` | `CLOUDFLARE_API_TOKEN` through `op run` |
| Cloudflare account id | Terraform, R2 bucket and endpoint | 1Password, `cloudflare-api/account_id` | `TF_VAR_cloudflare_account_id` through `op run` |
| Njalla API token | Terraform, `njalla` provider | 1Password, `njalla-api/credential` | `TF_VAR_njalla_api_token` through `op run` |
| SSH key pair | `hz.sh` for every ssh and rsync | laptop, `~/.ssh/caselaw-prod` (private); Hetzner and `authorized_keys` (public) | `ssh -i` |
| Postgres password | the `postgres` container | server, `/etc/caselaw/secrets/postgres_password` | `POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password` |
| Postgres DSN | the `api` container | server, `/etc/caselaw/secrets/caselaw_dsn` | `CASELAW_DSN_FILE=/run/secrets/caselaw_dsn` |
| exporter DSN | the `alloy` container, `postgres_exporter` | server, `/etc/caselaw/secrets/exporter_dsn` | `local.file` with `is_secret = true` |
| R2 key pair | the loader in `api`, `backup.sh` | 1Password, item `caselaw-server`; then `caselaw.env` on the server | `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` in the environment |
| Grafana Cloud token | the `alloy` container | 1Password, item `caselaw-server`; then `caselaw.env` on the server | `GCLOUD_RW_API_KEY` in the environment, read by `sys.env()` |
| healthchecks URL (optional) | `backup.sh` | `caselaw.env` on the server | `BACKUP_HEALTHCHECKS_URL` in the environment |

Three values travel with the secrets but are not secret: `R2_ENDPOINT`, `R2_BUCKET` and
`CASELAW_RUN`. They are in `runtime.secrets` because one file is simpler than two. The
`GCLOUD_*_URL`, `GCLOUD_*_ID` and Cloudflare account id values are identifiers, not credentials.

The exporter DSN differs from the API DSN by one suffix, `?sslmode=disable`. The Postgres
container has no TLS, and `postgres_exporter` would otherwise insist on it.

## 5. The three places and the rule for each

**1Password only.** Every token issued by a provider. The rule: the value is never written to a
file on the laptop. It is read at the moment of use, by `op run` or `op inject`, and then
forgotten. The committed `terraform.op.env` and the gitignored `runtime.secrets` hold references
only. Commit `625a9a9` states the goal: "the real R2 key never sits on the laptop disk".

**The server only.** The Postgres password and the two DSNs. The rule: the value is generated on
the machine that uses it and never leaves it. `cloud-init.yaml` runs `openssl rand -hex 24` on
first boot and builds the two DSNs from the result. Nobody knows the password, and nobody needs
to, because every reader is a container on the same host. The directory is `0750 root:caselaw`,
the files are `0640 root:caselaw`.

**The laptop, in a gitignored file.** Three things that cannot live elsewhere:

- `~/.ssh/caselaw-prod`, the private SSH key. It is outside the repository. The files do not say
  whether a copy is also stored in 1Password.
- `infra/hetzner/terraform.tfstate`. Terraform state records resource attributes in plain text
  (general Terraform behaviour). The report, section 8.5, calls it "the only trace" after a
  destroy.
- `infra/hetzner/runtime.secrets`. With references it holds no secret. With plain values it is a
  secret file, and the example header allows both.

`infra/hetzner/terraform.env` is an older path. Its example header says the Makefile sources it.
The current Makefile does not; every `hz-*` target calls `scripts/hz.sh`, which uses `op run`.
The file stays gitignored in case someone creates it.

## 6. The 1Password CLI in depth

### 6.1 `op run` for Terraform

`scripts/hz.sh` wraps every Terraform command in one function:

```bash
tf() { op run --env-file "$HZ/terraform.op.env" -- terraform -chdir="$HZ" "$@"; }
```

`terraform.op.env` has four lines of the form `NAME=op://caselaw/item/field`. `op run` resolves
them and starts `terraform` with the four variables set. The `hcloud` and `cloudflare` providers
read their tokens from `HCLOUD_TOKEN` and `CLOUDFLARE_API_TOKEN`. The `njalla` provider takes
its token as an attribute, so the file sets `TF_VAR_njalla_api_token` and `versions.tf` passes
the variable in. The variable is marked `sensitive = true`, so plan output masks it.

### 6.2 `op inject` for the server env file

The server needs a file, not a process environment. `hz.sh secrets` therefore uses `op inject`:

```bash
if grep -q 'op://' "$f"; then rendered=$(op inject -i "$f"); else rendered=$(cat "$f"); fi
grep -q 'op://' <<< "$rendered" && { echo "unresolved op:// reference in $f" >&2; exit 1; }
grep -v '^#' <<< "$rendered" | grep -q '\$' && { echo "a value in $f contains \$, which Compose would expand" >&2; exit 1; }
sshc 'sudo install -m 0640 -o root -g caselaw /dev/stdin /etc/caselaw/caselaw.env' <<< "$rendered"
```

The rendered text lives in a shell variable, goes through the ssh pipe, and lands in
`/etc/caselaw/caselaw.env` with mode 640. No temporary file exists on the laptop. The
`install` command writes the file with the right owner and mode in one step.

Two checks run before the upload. The first fails if an `op://` reference survived, which
happens when the vault, item or field name is wrong. The second fails if a non-comment line
contains `$`; section 7.3 explains why.

### 6.3 `op inject` reads comments too

`op inject` is a template engine. It replaces every `op://` reference in the input, inside a
comment or not. It does not know the comment syntax of the target file (general CLI
behaviour). A comment such as `# example: op://caselaw/foo/bar` would make `op inject` look up a
field that does not exist, and the command would fail. The header of `runtime.secrets.example`
therefore names `op inject` in words and shows no literal reference.

The `$` check has a related history. The first version grepped the whole file. The example
header contains the sentence "No `$` in any value", so a file copied from the example failed its
own check. Commit `625a9a9` changed the check to skip comment lines.

### 6.4 The desktop app integration

`hz.sh` sets one variable before any `op` call:

```bash
export OP_BIOMETRIC_UNLOCK_ENABLED="${OP_BIOMETRIC_UNLOCK_ENABLED:-true}"
```

With this variable set to `true`, the CLI asks the 1Password desktop app to unlock, and the app
asks for Touch ID (general CLI behaviour). Without it, the CLI needs `op signin`, which puts a
session token into the shell environment. The script allows an override, so a machine without
the app can set the variable to `false`.

## 7. Compose secrets, environment variables and the `$` rule

### 7.1 Files versus environment variables

`compose.yml` declares three secrets and gives each service the ones it needs:

```yaml
secrets:
  postgres_password:
    file: /etc/caselaw/secrets/postgres_password
  caselaw_dsn:
    file: /etc/caselaw/secrets/caselaw_dsn
  exporter_dsn:
    file: /etc/caselaw/secrets/exporter_dsn
```

Compose bind-mounts each file at `/run/secrets/<name>` in the services that list it. The
`postgres` image reads `POSTGRES_PASSWORD_FILE`. The API reads `CASELAW_DSN_FILE`; the function
`dsn_from_env` in `src/caselaw_extraction/store.py` prefers `CASELAW_DSN`, then reads the file
named by `CASELAW_DSN_FILE`. Alloy reads `/run/secrets/exporter_dsn` with `local.file` and
`is_secret = true`, so its UI and logs mask the content.

The other values are environment variables. Compose reads `/etc/caselaw/caselaw.env` through
`--env-file` and substitutes `${R2_SECRET_ACCESS_KEY:-}` and the `GCLOUD_*` values into the
service environments. These values do appear in `docker inspect` and in `/proc/<pid>/environ`
(general Docker behaviour). Anyone in the `docker` group on the server can read them.

### 7.2 Why the DSN is a file

The DSN contains the Postgres password. If the DSN were an environment variable, the password
would be visible in `docker inspect api`. A file under `/run/secrets` is visible only inside the
container and to root on the host. The report, section 8.1, gives this reason: the secrets
"appear in no `docker inspect` output".

A file needs the right permissions. The API image runs as uid 1000 (`Dockerfile`, `useradd
--uid 1000 app`). The secret files belong to group `caselaw` with mode 640. The container joins
that group through `group_add: ["${CASELAW_GID:-1001}"]`, and cloud-init writes the gid into
`/etc/caselaw/hosts.env`. Section 10 tells what happened before that line existed.

### 7.3 Why no value may contain `$`

Compose interpolates `${VAR}` and `$VAR` in the compose file, and the values for that come from
the env file. Compose also interpolates inside the env file itself (general Compose v2
behaviour). A token with `$` in it would therefore be changed before it reaches the container,
and nothing would report an error. Both headers of the example files say "no `$` in any value",
and `hz.sh secrets` enforces it. The server-generated secrets are hex strings, so they cannot
contain `$`; they are also files, so interpolation never touches them.

## 8. The gitignore entries

`.gitignore` names the deployment files that must not be committed:

```
infra/hetzner/terraform.env
infra/hetzner/runtime.secrets
infra/hetzner/.terraform/
infra/hetzner/*.tfstate
infra/hetzner/*.tfstate.*
infra/hetzner/*.tfplan
caselaw.env
```

`*.tfplan` matters because a saved plan can contain variable values. `caselaw.env` is the name
of the server file, in case someone copies it back to the laptop. The `deploy` command of
`hz.sh` repeats the list as rsync excludes, so the files do not reach `/opt/caselaw/repo` on
the server either.

## 9. Walkthrough of the setup, as done by hand

1. Install the 1Password CLI and the desktop app. Turn on the CLI integration in the app.
2. Create the vault `caselaw`.
3. Create an API token at Hetzner (project `caselaw`, read and write). Store it as
   `hetzner-api`, field `credential`.
4. Create a Cloudflare token with the permissions in `terraform.env.example`. Store it as
   `cloudflare-api`, field `credential`. Store the account id in the field `account_id`.
5. Create a Njalla API token. Store it as `njalla-api`, field `credential`.
6. Generate the SSH key pair `~/.ssh/caselaw-prod`. Keep the private key outside the
   repository.
7. Run `make hz-apply`. The Touch ID prompt appears once. Terraform creates the server, the
   bucket and the DNS records.
8. Run `scripts/hz.sh wait`. Cloud-init generates the Postgres secrets on the server during this time.
9. Create the R2 key pair with "Object Read & Write" on the bucket `caselaw-runs`. Store both
   values in the item `caselaw-server`.
10. Create the Grafana Cloud token. Store it and the four `GCLOUD_*` identifiers in the item
    `caselaw-server`.
11. Copy `runtime.secrets.example` to `runtime.secrets`. Replace each empty value with the
    matching `op://caselaw/caselaw-server/<field>` reference.
12. Run `make hz-secrets`. The output says how many values were set.
13. Run `make hz-deploy`. The containers start with the new environment.

The repository names only the variables; the field names in `caselaw-server` are the creator's choice.

## 10. What went wrong, and what each mistake teaches

The evidence in the repository is thin: two commits describe secret-related fixes, and no commit
or comment documents a leak. The items below are the documented ones.

**The API container could not read its secret file.** Commit `1542125` and report section 8.1
describe it. The host group `caselaw` received gid 1001, because Docker took gid 1000 first.
The container runs as uid 1000 with no matching group, so the 640 file was unreadable. The fix
is `group_add` with the gid from `hosts.env`. Lesson: a file secret shifts the problem from
"who can see the environment" to "who can read the file". Check uid and gid on both sides.

**The R2 key sat on the laptop disk.** Before commit `625a9a9`, `runtime.secrets` held plain
values, and `hz.sh secrets` sent the file as it was. The commit added `op inject`, so the file
now holds references. Lesson: an env file with real values is a secret file even if git ignores
it. Backups, sync tools and shell history can copy it.

**The `$` check rejected the example header.** The same commit changed the check to skip
comments, because the header sentence contains a `$`. Lesson: a check that scans a whole file
must know what is a value and what is a comment.

**A debug flag printed the R2 key pair.** This incident is not in any commit message; it is
recorded here from the session of 2026-11-03 by the assistant that caused it. While debugging
the rclone 501 errors (commit `4860de7`), rclone ran with `-vv`. At that level rclone prints
every configuration value it reads from the environment, including `access_key_id` and
`secret_access_key`, and a filter on the word "authorization" did not catch those lines. The
two values landed in the session transcript on the laptop and in the conversation sent to the
model API. The key had object rights on one bucket, nothing else. The user rolled the token in
Cloudflare, updated the 1Password item and ran `make hz-secrets` and `make hz-deploy`, the
steps of section 11. The later tests used a temporary rclone config file, which prints nothing.
Lesson: never raise a tool to debug level while credentials are in its environment, and
filter output by what is allowed through, not by what is known to be dangerous.

## 11. What a leak looks like, and the rotation steps

A leak is a secret value in a place that is not one of the three places of section 5. The
likely places, in order of frequency (general experience, not an incident list):

- a terminal transcript or a log of a command run with a debug or verbose flag;
- the shell history, after a value was pasted into a command line;
- `docker inspect` or `docker compose config` output pasted into a chat or an issue;
- a committed file, including a saved Terraform plan or state.

For an environment-variable secret such as the R2 key, the rotation follows this order. The
repository does not script it; the commands below are the existing `make` targets.

1. Create the new key at the provider. Keep the old key active.
2. Replace the values in the 1Password item `caselaw-server`.
3. Run `make hz-secrets`. The server file now holds the new key.
4. Run `make hz-deploy`. Compose recreates the `api` container with the new environment.
   `backup.sh` reads the env file at each run, so it needs no restart.
5. Run `scripts/hz.sh backup-now`. The log line must start with `backup ok`.
6. Revoke the old key at the provider.
7. Search the place of the leak and remove the value, if the medium allows it.

The Grafana token follows the same steps, with `alloy` as the recreated container. A Terraform
token needs only steps 1, 2 and 6, plus one `make hz-plan` to confirm. No script rotates the
Postgres password. That rotation would need `ALTER USER`, three rewritten files under
`/etc/caselaw/secrets`, and a restart of `postgres`, `api` and `alloy`.

## 12. How to verify

Run these from the repository root. None of them prints a secret value.

```bash
git check-ignore -v infra/hetzner/runtime.secrets infra/hetzner/terraform.tfstate infra/hetzner/terraform.env
git ls-files infra/hetzner | grep -E 'secrets|\.env|tfstate'      # must show only *.example and terraform.op.env
grep -c 'op://' infra/hetzner/runtime.secrets                       # one reference per secret value
grep -v '^#' infra/hetzner/runtime.secrets | grep -E 'KEY|TOKEN' | grep -v 'op://'   # must print nothing
```

On the server, through `make hz-ssh`:

```bash
ls -la /etc/caselaw /etc/caselaw/secrets        # 640 root:caselaw, directory 750
docker inspect hetzner-api-1 --format '{{json .Config.Env}}' | grep -c CASELAW_DSN_FILE   # 1: the path, not the DSN
docker inspect hetzner-api-1 --format '{{json .Config.Env}}' | grep -c 'postgresql://'    # 0: the DSN is not in the container config
docker exec hetzner-api-1 ls -la /run/secrets/   # caselaw_dsn present
```

## 13. Alternatives and a stricter setup

- **Plain env files on the laptop.** The first version of this deployment did that for the
  runtime values. It works. The cost is one more secret file to protect.
- **1Password service accounts.** A token that lets a CI runner call `op` without the desktop
  app and without a human. It would replace the laptop in `make hz-secrets` and `make hz-deploy`.
  Report section 10 lists a deploy job over SSH as the next step; this is what it would need.
- **Short-lived tokens.** Cloudflare tokens and Grafana Cloud tokens can carry an expiry (general provider behaviour).
  The AWS design (report section 8.6) goes further and uses GitHub OIDC, so no long-lived key
  exists at all. The Hetzner stack does not do this yet.
- **SOPS or age-encrypted files.** `runtime.secrets` could be committed in encrypted form, with
  the key in 1Password. The history of the file would then be in git. The gain is small for one
  operator and one file, which is why the plain references were chosen.

## 14. Questions to be able to answer afterwards

- Which secret exists in exactly one copy, and why does nobody need to know it?
- Why does `op run` fit Terraform and `op inject` fit the server, and not the other way round?
- What does `op inject` do with an `op://` string inside a comment?
- Where does an environment variable of a container become visible, and to whom?
- Why is the DSN a file, when `GCLOUD_RW_API_KEY` is an environment variable?
- What would a `$` inside a token do, and which check stops it?
- In which order do you rotate a key, and why does the old key stay active until step 6?
- What does Terraform state contain, and why is it gitignored?

## 15. Files

| file | role |
|---|---|
| `infra/hetzner/terraform.op.env` | the four Terraform references, committed |
| `infra/hetzner/terraform.env.example` | the older plain-value path, header with the Cloudflare permissions |
| `infra/hetzner/runtime.secrets.example` | the names of the runtime values, header with the `$` rule |
| `scripts/hz.sh` | the `tf` wrapper with `op run`, the `secrets` command with `op inject`, the rsync excludes |
| `infra/hetzner/cloud-init.yaml` | generation of the Postgres password and the two DSNs, modes and owners |
| `infra/hetzner/compose.yml` | the `secrets` section, the `*_FILE` variables, `group_add` |
| `infra/hetzner/alloy/config.alloy` | `local.file` with `is_secret`, `sys.env()` for the Grafana values |
| `infra/hetzner/backup.sh` | rclone configured from the environment, the optional healthchecks ping |
| `infra/hetzner/versions.tf`, `variables.tf` | provider credentials from the environment, `sensitive = true` |
| `src/caselaw_extraction/store.py` | `dsn_from_env`, `CASELAW_DSN` then `CASELAW_DSN_FILE` |
| `.gitignore` | the seven deployment entries of section 8 |
| `docs/report.md`, section 8.1 | the paragraph "Secrets" |
