"""Optional in-process APScheduler for local runs."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from django.conf import settings

from integrations.checker import run_checks, within_market_hours

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def scheduled_check():
    if not within_market_hours():
        logger.debug("Outside market hours; skipping checks")
        return
    logger.info("Running scheduled price checks")
    run_checks()


def start_scheduler() -> BackgroundScheduler | None:
    # Host crontab is the supported path; keep this off in Podman (ENABLE_SCHEDULER=false).
    global _scheduler
    if not settings.ENABLE_SCHEDULER:
        return None
    if _scheduler and _scheduler.running:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    _scheduler.add_job(
        scheduled_check,
        "interval",
        minutes=settings.CHECK_INTERVAL_MINUTES,
        id="price_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("APScheduler started (every %s minutes)", settings.CHECK_INTERVAL_MINUTES)
    return _scheduler
