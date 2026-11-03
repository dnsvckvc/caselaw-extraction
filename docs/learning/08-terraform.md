# Terraform: the Hetzner stack in use, the AWS stack kept as a design, and what we learned

This note explains how Terraform creates the infrastructure of the caselaw deployment. It is
written for someone who would build the same thing by hand and wants to understand each piece
before copying it. The configuration in use is `infra/hetzner/`. The second configuration,
`infra/terraform/`, describes an AWS deployment that was validated but never applied. The
report discusses both in section 8 of `docs/report.md`.

## 1. The problem Terraform solves here

The service needs five kinds of things that exist outside the server. They are the server
itself, a firewall, an SSH key registered at the provider, a storage bucket and two DNS
records. Three companies provide them. Hetzner provides the server, the firewall and the key. Cloudflare
provides the R2 bucket. Njalla provides the DNS zone `inat.io`.

Without Terraform, a person would click through three web consoles and write down what they
did. The next person would not know which settings matter. Terraform replaces the clicking
with six resource blocks in `infra/hetzner/main.tf`. One command creates all of them in the
right order. One command removes all of them. The report says in section 8.5 that
`make hz-destroy` removes the server, the bucket and the two records.

Everything on the server is not Terraform's job. Docker, the Compose stack, Postgres and
Caddy are installed by cloud-init and deployed by `scripts/hz.sh`. Terraform only passes
the cloud-init file to the server as `user_data`.

## 2. The vocabulary

These definitions describe general Terraform behaviour, not something specific to this repository.

**Provider.** A plugin that knows the API of one company. This repository uses five:
`hetznercloud/hcloud`, `cloudflare/cloudflare` and `Sighery/njalla` in the Hetzner stack, and
`hashicorp/aws` and `hashicorp/random` in the AWS stack. `terraform init` downloads them.

**Resource.** One object that Terraform creates and owns, for example `hcloud_server "app"`.
The first word is the type, defined by the provider. The second word is the local name.
Other blocks refer to it as `hcloud_server.app`.

**Data source.** A read-only lookup of something that already exists. The AWS stack reads
the default VPC with `data "aws_vpc" "default"`. The Hetzner stack has no data source.

**Variable, local, output.** A variable is an input with a type and an optional default.
A local is a named expression. An output is a value printed after `apply` and readable later
with `terraform output`. The deploy script reads the server address this way.

**State.** A JSON file that records which real object belongs to which resource block.
Terraform compares the state with the configuration and with the real objects. Without the
state, Terraform would create everything a second time. Here the state is the local file
`infra/hetzner/terraform.tfstate`, which git ignores.

**Plan and apply.** `plan` computes the difference between the configuration and the state
and prints it. `apply` executes that difference. A plan that shows "No changes" means the
state and the configuration agree.

**Dependency graph.** Terraform orders operations by references. `njalla_record_a.site`
reads `hcloud_server.app.ipv4_address`, so the server is created before the record.

**Lifecycle, `ignore_changes`.** A per-resource setting. Terraform does not compare the listed
attributes after the first creation. Section 4.5 explains why the server uses it.

**Lock file.** `.terraform.lock.hcl` pins the exact provider versions that `init` selected.
It is committed, so a second machine downloads the same versions.

## 3. How the pieces connect

```
 laptop                                               providers
 +------------------------------------------------+
 | 1Password vault `caselaw`                      |
 |   hetzner-api/credential ---+                  |
 |   cloudflare-api/credential  | op run          |
 |   cloudflare-api/account_id  | --env-file      |
 |   njalla-api/credential ----+ terraform.op.env |
 |                              v                 |
 |   terraform -chdir=infra/hetzner apply         |
 |     versions.tf   providers and versions       |      +-------------------------+
 |     variables.tf  12 inputs                    | ---> | Hetzner: ssh key,       |
 |     main.tf       6 resources     -------------+      |   firewall, server cx23 |
 |     outputs.tf    9 outputs                    |      |   (user_data = cloud-init)
 |     cloud-init.yaml  rendered by templatefile  | ---> | Cloudflare: R2 bucket   |
 |                                                | ---> | Njalla: two A records   |
 |   terraform.tfstate  (local, ignored by git)   |      +-------------------------+
 +------------------------------------------------+
```

