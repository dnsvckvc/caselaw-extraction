# Grafana Cloud and Grafana Alloy: what they do, how we use them, what we learned

This note explains the monitoring of the caselaw server. It is written for someone who
would build the same thing by hand, without an AI assistant, and wants to understand each
piece before copying it. The config it describes is `infra/hetzner/alloy/config.alloy`, the
container is the `alloy` service in `infra/hetzner/compose.yml`, and the report discusses the
design in section 8.3 of `docs/report.md`.

## 1. The problem monitoring solves here

The server runs four containers: Postgres, the API, Caddy and the agent itself. Nobody
watches it. We want to know, without logging in, four things:

- Is the API up, and how fast does it answer?
- How full are CPU, memory and disk of the one server?
- Is Postgres healthy, and how many connections does it hold?
- What did the containers log in the last hour, when something broke?

In the AWS design these answers come from CloudWatch, which collects the numbers of the load
balancer, ECS and RDS on its own. On a bare server nothing collects anything. Monitoring
therefore needs three parts: something that measures, somewhere to store the measurements,
and a place to look at them and get alerted. Grafana Cloud provides the last two. Grafana
Alloy, which runs on the server, provides the first.

## 2. The vocabulary

**Metric.** A named number measured over time, for example `node_memory_MemAvailable_bytes`.
Each sample is a timestamp and a value.

**Label.** A key-value pair attached to a metric that splits it into series. The metric
`caddy_http_requests_total` has the labels `code` (200, 308, 404) and `handler`. One metric
with three label values is three time series. The two labels that every series in our setup
carries are `job`, which names the kind of source, and `instance`, which names the machine.

**Cardinality.** The number of distinct series. The free tier allows 10,000 series. Labels
with many values, such as a request path or a user id, multiply the count and are the usual
way to exceed a quota. We send about 2,000 series.

**Counter, gauge, histogram.** A counter only goes up, such as requests served. A gauge goes
both ways, such as memory used. A histogram counts observations in buckets, such as request
durations under 0.1 s, under 0.5 s and so on, which is how a p95 latency is computed later.
Queries on counters use `rate()`, which turns the total into a per-second value.

**Scrape.** Prometheus-style collection is pull based. A program exposes its current numbers
as a text page at `/metrics`, and the collector reads that page every 30 seconds. The program
does not need to know where the collector is.

**Exporter.** A small program that exposes metrics for something that has none of its own.
`node_exporter` reads the kernel's counters for CPU, memory, disk and network. cAdvisor reads
the cgroup accounting of the containers. `postgres_exporter` runs SQL statements against the
database and exposes the results. Caddy exposes its own metrics, so it needs no exporter.

**Remote write.** The collector pushes the scraped samples to a remote store over HTTPS with
basic authentication. This is the only outgoing connection; nothing calls into the server.

**Loki, LogQL, stream.** Loki is the log store. It indexes only labels, not the text of each
line. A set of labels defines a stream. Queries select streams by label, for example
`{container="hetzner-api-1"}`, and then filter the text with `|=` or a regular expression.
Few labels, with few values each, is the rule. Grafana's own guidance says a label such as a
request id is wrong, because every line would open a new stream.

**Integration.** A Grafana Cloud package for one kind of source: an Alloy config snippet,
dashboards and alert rules. The dashboards and rules select data by fixed label values, for
example `job="integrations/node_exporter"`. Send a different value, and the dashboards are
empty although the data is there. This is the single most important fact in this note.

## 3. How the pieces connect

```
 server (Hetzner cx23)                                   Grafana Cloud (EU)
 +---------------------------------------------+
 | kernel ---- node_exporter ----+             |
 | cgroups --- cAdvisor ---------+             |      +--------------------+
 | Postgres -- postgres_exporter + scrape      |      | Mimir (metrics)    |
 | Caddy :2020 ------------------+   |         |      |   <- remote_write  |
 | Alloy itself -----------------+   v         |      |                    |
 |                            remote_write ------------> prometheus-prod-58 |
 |                                             |      |                    |
 | docker.sock -- loki.source.docker -- loki.write ----> Loki (logs)        |
 |                                             |      |   logs-prod-039    |
 |              one container: grafana/alloy   |      |                    |
 +---------------------------------------------+      | Grafana UI,        |
                                                      | Alerting           |
                                                      +--------------------+
```

Everything in the left box is one container, `hetzner-alloy-1`. Alloy embeds the exporters,
the scraper, the remote-write client, the Docker log tailer and the Loki client. Before Alloy
existed, each of those was a separate process to install and keep running.

## 4. Grafana Alloy, the collector

