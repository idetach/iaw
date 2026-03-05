from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    neo4j_uri: str = "neo4j://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str

    gcs_bucket: str
    cases_prefix: str = "cases"

    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-large"
    embedding_dim: int = 3072
    openai_api_key: str | None = None

    ingest_batch_size: int = 200
    ingest_poll_interval_seconds: int = 30
    ingest_once: bool = True
