from __future__ import annotations

import argparse
import os
from pathlib import Path

from neo4j import GraphDatabase


def _read_statements(schema_path: Path) -> list[str]:
    lines: list[str] = []
    for raw in schema_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("//"):
            continue
        lines.append(raw)

    merged = "\n".join(lines)
    statements = [stmt.strip() for stmt in merged.split(";") if stmt.strip()]
    return statements


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Neo4j schema file with Python driver")
    parser.add_argument("--schema-file", required=True)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not user or not password:
        raise SystemExit("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD must be set")

    schema_path = Path(args.schema_file)
    statements = _read_statements(schema_path)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for stmt in statements:
                session.run(stmt).consume()
    finally:
        driver.close()


if __name__ == "__main__":
    main()
