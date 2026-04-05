from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .client import get_http_client
from .config import get_settings

router = APIRouter(prefix="/v1/trade", tags=["trade"])
_log = logging.getLogger("bybit_trading.trade")


def _require_auth(settings) -> None:
    if not settings.has_credentials:
        raise HTTPException(status_code=401, detail="API credentials required")


def _raise_if_bybit_error(resp: dict) -> dict:
    ret_code = resp.get("retCode", 0)
    if ret_code != 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bybit error {ret_code}: {resp.get('retMsg', 'unknown')}",
        )
    return resp


def _safe_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OpenOrderRequest(BaseModel):
    symbol: str
    side: Literal["Buy", "Sell"]
    order_type: Literal["Market", "Limit"] = Field(alias="orderType", default="Market")
    qty: str = Field(description="Order quantity in base asset (e.g. '0.01' BTC)")
    price: str | None = Field(
        default=None,
        description="Limit price. Required when orderType=Limit",
    )
    stop_loss: str | None = Field(default=None, alias="stopLoss")
    take_profit: str | None = Field(default=None, alias="takeProfit")
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="slTriggerBy"
    )
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="tpTriggerBy"
    )
    reduce_only: bool = Field(default=False, alias="reduceOnly")
    time_in_force: Literal["GTC", "IOC", "FOK", "PostOnly"] = Field(
        default="GTC", alias="timeInForce"
    )
    position_idx: Literal[0, 1, 2] = Field(
        default=0,
        alias="positionIdx",
        description="0=one-way, 1=hedge Buy side, 2=hedge Sell side",
    )
    order_link_id: str | None = Field(default=None, alias="orderLinkId")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def check_limit_price(self) -> "OpenOrderRequest":
        if self.order_type == "Limit" and not self.price:
            raise ValueError("price is required for Limit orders")
        return self


class SetSLTPRequest(BaseModel):
    symbol: str
    stop_loss: str | None = Field(default=None, alias="stopLoss")
    take_profit: str | None = Field(default=None, alias="takeProfit")
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="slTriggerBy"
    )
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="tpTriggerBy"
    )
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def check_at_least_one(self) -> "SetSLTPRequest":
        if not self.stop_loss and not self.take_profit:
            raise ValueError("At least one of stopLoss or takeProfit must be provided")
        return self


class SetPartialSLTPRequest(BaseModel):
    """
    Set SL/TP on a partial position using the tpsl_mode=Partial strategy.
    Specify tp_size/sl_size to apply TP/SL to a subset of the position qty.
    """
    symbol: str
    stop_loss: str | None = Field(default=None, alias="stopLoss")
    take_profit: str | None = Field(default=None, alias="takeProfit")
    tp_size: str | None = Field(
        default=None,
        alias="tpSize",
        description="Qty to close at take-profit (partial TP)",
    )
    sl_size: str | None = Field(
        default=None,
        alias="slSize",
        description="Qty to close at stop-loss (partial SL)",
    )
    sl_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="slTriggerBy"
    )
    tp_trigger_by: Literal["LastPrice", "MarkPrice", "IndexPrice"] = Field(
        default="MarkPrice", alias="tpTriggerBy"
    )
    tp_order_type: Literal["Market", "Limit"] = Field(default="Market", alias="tpOrderType")
    sl_order_type: Literal["Market", "Limit"] = Field(default="Market", alias="slOrderType")
    tp_limit_price: str | None = Field(default=None, alias="tpLimitPrice")
    sl_limit_price: str | None = Field(default=None, alias="slLimitPrice")
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def check_at_least_one(self) -> "SetPartialSLTPRequest":
        if not self.stop_loss and not self.take_profit:
            raise ValueError("At least one of stopLoss or takeProfit must be provided")
        return self


class ClosePositionRequest(BaseModel):
    symbol: str
    qty: str | None = Field(
        default=None,
        description="Qty to close. Omit or set to None to close entire position.",
    )
    order_type: Literal["Market", "Limit"] = Field(default="Market", alias="orderType")
    price: str | None = Field(
        default=None,
        description="Limit price for partial close. Required when orderType=Limit.",
    )
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")
    order_link_id: str | None = Field(default=None, alias="orderLinkId")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/positions")
