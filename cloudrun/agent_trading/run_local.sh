#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PORT="${PORT:-8082}"

uvicorn agent_trading.app.main:app \
  --host 127.0.0.1 \
  --port "$PORT" \
  --reload \
  --log-level debug
