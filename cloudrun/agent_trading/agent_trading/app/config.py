from __future__ import annotations

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

    gcs_bucket: str = Field(alias="GCS_BUCKET")
    cases_prefix: str = Field(default="cases", alias="CASES_PREFIX")

    bybit_trading_url: str = Field(
        default="http://localhost:8081", alias="BYBIT_TRADING_URL"
    )
    bybit_trading_token: str = Field(default="", alias="BYBIT_TRADING_TOKEN")
    bybit_trading_timeout: float = Field(default=30.0, alias="BYBIT_TRADING_TIMEOUT")

    frontend_cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        alias="FRONTEND_CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_cors_origins.split(",") if o.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