Alloy is Grafana's successor of the Grafana Agent. Its config is a graph of components. Each
component has a type, a name, arguments, and exports that other components reference. The
config language looks like Terraform's HCL. The data flows along the references.

Our graph, read from `infra/hetzner/alloy/config.alloy`:

| component | what it does | export used by |
|---|---|---|
| `prometheus.exporter.unix "host"` | node_exporter in process, reading the host through `/rootfs` | `discovery.relabel "host"` |
| `prometheus.exporter.cadvisor "containers"` | cAdvisor in process, reading Docker and cgroups | `discovery.relabel "cadvisor"` |
| `local.file "exporter_dsn"` | reads the Postgres connection string from a Compose secret file, marked secret | `prometheus.exporter.postgres "db"` |
| `prometheus.exporter.postgres "db"` | postgres_exporter in process | `discovery.relabel "postgres"` |
| `prometheus.exporter.self "alloy"` | Alloy's own health metrics | `discovery.relabel "alloy"` |
| `discovery.relabel` (five of them) | set `job` and `instance` on each target | the matching `prometheus.scrape` |
| `prometheus.scrape` (five of them) | read `/metrics` every 30 or 60 s | `prometheus.remote_write "cloud"` |
| `prometheus.remote_write "cloud"` | push to Grafana Cloud Mimir with basic auth, adds `host=caselaw` | |
| `discovery.docker "containers"` | lists running containers through the Docker socket | `discovery.relabel "containers"` |
| `discovery.relabel "containers"` | turns `/hetzner-api-1` into the label `container=hetzner-api-1` | `loki.source.docker` |
| `loki.source.docker "containers"` | tails each container's stdout and stderr | `loki.write "cloud"` |
| `loki.write "cloud"` | push to Grafana Cloud Loki with basic auth | |

Three details deserve attention.

**Credentials come from the environment.** `sys.env("GCLOUD_RW_API_KEY")` reads a variable
that Compose sets from `/etc/caselaw/caselaw.env`. The config file itself holds no secret and
is committed. The Postgres connection string is not in the environment at all. It is a file
under `/run/secrets`, read by `local.file` with `is_secret = true`, so Alloy's own UI and logs
mask it.

**The relabel blocks are the glue to Grafana Cloud.** Each exporter sets its own default
`job` label, for example `integrations/unix`, and the `instance` label defaults to the
container's hostname, which is a 12-character id. The `discovery.relabel` blocks overwrite
both: `job` becomes the value the Grafana integration expects, `instance` becomes `caselaw`.
A rule with only `target_label` and `replacement` sets a constant label.

**Scrape targets are internal.** The exporters live inside Alloy, so their targets are
addresses on Alloy's internal server, not network ports. Caddy is the one external target,
`caddy:2020`, resolved by Docker's DNS inside the Compose network.

### 4.1 What the container needs from the host

The `alloy` service in `infra/hetzner/compose.yml` is the most privileged container on the
server, and each privilege has one reason:

| setting | reason |
|---|---|
| `/:/rootfs:ro`, `/sys:/sys:ro` | node_exporter reads `/proc` and `/sys` of the host, not of the container |
| `/var/run/docker.sock:ro` | cAdvisor and the log tailer ask the Docker daemon for container names and log streams |
| `/var/lib/docker:ro` | cAdvisor maps a container to its writable layer to report its disk use |
| `privileged: true`, `pid: host` | cAdvisor reads cgroup files that an unprivileged container cannot see |
| `--server.http.listen-addr=127.0.0.1:12345` | Alloy's UI and API stay inside the container; no port is published |
| `profiles: [monitoring]` | the service starts only when the deploy script passes `--profile monitoring`, which it does when `GCLOUD_RW_API_KEY` has a value |

Read access to the Docker socket is still root-equivalent on the host, because the socket can
start containers. The mitigation here is that the container runs an image from Grafana, with
a pinned version, and exposes no port. A stricter setup would run cAdvisor and the log tailer
in a separate container and keep Alloy unprivileged.

## 5. Grafana Cloud, the backend

The free tier gives one stack with Mimir for metrics, Loki for logs, Tempo for traces, and
the Grafana UI with alerting. The limits that matter: 10,000 active metric series, 50 GB of
logs per month, 14 days of retention for both. The stack lives in one region; ours is
`prod-eu-central-0`, which is Frankfurt. The data leaves the server, so the region is a
compliance question, not only a latency one.

Each stack has two write endpoints with their own numeric user id, one for metrics and one
for logs, and one access policy token that starts with `glc_` and has the scopes
`metrics:write` and `logs:write`. That is why there are five values in the env file and not
one. The token cannot read, so a leaked token lets someone pollute the data but not read it.

