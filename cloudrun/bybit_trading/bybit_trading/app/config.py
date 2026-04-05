from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bybit_api_key: str = Field(default="", alias="BYBIT_API_KEY")
    bybit_api_secret: str = Field(default="", alias="BYBIT_API_SECRET")
    bybit_testnet: bool = Field(default=False, alias="BYBIT_TESTNET")
    bybit_category: str = Field(default="linear", alias="BYBIT_CATEGORY")

    bybit_trading_token: str = Field(default="", alias="BYBIT_TRADING_TOKEN")

    frontend_cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        alias="FRONTEND_CORS_ORIGINS",
    )

    radar_price_change_pct_threshold: float = Field(
        default=3.0, alias="RADAR_PRICE_CHANGE_PCT_THRESHOLD"
    )
    radar_volume_threshold_usdt: float = Field(
        default=50_000_000.0, alias="RADAR_VOLUME_THRESHOLD_USDT"
    )
    radar_funding_rate_threshold: float = Field(
        default=-0.0005, alias="RADAR_FUNDING_RATE_THRESHOLD"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_cors_origins.split(",") if o.strip()]

    @property
    def has_credentials(self) -> bool:
        return bool(self.bybit_api_key and self.bybit_api_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
