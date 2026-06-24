"""Shared APScheduler instance — Sprint 4.

Both `observable_job` and `watcher_job` add themselves here at startup so
we have ONE in-proc scheduler with multiple recurring jobs.

On Cloud Run scale-to-zero, the scheduler only runs while the container is
warm. For guaranteed cadence we expose admin endpoints that Cloud Scheduler
can hit to force-run a batch:

  - POST /v1/admin/observables/run-batch  (existing)
  - POST /v1/admin/watchers/run-batch     (Sprint 4)
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_scheduler: Any = None  # apscheduler.schedulers.background.BackgroundScheduler


def get_or_create_scheduler():
    """Return the singleton scheduler, starting it if not yet running."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:  # pragma: no cover
        log.warning("APScheduler not installed — no in-proc scheduler.")
        return None

    sched = BackgroundScheduler(daemon=True, timezone="UTC")
    sched.start()
    _scheduler = sched
    log.info("Shared APScheduler started.")
    return sched


def shutdown_scheduler() -> None:
    """Stop the scheduler if running."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
