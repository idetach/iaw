from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path as ApiPath
from pydantic import BaseModel, Field

from . import bybit_client as bybit
from .config import get_settings
from .gcs import get_storage_client, read_case_json, write_case_json
from .proposal import calculate_qty, ensure_min_notional, entry_price_from_proposal, proposal_to_order_params, snap_qty_to_step

router = APIRouter(prefix="/v1/trader", tags=["trader"])
_log = logging.getLogger("agent_trading.trader")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ExecuteTradeRequest(BaseModel):
    """
    Parameters for auto-executing a trade from proposal_validated.json.
    All fields are optional overrides; the proposal values are used by default.
    """
    order_type: Literal["Market", "Limit"] = Field(default="Limit", alias="orderType")
    qty: str | None = Field(
        default=None,
        description="Override qty. If omitted, calculated from balance × margin_percent × leverage / entry_price.",
    )
    qty_precision: int = Field(
        default=3,
        alias="qtyPrecision",
        description="Decimal places to round auto-calculated qty.",
    )
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")
    set_leverage: bool = Field(
        default=True,
        alias="setLeverage",
        description="Call bybit_trading to set leverage before placing the order.",
    )

    model_config = {"populate_by_name": True}


class ManualTradeRequest(BaseModel):
    """
    Manual order placement from the frontend trade form.
    Maps directly to bybit_trading POST /v1/trade/order.
    """
    symbol: str
    side: Literal["Buy", "Sell"]
    order_type: Literal["Market", "Limit"] = Field(default="Market", alias="orderType")
    qty: str
    price: str | None = None
    stop_loss: str | None = Field(default=None, alias="stopLoss")
    take_profit: str | None = Field(default=None, alias="takeProfit")
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="slTriggerBy"
    )
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="tpTriggerBy"
    )
    leverage: int | None = Field(
        default=None,
        description="If provided, calls bybit_trading to set leverage before placing order.",
    )
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")
    order_link_id: str | None = Field(default=None, alias="orderLinkId")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_trade_record(
    *,
    case_id: str,
    source: str,
    order_result: dict[str, Any],
    order_params: dict[str, Any],
    proposal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "source": source,
        "executed_at": _now_iso(),
        "order_params": order_params,
        "order_result": order_result,
        "proposal_snapshot": proposal,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/cases/{case_id}/execute")
async def execute_trade_from_proposal(
    case_id: str = ApiPath(..., min_length=6),
    body: ExecuteTradeRequest = ...,
) -> dict[str, Any]:
    """
    Auto-place a futures order from the case's proposal_validated.json.

    Flow:
    1. Read proposal_validated.json + request.json from GCS
    2. Derive qty from wallet balance (unless overridden)
    3. Optionally set leverage via bybit_trading
    4. Place order via bybit_trading
    5. Write result to trade.json in GCS
    """
    settings = get_settings()
    client = get_storage_client()

    # -- read GCS artifacts --
    try:
        proposal: dict[str, Any] = read_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="proposal_validated.json",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"proposal_validated.json not found: {exc}")

    try:
        request_obj: dict[str, Any] = read_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="request.json",
        )
    except Exception:
        request_obj = {}

    symbol: str | None = request_obj.get("symbol") if isinstance(request_obj, dict) else None
    if not symbol:
        raise HTTPException(status_code=422, detail="Symbol not found in case request.json")

    # -- resolve qty --
    qty = body.qty
    if not qty:
        leverage_val = proposal.get("leverage")
        margin_pct = proposal.get("margin_percent")
        if not leverage_val or not margin_pct:
            raise HTTPException(
                status_code=422,
                detail="proposal is missing leverage or margin_percent; provide qty explicitly",
            )

        entry_price = entry_price_from_proposal(proposal)
        if not entry_price:
            raise HTTPException(
                status_code=422,
                detail="proposal has no entry_price_min/max; provide qty explicitly",
            )

        balance_resp, instrument_resp = await asyncio.gather(
            bybit.get_balance(settings),
            bybit.get_instrument_info(settings, symbol),
        )
        total_equity = balance_resp.get("totalEquity") or (
            (balance_resp.get("usdt") or {}).get("equity")
        )
        if not total_equity:
            raise HTTPException(
                status_code=422,
                detail="Could not resolve USDT balance from bybit_trading",
            )

        lot_size = instrument_resp.get("instrument", {}).get("lotSizeFilter", {})
        qty_step: str = lot_size.get("qtyStep", "1")
        min_notional: float = float(lot_size.get("minNotionalValue") or 0)

        raw_qty = calculate_qty(
            balance_usdt=float(total_equity),
            margin_percent=float(margin_pct),
            leverage=float(leverage_val),
            entry_price=entry_price,
            qty_precision=body.qty_precision,
        )
        qty = ensure_min_notional(
            qty=float(raw_qty),
            price=entry_price,
            min_notional=min_notional,
            qty_step=qty_step,
        )
        _log.info(
            "Auto-calculated qty=%s (raw=%s, step=%s, minNotional=%s) for case=%s "
            "(balance=%s, margin=%s%%, leverage=%s, entry=%s)",
            qty, raw_qty, qty_step, min_notional, case_id,
            total_equity, margin_pct, leverage_val, entry_price,
        )

    # -- optionally set leverage --
    if body.set_leverage and proposal.get("leverage"):
        leverage_int = int(round(float(proposal["leverage"])))
        _log.info("Setting leverage %sx for %s", leverage_int, symbol)
        await bybit.set_leverage(settings, symbol=symbol, leverage=leverage_int)

    # -- build and place order --
    order_params = proposal_to_order_params(
        proposal=proposal,
        symbol=symbol,
        qty=qty,
        order_type=body.order_type,
        position_idx=body.position_idx,
    )
    _log.info("Placing auto-order for case=%s: %s", case_id, order_params)
    order_result = await bybit.place_order(settings, order_params)

    # -- persist to GCS --
    trade_record = _build_trade_record(
        case_id=case_id,
        source="execute_from_proposal",
        order_result=order_result,
        order_params=order_params,
        proposal=proposal,
    )
    try:
        write_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="trade_execution.json",
            obj=trade_record,
        )
    except Exception as exc:
        _log.warning("Failed to write trade_execution.json for case=%s: %s", case_id, exc)

    return {
        "ok": True,
        "case_id": case_id,
        "symbol": symbol,
        "order_params": order_params,
        "order_result": order_result,
        "trade_record": trade_record,
    }


