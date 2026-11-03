# Caddy, Let's Encrypt and Njalla DNS: what they do, how we use them, what we learned

This note explains how the two public hosts of the caselaw server get a name, a certificate
and a route to the right process. It is written for someone who would build the same thing by
hand and wants to understand each piece before copying it. The config is
`infra/hetzner/Caddyfile`. The container is the `caddy` service in `infra/hetzner/compose.yml`.
The DNS records are the two `njalla_record_a` resources in `infra/hetzner/main.tf`. The report
describes the layer in one row of the table in section 8.1 of `docs/report.md`.

Facts about this repository come from those files and the commit history. General Caddy,
ACME or DNS behaviour is marked as such.

## 1. The problem this layer solves

The server runs one API container on port 8000 inside the Docker network. The report and the
graph are two HTML files in `/opt/caselaw/site`. Nothing on the server listens on port 80 or
443. We want four things:

- The API answers at `https://api.caselaw.inat.io`.
- The report and the graph answer at `https://caselaw.inat.io`.
- Both hosts have a valid certificate that renews itself.
- A request over plain HTTP is redirected to HTTPS.

In the AWS design (report section 8.6) a load balancer did the routing over HTTP only, because
there was no domain. On the Hetzner server Caddy does the routing, the static files and the
certificates in one container. The domain `inat.io` provides the names.

## 2. The vocabulary

**Reverse proxy.** A server that accepts a request from the internet and forwards it to a
process behind it. Caddy forwards requests for the API host to `api:8000`. The API never sees
the internet directly.

**Static file server.** A server that maps a URL path to a file on disk. Caddy serves
`/srv/site/index.html` for `https://caselaw.inat.io/`.

**TLS certificate.** A signed statement that a public key belongs to a host name. The browser
checks the signature against a certificate authority (CA) that it trusts. Let's Encrypt is a
free CA.

**ACME.** The protocol between a server and the CA to prove control of a name and obtain a
certificate. Caddy contains an ACME client. This is general Caddy behaviour.

**HTTP-01 challenge.** One ACME method of proof. The CA asks the server to publish a token
at `http://<host>/.well-known/acme-challenge/<token>`. The CA fetches that URL over port 80.
If the token matches, the CA issues the certificate. The challenge runs over HTTP, not HTTPS.

**A record.** A DNS record that maps a host name to an IPv4 address. The two records here
map `caselaw.inat.io` and `api.caselaw.inat.io` to the server's IPv4 address.

**Zone.** The set of DNS records of one domain, kept at one DNS provider. The zone of `inat.io`
is at Njalla, where the domain is registered.

**TTL.** The number of seconds that a resolver may cache a record. Both records use 300.

**308 Permanent Redirect.** An HTTP status that tells the client to repeat the same request at
another URL with the same method. Caddy answers every plain HTTP request with a 308 to the
HTTPS URL. This is general Caddy behaviour.

**HSTS.** The `Strict-Transport-Security` header. It tells the browser to use HTTPS for this
host for the given number of seconds, here one year.

**Site block and placeholder.** A Caddyfile is a list of site blocks. Each block starts with
an address. `{$API_HOST}` is a placeholder that Caddy fills from the environment variable
`API_HOST` when it loads the config.

**Admin API.** Caddy's own control endpoint on `localhost:2019`. The `caddy reload` command
talks to it. The metrics live there too, unless a site serves them.

## 3. How the pieces connect

```
 laptop / browser                 Njalla DNS (zone inat.io)
   |  1. A? api.caselaw.inat.io -----> A record, TTL 300, created by Terraform
   |  2. <ipv4 of the server> <------
   |
   |  3. tcp 80 or 443
   v
 Hetzner firewall (22, 80, 443, icmp)         Let's Encrypt
   v                                             |  HTTP-01: GET /.well-known/acme-challenge/<token>
 ufw on the host (22, 80, 443)                   |  over port 80
   v                                             v
 Docker: ports 80:80 and 443:443 -------------> caddy container (caddy:2-alpine)
                                                 |  :80   308 redirect to https
                                                 |  :443  {$API_HOST}  -> reverse_proxy api:8000
                                                 |        {$SITE_HOST} -> file_server /srv/site
                                                 |  :2020 metrics (Docker network only)  <-- alloy container
                                                 |  localhost:2019 admin API (container only)
                                                 |
                                                 +-- /data   volume caddy_data   (certificates, keys)
                                                 +-- /config volume caddy_config (autosaved config)
```

Three network boundaries sit in front of Caddy. The Hetzner firewall in `main.tf` admits
22, 80, 443 and ping. `ufw` in `cloud-init.yaml` repeats 22, 80 and 443. Compose publishes 80
and 443 to the container. All three must allow port 80, or the challenge fails.

