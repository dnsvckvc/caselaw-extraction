# Cloudflare R2 and rclone: object storage for the runs and the backups

This note explains the object storage of the caselaw deployment. It is written for someone
who would build the same thing by hand and wants to understand each piece before copying it.
The bucket is `cloudflare_r2_bucket.runs` in `infra/hetzner/main.tf`. The nightly writer is
`infra/hetzner/backup.sh`. The reader is `open_run` in `src/caselaw_extraction/db.py`. The
report discusses the design in sections 8.1, 8.3 and 8.5 of `docs/report.md`.

## 1. The problem object storage solves here

The server holds two kinds of data that must survive the server. The first is the run
directory under `/var/lib/caselaw/runs`: the Parquet tables and `run.json` of each extraction
run. The second is the Postgres database, which the loader rebuilds from a run in seconds.
Report section 8.1 gives the size as about 8 MB per run.

Both must leave the server every night, because `make hz-destroy` deletes the server and
its disk. A second copy on the same disk is not a backup. A bucket at a different provider
is a backup, and it is also the handover point between the pipeline and the database. The
loader can read a run from the bucket, so a new server needs no upload from the laptop.

The AWS design in `infra/terraform/s3.tf` used an S3 bucket for the same role. The Hetzner
design keeps the S3 protocol and replaces the provider with Cloudflare R2. The code paths
and tools do not change.

## 2. The vocabulary

**Object store.** A service that stores blobs under names and serves them over HTTP. It is not
a file system. There are no directories, no rename in place, no append and no partial write.
A write replaces the whole object.

**Bucket.** The top-level container for objects. A bucket has a name that is unique within
the account and a location. Ours is `caselaw-runs`, created in location `WEUR` (Western
Europe).

**Key.** The full name of an object inside a bucket, for example
`runs/regex-v0.4/decisions.parquet`. The slashes are characters in the key, not directory
separators. Tools such as rclone and the S3 console show a "folder" by listing keys with a
common prefix. This is general S3 behaviour.

**Prefix.** The leading part of a key that several keys share. Our two prefixes are
`backups/` and `runs/`. A list request with a prefix returns only the matching keys.

**S3 API.** The HTTP protocol that Amazon S3 defined and that many stores implement: PUT,
GET, HEAD, DELETE and LIST on buckets and keys, signed with an access key id and a secret
access key. R2 implements this API. Any S3 client works against R2 when it is pointed at the
R2 endpoint.

**Endpoint.** The base URL that a client sends S3 requests to. For R2 the form is
`https://<account id>.r2.cloudflarestorage.com`. `infra/hetzner/outputs.tf` builds this
string from `var.cloudflare_account_id`. The account id is not a secret, but the project
treats it as a Terraform variable from 1Password so that it does not sit in the repository.

**Region.** An S3 request carries a region in its signature. R2 has no regions in the AWS
sense and accepts the value `auto`. Both `backup.sh` and `compose.yml` set `auto`.

**Consistency.** R2 is strongly consistent according to Cloudflare's documentation: a GET or
LIST after a PUT returns the new object. This is general knowledge about R2, not something
the repository tests. It matters for `rclone sync`, which lists the bucket to decide what
to copy.

**Versioning and version id.** Some stores keep old versions of an object and return an
`x-amz-version-id` header on PUT. R2 returns such a header. Section 6 explains why that
header caused the one problem in this setup.

**Scoped token.** An API token that may do a fixed set of operations on a fixed set of
resources. R2 offers tokens with `Object Read & Write` on one bucket. Such a token cannot
create or delete buckets and cannot touch other buckets.

## 3. How the pieces connect

