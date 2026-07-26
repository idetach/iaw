from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_SERVICE_ROOT = Path(__file__).resolve().parents[2]

ExecutionMode = Literal["shadow", "demo", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_SERVICE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Execution safety
    execution_mode: ExecutionMode = Field(default="demo", alias="EXECUTION_MODE")
    loop_enabled: bool = Field(default=True, alias="LOOP_ENABLED")

    # Storage — separate prefix from the manual vision pipeline ("cases")
    # so both streams share one bucket but stay cleanly separable.
    gcs_bucket: str = Field(default="", alias="GCS_BUCKET")
    cases_prefix: str = Field(default="cases-auto", alias="CASES_PREFIX")
    persist_cases: bool = Field(default=True, alias="PERSIST_CASES")

    # Optional LLM memory context (off by default: recent outcomes can bias
    # the synthesis; enable deliberately and measure via an experiment log).
    include_recent_outcomes: bool = Field(default=False, alias="INCLUDE_RECENT_OUTCOMES")

    # Upstream services
    bybit_trading_url: str = Field(default="http://localhost:8081", alias="BYBIT_TRADING_URL")
    bybit_trading_token: str = Field(default="", alias="BYBIT_TRADING_TOKEN")
    bybit_trading_timeout: float = Field(default=30.0, alias="BYBIT_TRADING_TIMEOUT")
    agent_trading_url: str = Field(default="http://localhost:8082", alias="AGENT_TRADING_URL")

    # Models (ADR-0004)
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    model_gate: str = Field(default="claude-fable-5", alias="MODEL_GATE")
    model_synthesis: str = Field(default="claude-opus-5", alias="MODEL_SYNTHESIS")
    model_reflection: str = Field(default="claude-opus-5", alias="MODEL_REFLECTION")

    # Watchlist / candidates
    watchlist: str = Field(default="BTCUSDT,ETHUSDT,SOLUSDT", alias="WATCHLIST")
    radar_enabled: bool = Field(default=True, alias="RADAR_ENABLED")
    max_candidates_per_tick: int = Field(default=6, alias="MAX_CANDIDATES_PER_TICK")

    # Indicator engine
    timeframes: str = Field(default="4h,1h,30m,15m", alias="TIMEFRAMES")
    kline_limit: int = Field(default=200, alias="KLINE_LIMIT")

    # Risk governor (risk-governor-spec)
    risk_fraction: float = Field(default=0.0075, alias="RISK_FRACTION")
    max_concurrent_positions: int = Field(default=4, alias="MAX_CONCURRENT_POSITIONS")
    max_total_margin_fraction: float = Field(default=0.40, alias="MAX_TOTAL_MARGIN_FRACTION")
    max_aggregate_open_risk: float = Field(default=0.03, alias="MAX_AGGREGATE_OPEN_RISK")
    max_leverage: float = Field(default=10.0, alias="MAX_LEVERAGE")
    max_margin_percent: float = Field(default=25.0, alias="MAX_MARGIN_PERCENT")
    symbol_cooldown_hours: float = Field(default=4.0, alias="SYMBOL_COOLDOWN_HOURS")
    daily_loss_breaker_fraction: float = Field(default=0.03, alias="DAILY_LOSS_BREAKER_FRACTION")
    weekly_loss_breaker_fraction: float = Field(default=0.06, alias="WEEKLY_LOSS_BREAKER_FRACTION")
    min_confidence: float = Field(default=0.6, alias="MIN_CONFIDENCE")

    # Server
    frontend_cors_origins: str = Field(
        default="http://127.0.0.1:5173,http://localhost:5173",
        alias="FRONTEND_CORS_ORIGINS",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_cors_origins.split(",") if o.strip()]

    @property
    def watchlist_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.watchlist.split(",") if s.strip()]

    @property
    def timeframes_list(self) -> list[str]:
        return [t.strip() for t in self.timeframes.split(",") if t.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
