from __future__ import annotations

from typing import Any

from app.db import Database
from app.utils import json_fingerprint


SOURCE_TO_TABLE = {
    "isolated_margin_tier": "isolated_margin_tier_snapshots",
    "cross_margin_collateral_ratio": "cross_margin_collateral_ratio_snapshots",
    "risk_based_liquidation_ratio": "risk_based_liquidation_ratio_snapshots",
}


def persist_change_event_if_needed(
    *,
    db: Database,
    source_key: str,
    collected_at,
    asset: str | None,
    symbol: str | None,
    previous_payload: dict[str, Any] | None,
    current_payload: dict[str, Any],
) -> None:
    table = SOURCE_TO_TABLE[source_key]
    previous_fingerprint = None if previous_payload is None else json_fingerprint(previous_payload)
    current_fingerprint = json_fingerprint(current_payload)
    if previous_fingerprint == current_fingerprint:
        return
    if previous_payload is None:
        summary = f"Initial snapshot captured for {source_key}"
    else:
        changed_fields = sorted([key for key in current_payload.keys() if previous_payload.get(key) != current_payload.get(key)])
        summary = f"{source_key} changed: {', '.join(changed_fields[:8])}"
    db.insert_change_event(
        collected_at=collected_at,
        asset=asset,
        symbol=symbol,
        source_table=table,
        event_type=f"{source_key}_changed",
        summary=summary,
        previous_payload=previous_payload,
        current_payload=current_payload,
    )