```
 laptop                                  Cloudflare account
 +-----------------------------+         +---------------------------------------+
 | terraform (op run)          |         | R2 bucket caselaw-runs (WEUR)         |
 |   CLOUDFLARE_API_TOKEN -----+--create-> |                                     |
 |   (account-level token)     |         |   backups/caselaw-<stamp>.dump        |
 +-----------------------------+         |   runs/<run>/decisions.parquet        |
                                         |   runs/<run>/spans.parquet            |
 server (Hetzner cx23)                   |   runs/<run>/citations.parquet        |
 +-----------------------------+         |   runs/<run>/centrality.parquet       |
 | /etc/caselaw/caselaw.env    |         |   runs/<run>/run.json                 |
 |   R2_ACCESS_KEY_ID          |         +------------------^-------------^------+
 |   R2_SECRET_ACCESS_KEY      |                            |             |
 |   R2_ENDPOINT, R2_BUCKET    |      S3 API over HTTPS     |             |
 |                             |                            |             |
 | cron 03:30 -> backup.sh     |                            |             |
 |   pg_dump --> rclone copy ---------- PUT backups/ -------+             |
 |   runs dir -> rclone sync ---------- PUT/DELETE runs/ ---+             |
 |   rclone delete --min-age 14d ------ DELETE backups/ ----+             |
 |                             |                                          |
 | api container (optional)    |                                          |
 |   caselaw db-load           |                                          |
 |   --runs-dir s3://.../runs --------- GET runs/ (pyarrow S3FileSystem) -+
 +-----------------------------+
```

Two different credentials appear in this picture. The account-level token at the top is
used once, by Terraform, to create the bucket. The scoped key pair in the middle is used
every night, by the server, to write and read objects. Section 4.2 explains why they are
not the same key.

## 4. Cloudflare R2, the store

### 4.1 Pricing and limits

Report section 8.5 states the cost of R2 for this project as EUR 0 per month. The project
stores about 20 MB and sends a few hundred requests. The free tier covers 10 GB of storage.
The report gives no other R2 price.

The general pricing model of R2, from Cloudflare's own documentation, is storage per GB and
month plus a price per million requests. Cloudflare charges nothing for egress, that is for
bytes downloaded from the bucket. AWS S3 charges for egress to the internet. This is the
usual argument for R2 when a bucket is read from outside the provider's network, as a loader
on a Hetzner server does. The report does not make this argument explicitly; it only reports
the free tier.

### 4.2 Two credentials, two jobs

**The account-level token.** `infra/hetzner/versions.tf` declares the Cloudflare provider.
The provider reads `CLOUDFLARE_API_TOKEN` from the environment. `scripts/hz.sh` runs
Terraform under `op run --env-file infra/hetzner/terraform.op.env`, and that file holds a
1Password reference, not a value. This token may create and delete R2 buckets in the
account. Terraform needs exactly that right for `cloudflare_r2_bucket.runs`. The token is
used only on the laptop and only during `terraform apply` and `terraform destroy`.

