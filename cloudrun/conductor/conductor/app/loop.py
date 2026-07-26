"""
The Conductor tick (conductor-design):

  A. gather candidates (watchlist + radar)
  B. snapshot + Fable gate
  C. Opus synthesis -> proposal
  D. risk governor
  E. execute (demo/live) or log (shadow)
  F. manage open positions
  (G. reflection runs on close — triggered from F)

Exposed two ways:
  POST /v1/loop/tick         — run one tick, return the full TickResult
  GET  /v1/loop/tick/stream  — run one tick, stream per-phase SSE events
                               (data: {"event": ...} lines) for live UIs

Stateless: Bybit account + GCS cases are the source of truth.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from . import gcs, governor, lifecycle, llm, orders as orders_mod, pnl
from .auth import id_token_for_cloud_run
from .config import Settings, get_settings
from .indicators.engine import build_snapshot
from .market_data import BybitTradingProvider
from .models import IndicatorSnapshot, PortfolioState, TickResult

router = APIRouter(prefix="/v1/loop", tags=["loop"])
_log = logging.getLogger("conductor.loop")

# One tick at a time — shared by POST /tick, GET /tick/stream and the internal
# ticker. Overlapping ticks would double-count portfolio headroom.
TICK_LOCK = asyncio.Lock()

# Runtime kill-switch override (web_app). None = follow LOOP_ENABLED env.
# NOTE: in-memory — resets on restart and is per-instance; run Cloud Run with
# max-instances=1 (the loop must be single-instance anyway for one-decision-
# per-symbol semantics).
_runtime_enabled: bool | None = None


def effective_enabled(s: Settings) -> bool:
    return s.loop_enabled if _runtime_enabled is None else _runtime_enabled


@router.post("/enabled")
async def set_enabled(body: dict[str, Any]) -> dict[str, Any]:
    """Kill switch: {'enabled': false} halts new entries (positions still managed)."""
    global _runtime_enabled
    _runtime_enabled = bool(body.get("enabled"))
    _log.warning("kill switch set: enabled=%s", _runtime_enabled)
    return {"enabled": _runtime_enabled, "source": "runtime"}


@router.get("/status")
async def status() -> dict[str, Any]:
    from . import ticker

    s = get_settings()
    return {
        "execution_mode": s.execution_mode,
        "loop_enabled": effective_enabled(s),
        "loop_enabled_source": "env" if _runtime_enabled is None else "runtime",
        "tick_interval_minutes": s.tick_interval_minutes,
        "tick_in_progress": TICK_LOCK.locked(),
        "last_internal_tick_at": ticker.last_tick_at,
        "last_internal_tick_summary": ticker.last_tick_summary,
        "watchlist": s.watchlist_symbols,
        "timeframes": s.timeframes_list,
        "models": {
            "gate": s.model_gate,
            "synthesis": s.model_synthesis,
            "reflection": s.model_reflection,
        },
    }


# ---------------------------------------------------------------------------
# Tick as an event generator (single source of truth for both endpoints)
# ---------------------------------------------------------------------------

async def _tick_events(s: Settings) -> AsyncIterator[dict[str, Any]]:
    started = datetime.now(timezone.utc)
    tick_id = f"tick-{started.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    prefix = gcs.tick_prefix(s.cases_prefix, tick_id, started)
    cases: dict[str, dict[str, Any]] = {}  # symbol -> accumulated case artifact

    async def persist(symbol: str) -> None:
        if s.persist_cases and s.gcs_bucket and symbol in cases:
            await asyncio.to_thread(
                gcs.write_json, s.gcs_bucket, f"{prefix}/{symbol}.json", cases[symbol]
            )

    yield {
        "event": "start",
        "tick_id": tick_id,
        "execution_mode": s.execution_mode,
        "started_at": started.isoformat(),
    }

    provider = BybitTradingProvider(s)
    portfolio, portfolio_error, closed_records = await _portfolio_state(s)
    yield {
        "event": "portfolio",
        "equity_usdt": portfolio.equity_usdt,
        "open_positions": [p.get("symbol") for p in portfolio.open_positions],
        "open_orders": [
            f"{o.get('symbol')} {o.get('side')} {o.get('qty')}@{o.get('price')}"
            for o in portfolio.open_orders
        ],
        "margin_used_usdt": portfolio.total_margin_used_usdt,
        "open_risk_usdt": portfolio.open_risk_usdt,
        "realized_pnl_today_usdt": portfolio.realized_pnl_today_usdt,
        "realized_pnl_week_usdt": portfolio.realized_pnl_week_usdt,
        "symbols_on_cooldown": portfolio.symbols_on_cooldown,
        **({"error": portfolio_error, "note": "entries blocked (fail-safe)"} if portfolio_error else {}),
        **(
            {"orders_error": portfolio.orders_error, "orders_note": "order reconciliation skipped this tick"}
            if portfolio.orders_error
            else {}
        ),
    }
    if portfolio.orders_error:
        yield {
            "event": "error",
            "scope": "orders",
            "message": f"open orders unavailable — reconciliation skipped: {portfolio.orders_error}",
        }

    # --- reconcile resting conductor orders before anything else -------------
    # (a stale entry order is exposure booked at a dead thesis; see orders.py)
    still_resting: list[dict[str, Any]] = []
    for order in portfolio.open_orders:
        symbol = order.get("symbol", "")
        try:
            tf_snap = None
            try:
                candles = await provider.klines(
                    symbol, s.order_reconcile_timeframe, s.kline_limit
                )
                from .indicators.engine import build_timeframe_snapshot

                tf_snap = build_timeframe_snapshot(s.order_reconcile_timeframe, candles)
            except Exception as exc:
                _log.warning("reconcile snapshot failed for %s: %s", symbol, exc)

            verdict = orders_mod.assess_order(
                order,
                ttl_minutes=s.order_ttl_minutes,
                max_drift_atr=s.order_max_drift_atr,
                tf_snapshot=tf_snap,
            )
            cancelled = False
            if verdict["action"] == "CANCEL" and s.execution_mode != "shadow":
                await _bybit_delete(
                    s,
                    f"/v1/trade/order/{order.get('orderId')}",
                    params={"symbol": symbol},
                )
                cancelled = True
            if verdict["action"] == "KEEP":
                still_resting.append(order)
            yield {
                "event": "order",
                "symbol": symbol,
                "action": verdict["action"],
                "cancelled": cancelled,
                "reason": verdict["reason"],
                "side": order.get("side"),
                "qty": order.get("qty"),
                "price": order.get("price"),
                "order_id": order.get("orderId"),
            }
        except Exception as exc:
            still_resting.append(order)  # keep claim conservative on error
            yield {"event": "error", "scope": "order", "symbol": symbol, "message": str(exc)}
    # governor and dedupe see only the orders that survived reconciliation
    portfolio.open_orders = still_resting
    portfolio.open_risk_usdt = (
        sum(orders_mod.order_risk_usdt(o) for o in still_resting)
        + sum(
            abs(float(p.get("avgPrice") or 0) - float(p.get("stopLoss") or 0))
            * float(p.get("size") or 0)
            for p in portfolio.open_positions
            if float(p.get("avgPrice") or 0) and float(p.get("stopLoss") or 0)
        )
    )

    # --- F first: manage existing positions before considering new risk -----
    for pos in portfolio.open_positions:
        symbol = pos.get("symbol", "")
        try:
            snapshot = await _snapshot(provider, s, symbol)
            action = lifecycle.assess_position(
                settings=s, position=pos, snapshot=snapshot, proposal=None
            )
            await _apply_lifecycle_action(s, symbol=symbol, position=pos, decision=action)
            yield {
                "event": "lifecycle",
                "symbol": symbol,
                "action": action["action"],
                "reason": action["reason"],
                "new_stop": action.get("new_stop"),
                "side": pos.get("side"),
                "size": pos.get("size"),
                "avg_price": pos.get("avgPrice"),
                "unrealised_pnl": pos.get("unrealisedPnl"),
            }
        except Exception as exc:
            yield {"event": "error", "scope": "lifecycle", "symbol": symbol, "message": str(exc)}

    # --- kill switch: skip new-entry phases entirely -------------------------
    if not effective_enabled(s):
        yield {"event": "halted", "reason": "loop disabled (kill switch)"}
        yield _done_event(started, s)
        return

    # --- A: candidates -------------------------------------------------------
    candidates = list(s.watchlist_symbols)
    radar_set: set[str] = set()
    if s.radar_enabled:
        try:
            radar_syms = await _radar_symbols(s)
            radar_set = set(radar_syms)
            candidates += radar_syms
        except Exception as exc:
            yield {"event": "error", "scope": "radar", "message": str(exc)}
    # exclude symbols with open positions OR surviving resting orders — one
    # claim per symbol, never stacked entries across ticks
    open_symbols = {p.get("symbol") for p in portfolio.open_positions} | {
        o.get("symbol") for o in portfolio.open_orders
    }
    candidates = [c for c in dict.fromkeys(candidates) if c not in open_symbols]
    candidates = candidates[: s.max_candidates_per_tick]
    yield {
        "event": "candidates",
        "symbols": candidates,
        "sources": {c: ("radar" if c in radar_set else "watchlist") for c in candidates},
    }

    # --- B..E per candidate ---------------------------------------------------
    for symbol in candidates:
        cases[symbol] = {
            "tick_id": tick_id,
            "symbol": symbol,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "execution_mode": s.execution_mode,
            "source": "radar" if symbol in radar_set else "watchlist",
        }
        try:
            snapshot = await _snapshot(provider, s, symbol)
            cases[symbol]["snapshot"] = snapshot.model_dump(mode="json")
            yield {
                "event": "scanned",
                "symbol": symbol,
                "timeframes": [t.timeframe for t in snapshot.timeframes],
                "summary": "; ".join(
                    t.notes.split(";")[0] for t in snapshot.timeframes if t.notes
                ),
            }

            gate_out = await asyncio.to_thread(llm.gate, s, snapshot)  # Fable
            cases[symbol]["gate"] = gate_out
            if not gate_out.get("plausible"):
                await persist(symbol)
                yield {
                    "event": "gate",
                    "symbol": symbol,
                    "passed": False,
                    "reason": gate_out.get("reject_reason", ""),
                }
                continue
            yield {
                "event": "gate",
                "symbol": symbol,
                "passed": True,
                "reason": gate_out.get("setup_hint", ""),
            }

            recent = (
                pnl.recent_outcomes_summary(closed_records, symbol)
                if s.include_recent_outcomes and closed_records
                else None
            )
            proposal = await asyncio.to_thread(llm.synthesize, s, snapshot, recent)  # Opus
            cases[symbol]["proposal"] = proposal
            if proposal.get("long_short_none") == "NONE":
                await persist(symbol)
                yield {
                    "event": "proposal",
                    "symbol": symbol,
                    "direction": "NONE",
                    "reason": proposal.get("reason_abstain", ""),
                }
                continue
            yield {
                "event": "proposal",
                "symbol": symbol,
                "direction": proposal.get("long_short_none"),
                "confidence": proposal.get("confidence"),
                "entry_min": proposal.get("entry_price_min"),
                "entry_max": proposal.get("entry_price_max"),
                "stop_loss": proposal.get("stop_loss"),
                "target_price": proposal.get("target_price"),
                "duration": proposal.get("position_duration"),
                "reason": proposal.get("reason_entry", ""),
            }

            decision = governor.evaluate(
                settings=s, proposal=proposal, portfolio=portfolio, symbol=symbol
            )
            cases[symbol]["governor"] = decision.model_dump(mode="json")
            yield {
                "event": "governor",
                "symbol": symbol,
                "action": decision.action,
                "qty": decision.qty,
                "leverage": decision.leverage,
                "reject_reason": decision.reject_reason,
                "reason": (
                    "; ".join(decision.reasons)
                    if decision.action != "REJECT"
                    else f"rejected: {decision.reject_reason}"
                ),
                "audit": decision.audit,
            }
            if decision.action == "REJECT":
                await persist(symbol)
                continue

            try:
                executed, exec_note = await _execute(
                    s, symbol=symbol, proposal=proposal, decision=decision
                )
            except Exception as exc:
                executed, exec_note = False, f"order placement failed: {exc}"
                _log.exception("execute failed for %s", symbol)
            cases[symbol]["execution"] = {"placed": executed, "note": exec_note}
            await persist(symbol)
            yield {
                "event": "executed",
                "symbol": symbol,
                "placed": executed,
                "reason": exec_note,
            }
            if executed:
                # Reserve risk/margin so later candidates in this tick see it.
                portfolio.open_positions.append({"symbol": symbol})
                portfolio.open_risk_usdt += decision.audit.get("risk_usdt", 0.0)
                portfolio.total_margin_used_usdt += decision.audit.get("margin_needed", 0.0)
        except Exception as exc:
            _log.exception("candidate %s failed", symbol)
            cases[symbol]["error"] = str(exc)
            await persist(symbol)
            yield {"event": "error", "scope": "candidate", "symbol": symbol, "message": str(exc)}

    # tick summary (best-effort)
    if s.persist_cases and s.gcs_bucket:
        summary = {
            "tick_id": tick_id,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "execution_mode": s.execution_mode,
            "equity_usdt": portfolio.equity_usdt,
            "realized_pnl_today_usdt": portfolio.realized_pnl_today_usdt,
            "realized_pnl_week_usdt": portfolio.realized_pnl_week_usdt,
            "symbols_on_cooldown": portfolio.symbols_on_cooldown,
            "candidates": list(cases.keys()),
        }
        await asyncio.to_thread(gcs.write_json, s.gcs_bucket, f"{prefix}/_tick.json", summary)

    yield _done_event(started, s)


def _done_event(started: datetime, s: Settings) -> dict[str, Any]:
    return {
        "event": "done",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": s.execution_mode,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/tick")
async def tick() -> TickResult:
    """Run one tick and return the aggregate result (Cloud Scheduler entrypoint)."""
    if TICK_LOCK.locked():
        raise HTTPException(status_code=409, detail="tick already in progress")
    s = get_settings()
    started = datetime.now(timezone.utc)
    result = TickResult(
        started_at=started, finished_at=started, execution_mode=s.execution_mode
    )
    async with TICK_LOCK:
        result = await _collect_tick(s, result)
    return result


async def _collect_tick(s: Settings, result: TickResult) -> TickResult:
    async for ev in _tick_events(s):
        kind = ev.get("event")
        if kind == "candidates":
            result.candidates_scanned = len(ev.get("symbols", []))
        elif kind == "gate" and ev.get("passed"):
            result.passed_gate += 1
        elif kind == "proposal" and ev.get("direction") not in (None, "NONE"):
            result.proposals += 1
        elif kind == "governor" and ev.get("action") in ("APPROVE", "RESIZE"):
            result.approved += 1
        elif kind == "executed" and ev.get("placed"):
            result.executed += 1
        elif kind == "lifecycle":
            result.positions_managed += 1
        elif kind == "order":
            result.orders_reconciled += 1
            if ev.get("cancelled"):
                result.orders_cancelled += 1
        elif kind == "error":
            result.errors.append(
                f"{ev.get('scope', '?')} {ev.get('symbol', '')}: {ev.get('message', '')}".strip()
            )
        elif kind == "portfolio" and ev.get("error"):
            result.errors.append(f"portfolio: {ev['error']}")
        result.detail.append(ev)
    result.finished_at = datetime.now(timezone.utc)
    return result


@router.get("/tick/stream")
async def tick_stream() -> StreamingResponse:
    """Run one tick, streaming each phase as an SSE `data:` line (live UI)."""
    s = get_settings()

    async def gen() -> AsyncIterator[str]:
        if TICK_LOCK.locked():
            yield f"data: {json.dumps({'event': 'error', 'scope': 'tick', 'message': 'tick already in progress'})}\n\n"
            yield f"data: {json.dumps({'event': 'done'})}\n\n"
            return
        try:
            async with TICK_LOCK:
                async for ev in _tick_events(s):
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as exc:
            _log.exception("tick stream failed")
            yield f"data: {json.dumps({'event': 'error', 'scope': 'tick', 'message': str(exc)})}\n\n"
            yield f"data: {json.dumps({'event': 'done'})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _snapshot(
    provider: BybitTradingProvider, s: Settings, symbol: str
) -> IndicatorSnapshot:
    candles_by_tf = {
        tf: await provider.klines(symbol, tf, s.kline_limit) for tf in s.timeframes_list
    }
    ticker = await provider.ticker(symbol)
    return build_snapshot(symbol, candles_by_tf, ticker)


def _bybit_headers(s: Settings) -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    id_token = id_token_for_cloud_run(s.bybit_trading_url)
    if id_token:
        h["Authorization"] = f"Bearer {id_token}"
    if s.bybit_trading_token:
        h["X-Internal-Token"] = s.bybit_trading_token
    return h


async def _bybit_get(s: Settings, path: str, params: dict | None = None) -> dict[str, Any]:
    url = f"{s.bybit_trading_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(s.bybit_trading_timeout, connect=10.0)) as c:
        resp = await c.get(url, params=params, headers=_bybit_headers(s))
        resp.raise_for_status()
        return resp.json()


async def _bybit_delete(s: Settings, path: str, params: dict | None = None) -> dict[str, Any]:
    url = f"{s.bybit_trading_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(s.bybit_trading_timeout, connect=10.0)) as c:
        resp = await c.delete(url, params=params, headers=_bybit_headers(s))
        resp.raise_for_status()
        return resp.json()


async def _bybit_post(s: Settings, path: str, body: dict) -> dict[str, Any]:
    url = f"{s.bybit_trading_url.rstrip('/')}{path}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(s.bybit_trading_timeout, connect=10.0)) as c:
        resp = await c.post(url, json=body, headers=_bybit_headers(s))
        resp.raise_for_status()
        return resp.json()


async def _portfolio_state(
    s: Settings,
) -> tuple[PortfolioState, str | None, list[dict[str, Any]]]:
    """Assemble governor inputs from bybit_trading. Fail-safe: on error, return
    a state that blocks new entries (equity=0) plus the error for the tick log.
    Third element: raw closed-pnl records (for optional LLM context)."""
    closed_records: list[dict[str, Any]] = []
    try:
        balance = await _bybit_get(s, "/v1/trade/balance")
        positions_resp = await _bybit_get(s, "/v1/trade/positions")
        # Risk budget is denominated in USDT (we trade USDT perps). totalEquity
        # includes other coins in the unified account and would inflate sizing.
        usdt = balance.get("usdt") or {}
        equity = float(usdt.get("equity") or 0.0) or float(
            balance.get("totalEquity")
            or balance.get("result", {}).get("totalEquity")
            or 0.0
        )
        if equity <= 0:
            return (
                PortfolioState(equity_usdt=0.0),
                f"balance endpoint returned no equity: {str(balance)[:200]}",
                closed_records,
            )
        positions = positions_resp.get("positions") or positions_resp.get(
            "result", {}
        ).get("list", []) or []
        open_positions = [p for p in positions if float(p.get("size") or 0) > 0]
        margin_used = sum(float(p.get("positionIM") or 0) for p in open_positions)

        # Resting conductor entry orders (orderLinkId "conductor-*") — claims
        # on future exposure; reconciled and counted against slots/risk.
        open_orders: list[dict[str, Any]] = []
        orders_error: str | None = None
        try:
            orders_resp = await _bybit_get(s, "/v1/trade/orders")
            open_orders = [
                o
                for o in (orders_resp.get("orders") or [])
                if orders_mod.is_conductor_order(o) and not o.get("reduceOnly")
            ]
        except httpx.HTTPStatusError as exc:
            orders_error = (
                f"{exc.response.status_code} from {exc.request.url.path}: "
                f"{exc.response.text[:200]}"
            )
            _log.error("open orders unavailable (reconciliation skipped): %s", orders_error)
        except Exception as exc:
            orders_error = f"{type(exc).__name__}: {exc}"
            _log.error("open orders unavailable (reconciliation skipped): %s", orders_error)
        open_risk = 0.0
        for p in open_positions:
            entry = float(p.get("avgPrice") or 0)
            stop = float(p.get("stopLoss") or 0)
            size = float(p.get("size") or 0)
            if entry and stop:
                open_risk += abs(entry - stop) * size
        open_risk += sum(orders_mod.order_risk_usdt(o) for o in open_orders)

        # Realized PnL + cooldowns from closed-pnl (last 7 days). Non-fatal:
        # if unavailable, breakers see 0 and cooldowns are empty, but we log it.
        realized = {"realized_today": 0.0, "realized_week": 0.0, "cooldown_symbols": []}
        try:
            week_ago_ms = int((datetime.now(timezone.utc).timestamp() - 7 * 86400) * 1000)
            closed = await _bybit_get(
                s, "/v1/trade/closed-pnl", params={"start_time_ms": week_ago_ms}
            )
            closed_records = closed.get("records", [])
            realized = pnl.aggregate(
                closed_records, cooldown_hours=s.symbol_cooldown_hours
            )
        except Exception as exc:
            _log.warning("closed-pnl unavailable (breakers see 0): %s", exc)

        return (
            PortfolioState(
                equity_usdt=equity,
                total_margin_used_usdt=margin_used,
                open_positions=open_positions,
                open_orders=open_orders,
                orders_error=orders_error,
                open_risk_usdt=open_risk,
                realized_pnl_today_usdt=realized["realized_today"],
                realized_pnl_week_usdt=realized["realized_week"],
                symbols_on_cooldown=realized["cooldown_symbols"],
            ),
            None,
            closed_records,
        )
    except httpx.HTTPStatusError as exc:
        detail = f"{exc.response.status_code} from {exc.request.url.path}: {exc.response.text[:300]}"
        _log.error("portfolio state failed (blocking entries): %s", detail)
        return PortfolioState(equity_usdt=0.0), detail, closed_records
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        _log.error("portfolio state failed (blocking entries): %s", detail)
        return PortfolioState(equity_usdt=0.0), detail, closed_records


async def _radar_symbols(s: Settings) -> list[str]:
    data = await _bybit_get(s, "/v1/radar/extreme-events", params={"limit": 100})
    out: list[str] = []
    for key in ("extreme_price", "extreme_volume"):
        for item in data.get(key, []):
            sym = item.get("symbol")
            if sym:
                out.append(sym)
    return out


def _snap_down(value: float, step: float) -> float:
    """Snap value down to a multiple of step (exchange lot/tick filters)."""
    if step <= 0:
        return value
    return int(value / step + 1e-9) * step


def _step_decimals(step: float) -> int:
    text = f"{step:.10f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def _fmt_step(value: float, step: float) -> str:
    if step <= 0:
        return f"{value:.8f}".rstrip("0").rstrip(".")
    return f"{value:.{_step_decimals(step)}f}"


async def _instrument_filters(s: Settings, symbol: str) -> tuple[float, float, float]:
    """(qty_step, min_qty, tick_size); zeros when unavailable."""
    try:
        info = await _bybit_get(s, f"/v1/market/instrument/{symbol}")
        inst = info.get("instrument", {})
        lot = inst.get("lotSizeFilter", {})
        price_f = inst.get("priceFilter", {})
        return (
            float(lot.get("qtyStep") or 0),
            float(lot.get("minOrderQty") or 0),
            float(price_f.get("tickSize") or 0),
        )
    except Exception as exc:
        _log.warning("instrument filters unavailable for %s: %s", symbol, exc)
        return 0.0, 0.0, 0.0


async def _execute(
    s: Settings, *, symbol: str, proposal: dict[str, Any], decision: Any
) -> tuple[bool, str]:
    """Snap to exchange filters, then place the order (with SL/TP attached)
    or log it in shadow mode."""
    qty_step, min_qty, tick_size = await _instrument_filters(s, symbol)

    qty = _snap_down(float(decision.qty), qty_step)
    if min_qty and qty < min_qty:
        return False, (
            f"sized qty {decision.qty:.8f} snaps below minOrderQty {min_qty} "
            f"(step {qty_step}) — skipped"
        )

    entry = decision.audit.get("entry")
    price = _snap_down(float(entry), tick_size) if entry is not None else None
    stop_loss = proposal.get("stop_loss")
    target = proposal.get("target_price")

    order_link_id = f"conductor-{uuid.uuid4().hex[:12]}"
    body = {
        "symbol": symbol,
        "side": "Buy" if proposal["long_short_none"] == "LONG" else "Sell",
        "orderType": "Limit",
        "qty": _fmt_step(qty, qty_step),
        "price": _fmt_step(price, tick_size) if price is not None else None,
        "stopLoss": _fmt_step(_snap_down(float(stop_loss), tick_size), tick_size) if stop_loss is not None else None,
        "takeProfit": _fmt_step(_snap_down(float(target), tick_size), tick_size) if target is not None else None,
        "slTriggerBy": "MarkPrice",
        "tpTriggerBy": "MarkPrice",
        "orderLinkId": order_link_id,
    }
    if s.execution_mode == "shadow":
        _log.info("SHADOW order (not placed): %s", body)
        return False, f"shadow mode — order logged, not placed ({body['side']} {body['qty']} @ {body['price']})"
    # demo/live both go through bybit_trading; the demo/live split lives in the
    # bybit_trading credentials + endpoint config (ADR-0003).
    if decision.leverage:
        try:
            await _bybit_post(
                s, "/v1/trade/leverage", {"symbol": symbol, "leverage": int(decision.leverage)}
            )
        except Exception as exc:
            _log.warning("set leverage failed for %s: %s", symbol, exc)
    resp = await _bybit_post(s, "/v1/trade/order", body)
    _log.info("order placed %s: %s", order_link_id, resp)
    order_id = resp.get("orderId") or resp.get("result", {}).get("orderId", "")
    return True, f"{body['side']} {body['qty']} @ {body['price']} (order {order_id or order_link_id})"


async def _apply_lifecycle_action(
    s: Settings, *, symbol: str, position: dict[str, Any], decision: dict[str, Any]
) -> None:
    action = decision["action"]
    if action == "HOLD" or s.execution_mode == "shadow":
        return
    if action in ("MOVE_STOP_BREAKEVEN", "TRAIL_STOP") and decision.get("new_stop"):
        await _bybit_post(
            s, "/v1/trade/sltp", {"symbol": symbol, "stopLoss": _fmt(decision["new_stop"])}
        )
    elif action in ("EXIT_INVALIDATED", "EXIT_TIME"):
        await _bybit_post(s, "/v1/trade/close", {"symbol": symbol})
        # TODO: trigger llm.reflect(...) and persist to case + case_graph_analytics
    elif action == "ESCALATE_OPUS":
        # TODO: call llm for hold/exit decision with full context
        _log.info("escalation requested for %s (not yet implemented)", symbol)


def _fmt(v: Any) -> str | None:
    if v is None:
        return None
    return f"{float(v):.8f}".rstrip("0").rstrip(".")
