from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

pd.set_option("future.no_silent_downcasting", True)


def compute_stress_proxy(series: pd.Series, lookback: int = 288) -> pd.Series:
    min_window = max(2, min(lookback, len(series)))
    rolling_mean = series.rolling(window=min_window, min_periods=2).mean()
    rolling_std = series.rolling(window=min_window, min_periods=2).std(ddof=0).replace(0, pd.NA)
    z_score = (series - rolling_mean) / rolling_std
    return (-1 * z_score).fillna(0.0)


def compute_normalized_to_100(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    non_zero = series[series != 0]
    if non_zero.empty:
        return pd.Series([100.0] * len(series), index=series.index)
    base = non_zero.iloc[0]
    return (series / base) * 100.0


def compute_returns(series: pd.Series) -> pd.Series:
    return series.astype(float).pct_change().fillna(0.0)


def compute_inventory_change(series: pd.Series) -> pd.Series:
    return series.astype(float).pct_change().fillna(0.0)


def compute_rolling_correlation(
    price_series: pd.Series,
    inventory_series: pd.Series,
    *,
    points: int,
) -> pd.Series:
    price_returns = compute_returns(price_series)
    inventory_changes = compute_inventory_change(inventory_series)
    return price_returns.rolling(window=points, min_periods=points).corr(inventory_changes)


def infer_stress_regime(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1.5:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def build_derived_metric_rows(
    *,
    asset: str,
    symbol: str,
    points: list[dict[str, Any]],
    corr_24h_points: int,
    corr_7d_points: int,
) -> list[dict[str, Any]]:
    if len(points) < 2:
        return []
    frame = pd.DataFrame(points)
    frame = frame.sort_values("collected_at")
    frame["collected_at"] = pd.to_datetime(frame["collected_at"], utc=True)
    frame["available_inventory"] = frame["available_inventory"].astype(float)
    frame["close_price"] = frame["close_price"].astype(float)

    stress = compute_stress_proxy(frame["available_inventory"])
    corr_24h = compute_rolling_correlation(
        frame["close_price"],
        frame["available_inventory"],
        points=corr_24h_points,
    )
    corr_7d = compute_rolling_correlation(
        frame["close_price"],
        frame["available_inventory"],
        points=corr_7d_points,
    )
    normalized_price = compute_normalized_to_100(frame["close_price"])
    normalized_inventory = compute_normalized_to_100(frame["available_inventory"])
    corr_24h_min_periods = max(3, corr_24h_points // 4)
    corr_7d_min_periods = max(3, corr_7d_points // 4)

    rows: list[dict[str, Any]] = []
    for idx, collected_at in enumerate(frame["collected_at"]):
        rows.extend(
            [
                {
                    "collected_at": collected_at.to_pydatetime(),
                    "asset": asset,
                    "symbol": symbol,
                    "metric_name": "stress_proxy_zinv",
                    "metric_value": float(stress.iloc[idx]),
                    "window_label": "rolling",
                    "metadata": {"method": "negative_inventory_zscore", "lookback_points": min(288, len(frame))},
                },
                {
                    "collected_at": collected_at.to_pydatetime(),
                    "asset": asset,
                    "symbol": symbol,
                    "metric_name": "rolling_corr_price_vs_inventory_24h",
                    "metric_value": None if pd.isna(corr_24h.iloc[idx]) else float(corr_24h.iloc[idx]),
                    "window_label": "24h",
                    "metadata": {
                        "formula": "corr(pct_change(price), pct_change(inventory))",
                        "window_points": corr_24h_points,
                        "min_periods": corr_24h_min_periods,
                    },
                },
                {
                    "collected_at": collected_at.to_pydatetime(),
                    "asset": asset,
                    "symbol": symbol,
                    "metric_name": "rolling_corr_price_vs_inventory_7d",
                    "metric_value": None if pd.isna(corr_7d.iloc[idx]) else float(corr_7d.iloc[idx]),
                    "window_label": "7d",
                    "metadata": {
                        "formula": "corr(pct_change(price), pct_change(inventory))",
                        "window_points": corr_7d_points,
                        "min_periods": corr_7d_min_periods,
                    },
                },
                {
                    "collected_at": collected_at.to_pydatetime(),
                    "asset": asset,
                    "symbol": symbol,
                    "metric_name": "normalized_price_100",
                    "metric_value": float(normalized_price.iloc[idx]),
                    "window_label": "range",
                    "metadata": {"base": 100.0},
                },
                {
                    "collected_at": collected_at.to_pydatetime(),
                    "asset": asset,
                    "symbol": symbol,
                    "metric_name": "normalized_inventory_100",
                    "metric_value": float(normalized_inventory.iloc[idx]),
                    "window_label": "range",
                    "metadata": {"base": 100.0},
                },
            ]
        )
    return [row for row in rows if row["metric_value"] is not None]