## 4. Caddy in depth

### 4.1 The Caddyfile, block by block

```
{
	metrics
}

:2020 {
	metrics
}

{$API_HOST} {
	reverse_proxy api:8000 {
	}
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
		Access-Control-Allow-Origin *
	}
}

{$SITE_HOST} {
	root * /srv/site
	file_server
	encode zstd gzip
	header {
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options nosniff
	}
}
```

**The global block.** The first block without an address holds global options. `metrics`
turns on Prometheus metrics for every server. Without it, the request counters per host do
not exist.

**The `:2020` block.** A site with a port and no host name. Caddy serves it over plain HTTP.
Its only handler is `metrics`, so it answers `/metrics` and nothing else. Compose does not
publish port 2020. Only containers in the Compose network reach it, under the name
`caddy:2020`. The Grafana note explains the scrape.

**The API block.** The address is a host name, so Caddy serves it over HTTPS and obtains a
certificate for it. `reverse_proxy api:8000` forwards each request to the API container.
Docker's DNS resolves `api`. Caddy adds the `X-Forwarded-For`, `X-Forwarded-Proto` and
`X-Forwarded-Host` headers by default; that is general Caddy behaviour. `encode zstd gzip`
compresses the response when the client accepts it. `Access-Control-Allow-Origin *` lets a
page on any origin call the API from a browser. The API is public and read-only, so this is
acceptable.

**The site block.** `root * /srv/site` sets the directory. `file_server` serves the files.
Compose mounts `/opt/caselaw/site` read-only at `/srv/site`. The deploy script copies
`docs/report.html` there as `index.html` and `graph.html` beside it.

**The headers.** `Strict-Transport-Security "max-age=31536000"` tells the browser to use
HTTPS for one year. `X-Content-Type-Options nosniff` tells the browser to trust the declared
content type. The site block has no CORS header, because a static page needs none.

### 4.2 The placeholders and the env file

Caddy fills `{$API_HOST}` and `{$SITE_HOST}` from the environment of the container. The
`caddy` service in Compose sets them as `API_HOST: ${API_HOST:?API_HOST required}` and the
same for `SITE_HOST`. The `:?` form makes Compose fail if the variable is missing. Compose
reads the values from `/etc/caselaw/hosts.env`. Cloud-init writes that file at first boot
with the lines `SITE_HOST=${site_host}` and `API_HOST=${api_host}`.

Terraform fills `site_host` and `api_host` with `caselaw.inat.io` and `api.caselaw.inat.io`
from `locals.fqdn` in `main.tf`. The same values create the DNS records. One source therefore
names the hosts in DNS, in cloud-init and in Caddy.

### 4.3 Automatic HTTPS, and what must be true

Caddy issues a certificate for every site address that looks like a host name. It also opens
port 80 and answers each plain HTTP request with a 308 to the HTTPS URL. Both are general
Caddy behaviour and need no line in the Caddyfile. Caddy tries the HTTP-01 and TLS-ALPN-01
challenges by default. This note describes HTTP-01, because the firewall comment in `main.tf`
names it: `http (Let's Encrypt challenge, redirect)`.

The challenge works only when four things are true at the same time:

1. The A record of the host points to the server's public IPv4 address. Let's Encrypt
   resolves the name itself.
2. Port 80 is reachable from the internet. Here that means the Hetzner firewall rule, the
   `ufw allow 80/tcp` line and the `80:80` port mapping.
3. Caddy is running and serves that host name. Compose starts Caddy only after the `api`
   container is healthy (`depends_on: api: condition: service_healthy`).
4. The name is a public DNS name. Let's Encrypt does not issue certificates for IP addresses
   or private names.

Let's Encrypt limits the number of certificates per registered domain per week. A server that
fails the challenge in a loop can reach the limit. The commits show no such incident here.

### 4.4 Certificate storage and renewal

Caddy stores certificates, private keys and its ACME account under `/data`. Compose mounts
the named volume `caddy_data` there. Caddy writes its last active config under `/config`, the
volume `caddy_config`. A `docker compose up -d` keeps both volumes, so the certificates
survive a deploy. A `docker compose down -v` deletes them, and Caddy requests new ones.

Caddy renews a certificate on its own after about two thirds of its lifetime. Let's Encrypt
certificates are valid for 90 days, so renewal runs about every 60 days. This is general
behaviour, and nothing in the repository schedules it. The report lists "Caddy's own
certificate renewal" among the things that work without the monitoring agent.

### 4.5 The admin API and the metrics site

