from __future__ import annotations

from datetime import datetime

from chart_vision_common.models import LiquidationHeatmapObservations, Pass1Observations, TimeframeObservation, TradeProposal

from .base import VisionLLMProvider


class OpenAIStubProvider(VisionLLMProvider):
    async def pass1(self, *, symbol: str, timestamp_utc: datetime, images_by_tf: dict[str, bytes]):
        obs = []
        for tf in images_by_tf.keys():
            obs.append(
                TimeframeObservation(
                    timeframe=tf,
                    regime="UNKNOWN",
                    trend_dir="UNKNOWN",
                    vwap_state="UNKNOWN",
                    macd_state="UNKNOWN",
                    key_levels=[],
                    notes="openai stub",
                )
            )
        p1 = Pass1Observations(symbol=symbol, timestamp_utc=timestamp_utc, observations=obs, warnings=["stub provider"])
        return p1, {"stub": True}

    async def pass2(
        self,
        *,
        symbol: str,
        timestamp_utc: datetime,
        images_by_tf: dict[str, bytes],
        pass1: Pass1Observations,
        liquidation_heatmap: LiquidationHeatmapObservations | None = None,
    ):
        proposal = TradeProposal(
            position_id="stub",
            timestamp=timestamp_utc,
            long_short_none="NONE",
            target_price=None,
            stop_loss=None,
            leverage=None,
            margin_percent=None,
            entry_price_min=None,
            entry_price_max=None,
            entry_time_from=None,
            entry_time_to=None,
            exit_time_from=None,
            exit_time_to=None,
            position_duration=None,
            position_strategy=None,
            confidence=0.0,
            reason_entry="",
            reason_abstain="openai provider not implemented",
            rationale_tags=["STUB"],
        )
        return proposal, {"stub": True}

    async def pass_liquidation_heatmap(
        self,
        *,
        symbol: str,
        timestamp_utc: datetime,
        liquidation_heatmap_png: bytes,
        time_horizon_hours: int,
    ):
        obs = LiquidationHeatmapObservations(
            symbol=symbol,
            timestamp_utc=timestamp_utc,
            time_horizon_hours=time_horizon_hours,
            liquidity_bias="UNKNOWN",
            key_liquidity_levels=[],
            eta_summary="",
            notes="stub provider",
            warnings=["stub provider"],
        )
        return obs, {"stub": True}


class GeminiStubProvider(OpenAIStubProvider):
    pass