**The scoped R2 key.** `infra/hetzner/runtime.secrets.example` names four values:
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT` and `R2_BUCKET`. The comment says
where they come from: Cloudflare R2, **Manage R2 API tokens**, `Object Read & Write` on the
bucket `caselaw-runs`. The comment also says when to create it: after the first
`make hz-apply`, because the bucket must exist before a token can be scoped to it.
`scripts/hz.sh secrets` writes these values to `/etc/caselaw/caselaw.env` on the server,
owned by root, group `caselaw`, mode 640.

**Why the account-level token must not go to the server.** The server is the most exposed
machine in the design. It has ports 22, 80 and 443 open to the internet. A key that leaks
from the server should be able to do as little as possible. The scoped key can read and
write objects in one bucket. The account-level token can create and delete every bucket in
the account, and the Cloudflare provider token may have other Cloudflare rights too. The
blast radius of the two keys differs by an order of magnitude. The split also makes
rotation simple: a new scoped key needs `make hz-secrets` and nothing else.

**Where the scoped key is visible.** `compose.yml` passes the four values to the `api`
container as the environment variables `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_ENDPOINT_URL_S3` and `AWS_REGION`. This differs from the Postgres password, which
reaches the container as a secret file. The report explains the file route for Postgres in
section 8.1. The R2 key takes the environment route because pyarrow and the AWS SDK read the
standard `AWS_*` variables, and the compose comment says the loader is the only user. Someone
with `docker inspect` rights on the server can read the scoped key. That is a conscious
trade: the key is scoped, and the server already holds it in `caselaw.env`.

### 4.3 The bucket layout and retention

| prefix | writer | content | retention |
|---|---|---|---|
| `backups/` | `rclone copy` in `backup.sh` | `caselaw-<UTC stamp>.dump`, a `pg_dump -Fc` file | `rclone delete --min-age 14d` removes dumps older than 14 days |
| `runs/` | `rclone sync` in `backup.sh` | a mirror of `/var/lib/caselaw/runs`: one directory per run with Parquet and `run.json` | mirror; a run deleted on the server disappears from the bucket at the next sync |

The local copy of the dumps under `/var/lib/caselaw/backups` is pruned after 3 days by
`find -mtime +3 -delete`. The bucket is therefore the only place that holds 14 days.

Two general rclone facts explain the choice of `copy` for dumps and `sync` for runs. `copy`
adds and updates files and never deletes remote files. `sync` makes the destination equal to
the source, deletions included. Dumps accumulate, so `copy` plus an age-based delete is right.
The run directory is a mirror, so `sync` is right.

## 5. rclone, the client

rclone is a command-line program that moves files between local disks and about seventy
cloud storage backends. One backend type is `s3`, with a `provider` setting that adjusts the
details for each S3-compatible store. cloud-init installs the Ubuntu package on the server
(`infra/hetzner/cloud-init.yaml`, package list). The commit history names the version:
rclone 1.60 from Ubuntu 24.04.

### 5.1 Configuration through environment variables

rclone normally reads remotes from `~/.config/rclone/rclone.conf`. A remote named `r2` would
be a section `[r2]` with keys `type`, `provider` and so on. rclone also accepts each key as
an environment variable of the form `RCLONE_CONFIG_<REMOTE>_<KEY>`. This is general rclone
behaviour. `backup.sh` uses only this form:

```bash
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto \
  RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
```

The script sources `/etc/caselaw/caselaw.env` first, with `set -a` so that each value is
exported. The remote `r2` then exists for the lifetime of the script and nowhere else. The
file comment and report section 8.3 both state the reason: no rclone configuration file on
disk holds a key. The key lives in exactly one file, `caselaw.env`, with one owner and one
mode.

### 5.2 The three commands

```bash
rclone copy "$out" "r2:$R2_BUCKET/backups/" --s3-no-check-bucket --s3-no-head
rclone sync /var/lib/caselaw/runs "r2:$R2_BUCKET/runs/" --s3-no-check-bucket --s3-no-head
rclone delete "r2:$R2_BUCKET/backups/" --min-age 14d
```

The path form is `<remote>:<bucket>/<prefix>`. `$R2_BUCKET` defaults to `caselaw-runs` in
the script when `caselaw.env` does not set it.

### 5.3 The two flags

**`--s3-no-check-bucket`.** By default rclone checks that the bucket exists before the first
upload and creates it when it does not. This is general rclone behaviour. The check and the
create need bucket-level rights. The scoped key has object rights only, so the create would
fail with an access error. The flag skips the check. It also saves one request per run.

**`--s3-no-head`.** By default rclone sends a HEAD request after each upload to confirm the
object's size and metadata. This is general rclone behaviour. The flag skips that request.
Section 6 explains why this project needs it. The comment in `backup.sh` names the remaining
integrity check: rclone sends a `Content-MD5` header with each upload, and the store rejects
an upload whose body does not match it.

## 6. Walkthrough of the setup, as done by hand

1. Put the Cloudflare account id and an account-level API token into 1Password. The
   references go into `infra/hetzner/terraform.op.env`.
2. Run `make hz-apply`. Terraform creates the bucket `caselaw-runs` in `WEUR`.
3. In the Cloudflare dashboard, open **R2**, then **Manage R2 API tokens**.
4. Create a token with the permission **Object Read & Write** on the bucket `caselaw-runs`.
   The dashboard shows an access key id, a secret access key and the S3 endpoint.
5. Copy `infra/hetzner/runtime.secrets.example` to `infra/hetzner/runtime.secrets`.
6. Fill `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` and `R2_ENDPOINT` with values or with
   `op://` references.
