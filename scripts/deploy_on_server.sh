#!/usr/bin/env bash

set -Eeuo pipefail

log() {
    printf '[deploy] %s\n' "$*"
}

fail() {
    log "$*"
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
else
    fail "Docker Compose is not installed on the server"
fi

DEPLOY_PATH="${DEPLOY_PATH:-$(pwd)}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"

require_command git
require_command curl

cd "$DEPLOY_PATH"

[[ -d .git ]] || fail "DEPLOY_PATH must point to a git checkout: $DEPLOY_PATH"
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"

if [[ -f .env ]]; then
    set -a
    . ./.env
    set +a
else
    log "No .env file found in $DEPLOY_PATH; relying on existing environment variables"
fi

API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1:${API_PORT:-8000}/health}"

if [[ -n "$(git status --porcelain)" ]]; then
    fail "Deployment checkout is dirty. Commit or remove local changes on the server before deploying."
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$CURRENT_BRANCH" != "$DEPLOY_BRANCH" ]]; then
    fail "Deployment checkout is on branch '$CURRENT_BRANCH', expected '$DEPLOY_BRANCH'"
fi

log "Fetching latest code from origin/$DEPLOY_BRANCH"
git fetch origin "$DEPLOY_BRANCH"

LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse "origin/$DEPLOY_BRANCH")"

if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
    log "Updating repository"
    git pull --ff-only origin "$DEPLOY_BRANCH"
else
    log "Repository already matches origin/$DEPLOY_BRANCH"
fi

log "Rebuilding and restarting Docker services"
# --build: rebuild images (picks up new code after git pull)
# --force-recreate: always recreate containers so the new image is actually used
if [[ -n "${DEPLOY_NO_CACHE:-}" ]]; then
    log "Full rebuild (no cache) for api..."
    "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" build --no-cache api
fi
"${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" up -d --build --force-recreate --remove-orphans

log "Waiting for API health check at $API_HEALTH_URL"
SECONDS_WAITED=0
until curl --fail --silent --show-error "$API_HEALTH_URL" >/dev/null; do
    if (( SECONDS_WAITED >= HEALTH_TIMEOUT_SECONDS )); then
        log "Health check failed after ${HEALTH_TIMEOUT_SECONDS}s. Recent API logs:"
        "${DOCKER_COMPOSE[@]}" -f "$COMPOSE_FILE" logs --tail=100 api || true
        exit 1
    fi

    sleep 5
    SECONDS_WAITED=$((SECONDS_WAITED + 5))
done

log "Configuring Nginx reverse proxy..."
if [[ -f nginx/facebook_scraper.conf ]] && command -v nginx >/dev/null 2>&1; then
    sudo cp nginx/facebook_scraper.conf /etc/nginx/sites-available/facebook_scraper
    if [[ ! -h /etc/nginx/sites-enabled/facebook_scraper ]]; then
        sudo ln -s /etc/nginx/sites-available/facebook_scraper /etc/nginx/sites-enabled/
    fi
    sudo systemctl reload nginx
    log "Nginx configuration updated and reloaded."
else
    log "Skipping Nginx setup (nginx/facebook_scraper.conf not found or nginx not installed)."
fi

log "Deployment completed successfully at commit $(git rev-parse --short HEAD)"
