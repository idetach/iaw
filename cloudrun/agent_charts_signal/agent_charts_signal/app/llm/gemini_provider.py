from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx

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

logger = logging.getLogger(__name__)

GEMINI_REQUEST_TIMEOUT_SECONDS = 120.0
PASS1_MAX_TOKENS = 7200
PASS1_RETRY_MAX_TOKENS = 8800
LIQUIDATION_HEATMAP_MAX_TOKENS = 4800
LIQUIDATION_HEATMAP_RETRY_MAX_TOKENS = 6400
PASS2_MAX_TOKENS = 5600
PASS2_RETRY_MAX_TOKENS = 7200

GEMINI_MODEL_ALIASES: dict[str, str] = {
    # Gemini 3 family in Developer API is currently served as preview IDs.
    "gemini-3.1-pro": "gemini-3.1-pro-preview",
    "gemini-3-pro": "gemini-3-pro-preview",
    "gemini-3-flash": "gemini-3-flash-preview",
}


def _img_part(png_bytes: bytes) -> dict[str, Any]:
    return {
        "inline_data": {
            "mime_type": "image/png",
            "data": base64.b64encode(png_bytes).decode("ascii"),
        }
    }


def _text_part(text: str) -> dict[str, str]:
    return {"text": text}


def _coerce_optional_datetime(value: object, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Pass2 output had invalid %s datetime %r; dropping field", field_name, value)
        return None
    return normalized


def _coerce_required_datetime(value: object, *, field_name: str, fallback_iso: str) -> str:
    coerced = _coerce_optional_datetime(value, field_name=field_name)
    if coerced is None:
        logger.warning("Pass2 output missing/invalid %s; using fallback timestamp", field_name)
        return fallback_iso
    return coerced


def _normalize_proposal_obj(raw_obj: object, *, timestamp_utc: datetime) -> dict:
    if not isinstance(raw_obj, dict):
        raise ValueError("Pass2 output must be a JSON object")

    obj = dict(raw_obj)

    if obj.get("reason_entry") is None:
        obj["reason_entry"] = ""
    if obj.get("reason_abstain") is None:
        obj["reason_abstain"] = ""
    if obj.get("rationale_tags") is None:
        obj["rationale_tags"] = []
    if obj.get("position_id") in (None, ""):
        obj["position_id"] = "auto"
    obj["timestamp"] = _coerce_required_datetime(
        obj.get("timestamp"),
        field_name="timestamp",
        fallback_iso=timestamp_utc.isoformat(),
    )

    if obj.get("long_short_none") is None:
        logger.warning("Pass2 output missing long_short_none field, defaulting to NONE")
        obj["long_short_none"] = "NONE"
        if not obj.get("reason_abstain"):
            obj["reason_abstain"] = "Model output did not include trade direction"

    obj.setdefault("entry_price_min", None)
    obj.setdefault("entry_price_max", None)
    obj.setdefault("entry_time_from", None)
    obj.setdefault("entry_time_to", None)
    obj.setdefault("exit_time_from", None)
    obj.setdefault("exit_time_to", None)
    obj.setdefault("position_duration", None)
    obj.setdefault("position_strategy", None)

    obj["entry_time_from"] = _coerce_optional_datetime(obj.get("entry_time_from"), field_name="entry_time_from")
    obj["entry_time_to"] = _coerce_optional_datetime(obj.get("entry_time_to"), field_name="entry_time_to")
    obj["exit_time_from"] = _coerce_optional_datetime(obj.get("exit_time_from"), field_name="exit_time_from")
    obj["exit_time_to"] = _coerce_optional_datetime(obj.get("exit_time_to"), field_name="exit_time_to")

    return obj


def _normalize_regime_value(v: object) -> str:
    s = str(v or "UNKNOWN").strip().upper()
    mapping = {
        "UPTREND": "TREND",
        "DOWNTREND": "TREND",
        "TRENDING": "TREND",
        "BULLISH": "TREND",
        "BEARISH": "TREND",
        "SIDEWAYS": "RANGE",
        "CONSOLIDATING": "RANGE",
        "CONSOLIDATION": "RANGE",
        "FLAT": "RANGE",
        "BREAKOUT_UP": "BREAKOUT",
        "BREAKOUT_DOWN": "BREAKOUT",
        "CHOPPY": "CHOP",
        "CHOPPING": "CHOP",
        "NEUTRAL": "UNKNOWN",
    }
    s = mapping.get(s, s)
    if s not in {"TREND", "RANGE", "BREAKOUT", "CHOP", "UNKNOWN"}:
        return "UNKNOWN"
    return s


def _normalize_trend_dir_value(v: object) -> str:
    s = str(v or "UNKNOWN").strip().upper()
    mapping = {
        "BULLISH": "UP",
        "UPTREND": "UP",
        "LONG": "UP",
        "BEARISH": "DOWN",
        "DOWNTREND": "DOWN",
        "SHORT": "DOWN",
        "SIDEWAYS": "NEUTRAL",
        "RANGE": "NEUTRAL",
        "FLAT": "NEUTRAL",
    }
    s = mapping.get(s, s)
    if s not in {"UP", "DOWN", "NEUTRAL", "UNKNOWN"}:
        return "UNKNOWN"
    return s


def _normalize_vwap_state_value(v: object) -> str:
    s = str(v or "UNKNOWN").strip().upper()
    mapping = {
        "OVER": "ABOVE",
        "UNDER": "BELOW",
        "NEAR": "AROUND",
        "AT": "AROUND",
    }
    s = mapping.get(s, s)
    if s not in {"ABOVE", "BELOW", "AROUND", "UNKNOWN"}:
        return "UNKNOWN"
    return s


def _normalize_macd_state_value(v: object) -> str:
    s = str(v or "UNKNOWN").strip().upper()
    mapping = {
        "UP": "BULLISH",
        "DOWN": "BEARISH",
        "CROSS_UP": "CROSSING_UP",
        "CROSS_DOWN": "CROSSING_DOWN",
    }
    s = mapping.get(s, s)
    if s not in {
        "BULLISH",
        "BEARISH",
        "CROSSING_UP",
        "CROSSING_DOWN",
        "FLAT",
        "UNKNOWN",
    }:
        return "UNKNOWN"
    return s


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
    obj["key_liquidity_levels"] = [float(v) for v in levels if isinstance(v, (int, float))]

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


def _is_temperature_unsupported(error_body: Any) -> bool:
    if not isinstance(error_body, dict):
        return False
    msg = str(error_body.get("error", {}).get("message", "")).lower()
    status = str(error_body.get("error", {}).get("status", "")).lower()
    return "temperature" in msg and ("default" in msg or "unsupported" in msg or "invalid" in msg or "bad request" in status)


def _extract_text_from_response(resp_obj: dict[str, Any]) -> str:
    texts: list[str] = []
    candidates = resp_obj.get("candidates")
    if isinstance(candidates, list):
        for c in candidates:
            if not isinstance(c, dict):
                continue
            content = c.get("content")
            if not isinstance(content, dict):
                continue
            parts = content.get("parts")
            if not isinstance(parts, list):
                continue
            for p in parts:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    texts.append(p["text"])
    if not texts:
        logger.warning(
            "Gemini response had no text parts. promptFeedback=%s, candidates=%s",
            resp_obj.get("promptFeedback"),
            len(resp_obj.get("candidates", [])) if isinstance(resp_obj.get("candidates"), list) else "n/a",
        )
    return "".join(texts)


def _extract_first_json_value(text: str) -> Any:
    try:
        return extract_first_json_object(text)
    except ValueError:
        pass

    stripped = text.strip()

    # Handle markdown fenced blocks first.
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped).strip()

    # Try full-text JSON parse (supports object or array).
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass

    # Last resort: try decoding from the first object/array start positions.
    decoder = json.JSONDecoder()
    candidate_starts = [i for i, ch in enumerate(stripped) if ch in "[{"]
    for idx in candidate_starts:
        try:
            obj, _end = decoder.raw_decode(stripped[idx:])
            if isinstance(obj, (dict, list)):
                return obj
        except json.JSONDecodeError:
            continue

    preview = stripped[:280].replace("\n", "\\n")
    raise ValueError(f"No JSON found in Gemini output. Preview: {preview}")


