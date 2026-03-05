#!/usr/bin/env bash
set -euo pipefail

echo "Running agent_charts_signal locally..."

echo "Expecting env at cloudrun/agent_charts_signal/.env"

export HOST="127.0.0.1"
export PORT="8080"

exec bash ./cloudrun/agent_charts_signal/start.sh
