from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "metrics_margin"
    log_level: str = "INFO"

    postgres_host: str = "timescaledb"
    postgres_port: int = 5432
    postgres_db: str = "metrics_margin"
    postgres_user: str = "metrics_margin"
    postgres_password: str = "metrics_margin"

    binance_api_key: str | None = None
    binance_api_secret: str | None = None
    binance_base_url: str = "https://api.binance.com"

    tracked_assets: str = ""
    tracked_symbols: str = ""

    price_poll_seconds: int = 300
    inventory_poll_seconds: int = 900
    config_poll_seconds: int = 3600
    discover_poll_hours: int = 24
    backfill_hours: int = 168
    price_kline_interval: str = "5m"
    request_timeout_seconds: float = 20.0
    max_retries: int = 4
    retry_backoff_seconds: float = 1.5

    tg_iaw_metrics_alerts_bot_token: str = ""
    tg_iaw_metrics_alerts_bot_chat_id: str = ""

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def assets(self) -> list[str]:
        return [asset.strip().upper() for asset in self.tracked_assets.split(",") if asset.strip()]

    @property
    def symbols(self) -> list[str]:
        return [symbol.strip().upper() for symbol in self.tracked_symbols.split(",") if symbol.strip()]

    @property
    def asset_by_symbol(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for symbol in self.symbols:
            asset = symbol.removesuffix("USDT").removesuffix("BUSD")
            mapping[symbol] = asset
        return mapping


settings = Settings()
