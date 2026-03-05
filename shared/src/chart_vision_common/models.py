from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


VisionProvider = Literal["claude", "openai", "gemini"]


class CaseCreateResponse(BaseModel):
    case_id: str
    upload_urls: dict[str, str]
    extra_upload_urls: dict[str, str] = Field(default_factory=dict)
    analyze_url: str
    expires_at: datetime


class CaseAnalyzeRequest(BaseModel):
    symbol: str = Field(min_length=1)
    timestamp_utc: datetime
    timeframes_order: list[str]
    vision_provider: VisionProvider | None = None
    vision_model_pass1: str | None = None
    vision_model_pass2: str | None = None
    include_liquidation_heatmap: bool = False
    liquidation_heatmap_time_horizon_hours: int | None = Field(default=None, ge=1, le=168)

    @field_validator("timeframes_order")
    @classmethod
    def _tf_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("timeframes_order must be non-empty")
        return v


LongShortNone = Literal["LONG", "SHORT", "NONE"]
PositionDuration = Literal["HOUR", "DAY", "SWING"]
PositionStrategy = Literal["ADD_UP", "DCA", "CONTRARIAN", "SCALP", "HOLD"]


class TradeProposal(BaseModel):
    position_id: str
    timestamp: datetime

    long_short_none: LongShortNone

    target_price: float | None
    stop_loss: float | None
    leverage: float | None
    margin_percent: float | None

    # Entry/exit timing projections
    entry_price_min: float | None
    entry_price_max: float | None
    entry_time_from: datetime | None
    entry_time_to: datetime | None
    exit_time_from: datetime | None
    exit_time_to: datetime | None

    # Position characteristics
    position_duration: PositionDuration | None
    position_strategy: PositionStrategy | None

    confidence: float = Field(ge=0.0, le=1.0)

    reason_entry: str
    reason_abstain: str
    rationale_tags: list[str]
    
    model_used: str | None = None

    @model_validator(mode="after")
    def _validate_conditional_fields(self) -> "TradeProposal":
        if self.long_short_none == "NONE":
            if self.target_price is not None:
                raise ValueError("target_price must be null when long_short_none=NONE")
            if self.stop_loss is not None:
                raise ValueError("stop_loss must be null when long_short_none=NONE")
            if self.leverage is not None:
                raise ValueError("leverage must be null when long_short_none=NONE")
            if self.margin_percent is not None:
                raise ValueError("margin_percent must be null when long_short_none=NONE")
            if self.entry_price_min is not None:
                raise ValueError("entry_price_min must be null when long_short_none=NONE")
            if self.entry_price_max is not None:
                raise ValueError("entry_price_max must be null when long_short_none=NONE")
            if self.entry_time_from is not None:
                raise ValueError("entry_time_from must be null when long_short_none=NONE")
            if self.entry_time_to is not None:
                raise ValueError("entry_time_to must be null when long_short_none=NONE")
            if self.exit_time_from is not None:
                raise ValueError("exit_time_from must be null when long_short_none=NONE")
            if self.exit_time_to is not None:
                raise ValueError("exit_time_to must be null when long_short_none=NONE")
            if self.position_duration is not None:
                raise ValueError("position_duration must be null when long_short_none=NONE")
            if self.position_strategy is not None:
                raise ValueError("position_strategy must be null when long_short_none=NONE")
            if not self.reason_abstain.strip():
                raise ValueError("reason_abstain must be non-empty when long_short_none=NONE")
        else:
            if self.target_price is None:
                raise ValueError("target_price is required when long_short_none is LONG/SHORT")
            if self.stop_loss is None:
                raise ValueError("stop_loss is required when long_short_none is LONG/SHORT")
            if self.entry_price_min is None or self.entry_price_max is None:
                raise ValueError("entry_price_min and entry_price_max are required when long_short_none is LONG/SHORT")
            if self.position_duration is None:
                raise ValueError("position_duration is required when long_short_none is LONG/SHORT")
            if self.position_strategy is None:
                raise ValueError("position_strategy is required when long_short_none is LONG/SHORT")
        return self


class TimeframeObservation(BaseModel):
    timeframe: str

    regime: Literal["TREND", "RANGE", "BREAKOUT", "CHOP", "UNKNOWN"]
    trend_dir: Literal["UP", "DOWN", "NEUTRAL", "UNKNOWN"]
    vwap_state: Literal["ABOVE", "BELOW", "AROUND", "UNKNOWN"]
    macd_state: Literal[
        "BULLISH",
        "BEARISH",
        "CROSSING_UP",
        "CROSSING_DOWN",
        "FLAT",
        "UNKNOWN",
    ]

    key_levels: list[float]
    notes: str


class Pass1Observations(BaseModel):
    symbol: str
    timestamp_utc: datetime
    observations: list[TimeframeObservation]
    warnings: list[str] = Field(default_factory=list)


LiquidityBias = Literal["UP", "DOWN", "BALANCED", "UNKNOWN"]


class LiquidationHeatmapObservations(BaseModel):
    symbol: str
    timestamp_utc: datetime
    time_horizon_hours: int = Field(ge=1, le=168)
    liquidity_bias: LiquidityBias
    key_liquidity_levels: list[float]
    eta_summary: str
    notes: str
    warnings: list[str] = Field(default_factory=list)


class LLMRawEnvelope(BaseModel):
    provider: str
    model: str
    raw: Any
