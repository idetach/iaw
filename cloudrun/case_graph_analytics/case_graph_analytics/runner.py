from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .embedder import Embedder
from .gcs_source import get_storage_client, list_case_prefixes, read_case_artifacts
from .neo4j_sink import Neo4jSink
from .transform import build_case_payload

_LOG = logging.getLogger(__name__)


def _load_service_env() -> None:
    service_root = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=service_root / ".env")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest case artifacts from GCS into Neo4j")
    parser.add_argument("--case-id", default=None, help="ingest only one case_id")
    parser.add_argument("--once", action="store_true", help="run single pass")
    parser.add_argument("--poll", action="store_true", help="run polling loop")
    return parser.parse_args()


def _attach_embeddings(payload: dict, embedder: Embedder) -> None:
    chunks = payload.get("text_chunks") or []
    for chunk in chunks:
        text = chunk.get("text")
        chunk["embedding"] = embedder.embed(text) if text else None


def ingest_once(*, settings: Settings, sink: Neo4jSink, embedder: Embedder, only_case_id: str | None = None) -> None:
    client = get_storage_client()
    all_cases = list_case_prefixes(client=client, bucket=settings.gcs_bucket, cases_prefix=settings.cases_prefix)

    if only_case_id:
        case_prefix = all_cases.get(only_case_id)
        if not case_prefix:
            _LOG.warning("case_id %s not found under %s", only_case_id, settings.cases_prefix)
            return
        selected = {only_case_id: case_prefix}
    else:
        selected = all_cases

    _LOG.info("ingesting %s cases", len(selected))

    for idx, (case_id, case_prefix) in enumerate(selected.items(), start=1):
        artifacts = read_case_artifacts(client=client, bucket=settings.gcs_bucket, case_prefix=case_prefix)
        if not artifacts:
            continue

        payload = build_case_payload(case_id=case_id, case_prefix=case_prefix, artifacts=artifacts)
        _attach_embeddings(payload, embedder)
        sink.upsert_case_graph(
            payload,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
        )

        if idx % max(settings.ingest_batch_size, 1) == 0:
            _LOG.info("ingested %s/%s", idx, len(selected))

    _LOG.info("ingestion pass completed")


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    _load_service_env()
    settings = Settings()

    args = _parse_args()
    poll_mode = args.poll and not args.once
    if not args.poll and not args.once:
        poll_mode = not settings.ingest_once

    sink = Neo4jSink(uri=settings.neo4j_uri, user=settings.neo4j_user, password=settings.neo4j_password)
    embedder = Embedder(settings)

    try:
        if poll_mode:
            _LOG.info("starting polling mode with interval=%ss", settings.ingest_poll_interval_seconds)
            while True:
                ingest_once(settings=settings, sink=sink, embedder=embedder, only_case_id=args.case_id)
                time.sleep(max(settings.ingest_poll_interval_seconds, 1))
        else:
            ingest_once(settings=settings, sink=sink, embedder=embedder, only_case_id=args.case_id)
    finally:
        sink.close()


if __name__ == "__main__":
    run()
