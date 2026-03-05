# Ingestion workflow (GCS -> Neo4j)

## 1) Backfill pass

1. List case prefixes under `CASES_PREFIX` in GCS (`cases/YYYY-MM-DD/{case_id}`)
2. For each case, read available artifacts:
   - `request.json`
   - `generate_status.json`
   - `pass1_observations.json`
   - `liquidation_heatmap_observations.json` (optional)
   - `proposal_validated.json`
   - `trade.json` (optional)
3. Upsert graph entities in this order:
   - `Case`, `Symbol`, `AnalysisRun`
   - `Observation` subtypes + `Signal`
   - `Decision` + `Parameter`
   - `RationaleTag`
   - `TextChunk` (with embeddings)
   - `Artifact`
4. Attach explainability edges:
   - `(:Observation)-[:SUPPORTS]->(:Decision)`
   - `(:Observation)-[:INFLUENCES]->(:Parameter)`
5. Record ingest watermark on `Case`:
   - `ingestion_updated_at`
   - `ingestion_source_version`

## 2) Incremental sync

Use one or both:

- Event-triggered: call graph ingestion job after analyze pipeline writes final artifacts
- Polling: scan for changed object generation/checksum and re-upsert affected case only

Idempotency rule: all writes must be `MERGE`/`SET` style with deterministic IDs.

## 3) Embedding strategy

Create `TextChunk` for:

- proposal `reason_entry`
- proposal `reason_abstain`
- timeframe `notes`
- liquidation `notes`
- liquidation `eta_summary`

Store:

- `embedding_model`
- `embedding_dim`
- `embedding` vector

## 4) Correlation analysis patterns enabled

1. Cross-source alignment (`trend_dir` + `liquidity_bias` -> decision direction)
2. Parameter sensitivity (`observation family` -> `stop_loss`, `leverage`, `entry range`)
3. Conflict analysis (source disagreement vs confidence)
4. Retrieval-augmented investigation (vector search + graph expansion)

## 5) Future source onboarding contract

Each new source must map into:

- `Observation` subtype label
- `Signal` extraction rules
- optional `TextChunk` extraction
- provenance fields (`provider`, `model`, `artifact_name`, `artifact_path`)

This avoids schema churn when adding onchain/news/signals/reports.
