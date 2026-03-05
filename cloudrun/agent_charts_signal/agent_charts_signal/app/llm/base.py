from __future__ import annotations

from abc import ABC, abstractmethod

from chart_vision_common.models import LiquidationHeatmapObservations, Pass1Observations, TradeProposal


class VisionLLMProvider(ABC):
    @abstractmethod
    async def pass1(self, *, symbol: str, timestamp_utc, images_by_tf: dict[str, bytes]) -> tuple[Pass1Observations, object]:
        raise NotImplementedError

    @abstractmethod
    async def pass_liquidation_heatmap(
        self,
        *,
        symbol: str,
        timestamp_utc,
        liquidation_heatmap_png: bytes,
        time_horizon_hours: int,
    ) -> tuple[LiquidationHeatmapObservations, object]:
        raise NotImplementedError

    @abstractmethod
    async def pass2(
        self,
        *,
        symbol: str,
        timestamp_utc,
        images_by_tf: dict[str, bytes],
        pass1: Pass1Observations,
        liquidation_heatmap: LiquidationHeatmapObservations | None = None,
    ) -> tuple[TradeProposal, object]:
        raise NotImplementedError
