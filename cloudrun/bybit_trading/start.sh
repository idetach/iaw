#!/usr/bin/env bash
set -e

PORT="${PORT:-8080}"

exec uvicorn bybit_trading.app.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 1 \
  --loop uvloop \
  --log-level info
