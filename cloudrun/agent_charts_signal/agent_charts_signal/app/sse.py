from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class CaseEvent:
    type: str
    case_id: str
    ts: datetime
    data: dict[str, Any]


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[CaseEvent]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[CaseEvent]:
        q: asyncio.Queue[CaseEvent] = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[CaseEvent]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, type: str, case_id: str, data: dict[str, Any] | None = None) -> None:
        ev = CaseEvent(
            type=type,
            case_id=case_id,
            ts=datetime.now(timezone.utc),
            data=data or {},
        )
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                pass