The tokens never touch the disk of the laptop. `op run` resolves the four references in
`infra/hetzner/terraform.op.env` and sets them as environment variables of the one Terraform
process. The state file stays on the laptop. The deploy script excludes it from the rsync to
the server.

## 4. The Hetzner configuration in depth

### 4.1 Providers and versions

`infra/hetzner/versions.tf` requires Terraform 1.6 or newer and three providers:

```hcl
hcloud     = { source = "hetznercloud/hcloud", version = ">= 1.50" }
cloudflare = { source = "cloudflare/cloudflare", version = ">= 5.0" }
njalla     = { source = "Sighery/njalla", version = ">= 0.10" }
```

The lock file resolved these to `hcloud` 1.70.2, `cloudflare` 5.28.1 and `njalla` 0.10.0.
The state file records that Terraform 1.17.1 wrote it last. `Sighery/njalla` is a community
provider, not one from HashiCorp or from Njalla. The report notes this in section 8.1.

### 4.2 How credentials reach the providers

The three providers take their tokens in two different ways. `versions.tf` documents both:

```hcl
provider "hcloud" {}
provider "cloudflare" {}
provider "njalla" {
  api_token = var.njalla_api_token
}
```

The `hcloud` and `cloudflare` providers read `HCLOUD_TOKEN` and `CLOUDFLARE_API_TOKEN` from the
environment. The `njalla` provider has no such convention. It takes the token as an attribute.
The attribute reads the variable `njalla_api_token`, which is marked `sensitive = true`.
Terraform fills any variable from an environment variable named `TF_VAR_<name>`. This is
general Terraform behaviour.

`infra/hetzner/terraform.op.env` names the four values as 1Password references:

```
HCLOUD_TOKEN=op://caselaw/hetzner-api/credential
CLOUDFLARE_API_TOKEN=op://caselaw/cloudflare-api/credential
TF_VAR_cloudflare_account_id=op://caselaw/cloudflare-api/account_id
TF_VAR_njalla_api_token=op://caselaw/njalla-api/credential
```

The file holds no secret, so it is committed. The function `tf` in `scripts/hz.sh` wraps every
Terraform call:

```bash
tf() { op run --env-file "$HZ/terraform.op.env" -- terraform -chdir="$HZ" "$@"; }
```

`op run` reads each reference and asks 1Password for the value. It then starts Terraform with
the values in its environment. The script sets `OP_BIOMETRIC_UNLOCK_ENABLED=true`, so the
1Password app unlocks with Touch ID. The `out` function calls `terraform output -raw` without
`op run`, because reading the local state needs no token.

The repository also holds `infra/hetzner/terraform.env.example`. It describes an older path:
a file `terraform.env` with the plain tokens, sourced by the Makefile. The Makefile does not
do this any more. The example file also mentions Cloudflare DNS records, which the current
configuration does not create. `.gitignore` still ignores `infra/hetzner/terraform.env`.

### 4.3 The six resources

| resource | what it creates | depends on |
|---|---|---|
| `hcloud_ssh_key "admin"` | the public key `~/.ssh/caselaw-prod.pub`, registered at Hetzner | nothing |
| `hcloud_firewall "web"` | four inbound rules: TCP 22, 80, 443 and ICMP, from any address | nothing |
| `hcloud_server "app"` | one `cx23` server, Ubuntu 24.04, in `nbg1`, with IPv4 and IPv6 | the key, the firewall |
| `cloudflare_r2_bucket "runs"` | the bucket `caselaw-runs` in location `WEUR` | the account id variable |
| `njalla_record_a "site"` | the A record `caselaw` in the zone `inat.io`, TTL 300 | the server's IPv4 address |
| `njalla_record_a "api"` | the A record `api.caselaw` in the zone `inat.io`, TTL 300 | the server's IPv4 address |

The server block passes the cloud-init file through `templatefile`:

```hcl
user_data = templatefile("${path.module}/cloud-init.yaml", {
  ssh_public_key = trimspace(file(pathexpand(var.ssh_public_key)))
  site_host      = local.fqdn.site
  api_host       = local.fqdn.api
})
```

