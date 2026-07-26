"""
Model routing per ADR-0004:
  - Fable 5 (MODEL_GATE): cheap high-cadence pre-filter + position checks
  - Opus 5 (MODEL_SYNTHESIS / MODEL_REFLECTION): entry synthesis + post-mortems

All prompts consume the numeric IndicatorSnapshot (ADR-0002) and emit strict
JSON. Behavioral contract (strategy-spec) is embedded in the system prompts;
hard risk limits are enforced in governor.py, never here.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

from .config import Settings
from .models import IndicatorSnapshot

_log = logging.getLogger("conductor.llm")

BEHAVIOR_CONTRACT = """
You are a disciplined human-like swing trader. Hard rules:
- You trade multi-timeframe confluence swing setups only: trend-pullback
  continuation, mean-reversion at strong levels, break-and-retest.
- NO scalping, no chasing extended moves, no trading without a clear
  invalidation level. Abstaining (NONE) is the most common correct output.
- Every LONG/SHORT must include: entry zone, stop_loss beyond invalidation,
  target_price, and honest confidence in [0,1].
- Higher timeframes set bias; lower timeframes time the entry. If timeframes
  conflict with no clean invalidation: NONE.
""".strip()

GATE_INSTRUCTIONS = """
Task: cheap pre-filter. Given the numeric multi-timeframe snapshot, decide if
there is a PLAUSIBLE swing setup worth deeper analysis. Do not construct the
full trade. Err toward rejecting; deep analysis is expensive.

Return strict JSON only:
{"plausible": true|false, "setup_hint": "string", "reject_reason": "string"}
""".strip()

SYNTHESIS_INSTRUCTIONS = """
Task: synthesize ONE trade proposal or NONE from the numeric snapshot.

Return strict JSON with ALL fields:
{
  "position_id": "string",
  "timestamp": "ISO8601",
  "long_short_none": "LONG | SHORT | NONE",
  "target_price": number|null,
  "stop_loss": number|null,
  "leverage": number|null,
  "margin_percent": number|null,
  "entry_price_min": number|null,
  "entry_price_max": number|null,
  "entry_time_from": "ISO8601"|null,
  "entry_time_to": "ISO8601"|null,
  "exit_time_from": "ISO8601"|null,
  "exit_time_to": "ISO8601"|null,
  "position_duration": "HOUR | DAY | SWING" | null,
  "position_strategy": "ADD_UP | DCA | CONTRARIAN | HOLD" | null,
  "confidence": number,
  "reason_entry": "string",
  "reason_abstain": "string",
  "rationale_tags": ["string"]
}

Notes:
- position_strategy SCALP is forbidden.
- If NONE: target_price, stop_loss, leverage, margin_percent must be null and
  reason_abstain non-empty.
- Entry zone must reference visible key_levels/VWAP from the snapshot.
""".strip()

REFLECTION_INSTRUCTIONS = """
Task: post-trade reflection. Given the original snapshot, the proposal, and the
trade outcome, write an honest post-mortem.

Return strict JSON:
{
  "thesis_correct": true|false|null,
  "entry_quality": "GOOD | EARLY | LATE | BAD",
  "stop_quality": "GOOD | TOO_TIGHT | TOO_WIDE",
  "size_quality": "GOOD | TOO_BIG | TOO_SMALL",
  "what_happened": "string",
  "lesson": "string",
  "repeat_mistake": true|false,
  "tags": ["string"]
}
""".strip()


def _client(settings: Settings) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _extract_json(text: str) -> dict[str, Any]:
    """Tolerant strict-JSON extraction (handles accidental code fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {text[:200]}")
    return json.loads(text[start : end + 1])


def _call(
    settings: Settings, *, model: str, system: str, user: str, max_tokens: int
) -> dict[str, Any]:
    """
    Call the model and parse strict JSON. Retries once with a 4x token budget
    when the output is truncated (stop_reason=max_tokens) or empty — reasoning
    models can spend the whole budget thinking before emitting any text.
    """
    client = _client(settings)
    tokens = max_tokens
    last_err: Exception | None = None
    for attempt in range(2):
        resp = client.messages.create(
            model=model,
            max_tokens=tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        truncated = getattr(resp, "stop_reason", None) == "max_tokens"
        try:
            return _extract_json(text)
        except Exception as exc:
            last_err = exc
            if attempt == 0 and (truncated or not text.strip()):
                _log.warning(
                    "%s output %s (stop_reason=%s, %d tokens); retrying with %d",
                    model,
                    "truncated" if truncated else "empty",
                    getattr(resp, "stop_reason", None),
                    tokens,
                    tokens * 4,
                )
                tokens *= 4
                continue
            break
    raise ValueError(f"model output unparseable after retry: {last_err}")


def gate(settings: Settings, snapshot: IndicatorSnapshot) -> dict[str, Any]:
    """Fable pre-filter: {'plausible': bool, 'setup_hint': str, 'reject_reason': str}."""
    user = (
        f"{GATE_INSTRUCTIONS}\n\nSnapshot:\n"
        f"{snapshot.model_dump_json(indent=1)}"
    )
    try:
        return _call(
            settings,
            model=settings.model_gate,
            system=BEHAVIOR_CONTRACT,
            user=user,
            max_tokens=1000,
        )
    except Exception as exc:  # gate failure = no trade, never a default-pass
        _log.warning("gate failed for %s: %s", snapshot.symbol, exc)
        return {"plausible": False, "setup_hint": "", "reject_reason": f"gate_error: {exc}"}


def synthesize(
    settings: Settings,
    snapshot: IndicatorSnapshot,
    recent_outcomes: str | None = None,
) -> dict[str, Any]:
    """Opus Pass-2: returns a TradeProposal-shaped dict (may be NONE).

    recent_outcomes: optional compact history of this symbol's recent closed
    trades (INCLUDE_RECENT_OUTCOMES config, off by default). Context only —
    it must inform, not dictate.
    """
    context = ""
    if recent_outcomes:
        context = (
            "\n\nRecent closed trades on this symbol (context only — judge the "
            f"current setup on its own merits): {recent_outcomes}"
        )
    user = (
        f"{SYNTHESIS_INSTRUCTIONS}\n\n"
        f"Caps (hard, enforced downstream): max leverage {settings.max_leverage}, "
        f"max margin percent {settings.max_margin_percent}.{context}\n\nSnapshot:\n"
        f"{snapshot.model_dump_json(indent=1)}"
    )
    return _call(
        settings,
        model=settings.model_synthesis,
        system=BEHAVIOR_CONTRACT,
        user=user,
        max_tokens=1500,
    )


def reflect(
    settings: Settings,
    *,
    snapshot: dict[str, Any] | None,
    proposal: dict[str, Any],
    trade_outcome: dict[str, Any],
) -> dict[str, Any]:
    """Opus post-mortem on a closed position."""
    user = (
        f"{REFLECTION_INSTRUCTIONS}\n\nOriginal snapshot:\n{json.dumps(snapshot, default=str)}\n\n"
        f"Proposal:\n{json.dumps(proposal, default=str)}\n\n"
        f"Outcome:\n{json.dumps(trade_outcome, default=str)}"
    )
    return _call(
        settings,
        model=settings.model_reflection,
        system=BEHAVIOR_CONTRACT,
        user=user,
        max_tokens=800,
    )
