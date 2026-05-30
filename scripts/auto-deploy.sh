#!/usr/bin/env sh
set -eu

DEPLOY_DIR="${DEPLOY_DIR:-/opt/complass-service}"
IMAGE_NAME="${IMAGE_NAME:-complass-service:latest}"
LOCK_FILE="${LOCK_FILE:-/tmp/complass-deploy.lock}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/health}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die()  { log "FATAL: $*" >&2; exit 1; }

# ---- concurrency guard ----
if [ -f "${LOCK_FILE}" ]; then
    pid="$(cat "${LOCK_FILE}")"
    if kill -0 "${pid}" 2>/dev/null; then
        log "Another deployment (pid=${pid}) is running, aborting."
        exit 0
    fi
    log "Stale lock file found (pid=${pid} is gone), removing."
    rm -f "${LOCK_FILE}"
fi
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT INT TERM HUP

cd "${DEPLOY_DIR}"

DEPLOYED_HASH_FILE="${DEPLOYED_HASH_FILE:-/tmp/complass-deployed-hash}"

log "Fetching origin/dev..."
git fetch origin dev

REMOTE_HEAD="$(git rev-parse origin/dev)"
DEPLOYED_HEAD="$(cat "${DEPLOYED_HASH_FILE}" 2>/dev/null || true)"

if [ "${DEPLOYED_HEAD}" = "${REMOTE_HEAD}" ]; then
    log "Already deployed: ${REMOTE_HEAD}"
    exit 0
fi

# Snapshot the currently running image ID for possible rollback.
OLD_IMAGE_ID="$(docker inspect --format='{{.Image}}' complass-service 2>/dev/null || true)"

# Drop any uncommitted local edits so pull can proceed
git checkout -- . 2>/dev/null || true
git stash clear 2>/dev/null || true

git reset --hard origin/dev

log "Building image..."
docker build -t "${IMAGE_NAME}" .

log "Redeploying app container..."
docker compose up -d complass-service

log "Waiting for service to become healthy..."
sleep 5
if curl -fsS --max-time 10 --retry 10 --retry-delay 3 "${HEALTH_URL}"; then
    echo
    log "Deploy succeeded."
    docker compose ps
    echo "${REMOTE_HEAD}" > "${DEPLOYED_HASH_FILE}"

    # Drop dangling images (old untagged layers from previous builds).
    docker image prune -f 2>/dev/null || true
else
    echo
    log "Health check failed, rolling back..."
    if [ -n "${OLD_IMAGE_ID}" ]; then
        docker tag "${OLD_IMAGE_ID}" "${IMAGE_NAME}" 2>/dev/null || true
        docker compose up -d complass-service
        log "Rolled back to ${OLD_IMAGE_ID}"
    else
        log "No previous image to roll back to."
    fi
    die "Deploy failed: health check returned non-zero."
fi
