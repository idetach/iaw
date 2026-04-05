from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ConfigSnapshot:
    collected_at: datetime
    endpoint: str
    asset: str | None
    symbol: str | None
    payload: dict[str, Any] | list[Any]
    fingerprint: str
