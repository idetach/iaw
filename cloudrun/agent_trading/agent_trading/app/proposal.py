from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt_price(v: float, precision: int = 8) -> str:
    """Format a price removing trailing zeros."""
    return f"{v:.{precision}f}".rstrip("0").rstrip(".")


def proposal_to_order_params(
    *,
    proposal: dict[str, Any],
    symbol: str,
    qty: str,
    order_type: str = "Limit",
    position_idx: int = 0,
) -> dict[str, Any]:
    """
    Map a proposal_validated dict → bybit_trading POST /v1/trade/order body.

    Raises HTTPException(422) if the proposal direction is NONE.
    """
    direction = proposal.get("long_short_none", "NONE")
    if direction == "NONE":
        raise HTTPException(
            status_code=422,
            detail="Proposal direction is NONE — no trade to execute",
        )

    side = "Buy" if direction == "LONG" else "Sell"

    entry_min = _safe_float(proposal.get("entry_price_min"))
    entry_max = _safe_float(proposal.get("entry_price_max"))
    target_price = _safe_float(proposal.get("target_price"))
    stop_loss = _safe_float(proposal.get("stop_loss"))

    resolved_order_type = order_type
    price: str | None = None

    if resolved_order_type == "Limit":
        if entry_min is not None and entry_max is not None:
            mid = (entry_min + entry_max) / 2
            price = _fmt_price(mid)
        elif entry_min is not None:
            price = _fmt_price(entry_min)
        elif entry_max is not None:
            price = _fmt_price(entry_max)
        else:
            resolved_order_type = "Market"

    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "orderType": resolved_order_type,
        "qty": qty,
        "positionIdx": position_idx,
    }

    if resolved_order_type == "Limit" and price:
        params["price"] = price

    if stop_loss is not None:
        params["stopLoss"] = _fmt_price(stop_loss)
        params["slTriggerBy"] = "MarkPrice"

    if target_price is not None:
        params["takeProfit"] = _fmt_price(target_price)
        params["tpTriggerBy"] = "MarkPrice"

    return params


def calculate_qty(
    *,
    balance_usdt: float,
    margin_percent: float,
    leverage: float,
    entry_price: float,
    qty_precision: int = 3,
) -> str:
    """
    Derive order quantity from wallet balance and proposal sizing fields.

      qty = (balance × margin_percent% × leverage) / entry_price
    """
    if balance_usdt <= 0:
        raise HTTPException(status_code=422, detail="Wallet balance is zero or negative")
    if margin_percent <= 0 or margin_percent > 100:
        raise HTTPException(status_code=422, detail=f"Invalid margin_percent: {margin_percent}")
    if leverage <= 0:
        raise HTTPException(status_code=422, detail=f"Invalid leverage: {leverage}")
    if entry_price <= 0:
        raise HTTPException(status_code=422, detail=f"Invalid entry_price: {entry_price}")

    margin_usdt = balance_usdt * (margin_percent / 100.0)
    position_usdt = margin_usdt * leverage
    qty = position_usdt / entry_price
    return str(round(qty, qty_precision))


def snap_qty_to_step(qty: float, qty_step: str) -> str:
    """
    Round qty DOWN to the nearest multiple of qty_step.

    Bybit rejects orders whose qty doesn't align with lotSizeFilter.qtyStep.
    Examples:
      snap_qty_to_step(8.182, "1")    → "8"
      snap_qty_to_step(8.182, "0.1")  → "8.1"
      snap_qty_to_step(8.182, "0.01") → "8.18"
    """
    try:
        step = float(qty_step)
    except (TypeError, ValueError):
        return str(qty)
    if step <= 0:
        return str(qty)
    snapped = int(qty / step) * step
    # figure out decimal places from step string to avoid float repr issues
    if "." in qty_step:
        decimals = len(qty_step.rstrip("0").split(".")[1])
    else:
        decimals = 0
    return f"{snapped:.{decimals}f}"


def ensure_min_notional(
    *,
    qty: float,
    price: float,
    min_notional: float,
    qty_step: str,
    buffer: float = 0.10,
) -> str:
    """
    If qty × price is below min_notional, ceil qty up to meet (min_notional × (1+buffer)).

    Uses ceiling division so the result is always ≥ the target, snapped to qty_step.
    Example: qty=8.1, price=0.22, min_notional=5, buffer=0.10
      required_value = 5 × 1.10 = 5.5 USDT
      min_qty = 5.5 / 0.22 = 25.0
      step=0.1 → ceil(25.0 / 0.1) × 0.1 = 25.0 → "25.0"
    """
    if min_notional <= 0 or price <= 0:
        return snap_qty_to_step(qty, qty_step)

    required_value = min_notional * (1.0 + buffer)
    if qty * price >= required_value:
        return snap_qty_to_step(qty, qty_step)

    min_qty = required_value / price
    try:
        step = float(qty_step)
    except (TypeError, ValueError):
        step = 0.0

    if step > 0:
        bumped = math.ceil(min_qty / step) * step
    else:
        bumped = min_qty

    if "." in qty_step:
        decimals = len(qty_step.rstrip("0").split(".")[1])
    else:
        decimals = 0
    return f"{bumped:.{decimals}f}"


def entry_price_from_proposal(proposal: dict[str, Any]) -> float | None:
    """Return the midpoint entry price from proposal fields, or None."""
    entry_min = _safe_float(proposal.get("entry_price_min"))
    entry_max = _safe_float(proposal.get("entry_price_max"))
    if entry_min is not None and entry_max is not None:
        return (entry_min + entry_max) / 2
    return entry_min or entry_max
