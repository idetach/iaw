from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    gcs_bucket: str
    cases_prefix: str = "cases"
    signed_url_ttl_seconds: int = 900

    vision_provider: str = "claude"

    anthropic_api_key: str | None = None
    claude_model_pass1: str = "claude-opus-4-6"
    claude_model_pass2: str = "claude-opus-4-6"
    claude_model_fallbacks: str = "claude-opus-4-5,claude-opus-4-1,claude-opus-4,claude-sonnet-4-20250514,claude-3-7-sonnet-20250219,claude-3-5-sonnet-20241022,claude-3-5-sonnet-20240620,claude-3-haiku-20240307"

    openai_api_key: str | None = None
    openai_model_pass1: str = "gpt-5.2"
    openai_model_pass2: str = "gpt-5.2"
    openai_model_fallbacks: str = "gpt-5.1,gpt-4.1"

    gemini_api_key: str | None = None
    gemini_model_pass1: str = "gemini-3.1-pro"
    gemini_model_pass2: str = "gemini-3.1-pro"
    gemini_model_fallbacks: str = "gemini-2.5-pro,gemini-2.5-flash"

    max_leverage: float = 10.0
    max_margin_percent: float = 25.0
    liquidation_heatmap_time_horizon_hours: int = 24

    capture_worker_url: str | None = None
    capture_worker_token: str | None = None
    capture_worker_timeout_seconds: float = 30.0
    generation_stale_minutes: int = 20


class Caps(BaseModel):
    max_leverage: float
    max_margin_percent: float
