from __future__ import annotations

import logging
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.collector import CollectorService
from app.config import settings
from app.db import Database
from app.exchanges import BinanceAdapter
from app.logging_utils import configure_logging


configure_logging(settings.log_level)
log = logging.getLogger("metrics_margin.main")


def run() -> None:
    db = Database(settings)
    db.ensure_schema()
    adapter = BinanceAdapter(settings)
    service = CollectorService(settings, db, adapter)

    service.discover_margin_pairs()

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(service.poll_prices, IntervalTrigger(seconds=settings.price_poll_seconds), id="poll_prices", max_instances=1, coalesce=True)
    scheduler.add_job(service.poll_available_inventory, IntervalTrigger(seconds=settings.inventory_poll_seconds), id="poll_inventory", max_instances=1, coalesce=True)
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
