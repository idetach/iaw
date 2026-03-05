#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

load_env_key() {
  local key="$1"
  local env_file="$2"
  local line
  local value

  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$env_file" | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    return 0
  fi

  value="${line#*=}"
  value="${value#${value%%[![:space:]]*}}"
  value="${value%${value##*[![:space:]]}}"

  if [[ "$value" == \"*\" && "$value" == *\" ]]; then
    value="${value:1:${#value}-2}"
  elif [[ "$value" == \'.*\' && "$value" == *\' ]]; then
    value="${value:1:${#value}-2}"
  fi

  printf -v "$key" '%s' "$value"
  export "$key"
}

if [[ -f "$SCRIPT_DIR/.env" ]]; then
  load_env_key "NEO4J_URI" "$SCRIPT_DIR/.env"
  load_env_key "NEO4J_USER" "$SCRIPT_DIR/.env"
  load_env_key "NEO4J_PASSWORD" "$SCRIPT_DIR/.env"
fi

: "${NEO4J_URI:?NEO4J_URI must be set in .env or environment}"
: "${NEO4J_USER:?NEO4J_USER must be set in .env or environment}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD must be set in .env or environment}"

if command -v cypher-shell >/dev/null 2>&1; then
  cypher-shell \
    -a "$NEO4J_URI" \
    -u "$NEO4J_USER" \
    -p "$NEO4J_PASSWORD" \
    -f "$SCRIPT_DIR/neo4j_schema.cypher"
else
  PYTHON_BIN="python3"
  if ! "$PYTHON_BIN" -c "import neo4j" >/dev/null 2>&1; then
    if [[ -x "$REPO_ROOT/.venv/bin/python3" ]] && "$REPO_ROOT/.venv/bin/python3" -c "import neo4j" >/dev/null 2>&1; then
      PYTHON_BIN="$REPO_ROOT/.venv/bin/python3"
    fi
  fi

  PYTHONPATH="$SCRIPT_DIR" \
    "$PYTHON_BIN" -m case_graph_analytics.apply_schema \
    --schema-file "$SCRIPT_DIR/neo4j_schema.cypher"
fi

echo "Neo4j schema applied successfully."
