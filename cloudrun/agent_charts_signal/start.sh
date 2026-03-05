#!/usr/bin/env bash
set -euo pipefail

echo "Starting agent_charts_signal..."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Prefer currently activated venv first, then service-local .venv
if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/uvicorn" ]; then
  UVICORN="$VIRTUAL_ENV/bin/uvicorn"
elif [ -x "$SCRIPT_DIR/.venv/bin/uvicorn" ]; then
  UVICORN="$SCRIPT_DIR/.venv/bin/uvicorn"
else
  UVICORN="uvicorn"
fi

exec "$UVICORN" --app-dir "$SCRIPT_DIR" agent_charts_signal.app.main:app --host "$HOST" --port "$PORT"