7. Run `make hz-secrets`. The script writes `/etc/caselaw/caselaw.env` on the server.
8. Run `make hz-deploy`. The script installs `/etc/cron.d/caselaw-backup` with the line
   `30 3 * * * caselaw /opt/caselaw/repo/infra/hetzner/backup.sh`.
9. Run `scripts/hz.sh backup-now`. The script prints `backup ok <stamp> <size>`.

Step 4 must follow step 2. A token scoped to a bucket needs the bucket to exist, and the
comment in `runtime.secrets.example` says so.

## 7. What went wrong, and what each mistake teaches

One problem is in evidence, in commit `4860de7` and in the comment of `backup.sh`. The
other setup steps left no trace of trouble in commits, comments or the report.

**Every upload was reported as failed although the object was stored.** R2 returns an
`x-amz-version-id` header on PUT. rclone 1.60 reads that header and then sends a HEAD
request with `?versionId=<id>` to verify the upload. R2 does not implement HEAD by version
id and answers 501 Not Implemented. rclone treated the 501 as a failed upload and retried.
The object was already in the bucket after the first PUT. The fix in commit `4860de7` is the
flag `--s3-no-head` on both `rclone copy` and `rclone sync`. The upload is still verified by
`Content-MD5`.

The lesson has three parts. First, "S3-compatible" describes the common subset of the API,
not the whole API. Each store implements a different subset, and a client written against
AWS behaviour can trip over the gap. Second, read the client's error before you trust it. A
"failed" upload that leaves an object in the bucket is a verification problem, not a
transfer problem. Third, an old client from a distribution package meets more such gaps than
a current one. Ubuntu 24.04 ships rclone 1.60. A newer rclone may handle R2's version id
differently, but the repository has not tested that.

## 8. How to verify

The repository offers no verification command of its own. The following steps use the
existing scripts and general rclone commands. Run them from the repository root.

1. Run `scripts/hz.sh backup-now`. The last line is `backup ok <stamp> <size>`.
2. Run `scripts/hz.sh ssh 'tail -n 5 /var/lib/caselaw/backups/backup.log'`. The log shows
   one `backup ok` line per night and no `backup FAILED` line.
3. Run `scripts/hz.sh ssh 'ls -l /var/lib/caselaw/backups'`. The directory holds at most
   three days of dumps.
4. Run the following on the server to list the bucket with the same environment as the
   backup. The output shows the `backups/` and `runs/` prefixes.

   ```bash
   set -a; . /etc/caselaw/caselaw.env; set +a
   export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto \
     RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
     RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
   rclone lsd "r2:$R2_BUCKET"
   rclone ls "r2:$R2_BUCKET/backups/"
   ```

5. If `BACKUP_HEALTHCHECKS_URL` is set, open the check at healthchecks.io. The last ping
   time is after 03:30 UTC of the current day.

A restore test is the real verification. The repository has no restore script. The manual
path is `rclone copy` of one dump to the server, then `pg_restore` into the `postgres`
container. Report section 10 lists switching on the scoped key as the first next step, so
the first nightly run and the first restore are still ahead.

## 9. The loader reads from the bucket

`open_run(runs_dir, name)` in `src/caselaw_extraction/db.py` returns a pyarrow filesystem
and a base path. It handles three cases:

| `runs_dir` | filesystem | base path |
|---|---|---|
| a local path | `LocalFileSystem` | the resolved absolute path |
| `s3://bucket/prefix` with `AWS_ENDPOINT_URL_S3` or `AWS_ENDPOINT_URL` set | `S3FileSystem(endpoint_override=..., region=AWS_REGION or "auto")` | `bucket/prefix/<name>` |
| any other `scheme://` | `FileSystem.from_uri` | as pyarrow returns it |

