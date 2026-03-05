from __future__ import annotations

import base64
import logging
from datetime import datetime

from anthropic import AsyncAnthropic, NotFoundError

logger = logging.getLogger(__name__)

from chart_vision_common.constants import TIMEFRAMES_ORDER
from chart_vision_common.models import LiquidationHeatmapObservations, Pass1Observations, TradeProposal

from .base import VisionLLMProvider
from .json_extract import extract_first_json_object
from .prompts import (
    PASS1_INSTRUCTIONS,
    PASS2_INSTRUCTIONS,
    format_liquidation_heatmap_pass_instructions,
    format_system_rulebook,
)


def _img_block(png_bytes: bytes) -> dict:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": b64},
    }


def _normalize_proposal_obj(raw_obj: object, *, timestamp_utc: datetime) -> dict:
    if not isinstance(raw_obj, dict):
        raise ValueError("Pass2 output must be a JSON object")

    obj = dict(raw_obj)

    # Defensive normalization: some model outputs emit nulls for required strings.
    if obj.get("reason_entry") is None:
        obj["reason_entry"] = ""
    if obj.get("reason_abstain") is None:
        obj["reason_abstain"] = ""
    if obj.get("rationale_tags") is None:
        obj["rationale_tags"] = []
    if obj.get("position_id") in (None, ""):
        obj["position_id"] = "auto"
    if obj.get("timestamp") in (None, ""):
        obj["timestamp"] = timestamp_utc.isoformat()
    
    # If long_short_none is missing, default to NONE (abstain)
    if obj.get("long_short_none") is None:
        logger.warning("Pass2 output missing long_short_none field, defaulting to NONE")
        obj["long_short_none"] = "NONE"
        if not obj.get("reason_abstain"):
            obj["reason_abstain"] = "Model output did not include trade direction"
    
    # Ensure new fields have defaults
    obj.setdefault("entry_price_min", None)
    obj.setdefault("entry_price_max", None)
    obj.setdefault("entry_time_from", None)
    obj.setdefault("entry_time_to", None)
    obj.setdefault("exit_time_from", None)
    obj.setdefault("exit_time_to", None)
    obj.setdefault("position_duration", None)
    obj.setdefault("position_strategy", None)

    return obj


def _normalize_liquidation_heatmap_obj(
    raw_obj: object,
    *,
    symbol: str,
    timestamp_utc: datetime,
    time_horizon_hours: int,
) -> dict:
    if not isinstance(raw_obj, dict):
        raise ValueError("Liquidation heatmap pass output must be a JSON object")

    obj = dict(raw_obj)
    obj.setdefault("symbol", symbol)
    obj.setdefault("timestamp_utc", timestamp_utc.isoformat())
    obj.setdefault("time_horizon_hours", time_horizon_hours)

    bias = str(obj.get("liquidity_bias") or "UNKNOWN").upper()
    if bias not in {"UP", "DOWN", "BALANCED", "UNKNOWN"}:
        bias = "UNKNOWN"
    obj["liquidity_bias"] = bias

    levels = obj.get("key_liquidity_levels")
    if not isinstance(levels, list):
        levels = []
    norm_levels: list[float] = []
    for lv in levels:
        if isinstance(lv, (int, float)):
            norm_levels.append(float(lv))
    obj["key_liquidity_levels"] = norm_levels

    warnings_val = obj.get("warnings")
    if warnings_val is None:
        obj["warnings"] = []
    elif isinstance(warnings_val, str):
        obj["warnings"] = [warnings_val] if warnings_val.strip() else []
    elif isinstance(warnings_val, list):
        obj["warnings"] = [str(w) for w in warnings_val if str(w).strip()]
    else:
        obj["warnings"] = []

    if obj.get("eta_summary") is None:
        obj["eta_summary"] = ""
    if obj.get("notes") is None:
        obj["notes"] = ""

    return obj


