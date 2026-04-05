from __future__ import annotations

from functools import lru_cache

from pybit.unified_trading import HTTP

from .config import Settings


def build_http_client(settings: Settings) -> HTTP:
    """Build a pybit HTTP session.

    When no credentials are provided a public-only client is returned
    (trading endpoints will raise 401 from Bybit).
    """
    kwargs: dict = {
        "testnet": settings.bybit_testnet,
    }
    if settings.has_credentials:
        kwargs["api_key"] = settings.bybit_api_key
        kwargs["api_secret"] = settings.bybit_api_secret
    return HTTP(**kwargs)


@lru_cache(maxsize=1)
def _cached_client_key(api_key: str, testnet: bool) -> str:
    return f"{api_key}:{testnet}"


_http_client: HTTP | None = None
_http_client_key: str | None = None


def get_http_client(settings: Settings) -> HTTP:
    global _http_client, _http_client_key
    key = f"{settings.bybit_api_key}:{settings.bybit_testnet}"
    if _http_client is None or _http_client_key != key:
        _http_client = build_http_client(settings)
        _http_client_key = key
    return _http_client
