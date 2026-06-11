#!/usr/bin/env bash
#
# Isolated Rhapsode test environment.
#
# Why: agent and manual testing must never share the developer's live data
# (backend/data/rhapsode.db on port 8000 + frontend on 5173). This launcher
# pins everything to backend/data-test and dedicated ports, so grading a card
# here can never perturb real review schedules.
#
# Usage:
#   scripts/test-env.sh seed       # migrate + seed languages/plugins + sandbox passage
#   scripts/test-env.sh backend    # run the API on the test DB (port 8799)
#   scripts/test-env.sh frontend   # run the dev UI proxied to the test API (port 5199)
#   scripts/test-env.sh reset      # wipe backend/data-test
#   scripts/test-env.sh env        # print the env + URLs
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"

# Dedicated, non-default ports so the test env can run alongside the real one.
export RHAPSODE_HOST=127.0.0.1
export RHAPSODE_PORT=8799
export RHAPSODE_DATA_DIR=data-test
export RHAPSODE_DATABASE_URL="sqlite:///data-test/rhapsode.db"
export RHAPSODE_MEDIA_DIR=data-test/media
export RHAPSODE_BACKUP_DIR=data-test/backups
FRONTEND_PORT=5199
API_TARGET="http://${RHAPSODE_HOST}:${RHAPSODE_PORT}"

cmd="${1:-env}"
case "$cmd" in
  seed)
    cd "$BACKEND_DIR"
    uv run python scripts/seed_test_passage.py
    ;;
  backend)
    cd "$BACKEND_DIR"
    uv run python scripts/seed_test_passage.py
    exec uv run rhapsode
    ;;
  frontend)
    cd "$FRONTEND_DIR"
    exec env RHAPSODE_API_TARGET="$API_TARGET" npm run dev -- --port "$FRONTEND_PORT" --strictPort
    ;;
  reset)
    rm -rf "$BACKEND_DIR/data-test"
    echo "wiped $BACKEND_DIR/data-test"
    ;;
  env)
    cat <<EOF
Test environment (isolated from live data on 8000/5173):
  RHAPSODE_PORT          $RHAPSODE_PORT
  RHAPSODE_DATABASE_URL  $RHAPSODE_DATABASE_URL
  API                    $API_TARGET/api/v1
  Frontend (when up)     http://${RHAPSODE_HOST}:${FRONTEND_PORT}
EOF
    ;;
  *)
    echo "unknown command: $cmd" >&2
    echo "usage: scripts/test-env.sh {seed|backend|frontend|reset|env}" >&2
    exit 2
    ;;
esac
