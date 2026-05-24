#!/usr/bin/env sh
set -eu

DEPLOY_DIR="${DEPLOY_DIR:-/opt/complass-service}"
IMAGE_NAME="${IMAGE_NAME:-complass-service:latest}"

cd "${DEPLOY_DIR}"

git fetch origin dev
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse origin/dev)"

# Skip work when dev has not changed since the previous deployment.
if [ "${LOCAL_HEAD}" = "${REMOTE_HEAD}" ]; then
    echo "Already up to date: ${LOCAL_HEAD}"
    exit 0
fi

git pull --ff-only origin dev
docker build -t "${IMAGE_NAME}" .
docker compose up -d
docker compose ps
curl -f http://127.0.0.1:8080/health