Caddy's admin API binds to `localhost:2019` inside the container. `caddy reload` in the
deploy script uses it. No other container can reach it, and Compose does not publish it.
That is the intended state.

The metrics are a different matter. Without the `:2020` site they are served only by the
admin API. Alloy runs in another container, so `localhost` of Caddy is not reachable for it.
Commit `6a4362f` added the `:2020` site for that reason. The commit message says: "Caddy's
admin API stays on localhost; a metrics-only site on :2020 serves Alloy."

## 5. The DNS side

### 5.1 The records at Njalla

Terraform creates the two records in `infra/hetzner/main.tf`:

```
resource "njalla_record_a" "site" {
  domain  = var.domain
  name    = var.site_host
  content = hcloud_server.app.ipv4_address
  ttl     = var.dns_ttl
}
# njalla_record_a "api" is the same block with name = var.api_host
```

The variables in `variables.tf` give `domain = "inat.io"`, `site_host = "caselaw"`,
`api_host = "api.caselaw"` and `dns_ttl = 300`. `content` references the server resource, so
Terraform creates the server first and the records after it. A new server gets new records
with its new address in the same `apply`.

The provider is `Sighery/njalla`, version `>= 0.10`, declared in `versions.tf`. It is a
community provider, as the report notes in section 8.1. It takes its token as an attribute,
`api_token = var.njalla_api_token`. The deploy script runs Terraform through `op run`, and
`terraform.op.env` maps `TF_VAR_njalla_api_token` to a 1Password reference. No token is on
disk on the laptop.

The server has IPv6 enabled (`ipv6_enabled = true`), and `outputs.tf` prints the address.
Terraform creates no AAAA record. All traffic to the two hosts, including the challenge, uses
IPv4.

### 5.2 Why Cloudflare DNS was not an option

The Cloudflare provider is in the stack for one purpose: the R2 bucket `caselaw-runs`. A zone
at Cloudflare would need the registrar to point the domain's nameservers at Cloudflare. The
report says in section 8.1 that "the zone stays where the domain is registered", that is at
Njalla. Moving the zone would move every record of `inat.io`, not only the two records of this
project. The files give no further reason. `terraform.env.example` still lists a
`Zone / DNS / Edit` permission for the Cloudflare token; the live `terraform.op.env` does not
use it for DNS. That line is the only trace of an earlier plan.

## 6. Walkthrough of the setup, as done by hand

`make hz-bootstrap` does all of this. The steps below are the manual equivalent.

1. Create an API token at Njalla.
2. Store the token in 1Password as `caselaw/njalla-api/credential`.
3. Run `make hz-apply`.
   Terraform creates the server, the firewall and the two A records.
4. Run `scripts/hz.sh ssh cat /etc/caselaw/hosts.env`.
   The file shows `SITE_HOST=caselaw.inat.io` and `API_HOST=api.caselaw.inat.io`.
5. Run `dig +short api.caselaw.inat.io A` on the laptop.
   The output equals the address from `scripts/hz.sh ip`.
6. Run `make hz-deploy`.
   Compose starts Postgres, the API and Caddy. Caddy requests the two certificates.
7. Run `scripts/hz.sh logs caddy`.
   The log shows that Caddy obtained a certificate for each host.
8. Run `make hz-smoke`.
   The script calls three API paths over HTTPS and prints the status code of the site.

## 7. What went wrong, and what each mistake teaches

The commit history shows three problems in this layer. None concerns the certificate or the
DNS. The files contain no evidence of an ACME or DNS problem, so this note describes none.

**The metrics were on the wrong port.** The first Caddyfile (commit `3951571`) used the
option `servers { metrics }` and its comment said the metrics lived on `:2019` "inside the
Docker network only". That was wrong. Port 2019 is the admin API, and it binds to `localhost`
of the container. Alloy got "connection refused". Commit `6a4362f` replaced the option with
the global `metrics` option and the `:2020` site. Lesson: a port inside a container is
reachable from other containers only if the process binds to a non-loopback address.

**The reloaded Caddyfile was the old one.** Compose mounts the Caddyfile as a single file.
`rsync` writes a new file and renames it over the old one, so the inode changes. The container
keeps the old inode. Caddy reported "config is unchanged" after a reload. Commit `6a4362f`
added `--inplace` to the `rsync` call and a `caddy reload` step to `deploy`, because
`docker compose up -d` does not restart a container for a changed mounted file. Lesson: a
single-file bind mount follows the inode, not the path.

**The Caddyfile was not formatted.** `caddy reload` warns when the file does not match the
output of `caddy fmt`. The deploy script filters that warning with `grep -v 'not formatted'`.
Commit `c294b39` reformatted the file with tabs, so the warning no longer appears. Lesson: run
`caddy fmt --overwrite Caddyfile` before committing.