Alloy, from Grafana's point of view, is one of many "collectors". The install dialog in the
UI wants to install Alloy as a systemd service with the Fleet Management feature. We do not
use that path. The dialog's values are still the right ones; only the install command is not
run.

## 6. Walkthrough of the setup, as done by hand

1. Create the Grafana Cloud account and a stack in an EU region.
2. In **Connections**, **Add new connection**, choose **Linux Server**, click **Run Grafana
   Alloy**, create a token named after the server. The install command shows the five
   `GCLOUD_*` values. Copy them, do not run the command.
3. Put the five values into the runtime env file and install it on the server. In this
   repository: `infra/hetzner/runtime.secrets`, as 1Password references, then
   `make hz-secrets` and `make hz-deploy`.
4. Confirm that the Alloy container runs and sends. Without a published port, the check goes
   through `docker exec` into the container, which has `bash` but no `curl`:

   ```
   docker exec hetzner-alloy-1 bash -c 'exec 3<>/dev/tcp/127.0.0.1/12345; printf "GET /metrics HTTP/1.0\r\nHost: x\r\n\r\n" >&3; cat <&3' \
     | grep -E "^prometheus_remote_storage_samples_(total|failed_total)|^loki_write_(sent|dropped)_entries_total"
   ```

   `samples_total` must grow, `samples_failed_total` must stay 0. The same endpoint under
   `/api/v0/web/components/prometheus.scrape.host` shows each target's health and labels.
5. In the Linux Server integration page, click **Test Alloy connection**. It looks for the
   metric `alloy_build_info` with `job="integrations/alloy"`, nothing else. Then click
   **Proceed to install integration** and **Install**. The second test, on the integration
   page, looks for `node_uname_info` with `job="integrations/node_exporter"`.
6. Repeat the install for Docker, PostgreSQL and Caddy from **Add new connection**. Skip
   their Alloy configuration steps, because one Alloy already sends everything.
7. Open each dashboard. Select the instance `caselaw` where the dropdown offers more than one.
8. In **Alerting**, **Contact points**, add an email address. In **Notification policies**, set
   it as the default. Without this the installed alert rules fire into nothing.
9. In **Explore**, with the `-prom` source, run `up{instance="caselaw"}`: five series, all 1.
   With the `-logs` source, run `{host="caselaw"}`: lines from the containers.

## 7. What went wrong, and what each mistake teaches

These are the problems met on 2026-11-03, in the order they appeared. Each cost between ten
minutes and an hour. Someone building by hand would meet the same ones.

**The job label did not match the integration.** Data arrived, the Grafana test failed. The
integrations select by `job="integrations/<name>"`. Lesson: before writing the config, open
the integration's Alloy snippet and copy its `job` and `instance` conventions. The
integration dashboards also use `instance` as the dropdown, so make it a readable name.

**cAdvisor could not read the containers.** Docker 29 stores images with the containerd image
store by default. cAdvisor looks for the writable layer under
`/var/lib/docker/image/overlay2`, which does not exist in that mode, and logged
`failed to identify the read-write layer ID` for every container, every minute. The fix was
`/etc/docker/daemon.json` with `{"features": {"containerd-snapshotter": false},
"storage-driver": "overlay2"}` and a Docker restart, which drops all images and needs a
rebuild. Now in cloud-init, so a new server starts right. Lesson: a monitoring tool that reads
the internals of another tool depends on that tool's storage format, and defaults change.

**Caddy's metrics were unreachable.** Caddy serves metrics on its admin endpoint, which binds
to `localhost:2019` inside the container. Alloy, in another container, got "connection
refused". The fix is a second site block, `:2020 { metrics }`, which serves only metrics on
all interfaces of the container, while the admin API stays private. Lesson: "the port is
exposed" means nothing until the process binds to a non-loopback address.

**Config changes did not reach the containers.** Compose bind-mounts `config.alloy` and the
Caddyfile as single files. rsync writes a new file and renames it, so the inode changes, and
the container keeps the old inode. Caddy reported "config is unchanged" after a reload.
Fixes: `rsync --inplace`, and the deploy script now runs `caddy reload` and restarts Alloy.
Lesson: a single-file bind mount follows the inode, not the path.

**The Alloy connection test looked for Alloy's own metric.** Not for the host metrics. Adding
`prometheus.exporter.self` with `job="integrations/alloy"` made it pass. Lesson: each test
button in the UI checks one specific series; find out which one before debugging the pipeline.

