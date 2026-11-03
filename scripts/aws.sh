#!/usr/bin/env bash
# Helper for the AWS stack in infra/terraform (validated, not applied; the Hetzner stack in
# infra/hetzner is the deployment in use). Everything runs on the laptop with the AWS CLI,
# Docker and Terraform; nothing here is needed by the server.
#
#   scripts/aws.sh push            build the image for linux/amd64 and push it to ECR
#   scripts/aws.sh sync [run]      upload data/runs/<run> to s3://<bucket>/runs/<run>
#   scripts/aws.sh load [run]      run the loader task on Fargate and wait for it
#   scripts/aws.sh deploy          force a new deployment of the API service and wait
#   scripts/aws.sh smoke           call /health and one endpoint through the load balancer
#   scripts/aws.sh measure         time the main endpoints
#   scripts/aws.sh bootstrap [run] apply with 0 tasks, push, sync, load, apply with 1 task, smoke
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF="$ROOT/infra/terraform"
tf() { terraform -chdir="$TF" "$@"; }
out() { terraform -chdir="$TF" output -raw "$1"; }
run="${2:-${RUN:-regex-v0.4}}"

case "${1:-}" in
  push)
    region=$(out region); repo=$(out ecr_repository_url)
    aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "${repo%%/*}"
    docker buildx build --platform linux/amd64 -t "$repo:latest" -t "$repo:$(git -C "$ROOT" rev-parse --short HEAD)" --push "$ROOT"
    echo "pushed $repo:latest" ;;
  sync)
    bucket=$(out runs_bucket)
    aws s3 sync "$ROOT/data/runs/$run" "s3://$bucket/runs/$run" --exclude '*' --include '*.parquet' --include 'run.json'
    echo "synced s3://$bucket/runs/$run" ;;
  load)
    cluster=$(out cluster_name); family=$(out load_task_family)
    subnets=$(out subnet_ids); sg=$(out api_security_group_id)
    arn=$(aws ecs run-task --cluster "$cluster" --launch-type FARGATE --task-definition "$family" \
      --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$sg],assignPublicIp=ENABLED}" \
      --overrides "{\"containerOverrides\":[{\"name\":\"load\",\"command\":[\"caselaw\",\"db-load\",\"--run\",\"$run\",\"--runs-dir\",\"s3://$(out runs_bucket)/runs\"]}]}" \
      --query 'tasks[0].taskArn' --output text)
    echo "loader task $arn"; aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$arn"
    code=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$arn" --query 'tasks[0].containers[0].exitCode' --output text)
    [ "$code" = "0" ] || { echo "loader exited with $code; see $(out log_group) stream load/" >&2; exit 1; }
    echo "loaded $run" ;;
  deploy)
    cluster=$(out cluster_name); service=$(out service_name)
    aws ecs update-service --cluster "$cluster" --service "$service" --force-new-deployment >/dev/null
    aws ecs wait services-stable --cluster "$cluster" --services "$service"; echo "service stable" ;;
  smoke)
    url=$(out api_url)
    curl -fsS "$url/health" && echo && curl -fsS "$url/runs" | head -c 300 && echo ;;
  measure)
    url=$(out api_url)
    for p in /health /runs "/statutes/top?limit=10" "/trends/years" "/decisions/central?limit=10" /drift; do
      printf '%-32s' "$p"; curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' "$url$p"; done ;;
  bootstrap)
    tf apply -var api_desired_count=0
    "$0" push; "$0" sync "$run"; "$0" load "$run"
    tf apply -var api_desired_count=1
    "$0" smoke ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