Commit `6a4362f` also removed `header_up X-Forwarded-Proto {scheme}` without a stated reason.
Caddy sets that header by default, so the line was redundant. That explanation is general Caddy
behaviour, not a fact from the commit.

## 8. How to verify

The commands below run on the laptop, except where stated. `make hz-smoke` and
`make hz-measure` are the repository's own checks over HTTPS. The others are standard tools.

Check DNS:

```
dig +short caselaw.inat.io A
dig +short api.caselaw.inat.io A
```

Both answers must equal the output of `scripts/hz.sh ip`.

Check the redirect:

```
curl -sI http://api.caselaw.inat.io/health
```

The first line must be `HTTP/1.1 308 Permanent Redirect`. The `Location` header must be
`https://api.caselaw.inat.io/health`.

Check the certificate:

```
openssl s_client -connect api.caselaw.inat.io:443 -servername api.caselaw.inat.io </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```

The subject must name the host. The issuer must be Let's Encrypt. `notAfter` must be less
than 90 days ahead. Repeat with `caselaw.inat.io`. The `-servername` flag matters, because
Caddy picks the certificate by the name the client sends.

Check the headers and the compression:

```
curl -sI https://api.caselaw.inat.io/health
curl -sI -H 'Accept-Encoding: gzip' https://caselaw.inat.io/
```

The API response must carry `strict-transport-security`, `x-content-type-options` and
`access-control-allow-origin`. The site response must carry `content-encoding: gzip`.

Check the stored certificates, on the server:

```
make hz-ssh
docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env \
  -f /opt/caselaw/repo/infra/hetzner/compose.yml exec caddy ls -R /data/caddy/certificates
```

Caddy stores one directory per CA and per host. This path is general Caddy behaviour.

Check the metrics site with the same `exec` form and
`wget -qO- http://localhost:2020/metrics`. The `caddy:2-alpine` image has BusyBox `wget`. The
output must show `caddy_http_requests_total` with `code="308"` and `code="200"`.

## 9. Alternatives, and why not

- **nginx with certbot.** Two programs and a cron job for renewal. Caddy does the same work
  with one config file and no cron.
- **Traefik.** It also issues certificates and reads routes from Docker labels. The stack
  has two routes that never change, so a Caddyfile is simpler to read.
- **Cloudflare as a proxy in front of the server.** It would hide the server address and add
  a cache. It needs the zone at Cloudflare, which section 5.2 explains is not the case.
- **The DNS-01 challenge.** It proves control through a TXT record instead of port 80. It
  needs a Caddy build with a DNS plugin for the provider. The HTTP-01 challenge works here
  because port 80 is open anyway for the redirect.

## 10. Questions to be able to answer afterwards

- Which three places must admit port 80 before the HTTP-01 challenge can pass?
- Why does the challenge run over HTTP although the goal is HTTPS?
- What does a 308 tell the client that a 301 does not?
- Why does `{$API_HOST}` appear in the Caddyfile and `caselaw.inat.io` only in Terraform?
- Which volume holds the certificates, and what happens to them after `docker compose down -v`?
- Why can `caddy reload` reach port 2019 while Alloy cannot?
- Why would moving the DNS zone to Cloudflare affect more than this project?

## 11. Files

| file | role |
|---|---|
| `infra/hetzner/Caddyfile` | the global `metrics` option, the `:2020` site, the API host and the site host |
| `infra/hetzner/compose.yml`, service `caddy` | ports 80 and 443, the two placeholders, the mounts, `caddy_data` and `caddy_config` |
| `infra/hetzner/main.tf` | the firewall rules for 80 and 443, the two `njalla_record_a` resources, `locals.fqdn` |
| `infra/hetzner/variables.tf` | `domain`, `site_host`, `api_host`, `dns_ttl`, `njalla_api_token` |
| `infra/hetzner/outputs.tf` | `ipv4`, `site_url`, `api_url` for the deploy script |
| `infra/hetzner/versions.tf` | the `Sighery/njalla` provider and its token attribute |
| `infra/hetzner/terraform.op.env` | the 1Password reference for `TF_VAR_njalla_api_token` |
| `infra/hetzner/cloud-init.yaml` | `/etc/caselaw/hosts.env` and the `ufw` rules |
| `scripts/hz.sh` | `deploy` copies the site files and reloads Caddy; `smoke` and `measure` test over HTTPS |
| `docs/report.md`, section 8.1 | the TLS and DNS rows of the deployment table |
| `docs/learning/grafana.md` | the scrape of `caddy:2020` and the Caddy dashboard |