Three placeholders in `cloud-init.yaml` receive values from Terraform. The public key goes
into the authorized keys of the user `caselaw`. The two host names go into
`/etc/caselaw/hosts.env`, which Caddy and Compose read. This is the only channel from
Terraform to the inside of the server.

The state file confirms the count: it holds six managed resources and nine outputs.

### 4.4 Variables and outputs

`variables.tf` declares twelve variables. Ten have defaults, for example `server_type = "cx23"`,
`location = "nbg1"` and `domain = "inat.io"`. Two have no default and must come from the
environment: `cloudflare_account_id` and `njalla_api_token`. Both are fed by `TF_VAR_` lines
in `terraform.op.env`. A plan without `op run` therefore stops and asks for them. The
`-input=false` flag in `scripts/hz.sh` turns that question into an error, which is the right
behaviour in a script.

`outputs.tf` declares nine outputs. The deploy script uses three of them:

| output | used by |
|---|---|
| `ipv4` | `ip()` in `scripts/hz.sh`, for every SSH and rsync command |
| `api_url` | `smoke` and `measure` |
| `site_url` | `smoke` |

The `ssh` output builds a ready SSH command. It uses a conditional expression: if the key path
still has its default value, the command names the private key `~/.ssh/caselaw-prod`.
Otherwise it prints the placeholder `<private key>`.

### 4.5 The `ignore_changes = [user_data]` choice

```hcl
lifecycle {
  ignore_changes = [user_data] # cloud-init runs once; a changed script must not recreate the server
}
```

Hetzner cannot change the `user_data` of a running server. The provider therefore treats a
changed `user_data` as a reason to destroy the server and create a new one. That would delete
the database volume and the secret files that cloud-init generated. The lifecycle block tells
Terraform to ignore the attribute after creation. The price is a gap between the file and the
server. Commit `7c274bf` shows it: cloud-init
gained `/etc/docker/daemon.json` for the overlay2 storage driver. The commit message says the
change was "applied by hand on the live server, all volumes kept". A new server starts with
the right file. The live server got the same content by SSH. Anyone who edits
`cloud-init.yaml` must repeat the edit on the server by hand or recreate the server.

### 4.6 State

The state is local. `.gitignore` excludes `infra/hetzner/*.tfstate`, `*.tfstate.*`,
`*.tfplan` and the `.terraform/` directory. The rsync in `scripts/hz.sh deploy` excludes
`infra/hetzner/*.tfstate*` as well, so the server never holds a copy. The report says in
section 8.5 that after `make hz-destroy` the state file on the laptop is the only trace.

A local state has two known limits. These are general Terraform facts. A second operator on
another laptop cannot run `apply` without a copy of the file. A lost laptop means a lost
state, and the resources must be imported again. The report names the same limit for the AWS
design: "a second operator would need an S3 backend".

## 5. Walkthrough of the setup, as done by hand

The steps cover Terraform only. The server-side steps are in the Hetzner note.

1. Install Terraform 1.6 or newer and the 1Password CLI `op`.
2. Create an SSH key pair at `~/.ssh/caselaw-prod` and `~/.ssh/caselaw-prod.pub`.
3. In the Hetzner Cloud console, project `caselaw`, open **Security**, **API tokens**. Create a
   token with read and write permission.
4. In Cloudflare, open **My Profile**, **API Tokens**. Create a token with the permission
   **Account / Workers R2 Storage / Edit**.
5. In Cloudflare, open the R2 overview page. Copy the account ID from the right-hand column.
6. At Njalla, create an API token for the zone `inat.io`.
7. In 1Password, in the vault `caselaw`, create the item `hetzner-api` with the field
   `credential`.
8. Create the item `cloudflare-api` with the fields `credential` and `account_id`.
9. Create the item `njalla-api` with the field `credential`.
10. From the repository root, run `make hz-init`.
   Terraform downloads the three providers and writes `.terraform.lock.hcl`.
11. Run `make hz-plan`.
    The plan lists six resources to add and no change or destruction.
12. Run `make hz-apply`.
    The report says in section 8.1 that this took 30 seconds, the server 24 of them.
13. Run `terraform -chdir=infra/hetzner output`.
    The nine outputs appear, including `api_url` and the `ssh` command.
