#!/usr/bin/env bash
# Nightly backup on the server (installed as /etc/cron.d/caselaw-backup by scripts/hz.sh):
# pg_dump of the database and a copy of the run Parquet to the R2 bucket, 14 days retention.
# rclone is configured through environment variables, so no rclone.conf exists on disk.
# --s3-no-head: R2 returns a version id on PUT and rclone 1.60 (Ubuntu 24.04) then sends
# HEAD ?versionId=..., which R2 answers with 501. The upload itself is verified by Content-MD5.
# Optional: BACKUP_HEALTHCHECKS_URL in /etc/caselaw/caselaw.env pings healthchecks.io.
set -euo pipefail
ENV_FILE=/etc/caselaw/caselaw.env
COMPOSE=(docker compose --env-file "$ENV_FILE" --env-file /etc/caselaw/hosts.env -f /opt/caselaw/repo/infra/hetzner/compose.yml)
set -a; . "$ENV_FILE"; set +a
: "${R2_ACCESS_KEY_ID:?}" "${R2_SECRET_ACCESS_KEY:?}" "${R2_ENDPOINT:?}" "${R2_BUCKET:=caselaw-runs}"
export RCLONE_CONFIG_R2_TYPE=s3 RCLONE_CONFIG_R2_PROVIDER=Cloudflare RCLONE_CONFIG_R2_REGION=auto \
  RCLONE_CONFIG_R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" RCLONE_CONFIG_R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  RCLONE_CONFIG_R2_ENDPOINT="$R2_ENDPOINT"
hc() { [ -n "${BACKUP_HEALTHCHECKS_URL:-}" ] && curl -fsS -m 10 --retry 3 "${BACKUP_HEALTHCHECKS_URL}$1" >/dev/null || true; }
trap 'echo "backup FAILED $(date -u +%FT%TZ)" >&2; hc /fail' ERR
hc /start
stamp=$(date -u +%Y%m%dT%H%M%SZ)
out=/var/lib/caselaw/backups/caselaw-$stamp.dump
"${COMPOSE[@]}" exec -T postgres pg_dump -U caselaw -Fc caselaw > "$out"
rclone copy "$out" "r2:$R2_BUCKET/backups/" --s3-no-check-bucket --s3-no-head
rclone sync /var/lib/caselaw/runs "r2:$R2_BUCKET/runs/" --s3-no-check-bucket --s3-no-head
rclone delete "r2:$R2_BUCKET/backups/" --min-age 14d
find /var/lib/caselaw/backups -name '*.dump' -mtime +3 -delete
echo "backup ok $stamp $(du -h "$out" | cut -f1)"
hc ""
