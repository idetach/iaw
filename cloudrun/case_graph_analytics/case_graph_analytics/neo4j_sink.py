from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from neo4j import Driver, GraphDatabase


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Neo4jSink:
    def __init__(self, *, uri: str, user: str, password: str):
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    @property
    def driver(self) -> Driver:
        return self._driver

    def close(self) -> None:
        self._driver.close()

    def upsert_case_graph(self, payload: dict[str, Any], *, embedding_model: str, embedding_dim: int) -> None:
        case = payload["case"]
        run = payload["run"]
        symbol = payload.get("symbol")

        with self._driver.session() as session:
            session.execute_write(self._upsert_case, case)
            if symbol:
                session.execute_write(self._upsert_symbol, case["case_id"], symbol)
            session.execute_write(self._upsert_run, run)

            if payload.get("observations"):
                session.execute_write(self._upsert_observations, run["run_id"], payload["observations"])
            if payload.get("signals"):
                session.execute_write(self._upsert_signals, payload["signals"])

            decision = payload.get("decision")
            if decision:
                session.execute_write(self._upsert_decision, run["run_id"], decision)

            if payload.get("parameters"):
                session.execute_write(self._upsert_parameters, payload["parameters"])

            if payload.get("rationale_tags") and decision:
                session.execute_write(self._upsert_rationale_tags, decision["decision_id"], payload["rationale_tags"])

            if payload.get("artifacts"):
                session.execute_write(self._upsert_artifacts, payload["artifacts"])

            trade = payload.get("trade")
            if isinstance(trade, dict):
                session.execute_write(self._upsert_trade, case["case_id"], run["run_id"], trade)

            if payload.get("text_chunks"):
                session.execute_write(
                    self._upsert_text_chunks,
                    payload["text_chunks"],
                    embedding_model,
                    embedding_dim,
                )

            if payload.get("support_links"):
                session.execute_write(self._upsert_support_links, payload["support_links"])
            if payload.get("influence_links"):
                session.execute_write(self._upsert_influence_links, payload["influence_links"])

    @staticmethod
    def _upsert_case(tx, case: dict[str, Any]) -> None:
        tx.run(
            """
            MERGE (c:Case {case_id: $case.case_id})
            SET c += $case
            """,
            case=case,
        )

    @staticmethod
    def _upsert_symbol(tx, case_id: str, symbol: str) -> None:
        tx.run(
            """
            MERGE (s:Symbol {symbol: $symbol})
            WITH s
            MATCH (c:Case {case_id: $case_id})
            MERGE (c)-[:FOR_SYMBOL]->(s)
            """,
            case_id=case_id,
            symbol=symbol,
        )

    @staticmethod
    def _upsert_run(tx, run: dict[str, Any]) -> None:
        tx.run(
            """
            MATCH (c:Case {case_id: $run.case_id})
            MERGE (r:AnalysisRun {run_id: $run.run_id})
            SET r += $run
            MERGE (c)-[:HAS_RUN]->(r)
            """,
            run=run,
        )

    @staticmethod
    def _upsert_observations(tx, run_id: str, observations: list[dict[str, Any]]) -> None:
        tx.run(
            """
            MATCH (r:AnalysisRun {run_id: $run_id})
            UNWIND $rows AS row
            MERGE (o:Observation {obs_id: row.obs_id})
            SET o += row
            FOREACH (_ IN CASE WHEN row.source_type = 'timeframe_chart' THEN [1] ELSE [] END |
              SET o:TimeframeObservation
            )
            FOREACH (_ IN CASE WHEN row.source_type = 'liquidation_heatmap' THEN [1] ELSE [] END |
              SET o:LiquidationObservation
            )
            MERGE (r)-[:HAS_OBSERVATION]->(o)
            """,
            run_id=run_id,
            rows=observations,
        )

    @staticmethod
    def _upsert_signals(tx, signals: list[dict[str, Any]]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (o:Observation {obs_id: row.obs_id})
            MERGE (s:Signal {signal_id: row.signal_id})
            SET s += row
            MERGE (o)-[:EMITS_SIGNAL]->(s)
            """,
            rows=signals,
        )

    @staticmethod
    def _upsert_decision(tx, run_id: str, decision: dict[str, Any]) -> None:
        tx.run(
            """
            MATCH (r:AnalysisRun {run_id: $run_id})
            MERGE (d:Decision {decision_id: $decision.decision_id})
            SET d += $decision
            MERGE (r)-[:YIELDED_DECISION]->(d)
            """,
            run_id=run_id,
            decision=decision,
        )

    @staticmethod
    def _upsert_parameters(tx, parameters: list[dict[str, Any]]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (d:Decision {decision_id: row.decision_id})
            MERGE (p:Parameter {parameter_id: row.parameter_id})
            SET p += row
            MERGE (d)-[:SETS_PARAMETER]->(p)
            """,
            rows=parameters,
        )

    @staticmethod
    def _upsert_rationale_tags(tx, decision_id: str, tags: list[str]) -> None:
        tx.run(
            """
            MATCH (d:Decision {decision_id: $decision_id})
            UNWIND $tags AS tag
            MERGE (t:RationaleTag {tag: tag})
            MERGE (d)-[:TAGGED_AS]->(t)
            """,
            decision_id=decision_id,
            tags=tags,
        )

    @staticmethod
    def _upsert_artifacts(tx, artifacts: list[dict[str, Any]]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Case {case_id: row.case_id})
            MERGE (a:Artifact {case_id: row.case_id, name: row.name})
            SET a += row
            MERGE (c)-[:HAS_ARTIFACT]->(a)
            """,
            rows=artifacts,
        )

    @staticmethod
    def _upsert_trade(tx, case_id: str, run_id: str, trade: dict[str, Any]) -> None:
        row = {
            "case_id": case_id,
            "trade_id": trade.get("trade_id") or f"{case_id}:trade",
            "saved_at": trade.get("saved_at") or _iso_now(),
            "status": trade.get("status"),
            "pnl": trade.get("pnl"),
            "outcome_label": trade.get("outcome_label"),
            "raw": trade,
            "run_id": run_id,
        }
        tx.run(
            """
            MATCH (c:Case {case_id: $row.case_id})
            MATCH (r:AnalysisRun {run_id: $row.run_id})
            MERGE (t:Trade {trade_id: $row.trade_id})
            SET t += $row
            MERGE (c)-[:HAS_TRADE]->(t)
            MERGE (r)-[:HAS_TRADE]->(t)
            """,
            row=row,
        )

    @staticmethod
    def _upsert_text_chunks(tx, chunks: list[dict[str, Any]], embedding_model: str, embedding_dim: int) -> None:
        now = _iso_now()
        rows = []
        for chunk in chunks:
            rows.append(
                {
                    **chunk,
                    "embedding_model": embedding_model,
                    "embedding_dim": embedding_dim,
                    "created_at": now,
                    "embedding": chunk.get("embedding"),
                }
            )

        tx.run(
            """
            UNWIND $rows AS row
            MERGE (tc:TextChunk {chunk_id: row.chunk_id})
            SET tc += row
            WITH tc, row
            OPTIONAL MATCH (o:Observation {obs_id: row.source_ref})
            FOREACH (_ IN CASE WHEN o IS NULL THEN [] ELSE [1] END |
              MERGE (o)-[:HAS_TEXT_CHUNK]->(tc)
            )
            WITH tc, row
            OPTIONAL MATCH (d:Decision {decision_id: row.source_ref})
            FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
              MERGE (d)-[:HAS_TEXT_CHUNK]->(tc)
            )
            """,
            rows=rows,
        )

    @staticmethod
    def _upsert_support_links(tx, links: list[dict[str, Any]]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (o:Observation {obs_id: row.obs_id})
            MATCH (d:Decision {decision_id: row.decision_id})
            MERGE (o)-[rel:SUPPORTS]->(d)
            SET rel.weight = row.weight,
                rel.rationale_span = row.rationale_span,
                rel.method = row.method
            """,
            rows=links,
        )

    @staticmethod
    def _upsert_influence_links(tx, links: list[dict[str, Any]]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (o:Observation {obs_id: row.obs_id})
            MATCH (p:Parameter {parameter_id: row.parameter_id})
            MERGE (o)-[rel:INFLUENCES]->(p)
            SET rel.weight = row.weight,
                rel.method = row.method
            """,
            rows=links,
        )
