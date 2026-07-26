from __future__ import annotations

import pytest

from conductor.app.loop import _fmt_step, _snap_down, _step_decimals


def test_snap_down_to_qty_step():
    assert _snap_down(66.395202, 0.01) == pytest.approx(66.39)
    assert _snap_down(0.0129, 0.001) == pytest.approx(0.012)
    assert _snap_down(5.0, 1.0) == pytest.approx(5.0)


def test_snap_down_no_step_passthrough():
    assert _snap_down(1.2345, 0) == 1.2345


def test_snap_down_never_rounds_up():
    # rounding up could breach margin/risk caps — must always floor
    assert _snap_down(0.999999, 0.1) == pytest.approx(0.9)
    assert _snap_down(66.399999, 0.01) == pytest.approx(66.39)


def test_snap_down_exact_multiple_stable():
    # float noise must not knock an exact multiple down a step
    assert _snap_down(66.39, 0.01) == pytest.approx(66.39)
    assert _snap_down(0.012, 0.001) == pytest.approx(0.012)


def test_step_decimals():
    assert _step_decimals(0.01) == 2
    assert _step_decimals(0.001) == 3
    assert _step_decimals(1.0) == 0
    assert _step_decimals(0.5) == 1


def test_fmt_step_formats_to_step_precision():
    assert _fmt_step(66.39, 0.01) == "66.39"
    assert _fmt_step(1878.4, 0.1) == "1878.4"
    assert _fmt_step(5.0, 1.0) == "5"
    assert _fmt_step(0.012, 0.001) == "0.012"
