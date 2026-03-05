from __future__ import annotations

import logging

from .config import Settings

_LOG = logging.getLogger(__name__)


class Embedder:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

        if settings.embedding_provider.lower() != "openai":
            _LOG.info("embedding provider %s is not implemented; embeddings disabled", settings.embedding_provider)
            return

        if not settings.openai_api_key:
            _LOG.info("OPENAI_API_KEY is empty; embeddings disabled")
            return

        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=settings.openai_api_key)
        except Exception as exc:
            _LOG.warning("failed to initialize openai client: %s", exc)
            self._client = None

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def embed(self, text: str) -> list[float] | None:
        if not self._client:
            return None
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        try:
            response = self._client.embeddings.create(
                model=self._settings.embedding_model,
                input=cleaned,
            )
            return list(response.data[0].embedding)
        except Exception as exc:
            _LOG.warning("embedding failed: %s", exc)
            return None
