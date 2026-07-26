#!/usr/bin/env bash
# Trigger one conductor tick locally (used by launchd/cron, or run by hand).
# Logs the summary line to ~/Library/Logs/iaw-conductor-tick.log
CONDUCTOR_URL="${CONDUCTOR_URL:-http://127.0.0.1:8084}"
LOG="$HOME/Library/Logs/iaw-conductor-tick.log"

result="$(curl -sS -X POST --max-time 570 "$CONDUCTOR_URL/v1/loop/tick" 2>&1)"
status=$?
echo "$(date -u +%FT%TZ) exit=$status $(echo "$result" | head -c 400)" >> "$LOG"
exit $status