@router.post("/cases/{case_id}/manual")
async def manual_trade(
    case_id: str = ApiPath(..., min_length=6),
    body: ManualTradeRequest = ...,
) -> dict[str, Any]:
    """
    Place a manual order from the frontend trade form and save the result
    to the case's trade.json.

    Optionally sets leverage before placing if `leverage` is provided.
    """
    settings = get_settings()
    client = get_storage_client()

    # -- verify case exists --
    try:
        read_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="request.json",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Case not found: {exc}")

    # -- optionally set leverage --
    if body.leverage is not None:
        _log.info("Setting leverage %sx for %s (manual trade)", body.leverage, body.symbol)
        await bybit.set_leverage(settings, symbol=body.symbol, leverage=body.leverage)

    # -- build and place order --
    order_params: dict[str, Any] = {
        "symbol": body.symbol,
        "side": body.side,
        "orderType": body.order_type,
        "qty": body.qty,
        "positionIdx": body.position_idx,
        "slTriggerBy": body.sl_trigger_by,
        "tpTriggerBy": body.tp_trigger_by,
    }
    if body.order_type == "Limit" and body.price:
        order_params["price"] = body.price
    if body.stop_loss:
        order_params["stopLoss"] = body.stop_loss
    if body.take_profit:
        order_params["takeProfit"] = body.take_profit
    if body.order_link_id:
        order_params["orderLinkId"] = body.order_link_id

    _log.info("Placing manual order for case=%s: %s", case_id, order_params)
    order_result = await bybit.place_order(settings, order_params)

    # -- persist to GCS --
    trade_record = _build_trade_record(
        case_id=case_id,
        source="manual_trade_form",
        order_result=order_result,
        order_params=order_params,
    )
    try:
        write_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="trade_execution.json",
            obj=trade_record,
        )
    except Exception as exc:
        _log.warning("Failed to write trade_execution.json for case=%s: %s", case_id, exc)

    return {
        "ok": True,
        "case_id": case_id,
        "symbol": body.symbol,
        "order_params": order_params,
        "order_result": order_result,
        "trade_record": trade_record,
    }


@router.get("/cases/{case_id}/trade")
def get_trade(case_id: str = ApiPath(..., min_length=6)) -> dict[str, Any]:
    """Read the saved trade.json for a case."""
    settings = get_settings()
    client = get_storage_client()
    try:
        trade = read_case_json(
            client=client,
            bucket=settings.gcs_bucket,
            cases_prefix=settings.cases_prefix,
            case_id=case_id,
            name="trade_execution.json",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"case not found: {case_id}")
    except Exception:
        raise HTTPException(status_code=404, detail="trade_execution.json not found for this case")
    return {"case_id": case_id, "trade": trade}