14. Run `scripts/hz.sh wait`.
    The script polls for `/etc/caselaw/.provisioned` every 10 seconds, 60 times at most.

`make hz-bootstrap` runs steps 12 and 14 and then the secrets, deploy, sync, load and smoke
commands in one sequence.

## 6. What went wrong, and what each mistake teaches

The evidence for Terraform problems is thin. The commits of 2026-11-03 record problems in
Alloy, Caddy, Docker and the backup, not in Terraform. Section 8.1 of the report says the
first `apply` ran in 30 seconds. The three items below are the ones that the files support.

**The cloud-init file and the live server drifted.** Section 4.5 describes this. Commit
`7c274bf` changed `cloud-init.yaml` and applied the same change on the server by hand.
Lesson: `ignore_changes` trades a safe server for a manual step. Write the manual step into
the commit message, as this commit did, or into the deploy script.

**Two generations of credential handling live side by side.** `terraform.env.example`
describes a plain-text file sourced by the Makefile. `terraform.op.env` and `scripts/hz.sh`
describe the 1Password path. Only the second one works today. `.gitignore` still lists
`infra/hetzner/terraform.env`. Lesson: when a path changes, remove or rewrite the example
file of the old path in the same commit.

**The report named commands that did not exist for five days.** Section 8.6 of the report
refers to `make aws-bootstrap` and `make tf-destroy`. Commit `46a1e18` names `scripts/aws.sh`
and the `aws-*` targets in its message, but neither reached git: the files were lost in the
session that wrote that commit. The gap was found on 2026-11-03 while these notes were
written, and the script and the `tf-*` and `aws-*` targets were recreated in the same
session. Lesson: a command named in a document must exist in the repository, and a commit
message is not proof that it does; `git show --stat` is.

The two cost figures for the Hetzner server also differ. The comment in `main.tf` says
"about EUR 4.50". Section 8.5 of the report says "about EUR 5" and explains that Hetzner
renamed and repriced the line. The report is the later and more careful source.

## 7. How to verify

These commands read only the local files and the local state. None of them needs a token,
so none needs `op run`. Running them was outside the scope of this note.

```bash
terraform -chdir=infra/hetzner fmt -check -recursive
terraform -chdir=infra/hetzner validate
terraform -chdir=infra/hetzner state list
terraform -chdir=infra/hetzner output
```

`state list` must print six addresses, one for each resource in section 4.3. `output` must
print nine values.

The check against the real providers is `make hz-plan`. It needs the tokens, so `op run`
wraps it. The expected result is "No changes". A plan that wants to replace
`hcloud_server.app` must not be applied without a backup, because replacement deletes the
server's disk.

CI runs `fmt -check`, `init -backend=false` and `validate` on `infra/terraform` only, in
`.github/workflows/ci.yml`. The Hetzner directory is not validated in CI. `init -backend=false`
downloads the providers without touching any state. This lets `validate` run without
credentials.

## 8. The AWS stack in `infra/terraform`, as a comparison

### 8.1 What it would create

The AWS configuration spans eight files and two providers, `hashicorp/aws` 5.80 or newer and
`hashicorp/random` 3.6 or newer. The lock file resolved them to 6.71.0 and 3.9.1. The
provider block sets the region and two default tags, `Project` and `ManagedBy = "terraform"`,
on every resource.

| file | resources |
|---|---|
| `main.tf` | three data sources: the caller identity, the default VPC, its default subnets |
| `s3.tf` | the bucket `caselaw-runs-<account id>`, a public-access block, server-side encryption |
| `ecr.tf` | the image repository `caselaw-api` with scan on push and a rule that keeps 10 images |
| `rds.tf` | a random password, a subnet group, a security group, Postgres 16 on `db.t4g.micro` with 20 GB, one SSM `SecureString` with the connection string |
| `ecs.tf` | two IAM roles, a log group with 14 days retention, a cluster, two task definitions, two security groups, a load balancer, a target group, a listener on port 80, the Fargate service |
| `cloudwatch.tf` | an SNS topic, an optional e-mail subscription, eight alarms, a dashboard with ten widgets |
| `github.tf` | an OIDC provider and a deploy role, created only when `github_repo` is set |
| `outputs.tf` | fourteen outputs, including `api_url` and `dashboard_url` |