def get_positions(symbol: str | None = None) -> dict[str, Any]:
    """Fetch all open positions (or for a specific symbol)."""
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        kwargs: dict[str, Any] = {"category": category, "settleCoin": "USDT"}
        if symbol:
            kwargs["symbol"] = symbol
        resp = session.get_positions(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    positions = [
        p for p in resp.get("result", {}).get("list", [])
        if float(p.get("size") or "0") > 0
    ]
    return {"positions": positions, "count": len(positions)}


@router.get("/orders")
def get_open_orders(symbol: str | None = None) -> dict[str, Any]:
    """Fetch open/unfilled orders."""
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        kwargs: dict[str, Any] = {"category": category, "openOnly": 0}
        if symbol:
            kwargs["symbol"] = symbol
        resp = session.get_open_orders(**kwargs)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    return {
        "orders": resp.get("result", {}).get("list", []),
        "nextPageCursor": resp.get("result", {}).get("nextPageCursor"),
    }


@router.post("/order")
def place_order(body: OpenOrderRequest) -> dict[str, Any]:
    """
    Place a futures order (limit or market) with optional stop-loss and take-profit.

    For Market orders, `price` is ignored.
    For Limit orders, `price` is required.
    SL/TP are optional on open; they can also be set after via /sltp endpoints.
    """
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    order_params: dict[str, Any] = {
        "category": category,
        "symbol": body.symbol,
        "side": body.side,
        "orderType": body.order_type,
        "qty": body.qty,
        "timeInForce": body.time_in_force,
        "positionIdx": body.position_idx,
        "reduceOnly": body.reduce_only,
    }

    if body.order_type == "Limit" and body.price:
        order_params["price"] = body.price

    if body.stop_loss:
        order_params["stopLoss"] = body.stop_loss
        order_params["slTriggerBy"] = body.sl_trigger_by

    if body.take_profit:
        order_params["takeProfit"] = body.take_profit
        order_params["tpTriggerBy"] = body.tp_trigger_by

    if body.order_link_id:
        order_params["orderLinkId"] = body.order_link_id

    _log.info(
        "Placing %s %s order: symbol=%s qty=%s price=%s sl=%s tp=%s",
        body.side, body.order_type, body.symbol, body.qty, body.price,
        body.stop_loss, body.take_profit,
    )

    try:
        resp = session.place_order(**order_params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    result = resp.get("result", {})
    return {
        "orderId": result.get("orderId"),
        "orderLinkId": result.get("orderLinkId"),
        "symbol": body.symbol,
        "side": body.side,
        "orderType": body.order_type,
        "qty": body.qty,
        "price": body.price,
        "stopLoss": body.stop_loss,
        "takeProfit": body.take_profit,
        "raw": result,
    }


@router.post("/sltp")
def set_sltp_full(body: SetSLTPRequest) -> dict[str, Any]:
    """
    Set stop-loss and/or take-profit for the **entire** position.
    Uses tpslMode=Full — applies to 100% of the position size.
    """
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    params: dict[str, Any] = {
        "category": category,
        "symbol": body.symbol,
        "tpslMode": "Full",
        "positionIdx": body.position_idx,
    }

    if body.stop_loss:
        params["stopLoss"] = body.stop_loss
        params["slTriggerBy"] = body.sl_trigger_by

    if body.take_profit:
        params["takeProfit"] = body.take_profit
        params["tpTriggerBy"] = body.tp_trigger_by

    _log.info(
        "Setting full SL/TP: symbol=%s sl=%s tp=%s",
        body.symbol, body.stop_loss, body.take_profit,
    )

    try:
        resp = session.set_trading_stop(**params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    return {"ok": True, "symbol": body.symbol, "raw": resp.get("result", {})}


@router.post("/sltp/partial")
def set_sltp_partial(body: SetPartialSLTPRequest) -> dict[str, Any]:
    """
    Set stop-loss and/or take-profit for a **partial** position size.
    Uses tpslMode=Partial — you specify tp_size and/or sl_size.

    Bybit only supports partial SL/TP on positions where the instrument
    supports it (most linear perpetuals do).
    """
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    params: dict[str, Any] = {
        "category": category,
        "symbol": body.symbol,
        "tpslMode": "Partial",
        "positionIdx": body.position_idx,
    }

    if body.take_profit:
        params["takeProfit"] = body.take_profit
        params["tpTriggerBy"] = body.tp_trigger_by
        params["tpOrderType"] = body.tp_order_type
        if body.tp_size:
            params["tpSize"] = body.tp_size
        if body.tp_order_type == "Limit" and body.tp_limit_price:
            params["tpLimitPrice"] = body.tp_limit_price

    if body.stop_loss:
        params["stopLoss"] = body.stop_loss
        params["slTriggerBy"] = body.sl_trigger_by
        params["slOrderType"] = body.sl_order_type
        if body.sl_size:
            params["slSize"] = body.sl_size
        if body.sl_order_type == "Limit" and body.sl_limit_price:
            params["slLimitPrice"] = body.sl_limit_price

    _log.info(
        "Setting partial SL/TP: symbol=%s sl=%s (size=%s) tp=%s (size=%s)",
        body.symbol, body.stop_loss, body.sl_size, body.take_profit, body.tp_size,
    )

    try:
        resp = session.set_trading_stop(**params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    return {"ok": True, "symbol": body.symbol, "raw": resp.get("result", {})}


@router.post("/close")
def close_position(body: ClosePositionRequest) -> dict[str, Any]:
    """
    Close a position fully or partially.

    - Omit `qty` (or set to None) → close the **entire** position via a
      reduce-only Market order at the current position size.
    - Provide `qty` → close that many units (partial close).

    For a Limit partial close, provide `orderType=Limit` and `price`.
    """
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    # Determine close qty — if not specified, look up the current position size.
    close_qty = body.qty
    if not close_qty:
        try:
            pos_resp = session.get_positions(
                category=category,
                symbol=body.symbol,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")
        _raise_if_bybit_error(pos_resp)

        positions = pos_resp.get("result", {}).get("list", [])
        # Filter to matching positionIdx
        matching = [
            p for p in positions
            if int(p.get("positionIdx", 0)) == body.position_idx
            and float(p.get("size") or "0") > 0
        ]
        if not matching:
            raise HTTPException(
                status_code=404,
                detail=f"No open position found for {body.symbol} positionIdx={body.position_idx}",
            )
        pos = matching[0]
        close_qty = pos["size"]
        pos_side = pos.get("side", "")
        # Closing side is opposite of position side
        close_side: Literal["Buy", "Sell"] = "Buy" if pos_side == "Sell" else "Sell"
    else:
        # Must infer the close side from position
        try:
            pos_resp = session.get_positions(
                category=category,
                symbol=body.symbol,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")
        _raise_if_bybit_error(pos_resp)
        positions = pos_resp.get("result", {}).get("list", [])
        matching = [
            p for p in positions
            if int(p.get("positionIdx", 0)) == body.position_idx
            and float(p.get("size") or "0") > 0
        ]
        if not matching:
            raise HTTPException(
                status_code=404,
                detail=f"No open position found for {body.symbol} positionIdx={body.position_idx}",
            )
        pos_side = matching[0].get("side", "")
        close_side = "Buy" if pos_side == "Sell" else "Sell"

    order_params: dict[str, Any] = {
        "category": category,
        "symbol": body.symbol,
        "side": close_side,
        "orderType": body.order_type,
        "qty": close_qty,
        "reduceOnly": True,
        "positionIdx": body.position_idx,
        "timeInForce": "GTC",
    }

    if body.order_type == "Limit":
        if not body.price:
            raise HTTPException(
                status_code=400,
                detail="price is required for Limit close orders",
            )
        order_params["price"] = body.price

    if body.order_link_id:
        order_params["orderLinkId"] = body.order_link_id

    _log.info(
        "Closing position: symbol=%s side=%s qty=%s type=%s price=%s",
        body.symbol, close_side, close_qty, body.order_type, body.price,
    )

    try:
        resp = session.place_order(**order_params)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    result = resp.get("result", {})
    return {
        "orderId": result.get("orderId"),
        "orderLinkId": result.get("orderLinkId"),
        "symbol": body.symbol,
        "side": close_side,
        "qty": close_qty,
        "orderType": body.order_type,
        "reduceOnly": True,
        "raw": result,
    }


class SetLeverageRequest(BaseModel):
    symbol: str
    leverage: int = Field(ge=1, le=200)
    position_idx: Literal[0, 1, 2] = Field(default=0, alias="positionIdx")

    model_config = {"populate_by_name": True}


@router.post("/leverage")
def set_leverage(body: SetLeverageRequest) -> dict[str, Any]:
    """Set leverage for a symbol (both Buy and Sell sides in one-way mode)."""
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        resp = session.set_leverage(
            category=category,
            symbol=body.symbol,
            buyLeverage=str(body.leverage),
            sellLeverage=str(body.leverage),
        )
    except Exception as exc:
        if "110043" in str(exc):
            return {"ok": True, "symbol": body.symbol, "leverage": body.leverage, "already_set": True}
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    ret_code = resp.get("retCode", 0)
    if ret_code not in (0, 110043):
        raise HTTPException(
            status_code=400,
            detail=f"Bybit error {ret_code}: {resp.get('retMsg', 'unknown')}",
        )

    return {"ok": True, "symbol": body.symbol, "leverage": body.leverage, "raw": resp.get("result", {})}


@router.delete("/order/{order_id}")
def cancel_order(order_id: str, symbol: str) -> dict[str, Any]:
    """Cancel an open order by orderId."""
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)
    category = settings.bybit_category

    try:
        resp = session.cancel_order(
            category=category,
            symbol=symbol,
            orderId=order_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    return {"ok": True, "orderId": order_id, "raw": resp.get("result", {})}


@router.get("/balance")
def get_wallet_balance() -> dict[str, Any]:
    """Fetch unified margin wallet balance (USDT)."""
    settings = get_settings()
    _require_auth(settings)
    session = get_http_client(settings)

    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Bybit request failed: {exc}")

    _raise_if_bybit_error(resp)
    accounts = resp.get("result", {}).get("list", [])
    if not accounts:
        return {"balance": None}

    account = accounts[0]
    coins = account.get("coin", [])
    usdt = next((c for c in coins if c.get("coin") == "USDT"), None)

    return {
        "accountType": account.get("accountType"),
        "totalEquity": account.get("totalEquity"),
        "totalWalletBalance": account.get("totalWalletBalance"),
        "totalAvailableBalance": account.get("totalAvailableBalance"),
        "totalMarginBalance": account.get("totalMarginBalance"),
        "unrealisedPnl": account.get("totalPerpUPL"),
        "usdt": usdt,
        "raw": account,
    }
