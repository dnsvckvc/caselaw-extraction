#!/usr/bin/env bash
# Hetzner deployment helpers (week 4). Run from the repository root. Terraform credentials come
# from 1Password through `op run` (infra/hetzner/terraform.op.env); nothing is read from disk.
#   scripts/hz.sh init | plan | apply | destroy   Terraform in infra/hetzner
#   scripts/hz.sh wait            wait until cloud-init on the server has finished
#   scripts/hz.sh secrets         write infra/hetzner/runtime.secrets to /etc/caselaw/caselaw.env
#   scripts/hz.sh deploy          rsync the repo and the site files, build the image, start the stack
#   scripts/hz.sh sync [run]      rsync data/runs/<run> (Parquet + run.json) to the server
#   scripts/hz.sh load [run]      run the loader once against the server's Postgres
#   scripts/hz.sh smoke | measure | logs | ssh | backup-now | status
#   scripts/hz.sh bootstrap [run] apply, wait, secrets, deploy, sync, load, smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HZ="$ROOT/infra/hetzner"
KEY="${CASELAW_SSH_KEY:-$HOME/.ssh/caselaw-prod}"
tf() { op run --env-file "$HZ/terraform.op.env" -- terraform -chdir="$HZ" "$@"; }
out() { terraform -chdir="$HZ" output -raw "$1"; }
ip() { out ipv4; }
SSH_OPTS=(-i "$KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10)
sshc() { ssh "${SSH_OPTS[@]}" "caselaw@$(ip)" "$@"; }
COMPOSE='docker compose --env-file /etc/caselaw/caselaw.env --env-file /etc/caselaw/hosts.env -f /opt/caselaw/repo/infra/hetzner/compose.yml'
profile() { sshc 'grep -q "^GCLOUD_RW_API_KEY=.\+" /etc/caselaw/caselaw.env && echo "--profile monitoring" || true'; }
cmd=${1:-help}; shift || true

case "$cmd" in
  init)    tf init -input=false ;;
  plan)    tf plan -input=false ;;
  apply)   tf apply -input=false ;;
  destroy) tf destroy -input=false ;;
  ip)      ip ;;
  ssh)     exec ssh "${SSH_OPTS[@]}" "caselaw@$(ip)" "$@" ;;
  wait)
    echo "waiting for cloud-init on $(ip) ..."
    for _ in $(seq 60); do
      if sshc -o BatchMode=yes 'test -f /etc/caselaw/.provisioned' 2>/dev/null; then echo "server provisioned"; exit 0; fi
      sleep 10
    done
    echo "cloud-init did not finish in 10 minutes; check: $0 ssh sudo cloud-init status --long" >&2; exit 1 ;;
  secrets)
    f="$HZ/runtime.secrets"
    [ -f "$f" ] || { echo "missing $f (copy runtime.secrets.example)" >&2; exit 1; }
    grep -q '\$' "$f" && { echo "a value in $f contains \$, which Compose would expand" >&2; exit 1; }
    sshc 'sudo install -m 0640 -o root -g caselaw /dev/stdin /etc/caselaw/caselaw.env' < "$f"
    echo "wrote /etc/caselaw/caselaw.env ($(grep -c '=.\+' "$f") values set)" ;;
  deploy)
    rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
      --exclude .git --exclude .venv --exclude data --exclude models --exclude mlruns --exclude mlflow.db \
      --exclude labeling/data --exclude labeling/tasks --exclude '__pycache__' --exclude .pytest_cache \
      --exclude .ruff_cache --exclude 'infra/terraform/.terraform' --exclude 'infra/hetzner/.terraform' \
      --exclude 'infra/hetzner/*.tfstate*' --exclude 'infra/hetzner/runtime.secrets' --exclude 'infra/hetzner/terraform.env' \
      "$ROOT/" "caselaw@$(ip):/opt/caselaw/repo/"
    [ -f "$ROOT/docs/report.html" ] && scp "${SSH_OPTS[@]}" -q "$ROOT/docs/report.html" "caselaw@$(ip):/opt/caselaw/site/index.html"
    [ -f "$ROOT/data/runs/regex-v0.4/graph.html" ] && scp "${SSH_OPTS[@]}" -q "$ROOT/data/runs/regex-v0.4/graph.html" "caselaw@$(ip):/opt/caselaw/site/graph.html"
    sshc "$COMPOSE build api && $COMPOSE $(profile) up -d --remove-orphans"
    sshc 'sudo install -m 0644 /dev/stdin /etc/cron.d/caselaw-backup' <<< "30 3 * * * caselaw /opt/caselaw/repo/infra/hetzner/backup.sh >> /var/lib/caselaw/backups/backup.log 2>&1"
    echo "deployed; $0 status" ;;
  sync)
    run=${1:-regex-v0.4}
    rsync -az -e "ssh ${SSH_OPTS[*]}" --include '*.parquet' --include 'run.json' --exclude '*' \
      "$ROOT/data/runs/$run/" "caselaw@$(ip):/var/lib/caselaw/runs/$run/"
    echo "synced data/runs/$run" ;;
  load)
    run=${1:-regex-v0.4}
    sshc "$COMPOSE run --rm --no-deps api caselaw db-load --run $run --runs-dir /data/runs" ;;
  status)  sshc "$COMPOSE ps" ;;
  logs)    sshc "$COMPOSE logs -f --since 10m ${1:-}" ;;
  backup-now) sshc "/opt/caselaw/repo/infra/hetzner/backup.sh" ;;
  smoke)
    api=$(out api_url); site=$(out site_url)
    curl -fsS "$api/health"; echo
    curl -fsS "$api/runs"; echo
    curl -fsS "$api/statutes/top?limit=3"; echo
    curl -fsS -o /dev/null -w "site %{http_code} %{size_download} bytes\n" "$site/" ;;
  measure)
    base=$(out api_url)
    id=$(curl -fsS "$base/decisions?limit=1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["items"][0]["decision_id"])')
    for path in "/health" "/decisions/$id" "/statutes/top?limit=20" "/trends/years" "/decisions/central?limit=20" "/decisions?statute=BGG%2042&limit=50" "/drift?a=2026-08&b=2026-09"; do
      for _ in $(seq 30); do curl -o /dev/null -sS -w '%{time_total}\n' "$base$path"; done \
        | sort -n | awk -v p="$path" '{a[NR]=$1} END {printf "%-44s p50 %4.0f ms  p95 %4.0f ms\n", p, a[int(NR*0.5)]*1000, a[int(NR*0.95)]*1000}'
    done ;;
  bootstrap)
    run=${1:-regex-v0.4}
    "$0" apply; "$0" wait; "$0" secrets; "$0" deploy; "$0" sync "$run"; "$0" load "$run"; "$0" smoke ;;
  *) sed -n '2,13p' "$0" ;;
esac