Three patterns appear here that the Hetzner stack does not need. `count` makes a resource
optional: `aws_sns_topic_subscription.email` exists only when `alarm_email` is not empty.
`for_each` creates one ingress rule per entry of `db_allowed_cidrs`. `jsonencode` turns HCL
maps into the JSON that IAM policies, task definitions and the dashboard body expect.

Credentials work differently too. The `aws` provider block names only the region. The AWS
provider reads credentials from the AWS CLI configuration or the environment, which is
general provider behaviour. The repository has no `op.env` file for AWS. Non-secret values go
into `terraform.tfvars`, for which `terraform.tfvars.example` is the template.

### 8.2 Why it stayed a design

The report gives two reasons in the opening of section 8. The AWS stack would cost about
USD 47 per month, most of it for the load balancer and the managed database. The project
already runs a second service on Hetzner, Cloudflare and Njalla. The Hetzner server costs
under EUR 6 per month, as section 8.5 shows.

The AWS stack kept a role. `terraform validate` runs on it in CI on every push. The report
calls it "the stack to apply if a reader wants the managed variant". The next steps in
section 10 of the report list "a day on the AWS stack for a measured comparison" as optional.

The report also names what the cheaper design gives up. The three items are a managed
database with snapshots, a load balancer with its metrics, and the AWS name on the stack.
Section 8.3 of the report lists what replaces each of them on the server.

## 9. Alternatives, and why not

- **Create the resources by hand in the three consoles.** Six objects is few. Nobody could
  then reproduce or destroy them with confidence, and section 8.5 relies on `make hz-destroy`.
- **A shell script with the `hcloud` CLI.** The variable description for `server_type`
  mentions `hcloud server-type list` as a lookup tool. A script would need its own record of
  what exists. Terraform's state is that record.
- **Pulumi or OpenTofu.** Pulumi would need a Python program for the same six resources.
  OpenTofu reads the same HCL and would work with the same files. Neither was tried.
- **Ansible for the server.** Ansible configures a running machine. cloud-init does that once
  here, and `scripts/hz.sh deploy` does the rest with rsync and Compose.
- **A remote state backend.** An S3 or R2 bucket for the state would let a second operator
  run `apply`. The project has one operator, so the local file was kept.

## 10. Questions to be able to answer afterwards

- Which three providers does the Hetzner stack use, and which one is a community provider?
- Why does the `njalla` provider block have an attribute while the other two are empty?
- What does `op run --env-file` do, and why does `terraform output` not need it?
- Which two variables have no default, and where do their values come from?
- What happens to the server if `user_data` changes and `ignore_changes` is removed?
- Why does the deploy script exclude `*.tfstate*` from the rsync?
- What does `init -backend=false` allow CI to do without credentials?
- Which Terraform features does the AWS stack use that the Hetzner stack does not?
- Where is the password of the AWS database generated, and where is it stored?

## 11. Files

| file | role |
|---|---|
| `infra/hetzner/versions.tf` | Terraform version, three providers, how each gets its token |
| `infra/hetzner/main.tf` | the six resources and the `ignore_changes` lifecycle |
| `infra/hetzner/variables.tf` | twelve inputs, two without defaults |
| `infra/hetzner/outputs.tf` | nine outputs, three used by the deploy script |
| `infra/hetzner/cloud-init.yaml` | rendered by `templatefile`, passed as `user_data` |
| `infra/hetzner/terraform.op.env` | the four 1Password references, committed |
| `infra/hetzner/terraform.env.example` | the older plain-text path, no longer used |
| `infra/hetzner/.terraform.lock.hcl` | pinned provider versions, committed |
| `infra/hetzner/terraform.tfstate` | the local state, ignored by git |
| `scripts/hz.sh` | the `tf` wrapper with `op run`, the `init`, `plan`, `apply`, `destroy` commands |
| `Makefile`, targets `hz-*` | one target per `scripts/hz.sh` command |
| `infra/terraform/*.tf` | the AWS stack, validated in CI, never applied |
| `.github/workflows/ci.yml` | `fmt -check`, `init -backend=false`, `validate` on `infra/terraform` |
| `docs/report.md`, section 8 | the deployment, the cost, the AWS design in 8.6 |
