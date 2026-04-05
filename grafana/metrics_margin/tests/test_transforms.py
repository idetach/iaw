from __future__ import annotations

import pandas as pd

from app.transforms import (
    build_derived_metric_rows,
    compute_normalized_to_100,
    compute_rolling_correlation,
    compute_stress_proxy,
    infer_stress_regime,
)


def test_compute_normalized_to_100() -> None:
    series = pd.Series([10.0, 15.0, 20.0])
    result = compute_normalized_to_100(series)
    assert list(result.round(2)) == [100.0, 150.0, 200.0]


def test_compute_stress_proxy_inverse_behavior() -> None:
    series = pd.Series([100.0, 95.0, 90.0, 70.0, 50.0, 45.0])
    result = compute_stress_proxy(series, lookback=3)
    assert result.iloc[-1] > result.iloc[1]


def test_compute_rolling_correlation_returns_series() -> None:
    price = pd.Series([100, 101, 99, 98, 102, 103, 101, 100], dtype=float)
    inventory = pd.Series([50, 49, 48, 47, 46, 47, 48, 49], dtype=float)
    result = compute_rolling_correlation(price, inventory, points=4)
    assert len(result) == len(price)
    assert result.notna().sum() >= 1


def test_build_derived_metric_rows_contains_expected_metrics() -> None:
    points = [
        {"collected_at": f"2026-01-01T0{i}:00:00Z", "available_inventory": 100 - i * 2, "close_price": 30000 + i * 100}
        for i in range(10)
    ]
    rows = build_derived_metric_rows(asset="BTC", symbol="BTCUSDT", points=points)
    metric_names = {row["metric_name"] for row in rows}
    assert "stress_proxy_zinv" in metric_names
    assert "normalized_price_100" in metric_names
    assert "normalized_inventory_100" in metric_names


def test_infer_stress_regime_thresholds() -> None:
    assert infer_stress_regime(0.2) == "low"
    assert infer_stress_regime(0.8) == "medium"
    assert infer_stress_regime(2.0) == "high"
