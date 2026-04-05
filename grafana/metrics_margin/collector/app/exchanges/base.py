from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class ExchangeAdapter(ABC):
    @abstractmethod
    def fetch_available_inventory(self, *, assets: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_price_index(self, *, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch_spot_klines(
        self,
        *,
        symbol: str,
        interval: str,
        start_time: datetime | None,
        end_time: datetime | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_isolated_margin_tiers(self, *, symbols: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_cross_margin_collateral_ratios(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_risk_based_liquidation_ratios(self) -> list[dict[str, Any]]:
        raise NotImplementedError
