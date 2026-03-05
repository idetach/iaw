# case_graph_analytics

Correlation-first Neo4j schema and ingestion plan for multi-source trading analysis.

This service is intentionally separated from `agent_charts_signal` so inference serving and analytical graph workloads can evolve independently.

## Scope (phase 1)

- Ingest existing case artifacts from GCS produced by `agent_charts_signal`
- Materialize correlation-ready graph entities in Neo4j
- Build vectorized text chunks for semantic retrieval over notes/rationales
- Support explainable links from source observations to decisions and position parameters

## Source artifacts consumed (current)

From each case prefix (`cases/YYYY-MM-DD/{case_id}`):

- `request.json`
- `generate_status.json`
- `pass1_observations.json`
- `liquidation_heatmap_observations.json` (optional)
- `proposal_validated.json`
- `trade.json` (optional)

See schema: `neo4j_schema.cypher`.
See ingestion flow: `ingestion_workflow.md`.

## Why a separate service

1. Different scaling profile (batch/event ingestion + heavy graph queries)
2. Cleaner failure domains (graph outages should not block case generation)
3. Easier future extension (onchain/news/signals/reports connectors)

## Planned runtime responsibilities

- **Backfill job**: historical GCS -> Neo4j
- **Incremental sync**: poll/event-driven updates after case writes
- **Embedding worker**: creates vectors for text chunks
- **Query API** (optional phase 2): serves correlation and retrieval endpoints

## Suggested env vars

See `.env.example`.

## Run ingestion runner

1. Install dependencies:

```bash
pip install -r cloudrun/case_graph_analytics/requirements.txt
```

2. Ensure env is present:

```bash
cp cloudrun/case_graph_analytics/.env.example cloudrun/case_graph_analytics/.env
```

3. Use helper scripts (recommended):

```bash
./cloudrun/case_graph_analytics/apply_schema.sh
./cloudrun/case_graph_analytics/ingest_once.sh
./cloudrun/case_graph_analytics/ingest_poll.sh
```

What each script does:

- `apply_schema.sh`
  - loads `cloudrun/case_graph_analytics/.env` if present
  - validates `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
  - applies `neo4j_schema.cypher`
  - prefers `cypher-shell` if installed, otherwise uses Python `neo4j` driver fallback
- `ingest_once.sh`
  - runs one full ingestion pass from GCS to Neo4j
  - forwards extra args (for example `--case-id <case_id>`)
- `ingest_poll.sh`
  - runs continuous polling ingestion loop
  - forwards extra args (for example `--case-id <case_id>`)

4. Manual equivalents (optional):

Apply schema in Neo4j (once):

```bash
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" \
  -f cloudrun/case_graph_analytics/neo4j_schema.cypher
```

One-shot full ingestion:

```bash
PYTHONPATH=cloudrun/case_graph_analytics \
python3 -m case_graph_analytics --once
```

Polling mode:

```bash
PYTHONPATH=cloudrun/case_graph_analytics \
python3 -m case_graph_analytics --poll
```

Ingest a single case:

```bash
PYTHONPATH=cloudrun/case_graph_analytics \
python3 -m case_graph_analytics --once --case-id <case_id>
```

## About commented sections in `neo4j_schema.cypher`

Yes, this is intentional.

`neo4j_schema.cypher` contains three kinds of content:

1. **Executable DDL** (not commented)
   - constraints, indexes, vector index
   - run with:
     - `./cloudrun/case_graph_analytics/apply_schema.sh`

2. **Schema contract/reference** (commented)
   - `Labels and expected properties`
   - `Relationship contract`
   - these are design documentation and should stay commented (they are not Cypher statements)

3. **Starter analysis queries** (commented)
   - under `Correlation query starter examples`
   - uncomment only when you want to execute an analysis query manually

### What to run, and when

- **When setting up Neo4j schema (first time, or after schema changes):**
  - run `./cloudrun/case_graph_analytics/apply_schema.sh`
  - do **not** uncomment the schema contract/reference sections

- **When doing data analysis after ingestion exists:**
  - copy a starter query and remove `//` comments (or temporarily uncomment that query block)
  - run it with `cypher-shell` or Neo4j Browser

Example using `cypher-shell`:

```bash
cypher-shell -a "$NEO4J_URI" -u "$NEO4J_USER" -p "$NEO4J_PASSWORD"
```

Then paste the query and execute it.

If you temporarily uncomment a starter query in `neo4j_schema.cypher`, do not run the full file with `apply_schema.sh` for query execution. Run the query directly in a query session instead.

## Data strategy (recommended)

- Keep detailed raw artifacts in GCS as the source of truth (images + full JSON files).
- Use Neo4j for normalized entities, relationships, and correlation-oriented querying.
- Keep artifact traceability in graph nodes via `artifact_path` / `gcs_path` references.

This gives low-cost durable storage in GCS and high-value cross-source analytics in Neo4j.

## Embeddings rollout

- Embeddings are optional for ingestion success.
- If `OPENAI_API_KEY` is empty, ingestion still works and graph structure is populated.
- To enable embeddings, set `OPENAI_API_KEY` in `cloudrun/case_graph_analytics/.env` and rerun:

```bash
./cloudrun/case_graph_analytics/ingest_once.sh
```

Then keep incremental updates running with:

```bash
./cloudrun/case_graph_analytics/ingest_poll.sh
```

## How to run analytics today

At this stage, analytics is query-driven in Neo4j.

- Use Neo4j Browser or `cypher-shell` to run Cypher queries.
- Start from the starter queries in `neo4j_schema.cypher` under `Correlation query starter examples`.
- Build additional custom queries for your hypotheses (signal alignment, parameter sensitivity, source conflict, etc.).

Current implementation status:

- ✅ ingestion pipeline (GCS -> Neo4j) is implemented
- ✅ schema + indexes/vector index DDL are implemented
- ✅ helper scripts for apply/ingest are implemented
- ⏳ dedicated analytics API/service endpoints are not implemented yet (planned next phase)
