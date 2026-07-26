from __future__ import annotations

import pytest

from conductor.app.config import Settings
from conductor.app.governor import evaluate
from conductor.app.models import PortfolioState


def make_settings(**overrides) -> Settings:
    base = dict(
        EXECUTION_MODE="shadow",
        LOOP_ENABLED="true",
        GCS_BUCKET="test",
        RISK_FRACTION="0.01",
        MAX_CONCURRENT_POSITIONS="3",
        MAX_AGGREGATE_OPEN_RISK="0.03",
        MAX_LEVERAGE="10",
        MAX_MARGIN_PERCENT="25",
        MAX_TOTAL_MARGIN_FRACTION="0.40",
        DAILY_LOSS_BREAKER_FRACTION="0.03",
        WEEKLY_LOSS_BREAKER_FRACTION="0.06",
        MIN_CONFIDENCE="0.6",
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def make_proposal(**overrides) -> dict:
    p = dict(
        long_short_none="LONG",
        entry_price_min=100.0,
        entry_price_max=102.0,
        stop_loss=95.0,
        target_price=115.0,
        leverage=5,
        confidence=0.8,
    )
    p.update(overrides)
    return p


def portfolio(**overrides) -> PortfolioState:
    base = dict(equity_usdt=10_000.0)
    base.update(overrides)
    return PortfolioState(**base)


# ---------------------------------------------------------------------------
# sizing
# ---------------------------------------------------------------------------

def test_risk_based_sizing():
    s = make_settings()
    d = evaluate(settings=s, proposal=make_proposal(), portfolio=portfolio(), symbol="BTCUSDT")
    assert d.action in ("APPROVE", "RESIZE")
    # risk = 10_000 * 1% = 100 USDT; stop distance = |101 - 95| = 6 → qty ≈ 16.67
    assert d.qty == pytest.approx(100.0 / 6.0, rel=1e-6)


def test_loss_at_stop_equals_risk_budget():
    s = make_settings()
    d = evaluate(settings=s, proposal=make_proposal(), portfolio=portfolio(), symbol="X")
    loss_at_stop = d.qty * abs(101.0 - 95.0)
    assert loss_at_stop == pytest.approx(10_000 * 0.01, rel=1e-6)


# ---------------------------------------------------------------------------
# hard gates
# ---------------------------------------------------------------------------

def test_reject_none_direction():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(long_short_none="NONE"),
        portfolio=portfolio(),
        symbol="X",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "invalid_proposal"


def test_reject_missing_stop():
    s = make_settings()
    d = evaluate(
        settings=s, proposal=make_proposal(stop_loss=None), portfolio=portfolio(), symbol="X"
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "no_stop"


def test_reject_stop_on_wrong_side():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(stop_loss=110.0),  # LONG with stop above entry
        portfolio=portfolio(),
        symbol="X",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "invalid_proposal"


def test_reject_low_confidence():
    s = make_settings()
    d = evaluate(
        settings=s, proposal=make_proposal(confidence=0.3), portfolio=portfolio(), symbol="X"
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "low_confidence"


def test_reject_too_many_positions():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(),
        portfolio=portfolio(open_positions=[{"symbol": a} for a in "abc"]),
        symbol="X",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "too_many_positions"


def test_reject_cooldown():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(),
        portfolio=portfolio(symbols_on_cooldown=["BTCUSDT"]),
        symbol="BTCUSDT",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "cooldown"


def test_daily_breaker_blocks_entries():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(),
        portfolio=portfolio(realized_pnl_today_usdt=-301.0),  # > 3% of 10k
        symbol="X",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "breaker_daily"


def test_aggregate_risk_cap():
    s = make_settings()
    d = evaluate(
        settings=s,
        proposal=make_proposal(),
        portfolio=portfolio(open_risk_usdt=250.0),  # cap = 300; new risk 100 breaches
        symbol="X",
    )
    assert d.action == "REJECT"
    assert d.reject_reason == "aggregate_risk_cap"


def test_kill_switch():
    s = make_settings(LOOP_ENABLED="false")
    d = evaluate(settings=s, proposal=make_proposal(), portfolio=portfolio(), symbol="X")
    assert d.action == "REJECT"
    assert d.reject_reason == "loop_disabled"


# ---------------------------------------------------------------------------
# clamps
# ---------------------------------------------------------------------------

def test_leverage_clamped_to_max():
    s = make_settings()
    d = evaluate(
        settings=s, proposal=make_proposal(leverage=50), portfolio=portfolio(), symbol="X"
    )
    assert d.action in ("APPROVE", "RESIZE")
    assert d.leverage == 10.0


def test_margin_cap_resizes_qty():
    s = make_settings()
    # Tight stop -> huge qty -> margin cap must shrink it.
    p = make_proposal(entry_price_min=100.0, entry_price_max=100.0, stop_loss=99.9, leverage=1)
    d = evaluate(settings=s, proposal=p, portfolio=portfolio(), symbol="X")
    assert d.action == "RESIZE"
    margin_needed = d.qty * 100.0 / d.leverage
    assert margin_needed <= 10_000 * 0.25 * 1.001
