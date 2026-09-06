#!/usr/bin/env bash
# Deploy the LIFF and Core API to the libn production host.
# Shared MQTT/TTS services on this host must never be recreated by this script.
set -Eeuo pipefail

readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly ENV_FILE="${PROJECT_ROOT}/.env"
readonly REMOTE_DIR="${ZENBO_PRODUCTION_DIR:-/var/docker/zenbo-liff}"
readonly REMOTE_IMAGE="zenbo-liff-zenbo-core-api"
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [--dry-run]

Deploys only the Core API, LIFF static files, and Compose definitions to the
configured libn production host. It does not deploy APKs, n8n workflows, or
secrets.

Required local .env values: SSH_USER, SSH_IP_SERVER

`SERVER_PUBLIC_HOST` is optional locally and defaults to
https://libn.kku.ac.th for public verification.
EOF
}

while (($#)); do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

die() { printf 'deploy: %s\n' "$*" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"; }

[[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE"
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

[[ -n "${SSH_USER:-}" ]] || die "SSH_USER is not set in .env"
[[ -n "${SSH_IP_SERVER:-}" ]] || die "SSH_IP_SERVER is not set in .env"
[[ "$REMOTE_DIR" == /var/docker/* ]] || die "ZENBO_PRODUCTION_DIR must remain under /var/docker"

for binary in curl python3 rsync ssh tar; do require_command "$binary"; done
readonly SSH_TARGET="${SSH_USER}@${SSH_IP_SERVER}"
PUBLIC_HOST="${SERVER_PUBLIC_HOST:-https://libn.kku.ac.th}"
PUBLIC_HOST="${PUBLIC_HOST%/}"
readonly PUBLIC_HOST
readonly SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=15)

run_quality_gates() {
  printf '%s\n' 'Running local quality gates...'
  (
    cd "$PROJECT_ROOT"
    python3 -m py_compile services/core-api/main.py
    # Keep safety-gate assertions deterministic even when the deployer's local
    # .env has field-tested autonomous movement enabled for production.
    AUTONOMOUS_MOTION_ENABLED=false AUTONOMY_GOVERNANCE_REQUIRED=true \
      python3 services/core-api/test_scenarios.py
    python3 services/compiler-service/test_dialogue.py
    git diff --check
  )
}

remote_preflight_and_backup() {
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- "$REMOTE_DIR" <<'REMOTE'
set -Eeuo pipefail
remote_dir="$1"
cd "$remote_dir"
test -f docker-compose.yml
test -f docker-compose.libn.yml
test -f services/core-api/Dockerfile
test -d services/liff-app
docker ps --format '{{.Names}}' | grep -qx 'zenbo-core-api'

timestamp="$(date -u +%Y%m%d-%H%M%S)"
backup_dir=".deploy-backups/${timestamp}-core-liff"
mkdir -p "$backup_dir"
tar -czf "$backup_dir/source-before.tgz" docker-compose.yml docker-compose.libn.yml services/core-api services/liff-app
printf 'Remote backup: %s/%s\n' "$remote_dir" "$backup_dir/source-before.tgz"
REMOTE
}

sync_sources() {
  local -a options=(-az --itemize-changes --exclude '__pycache__/' --exclude '*.pyc' --exclude '.pytest_cache/')
  if "$DRY_RUN"; then options+=(-n); fi
  (
    cd "$PROJECT_ROOT"
    rsync "${options[@]}" --relative \
      docker-compose.yml docker-compose.libn.yml services/core-api services/liff-app \
      "${SSH_TARGET}:${REMOTE_DIR}/"
  )
}

deploy_core() {
  ssh "${SSH_OPTIONS[@]}" "$SSH_TARGET" bash -s -- "$REMOTE_DIR" "$REMOTE_IMAGE" <<'REMOTE'
set -Eeuo pipefail
remote_dir="$1"
image="$2"
cd "$remote_dir"
# Build directly: the base Compose file has absent build contexts for shared services.
docker build -t "$image" ./services/core-api
# Keep shared MQTT/TTS containers untouched.
docker compose -f docker-compose.yml -f docker-compose.libn.yml up -d --no-build --no-deps --force-recreate zenbo-core-api
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:5005/health >/dev/null; then
    docker compose -f docker-compose.yml -f docker-compose.libn.yml ps zenbo-core-api
    exit 0
  fi
  sleep 2
done
printf '%s\n' 'zenbo-core-api did not become healthy after deployment' >&2
exit 1
REMOTE
}

assert_behavior_contract() {
  local url="$1"
  curl -fsS "$url" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
items = payload.get("presets") or payload.get("scenarios")
if not items or not all(item.get("behavior") for item in items):
    raise SystemExit("behavior contract is missing from one or more items")
print(f"behavior_contract=ok items={len(items)}")
'
}

verify_public_release() {
  printf '%s\n' 'Verifying Core and public LIFF routes...'
  curl -fsS "http://${SSH_IP_SERVER}:5005/health"
  printf '\n'
  assert_behavior_contract "http://${SSH_IP_SERVER}:5005/api/v1/presentations"
  assert_behavior_contract "http://${SSH_IP_SERVER}:5005/api/v1/scenarios"
  # Use a temp file instead of a pipe so the early exit of grep -q does not
  # send SIGPIPE to curl and report a false failure.
  local scenario_tmp
  scenario_tmp="$(mktemp)"
  curl -fsS "${PUBLIC_HOST}/liff/scenario/" -o "$scenario_tmp"
  grep -q 'Booky สถานการณ์' "$scenario_tmp"
  rm -f "$scenario_tmp"
  assert_behavior_contract "${PUBLIC_HOST}/liff-api/api/v1/presentations"
  printf '%s\n' 'Public LIFF scenario route: ok'
}

printf 'Target: %s (%s)\n' "$SSH_TARGET" "$REMOTE_DIR"
run_quality_gates
if "$DRY_RUN"; then
  printf '%s\n' 'Dry run: no production files or containers will be changed.'
  sync_sources
  printf '%s\n' 'Dry run completed.'
  exit 0
fi
remote_preflight_and_backup
sync_sources
deploy_core
verify_public_release
printf '%s\n' 'Production deploy completed successfully.'
