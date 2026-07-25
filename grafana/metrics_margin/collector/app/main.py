from __future__ import annotations

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.collector import CollectorService
from app.config import settings
from app.db import Database
from app.exchanges import BinanceAdapter
from app.logging_utils import configure_logging


configure_logging(settings.log_level)
log = logging.getLogger("metrics_margin.main")


def _price_poll_trigger(
    kline_interval: str,
    offset_seconds: int,
    align: bool,
) -> CronTrigger | IntervalTrigger:
    """Return a trigger aligned to kline-close boundaries if align=True."""
    if not align:
        return IntervalTrigger(seconds=settings.price_poll_seconds)
    if kline_interval.endswith("m"):
        minutes = int(kline_interval[:-1])
        if minutes == 1:
            return CronTrigger(second=offset_seconds % 60, timezone="UTC")
        minute_list = ",".join(str(i) for i in range(0, 60, minutes))
        return CronTrigger(minute=minute_list, second=offset_seconds % 60, timezone="UTC")
    if kline_interval.endswith("h"):
        hours = int(kline_interval[:-1])
        return CronTrigger(hour=f"*/{hours}", minute=0, second=offset_seconds % 60, timezone="UTC")
    log.warning("price_kline_interval=%s unsupported for candle alignment, using IntervalTrigger", kline_interval)
    return IntervalTrigger(seconds=settings.price_poll_seconds)


def run() -> None:
    db = Database(settings)
    db.ensure_schema()
    adapter = BinanceAdapter(settings)
    service = CollectorService(settings, db, adapter)

    service.discover_margin_pairs()

    price_trigger = _price_poll_trigger(
        settings.price_kline_interval,
        settings.fetch_offset_seconds,
        settings.align_to_candle_close,
    )
    log.info(
        "price_trigger type=%s aligned=%s offset=%ss",
        type(price_trigger).__name__,
        settings.align_to_candle_close,
        settings.fetch_offset_seconds,
    )
    inv_trigger = _price_poll_trigger(
        settings.price_kline_interval,
        settings.fetch_offset_seconds,
        settings.align_to_candle_close,
    )
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(service.poll_prices, price_trigger, id="poll_prices", max_instances=1, coalesce=True)
    scheduler.add_job(service.poll_available_inventory, inv_trigger, id="poll_inventory", max_instances=1, coalesce=True)
    scheduler.add_job(service.poll_config_snapshots, IntervalTrigger(seconds=settings.config_poll_seconds), id="poll_config", max_instances=1, coalesce=True)
    scheduler.add_job(lambda: service.discover_margin_pairs(force_api=True), IntervalTrigger(hours=settings.discover_poll_hours), id="discover_pairs", max_instances=1, coalesce=True)

    service.backfill_price_history()
    service.poll_prices()
    service.poll_available_inventory()
    service.poll_config_snapshots()

    log.info("collector_started tracked_symbols=%d", len(service.tracked_symbols))
    try:
        scheduler.start()
    finally:
        adapter.close()


if __name__ == "__main__":
    while True:
        try:
            run()
            break
        except Exception as exc:
            log.exception("collector_crashed error=%s", exc)
            time.sleep(5)
