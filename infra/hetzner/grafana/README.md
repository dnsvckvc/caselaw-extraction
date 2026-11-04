# Grafana Cloud: alert rules and notifications

`alert-rules.yml` holds the eight alert rules of the caselaw server in the Prometheus
rule-file format. Grafana Cloud imports that format as Grafana-managed rules. The rules use
only series that the Alloy agent sends (see `docs/learning/12-grafana.md`), and the
thresholds come from `docs/report.md`, section 8.3.

| rule | fires when | severity |
|---|---|---|
| CaselawServerUnreachable | no `alloy_build_info` from the server for 5 min | critical |
| CaselawApiDown | cAdvisor has not seen `hetzner-api-1` for 2 min, or Caddy's metrics are down, for 3 min | critical |
| CaselawApi5xx | 5 or more 5xx responses through the reverse proxy in 5 min | warning |
| CaselawApiLatencyP95 | p95 of proxied requests above 1 s for 10 min | warning |
| CaselawDiskAbove85Percent | root filesystem above 85 percent for 15 min | warning |
| CaselawMemoryLow | less than 300 MB available for 15 min | warning |
| CaselawPostgresDown | `pg_up` is 0 or missing for 2 min | critical |
| CaselawPostgresConnectionsHigh | more than 40 connections for 5 min | warning |

The backup check is not a Grafana rule. `backup.sh` pings a healthchecks.io URL when
`BACKUP_HEALTHCHECKS_URL` is set in `runtime.secrets`; healthchecks.io alerts when the ping
is late. A missing cron run produces no metric, so a dead-man's switch is the right tool.

## 1. Create the contact point

Without a contact point the rules fire into nothing.

1. In Grafana, open **Alerting**, then **Contact points**.
2. Click **Create contact point**.
3. Set the name to `caselaw-email`, the integration to **Email**, and enter your address.
4. Click **Test**, then **Save contact point**. A test mail must arrive.
5. Open **Notification policies** and click **Edit** on the default policy.
6. Set the default contact point to `caselaw-email` and save.

## 2. Import the rules

1. Open **Alerting**, then **Alert rules**.
2. Click the **More** dropdown next to **New alert rule** and choose **Import to Grafana-managed rules**.
3. Under **Import source**, choose **Prometheus YAML file** and upload `alert-rules.yml`.
4. Set the data source to the Prometheus source of the stack, named `grafanacloud-<stack>-prom`.
5. Set the target folder to a new folder named `caselaw`. Keep the namespace and group names.
6. Click **Import**. The preview must list eight rules. Confirm.

If the **More** dropdown has no import entry, the stack runs an older Grafana. Then create
each rule by hand with **New alert rule**: paste the `expr` of the rule as the query, set the
pending period to the rule's `for` value, and copy the labels and annotations.

## 3. Check

1. In **Alert rules**, open the folder `caselaw`. Each rule must show **Normal** after one
   evaluation, which takes up to a minute.
2. Open the rule **CaselawApiDown** and click **View query**. The query must return no series
   while the API runs.
3. For a real test, stop the API on the server with
   `docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env -f /opt/caselaw/repo/infra/hetzner/compose.yml stop api`
   and start it again after four minutes with `start api`. The rule must go to **Pending**
   after two minutes and **Firing** after three, and a mail must arrive. `make hz-smoke`
   confirms that the API answers again afterwards.

## 4. Change a rule

Edit `alert-rules.yml`, commit, and import again into the same folder. Grafana updates the
rules by name. Rules edited in the UI are overwritten by the next import, so the file is the
source of truth.
