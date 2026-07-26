"""
Internal tick scheduler (local/dev cadence).

When TICK_INTERVAL_MINUTES > 0 (env or runtime settings), a background task
runs a tick every interval — handy on a local machine where no external cron
exists. In Cloud Run, leave it 0 and drive POST /v1/loop/tick with Cloud
Scheduler instead (scale-to-zero friendly; see deploy/setup_scheduler.sh).

The ticker never overlaps ticks: it skips a beat if one is still running
(shared TICK_LOCK with the HTTP endpoints).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .config import get_settings

_log = logging.getLogger("conductor.ticker")

_task: asyncio.Task | None = None
last_tick_at: str | None = None
last_tick_summary: dict | None = None

_IDLE_POLL_SECONDS = 15.0  # how often we re-check the interval setting when off


async def _run_forever() -> None:
    from . import loop as loop_mod

    _log.info("internal ticker started (interval=0 means idle)")
    while True:
        s = get_settings()
        interval = float(s.tick_interval_minutes or 0)
        if interval <= 0:
            await asyncio.sleep(_IDLE_POLL_SECONDS)
            continue
        try:
            if loop_mod.TICK_LOCK.locked():
                _log.info("ticker: previous tick still running — skipping this beat")
            else:
                global last_tick_at, last_tick_summary
                result = await loop_mod.tick()
                last_tick_at = datetime.now(timezone.utc).isoformat()
                last_tick_summary = {
                    "candidates_scanned": result.candidates_scanned,
                    "executed": result.executed,
                    "orders_reconciled": result.orders_reconciled,
                    "errors": len(result.errors),
                }
                _log.info("ticker: tick done %s", last_tick_summary)
        except Exception:
            _log.exception("ticker: tick failed")
        await asyncio.sleep(max(interval * 60.0, 60.0))


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_event_loop().create_task(_run_forever())