class ClaudeVisionProvider(VisionLLMProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model_pass1: str,
        model_pass2: str,
        model_fallbacks: list[str] | None = None,
        max_leverage: float = 10.0,
        max_margin_percent: float = 25.0,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model_pass1 = model_pass1
        self._model_pass2 = model_pass2
        self._model_fallbacks = model_fallbacks or []
        self._system_rulebook = format_system_rulebook(max_leverage, max_margin_percent)

    async def _create_with_fallback(self, *, model: str, max_tokens: int, temperature: float, system: str, messages: list[dict]) -> tuple[object, str]:
        """Returns (response, model_used)"""
        candidates: list[str] = []
        for m in [model, *self._model_fallbacks]:
            if m and m not in candidates:
                candidates.append(m)

        logger.info("Claude model candidates: %s", candidates)
        last_err: Exception | None = None
        for m in candidates:
            try:
                logger.info("Trying model: %s", m)
                resp = await self._client.messages.create(
                    model=m,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=messages,
                )
                logger.info("Success with model: %s", m)
                return resp, m
            except NotFoundError as e:
                logger.warning("Model not found: %s – %s", m, e)
                last_err = e
                continue

        if last_err:
            raise last_err
        raise RuntimeError("No candidate models configured for Claude provider")

    async def pass1(
        self, *, symbol: str, timestamp_utc: datetime, images_by_tf: dict[str, bytes]
    ) -> tuple[Pass1Observations, object]:
        tfs = [tf for tf in TIMEFRAMES_ORDER if tf in images_by_tf]

        # Claude best practice: images before text for better reliability
        content = []
        
        # First: all images with their timeframe labels
        for tf in tfs:
            content.append(_img_block(images_by_tf[tf]))
            content.append({"type": "text", "text": f"Timeframe: {tf}"})

        # Then: instructions
        content.append({"type": "text", "text": PASS1_INSTRUCTIONS})

        msg, model_used = await self._create_with_fallback(
            model=self._model_pass1,
            max_tokens=1800,
            temperature=0.2,
            system=self._system_rulebook,
            messages=[{"role": "user", "content": content}],
        )

        text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"])
        raw_obj = extract_first_json_object(text)

        # Defensive normalization for pass1 output
        if isinstance(raw_obj, dict):
            raw_obj.setdefault("symbol", symbol)
            
            # warnings must be a list, but model may return string or null
            warnings_val = raw_obj.get("warnings")
            if warnings_val is None:
                raw_obj["warnings"] = []
            elif isinstance(warnings_val, str):
                # Model returned string instead of list - wrap it or discard
                raw_obj["warnings"] = [warnings_val] if warnings_val.strip() else []
            elif not isinstance(warnings_val, list):
                raw_obj["warnings"] = []
            
            # Model may return non-datetime strings like "UNKNOWN" for timestamp_utc
            ts_val = raw_obj.get("timestamp_utc")
            if ts_val is None or (isinstance(ts_val, str) and len(ts_val) < 8):
                raw_obj["timestamp_utc"] = timestamp_utc.isoformat()
            
            # Normalize observations: convert old schema to new schema if needed
            observations = raw_obj.get("observations", [])
            if isinstance(observations, list):
                for obs in observations:
                    if isinstance(obs, dict):
                        # Convert old trend_or_range to new regime + trend_dir
                        if "trend_or_range" in obs and "regime" not in obs:
                            old_val = obs.pop("trend_or_range", "UNKNOWN")
                            if old_val == "UP":
                                obs["regime"] = "TREND"
                                obs["trend_dir"] = "UP"
                            elif old_val == "DOWN":
                                obs["regime"] = "TREND"
                                obs["trend_dir"] = "DOWN"
                            elif old_val == "RANGE":
                                obs["regime"] = "RANGE"
                                obs["trend_dir"] = "NEUTRAL"
                            else:
                                obs["regime"] = "UNKNOWN"
                                obs["trend_dir"] = "UNKNOWN"
                        
                        # Convert old vwap_relation to vwap_state
                        if "vwap_relation" in obs and "vwap_state" not in obs:
                            obs["vwap_state"] = obs.pop("vwap_relation", "UNKNOWN")
                        
                        # Ensure required fields exist
                        obs.setdefault("regime", "UNKNOWN")
                        obs.setdefault("trend_dir", "UNKNOWN")
                        obs.setdefault("vwap_state", "UNKNOWN")

        parsed = Pass1Observations.model_validate(raw_obj)
        return parsed, raw_obj

    async def pass_liquidation_heatmap(
        self,
        *,
        symbol: str,
        timestamp_utc: datetime,
        liquidation_heatmap_png: bytes,
        time_horizon_hours: int,
    ) -> tuple[LiquidationHeatmapObservations, object]:
        content = [
            _img_block(liquidation_heatmap_png),
            {
                "type": "text",
                "text": format_liquidation_heatmap_pass_instructions(time_horizon_hours),
            },
        ]

        msg, _model_used = await self._create_with_fallback(
            model=self._model_pass1,
            max_tokens=1200,
            temperature=0.2,
            system=self._system_rulebook,
            messages=[{"role": "user", "content": content}],
        )

        text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"])
        raw_obj = extract_first_json_object(text)
        normalized = _normalize_liquidation_heatmap_obj(
            raw_obj,
            symbol=symbol,
            timestamp_utc=timestamp_utc,
            time_horizon_hours=time_horizon_hours,
        )
        parsed = LiquidationHeatmapObservations.model_validate(normalized)
        return parsed, raw_obj

    async def pass2(
        self,
        *,
        symbol: str,
        timestamp_utc: datetime,
        images_by_tf: dict[str, bytes],
        pass1: Pass1Observations,
        liquidation_heatmap: LiquidationHeatmapObservations | None = None,
    ) -> tuple[TradeProposal, object]:
        tfs = [tf for tf in TIMEFRAMES_ORDER if tf in images_by_tf]

        # Claude best practice: images before text for better reliability
        content = []
        
        # First: all images with their timeframe labels
        for tf in tfs:
            content.append(_img_block(images_by_tf[tf]))
            content.append({"type": "text", "text": f"Timeframe: {tf}"})

        # Then: instructions and context
        content.append({"type": "text", "text": PASS2_INSTRUCTIONS})
        content.append(
            {
                "type": "text",
                "text": "Pass1 observations JSON:\n" + pass1.model_dump_json(indent=2),
            }
        )
        if liquidation_heatmap is not None:
            content.append(
                {
                    "type": "text",
                    "text": "Liquidation heatmap observations JSON:\n"
                    + liquidation_heatmap.model_dump_json(indent=2),
                }
            )

        msg, model_used = await self._create_with_fallback(
            model=self._model_pass2,
            max_tokens=1200,
            temperature=0.2,
            system=self._system_rulebook,
            messages=[{"role": "user", "content": content}],
        )

        text = "".join([b.text for b in msg.content if getattr(b, "type", None) == "text"])
        raw_obj = extract_first_json_object(text)
        normalized = _normalize_proposal_obj(raw_obj, timestamp_utc=timestamp_utc)
        normalized["model_used"] = model_used
        parsed = TradeProposal.model_validate(normalized)
        return parsed, raw_obj
