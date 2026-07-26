"""
Risk Governor — code-enforced portfolio risk layer (risk-governor-spec).

Every rule here is deterministic code. Nothing in this module calls an LLM.
Sizing is RISK-BASED: qty = (equity * risk_fraction) / stop_distance,
then clamped by leverage/margin caps. Breakers only ever reduce activity.
"""
from __future__ import annotations

import logging
from typing import Any

from .config import Settings
from .models import GovernorDecision, PortfolioState

_log = logging.getLogger("conductor.governor")


def evaluate(
    *,
    settings: Settings,
    proposal: dict[str, Any],
    portfolio: PortfolioState,
    symbol: str,
) -> GovernorDecision:
    """Gate a TradeProposal-shaped dict against portfolio rules and size it."""
    audit: dict[str, Any] = {"symbol": symbol}

    # --- hard gates, cheapest first ----------------------------------------
    if not settings.loop_enabled:
        return _reject("loop_disabled", audit)

    equity = portfolio.equity_usdt
    if equity <= 0:
        return _reject("invalid_proposal", audit, "equity unavailable or zero")

    if portfolio.realized_pnl_today_usdt <= -abs(settings.daily_loss_breaker_fraction * equity):
        return _reject("breaker_daily", audit)

    if portfolio.realized_pnl_week_usdt <= -abs(settings.weekly_loss_breaker_fraction * equity):
        return _reject("breaker_weekly", audit)

    direction = proposal.get("long_short_none", "NONE")
    if direction not in ("LONG", "SHORT"):
        return _reject("invalid_proposal", audit, "direction is NONE")

    confidence = float(proposal.get("confidence") or 0.0)
    audit["confidence"] = confidence
    if confidence < settings.min_confidence:
        return _reject("low_confidence", audit)

    if symbol in portfolio.symbols_on_cooldown:
        return _reject("cooldown", audit)

    # Resting entry orders are claims on future exposure — they occupy slots.
    slots_used = len(portfolio.open_positions) + len(portfolio.open_orders)
    if slots_used >= settings.max_concurrent_positions:
        audit["slots"] = f"{len(portfolio.open_positions)} positions + {len(portfolio.open_orders)} resting orders"
        return _reject("too_many_positions", audit)

    entry = _entry_price(proposal)
    stop = _f(proposal.get("stop_loss"))
    if entry is None or stop is None:
        return _reject("no_stop", audit, "entry or stop missing")
    stop_distance = abs(entry - stop)
    if stop_distance <= 0:
        return _reject("no_stop", audit, "zero stop distance")
    if (direction == "LONG" and stop >= entry) or (direction == "SHORT" and stop <= entry):
        return _reject("invalid_proposal", audit, "stop on wrong side of entry")

    # --- risk-based sizing --------------------------------------------------
    risk_usdt = equity * settings.risk_fraction
    qty = risk_usdt / stop_distance
    audit.update(
        {
            "entry": entry,
            "stop": stop,
            "stop_distance": stop_distance,
            "risk_usdt": round(risk_usdt, 4),
            "raw_qty": qty,
        }
    )

    # Aggregate open-risk cap
    max_open_risk = equity * settings.max_aggregate_open_risk
    if portfolio.open_risk_usdt + risk_usdt > max_open_risk:
        return _reject("aggregate_risk_cap", audit)

    # Leverage / margin clamps
    leverage = min(float(proposal.get("leverage") or 1.0), settings.max_leverage)
    leverage = max(leverage, 1.0)
    notional = qty * entry
    margin_needed = notional / leverage
    max_margin = equity * (settings.max_margin_percent / 100.0)

    resized = False
    if margin_needed > max_margin:
        scale = max_margin / margin_needed
        qty *= scale
        margin_needed = max_margin
        resized = True

    if portfolio.total_margin_used_usdt + margin_needed > equity * settings.max_total_margin_fraction:
        headroom = equity * settings.max_total_margin_fraction - portfolio.total_margin_used_usdt
        if headroom <= 0:
            return _reject("margin_cap", audit)
        scale = headroom / margin_needed
        qty *= scale
        margin_needed = headroom
        resized = True

    if qty <= 0:
        return _reject("risk_cap", audit, "size collapsed to zero after clamps")

    audit.update(
        {
            "final_qty": qty,
            "leverage": leverage,
            "margin_needed": round(margin_needed, 4),
            "notional": round(qty * entry, 4),
        }
    )

    decision = GovernorDecision(
        action="RESIZE" if resized else "APPROVE",
        qty=qty,
        leverage=leverage,
        reasons=["sized by risk_fraction of equity at stop distance"]
        + (["clamped by margin caps"] if resized else []),
        audit=audit,
    )
    _log.info("governor %s %s qty=%.8f audit=%s", decision.action, symbol, qty, audit)
    return decision


def _reject(reason: str, audit: dict[str, Any], note: str | None = None) -> GovernorDecision:
    if note:
        audit["note"] = note
    _log.info("governor REJECT %s audit=%s", reason, audit)
    return GovernorDecision(action="REJECT", reject_reason=reason, audit=audit)  # type: ignore[arg-type]


def _entry_price(proposal: dict[str, Any]) -> float | None:
    lo = _f(proposal.get("entry_price_min"))
    hi = _f(proposal.get("entry_price_max"))
    if lo is not None and hi is not None:
        return (lo + hi) / 2.0
    return lo if lo is not None else hi


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