**The Docker logs status panel showed red with logs visible.** Its query is
`sum(count_over_time({job=~"$job"}[$__auto]))`, and with the Job dropdown on **All** the
selector becomes `job=~".*"`. Loki rejects a query whose only matcher accepts the empty
string. Selecting the job in the dropdown fixes the panel. Lesson: a red status panel can be
a dashboard bug; open its query with the panel's **Explore** entry before touching the agent.

**Stale instance in the dropdown.** The first hour of data had the container id as instance.
The dashboards kept it selected and showed no data for the current window. Lesson: a label
change creates new series; the old ones linger for the retention period.

## 8. How to read the dashboards

- **Linux node / overview.** CPU as a percentage of the two vCPUs, memory available, root
  filesystem use, load average. The API image build is the only thing that fills the CPU.
- **Docker overview.** CPU and memory per container. The API uses about 210 MB, Postgres about
  180 MB with the tuned `shared_buffers`, Caddy under 20 MB, Alloy about 150 MB.
- **PostgreSQL overview.** Connections, transactions per second, cache hit ratio, database
  size. The API holds one connection per worker. `pg_up` is the liveness series.
- **Caddy overview.** Requests per second by status code and handler, in-flight requests,
  request duration percentiles from the histogram. The constant 0.033 requests per second is
  Alloy scraping Caddy every 30 seconds. A 308 is the redirect from HTTP to HTTPS.
- **Docker logs.** Volume per container and the lines. The API logs one line per request,
  Caddy logs JSON events such as certificate renewals, Postgres logs only on errors.

## 9. The alert rules still to create

The integrations install generic rules for CPU, memory, disk and Postgres. The seven rules in
report section 8.3 are specific to this service and are not created yet:

| rule | query sketch |
|---|---|
| API down | `sum(rate(caddy_http_requests_total{code=~"2.."}[3m])) == 0`, plus a synthetic check of `/health` |
| 5xx | `sum(increase(caddy_http_requests_total{code=~"5.."}[5m])) >= 5` |
| latency | `histogram_quantile(0.95, sum by (le) (rate(caddy_http_request_duration_seconds_bucket[5m]))) > 1` |
| disk | `node_filesystem_avail_bytes{mountpoint="/rootfs"} / node_filesystem_size_bytes < 0.15` |
| memory | `node_memory_MemAvailable_bytes < 300e6` for 15 m |
| database | `pg_up == 0` or `pg_stat_activity_count > 40` |
| backup | missing ping at healthchecks.io after 03:30, outside Grafana |

Grafana's alert rules can be stored as files and imported, or created in the UI. Each rule
needs a condition, a pending period, labels for routing, and annotations with the runbook
text.

## 10. Alternatives, and why not

- **CloudWatch** was the plan for AWS. On a server outside AWS it would need the CloudWatch
  agent and a paid account. Kept as the design in report section 8.6.
- **Self-hosted Prometheus and Grafana** on the same server: two more containers, about 500
  MB more RAM, and the alerts die with the server. Monitoring should not share the fate of
  what it watches.
- **Netdata, Uptime Kuma, healthchecks.io.** Lighter, good for a first signal. They do not
  give per-host request histograms or log search. healthchecks.io is still used for the backup
  cron, because a missing cron run is a "dead man's switch" problem that Grafana handles badly.
- **OpenTelemetry Collector** instead of Alloy. Alloy speaks OpenTelemetry too, and the same
  config would gain traces from the API with a few lines. Not needed for a read-only API with
  one upstream.

## 11. Questions to be able to answer afterwards

- Why does a scrape pull and remote write push? What does each direction mean for firewalls?
- What is the difference between `rate()` and `increase()`, and why is `rate()` wrong on a gauge?
- How does `histogram_quantile` produce a p95 from buckets, and why is it an estimate?
- Why are labels in Loki few, and labels in Prometheus many but bounded?
- Which process reads `/var/run/docker.sock` here, and why is that a root-equivalent right?
- What happens to the dashboards when the `instance` label changes?
- Where does a secret appear in this pipeline, and which one is in a file instead of the environment, and why?

## 12. Files

| file | role |
|---|---|
| `infra/hetzner/alloy/config.alloy` | the collector graph |
| `infra/hetzner/compose.yml`, service `alloy` | the container, its mounts and privileges |
| `infra/hetzner/Caddyfile` | the `:2020` metrics site and the global `metrics` option |
| `infra/hetzner/cloud-init.yaml` | `/etc/docker/daemon.json` for the overlay2 driver |
| `infra/hetzner/runtime.secrets.example` | the five `GCLOUD_*` names |
| `scripts/hz.sh` | `deploy` adds the monitoring profile, reloads Caddy and restarts Alloy |
| `docs/report.md`, section 8.3 | the design and the seven planned alert rules |
