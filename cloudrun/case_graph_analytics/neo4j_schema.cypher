// Correlation-first graph schema for trading decision intelligence
// Phase 1 sources: request.json, pass1_observations.json, liquidation_heatmap_observations.json,
// proposal_validated.json, generate_status.json, trade.json

// ---------- Constraints ----------
CREATE CONSTRAINT case_id_unique IF NOT EXISTS
FOR (c:Case) REQUIRE c.case_id IS UNIQUE;

CREATE CONSTRAINT symbol_unique IF NOT EXISTS
FOR (s:Symbol) REQUIRE s.symbol IS UNIQUE;

CREATE CONSTRAINT run_id_unique IF NOT EXISTS
FOR (r:AnalysisRun) REQUIRE r.run_id IS UNIQUE;

CREATE CONSTRAINT obs_id_unique IF NOT EXISTS
FOR (o:Observation) REQUIRE o.obs_id IS UNIQUE;

CREATE CONSTRAINT decision_id_unique IF NOT EXISTS
FOR (d:Decision) REQUIRE d.decision_id IS UNIQUE;

CREATE CONSTRAINT parameter_id_unique IF NOT EXISTS
FOR (p:Parameter) REQUIRE p.parameter_id IS UNIQUE;

CREATE CONSTRAINT tag_unique IF NOT EXISTS
FOR (t:RationaleTag) REQUIRE t.tag IS UNIQUE;

CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (tc:TextChunk) REQUIRE tc.chunk_id IS UNIQUE;

// ---------- Lookup indexes ----------
CREATE INDEX case_date_idx IF NOT EXISTS
FOR (c:Case) ON (c.date);

CREATE INDEX case_generation_state_idx IF NOT EXISTS
FOR (c:Case) ON (c.generation_state);

CREATE INDEX run_timestamp_idx IF NOT EXISTS
FOR (r:AnalysisRun) ON (r.timestamp_utc);

CREATE INDEX observation_source_idx IF NOT EXISTS
FOR (o:Observation) ON (o.source_type);

CREATE INDEX signal_name_value_idx IF NOT EXISTS
FOR (s:Signal) ON (s.name, s.value);

CREATE INDEX parameter_name_idx IF NOT EXISTS
FOR (p:Parameter) ON (p.name);

CREATE INDEX textchunk_source_idx IF NOT EXISTS
FOR (tc:TextChunk) ON (tc.source);

// ---------- Vector index ----------
// Keep dimension aligned with EMBEDDING_DIM env var (e.g. 1536 or 3072).
CREATE VECTOR INDEX textchunk_embedding_idx IF NOT EXISTS
FOR (tc:TextChunk) ON (tc.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 3072,
  `vector.similarity_function`: 'cosine'
}};

// ---------- Labels and expected properties ----------
// (:Case {
//   case_id, gcs_prefix, date, created_at, updated_at,
//   generation_state, generation_detail,
//   include_liquidation_heatmap, liquidation_horizon_hours,
//   ingestion_updated_at
// })
//
// (:Symbol {symbol})
//
// (:AnalysisRun {
//   run_id, case_id, symbol, timestamp_utc,
//   provider, model_pass1, model_pass2,
//   requested_at, started_at, completed_at,
//   status
// })
//
// (:Observation {
//   obs_id, case_id, run_id, source_type,
//   observed_at, valid_from, valid_to,
//   provider, model, confidence,
//   artifact_name, artifact_path
// })
//
// (:TimeframeObservation:Observation {
//   timeframe, regime, trend_dir, vwap_state, macd_state,
//   key_levels, notes, warnings
// })
//
// (:LiquidationObservation:Observation {
//   time_horizon_hours, liquidity_bias,
//   key_liquidity_levels, eta_summary, notes, warnings
// })
//
// (:Signal {
//   signal_id, name, value, numeric_value,
//   unit, timeframe
// })
//
// (:Decision {
//   decision_id, case_id, run_id,
//   long_short_none, confidence,
//   reason_entry, reason_abstain,
//   position_id, decision_timestamp,
//   model_used, artifact_name, artifact_path
// })
//
// (:Parameter {
//   parameter_id, case_id, run_id, decision_id,
//   name, value, value_type, unit,
//   valid_from, valid_to
// })
//
// (:RationaleTag {tag})
//
// (:TextChunk {
//   chunk_id, case_id, run_id,
//   source, source_ref,
//   text, embedding_model, embedding_dim, embedding,
//   created_at
// })
//
// (:Artifact {
//   case_id, name, gcs_path, content_type,
//   updated_at, checksum
// })
//
// (:Trade {
//   case_id, trade_id, saved_at,
//   status, pnl, outcome_label, raw
// })
//
// (:Outcome {
//   outcome_id, case_id, run_id,
//   horizon, realized_return, max_drawdown,
//   hit_target, hit_stop, label
// })

// ---------- Relationship contract ----------
// (c:Case)-[:FOR_SYMBOL]->(sym:Symbol)
// (c)-[:HAS_RUN]->(r:AnalysisRun)
// (r)-[:HAS_OBSERVATION]->(o:Observation)
// (o)-[:EMITS_SIGNAL]->(s:Signal)
// (r)-[:YIELDED_DECISION]->(d:Decision)
// (d)-[:SETS_PARAMETER]->(p:Parameter)
// (d)-[:TAGGED_AS]->(tag:RationaleTag)
// (o)-[:SUPPORTS {weight, rationale_span, method}]->(d)
// (o)-[:INFLUENCES {weight, method}]->(p)
// (o)-[:HAS_TEXT_CHUNK]->(tc:TextChunk)
// (d)-[:HAS_TEXT_CHUNK]->(tc:TextChunk)
// (c)-[:HAS_ARTIFACT]->(a:Artifact)
// (c)-[:HAS_TRADE]->(t:Trade)
// (d)-[:RESULTED_IN]->(out:Outcome)

// ---------- Correlation query starter examples ----------

// Q1: How often bullish multi-timeframe trend + upward liquidity bias leads to LONG decisions?
// MATCH (r:AnalysisRun)-[:HAS_OBSERVATION]->(tf:TimeframeObservation)
// WHERE tf.timeframe IN ['4h','1h'] AND tf.trend_dir = 'UP'
// WITH r, count(tf) AS up_tfs
// MATCH (r)-[:HAS_OBSERVATION]->(liq:LiquidationObservation)
// WHERE liq.liquidity_bias = 'UP' AND up_tfs >= 2
// MATCH (r)-[:YIELDED_DECISION]->(d:Decision)
// RETURN d.long_short_none AS decision, count(*) AS n
// ORDER BY n DESC;

// Q2: Which observation families influence stop_loss the most?
// MATCH (:AnalysisRun)-[:HAS_OBSERVATION]->(o:Observation)-[inf:INFLUENCES]->(p:Parameter {name:'stop_loss'})
// RETURN o.source_type AS source, avg(inf.weight) AS avg_weight, count(*) AS links
// ORDER BY avg_weight DESC;