class GeminiVisionProvider(VisionLLMProvider):
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
        self._api_key = api_key
        self._model_pass1 = model_pass1
        self._model_pass2 = model_pass2
        self._model_fallbacks = model_fallbacks or []
        self._system_rulebook = format_system_rulebook(max_leverage, max_margin_percent)
        self._unavailable_models: set[str] = set()
        self._timeout_deprioritized_models: set[str] = set()

    def _resolve_model_name(self, model: str) -> str:
        return GEMINI_MODEL_ALIASES.get(model, model)

    async def _create_with_fallback(
        self,
        *,
        model: str,
        max_tokens: int,
        temperature: float,
        user_parts: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        preferred_candidates: list[str] = []
        deprioritized_candidates: list[str] = []
        for m in [model, *self._model_fallbacks]:
            resolved = self._resolve_model_name(m)
            if not resolved or resolved in self._unavailable_models:
                continue
            if resolved in preferred_candidates or resolved in deprioritized_candidates:
                continue
            if resolved in self._timeout_deprioritized_models:
                deprioritized_candidates.append(resolved)
            else:
                preferred_candidates.append(resolved)

        candidates = [*preferred_candidates, *deprioritized_candidates]

        logger.info("Gemini model candidates: %s", candidates)
        last_err: Exception | None = None

        async with httpx.AsyncClient(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS) as client:
            for m in candidates:
                try:
                    logger.info("Trying model: %s", m)
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"

                    def _payload(include_temperature: bool) -> dict[str, Any]:
                        generation_config: dict[str, Any] = {
                            "maxOutputTokens": max_tokens,
                            "responseMimeType": "application/json",
                        }
                        if include_temperature:
                            generation_config["temperature"] = temperature

                        return {
                            "system_instruction": {
                                "parts": [_text_part(self._system_rulebook)],
                            },
                            "contents": [
                                {
                                    "role": "user",
                                    "parts": user_parts,
                                }
                            ],
                            "generationConfig": generation_config,
                        }

                    resp = await client.post(url, params={"key": self._api_key}, json=_payload(include_temperature=True))
                    if resp.status_code >= 400:
                        body: Any
                        try:
                            body = resp.json()
                        except Exception:
                            body = {"error": {"message": resp.text}}

                        if resp.status_code == 400 and _is_temperature_unsupported(body):
                            logger.info(
                                "Model %s rejected custom temperature=%s; retrying with model default temperature",
                                m,
                                temperature,
                            )
                            resp = await client.post(url, params={"key": self._api_key}, json=_payload(include_temperature=False))

                    resp.raise_for_status()
                    out = resp.json()

                    # Some Gemini responses can return no text parts (e.g., blocked/empty candidates).
                    # Treat that as candidate failure so we can try fallback models.
                    out_text = _extract_text_from_response(out)
                    if not out_text.strip():
                        prompt_feedback = out.get("promptFeedback")
                        candidates = out.get("candidates")
                        finish_reasons: list[str] = []
                        if isinstance(candidates, list):
                            for c in candidates:
                                if isinstance(c, dict) and c.get("finishReason"):
                                    finish_reasons.append(str(c.get("finishReason")))
                        raise ValueError(
                            f"Gemini returned empty text output (promptFeedback={prompt_feedback}, finishReasons={finish_reasons})"
                        )

                    logger.info("Success with model: %s", m)
                    self._timeout_deprioritized_models.discard(m)
                    return out, m
                except httpx.ReadTimeout as e:
                    logger.warning("Model request failed: %s - ReadTimeout (%r)", m, e)
                    self._timeout_deprioritized_models.add(m)
                    last_err = e
                    continue
                except httpx.HTTPStatusError as e:
                    logger.warning("Model request failed: %s - HTTP %s", m, e.response.status_code)
                    if e.response.status_code == 404:
                        self._unavailable_models.add(m)
                        logger.warning(
                            "Marking Gemini model as unavailable for this process: %s",
                            m,
                        )
                    last_err = e
                    continue
                except Exception as e:
                    logger.warning("Model request failed: %s - %s (%r)", m, type(e).__name__, e)
                    last_err = e
                    continue

        if last_err:
            raise last_err
        raise RuntimeError("No candidate models configured for Gemini provider")

    async def pass1(
        self, *, symbol: str, timestamp_utc: datetime, images_by_tf: dict[str, bytes]
    ) -> tuple[Pass1Observations, object]:
        tfs = [tf for tf in TIMEFRAMES_ORDER if tf in images_by_tf]

        user_parts: list[dict[str, Any]] = []
        for tf in tfs:
            user_parts.append(_img_part(images_by_tf[tf]))
            user_parts.append(_text_part(f"Timeframe: {tf}"))
        user_parts.append(_text_part(PASS1_INSTRUCTIONS))

        msg_obj, model_used = await self._create_with_fallback(
            model=self._model_pass1,
            max_tokens=PASS1_MAX_TOKENS,
            temperature=0.2,
            user_parts=user_parts,
        )

        text = _extract_text_from_response(msg_obj)
        raw_obj = _extract_first_json_value(text)

        # Gemini may return either the full Pass1 envelope, a single observation object,
        # or an array of observations. Coerce into the expected Pass1 envelope.
        if isinstance(raw_obj, list):
            raw_obj = {
                "symbol": symbol,
                "timestamp_utc": timestamp_utc.isoformat(),
                "observations": raw_obj,
                "warnings": [],
            }
        elif isinstance(raw_obj, dict) and "observations" not in raw_obj:
            looks_like_observation = any(
                k in raw_obj
                for k in ("timeframe", "regime", "trend_dir", "vwap_state", "macd_state", "key_levels", "notes")
            )
            if looks_like_observation:
                raw_obj = {
                    "symbol": symbol,
                    "timestamp_utc": timestamp_utc.isoformat(),
                    "observations": [raw_obj],
                    "warnings": [],
                }

        if isinstance(raw_obj, dict):
            raw_obj.setdefault("symbol", symbol)

            warnings_val = raw_obj.get("warnings")
            if warnings_val is None:
                raw_obj["warnings"] = []
            elif isinstance(warnings_val, str):
                raw_obj["warnings"] = [warnings_val] if warnings_val.strip() else []
            elif not isinstance(warnings_val, list):
                raw_obj["warnings"] = []

            ts_val = raw_obj.get("timestamp_utc")
            if ts_val is None or (isinstance(ts_val, str) and len(ts_val) < 8):
                raw_obj["timestamp_utc"] = timestamp_utc.isoformat()

            observations = raw_obj.get("observations", [])
            if isinstance(observations, dict):
                observations = [observations]
                raw_obj["observations"] = observations
            elif not isinstance(observations, list):
                observations = []
                raw_obj["observations"] = observations

            # Drop malformed observation items (e.g. bare numbers from key_levels leakage).
            if isinstance(observations, list):
                dict_observations = [obs for obs in observations if isinstance(obs, dict)]
                if len(dict_observations) != len(observations):
                    raw_obj["warnings"].append("Dropped malformed non-object entries from observations")
                observations = dict_observations
                raw_obj["observations"] = observations

            if not observations:
                raw_obj["warnings"].append("Pass1 output had no valid observations; using UNKNOWN placeholders")
                observations = [
                    {
                        "timeframe": tf,
                        "regime": "UNKNOWN",
                        "trend_dir": "UNKNOWN",
                        "vwap_state": "UNKNOWN",
                        "macd_state": "UNKNOWN",
                        "key_levels": [],
                        "notes": "Model output was malformed; placeholder observation generated.",
                    }
                    for tf in tfs
                ]
                raw_obj["observations"] = observations

            if isinstance(observations, list):
                for obs in observations:
                    if not isinstance(obs, dict):
                        continue
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

                    if "vwap_relation" in obs and "vwap_state" not in obs:
                        obs["vwap_state"] = obs.pop("vwap_relation", "UNKNOWN")

                    raw_regime = str(obs.get("regime") or "").upper()
                    obs["regime"] = _normalize_regime_value(obs.get("regime"))
                    obs["trend_dir"] = _normalize_trend_dir_value(obs.get("trend_dir"))
                    obs["vwap_state"] = _normalize_vwap_state_value(obs.get("vwap_state"))
                    obs["macd_state"] = _normalize_macd_state_value(obs.get("macd_state"))

                    if obs["regime"] == "TREND" and obs["trend_dir"] == "UNKNOWN":
                        # Infer direction from common raw regime tokens when available.
                        if "UP" in raw_regime or "BULL" in raw_regime:
                            obs["trend_dir"] = "UP"
                        elif "DOWN" in raw_regime or "BEAR" in raw_regime:
                            obs["trend_dir"] = "DOWN"

                    obs.setdefault("regime", "UNKNOWN")
                    obs.setdefault("trend_dir", "UNKNOWN")
                    obs.setdefault("vwap_state", "UNKNOWN")

            if isinstance(observations, list):
                obs_by_tf: dict[str, dict[str, Any]] = {}
                for obs in observations:
                    if not isinstance(obs, dict):
                        continue
                    tf_val = str(obs.get("timeframe") or "").strip().lower()
                    if tf_val in tfs and tf_val not in obs_by_tf:
                        obs_by_tf[tf_val] = obs

                completed_observations: list[dict[str, Any]] = []
                for tf in tfs:
                    obs = obs_by_tf.get(tf)
                    if obs is None:
                        obs = {
                            "timeframe": tf,
                            "regime": "UNKNOWN",
                            "trend_dir": "UNKNOWN",
                            "vwap_state": "UNKNOWN",
                            "macd_state": "UNKNOWN",
                            "key_levels": [],
                            "notes": "Model output missing timeframe; placeholder observation generated.",
                        }
                    else:
                        obs["timeframe"] = tf
                    completed_observations.append(obs)

                raw_obj["observations"] = completed_observations

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
        user_parts: list[dict[str, Any]] = [
            _img_part(liquidation_heatmap_png),
            _text_part(format_liquidation_heatmap_pass_instructions(time_horizon_hours)),
        ]

        msg_obj, _model_used = await self._create_with_fallback(
            model=self._model_pass1,
            max_tokens=LIQUIDATION_HEATMAP_MAX_TOKENS,
            temperature=0.2,
            user_parts=user_parts,
        )

        text = _extract_text_from_response(msg_obj)
        raw_obj = _extract_first_json_value(text)

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

        user_parts: list[dict[str, Any]] = []
        for tf in tfs:
            user_parts.append(_img_part(images_by_tf[tf]))
            user_parts.append(_text_part(f"Timeframe: {tf}"))
        user_parts.append(_text_part(PASS2_INSTRUCTIONS))
        user_parts.append(_text_part("Pass1 observations JSON:\n" + pass1.model_dump_json(indent=2)))
        if liquidation_heatmap is not None:
            user_parts.append(
                _text_part(
                    "Liquidation heatmap observations JSON:\n"
                    + liquidation_heatmap.model_dump_json(indent=2)
                )
            )

        msg_obj, model_used = await self._create_with_fallback(
            model=self._model_pass2,
            max_tokens=PASS2_MAX_TOKENS,
            temperature=0.2,
            user_parts=user_parts,
        )

        text = _extract_text_from_response(msg_obj)
        raw_obj = _extract_first_json_value(text)

        normalized = _normalize_proposal_obj(raw_obj, timestamp_utc=timestamp_utc)
        normalized["model_used"] = model_used
        parsed = TradeProposal.model_validate(normalized)
        return parsed, raw_obj
