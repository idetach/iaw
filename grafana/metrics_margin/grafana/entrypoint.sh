#!/bin/sh
set -e

# Copy provisioning templates to Grafana's writable provisioning dir
cp -r /opt/provisioning-tpl/* /etc/grafana/provisioning/ 2>/dev/null || true

# Template alerts.yaml – wrap chatid in quotes so YAML→JSON keeps it as a string
ALERTS=/etc/grafana/provisioning/alerting/alerts.yaml
if [ -f "$ALERTS" ]; then
  TMP=$(mktemp)
  awk -v bot="$TG_BOT_TOKEN" -v chat="$TG_CHAT_ID" '
    { gsub(/\$TG_BOT_TOKEN/, bot); gsub(/\$TG_CHAT_ID/, "\"" chat "\""); print }
  ' "$ALERTS" > "$TMP" && mv "$TMP" "$ALERTS"
fi

exec /run.sh "$@"