The second row is the R2 path. The code comment says that the variable names follow the AWS
CLI, so the same environment works for the AWS CLI, boto3 and pyarrow. The credentials come
from `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, which pyarrow reads on its own. The
test `test_open_run_local_and_s3_endpoint` in `tests/test_store_env.py` checks that an
endpoint variable selects `S3FileSystem` and that the base path is `bucket/runs/r`.

`load_run` then opens `<base>/run.json` with `fs.open_input_file` and reads each Parquet file
with `pq.read_table(path, filesystem=fs)`. The same code runs against a local directory. The
`api` service in `compose.yml` gets the `AWS_*` variables so that this command works on the
server:

```bash
caselaw db-load --run regex-v0.4 --runs-dir s3://caselaw-runs/runs
```

`scripts/hz.sh load` does not use this path. It runs the loader against `/data/runs`, the
read-only mount of `/var/lib/caselaw/runs`, after `scripts/hz.sh sync` has copied the run
with rsync from the laptop. The S3 path is the second route, for a rebuilt server that has
no local run yet.

## 10. Alternatives, and why not

- **Amazon S3**, as in `infra/terraform/s3.tf`. That design is kept and validated in CI
  (report section 8.6). It needs an AWS account, and reads from a Hetzner server pay egress.
  The bucket there also carries a public access block and server-side encryption settings
  that R2 applies by default or does not expose.
- **Hetzner Object Storage or Hetzner Storage Box.** Both are closer to the server. Neither is
  used, and the files give no reason. A copy at a second provider survives the loss of the
  Hetzner account, which a copy at the same provider does not.
- **A second disk or a Hetzner snapshot.** A snapshot restores the whole server but costs
  per GB per month and lives in the same account. It does not give the loader a readable
  run.
- **An rclone configuration file.** Simpler to type, but it is a second copy of the key with
  its own permissions to manage. Environment variables keep the key in one file.
- **The AWS CLI or `s3cmd` instead of rclone.** Both work against R2. rclone is one binary
  from the Ubuntu repository, and its `sync` and `delete --min-age` cover the whole backup in
  three lines.

## 11. Questions to be able to answer afterwards

- Why can an object store have no directories, and what does a "folder" in a listing mean?
- Which credential creates the bucket, which one writes to it, and where does each one live?
- What could an attacker do with the scoped key, and what could they do with the account token?
- Why must the scoped R2 key be created after the first `terraform apply`?
- How does rclone find the remote `r2` when no `rclone.conf` exists?
- What does `--s3-no-check-bucket` skip, and why would the scoped key fail without it?
- What does R2 return on PUT that rclone 1.60 did not expect, and which request then fails?
- Which check still verifies an upload when `--s3-no-head` is set?
- Why is `copy` right for `backups/` and `sync` right for `runs/`?
- Which environment variable makes pyarrow talk to R2 instead of AWS, and which one sets the region?

## 12. Files

| file | role |
|---|---|
| `infra/hetzner/main.tf` | `cloudflare_r2_bucket.runs`, location `WEUR` |
| `infra/hetzner/variables.tf` | `bucket` (default `caselaw-runs`), `cloudflare_account_id` |
| `infra/hetzner/outputs.tf` | `bucket`, `r2_endpoint` |
| `infra/hetzner/versions.tf` | the Cloudflare provider, token from `CLOUDFLARE_API_TOKEN` |
| `infra/hetzner/terraform.op.env` | 1Password references for the Terraform tokens |
| `infra/hetzner/runtime.secrets.example` | the four `R2_*` names and where the scoped key comes from |
| `infra/hetzner/backup.sh` | the nightly cron: `pg_dump`, `rclone copy`, `rclone sync`, `rclone delete` |
| `infra/hetzner/compose.yml`, service `api` | the `AWS_*` variables for the loader |
| `infra/hetzner/cloud-init.yaml` | installs rclone; creates `/var/lib/caselaw/runs` and `/var/lib/caselaw/backups` |
| `scripts/hz.sh` | `secrets`, `deploy` (installs the cron line), `backup-now`, `sync`, `load` |
| `src/caselaw_extraction/db.py` | `open_run`, `load_run` |
| `tests/test_store_env.py` | `test_open_run_local_and_s3_endpoint` |
| `infra/terraform/s3.tf` | the AWS S3 bucket of the design that was not applied |
| `docs/report.md`, sections 8.1, 8.3, 8.5, 10 | the design, the backup, the cost, the next step |
