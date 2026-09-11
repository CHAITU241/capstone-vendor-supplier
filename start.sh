#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
elif [[ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON="$BACKEND_DIR/.venv/Scripts/python.exe"
else
  echo "Backend virtual environment not found."
  echo "Create it and install dependencies from backend/requirements.txt first."
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is not available on PATH."
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run 'npm install' in frontend/ first."
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  echo
  echo "Stopping VendorLens AI..."

  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi

  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi

  wait "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
  exit "$exit_code"
}

trap cleanup EXIT INT TERM

echo "Applying PostgreSQL migrations..."
(
  cd "$BACKEND_DIR"
  "$PYTHON" -m alembic upgrade head
)

echo "Starting FastAPI at http://127.0.0.1:8000..."
(
  cd "$BACKEND_DIR"
  exec "$PYTHON" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

echo "Starting React at http://127.0.0.1:5173..."
(
  cd "$FRONTEND_DIR"
  exec npm run dev -- --host 127.0.0.1 --port 5173
) &
FRONTEND_PID=$!

echo "VendorLens AI is starting. Press Ctrl+C to stop both services."

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
SERVICE_STATUS=$?
set -e

if [[ $SERVICE_STATUS -ne 0 ]]; then
  echo "A service exited with status $SERVICE_STATUS."
else
  echo "A service stopped; shutting down the remaining service."
fi

exit "$SERVICE_STATUS"

