#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

if [[ -d /opt/homebrew/bin ]]; then
  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
fi

backend_pid=""
frontend_pid=""

cleanup() {
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

wait_for_url() {
  local url="$1"
  local label="$2"

  for _ in {1..60}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label is ready: $url"
      return 0
    fi
    sleep 1
  done

  echo "Timed out waiting for $label at $url" >&2
  return 1
}

repair_known_dev_db_drift() {
  local db_path="$BACKEND_DIR/data/rhapsode.db"

  if ! command -v sqlite3 >/dev/null 2>&1 || [[ ! -f "$db_path" ]]; then
    return 0
  fi

  local version
  version="$(sqlite3 "$db_path" "select version_num from alembic_version limit 1;" 2>/dev/null || true)"

  if [[ "$version" == "c8d9e0f1a2b3" ]] &&
    sqlite3 "$db_path" "select 1 from sqlite_master where type = 'table' and name = 'fsrs_review_logs';" |
      grep -q '^1$'; then
    echo "Repairing local dev DB migration marker for existing fsrs_review_logs table..."
    sqlite3 "$db_path" "update alembic_version set version_num = 'd9e0f1a2b3c4';"
  fi
}

echo "Preparing backend..."
cd "$BACKEND_DIR"
uv sync --all-groups
repair_known_dev_db_drift
uv run rhapsode-migrate
uv run rhapsode &
backend_pid="$!"

wait_for_url "http://127.0.0.1:8000/api/v1/health" "Backend"

echo "Preparing frontend..."
cd "$FRONTEND_DIR"
npm install
npm run dev -- --host 127.0.0.1 &
frontend_pid="$!"

wait_for_url "http://127.0.0.1:5173/" "Frontend"

cat <<'EOF'

Rhapsode is running:
  Backend health: http://127.0.0.1:8000/api/v1/health
  Frontend:       http://127.0.0.1:5173/

Press Ctrl-C to stop both processes.
EOF

wait
