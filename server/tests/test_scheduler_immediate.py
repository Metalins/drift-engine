"""ops-2 — the in-proc schedulers must force an immediate first run.

Regression guard: an APScheduler `interval` trigger first fires at
now+interval. On Cloud Run every deploy restarts the process and resets
that timer, so a burst of deploys could keep the observable batch from
ever reaching a first run (this is exactly what happened in ops-2). The
fix passes `next_run_time=now` so a fresh revision produces a row right
away. These tests assert that contract without starting real threads or
touching the DB: we inject a fake scheduler and inspect the add_job call.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")
os.environ.setdefault("METALINS_DB_URL", f"sqlite:////tmp/_metalins_sched_{os.getpid()}.db")


def _capture_add_job(monkeypatch, start_fn, **call_kwargs) -> dict:
    """Call start_fn with a fake shared scheduler; return the add_job kwargs."""
    captured: dict = {}

    class _FakeSched:
        def add_job(self, func, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs

    import app.services.scheduler as scheduler_mod

    # start_scheduler / start_watcher_scheduler do
    # `from app.services.scheduler import get_or_create_scheduler` at call
    # time, so patching the attribute on the module is enough.
    monkeypatch.setattr(scheduler_mod, "get_or_create_scheduler", lambda: _FakeSched())
    start_fn(**call_kwargs)
    return captured


def _assert_immediate(next_run_time) -> None:
    assert next_run_time is not None, "next_run_time must be set (immediate first run)"
    now = datetime.now(timezone.utc)
    delta = abs((now - next_run_time).total_seconds())
    assert delta < 60, f"first run should be ~now, not now+interval (delta={delta}s)"


def test_observable_scheduler_first_run_is_immediate(monkeypatch):
    from app.services.observable_job import start_scheduler

    cap = _capture_add_job(monkeypatch, start_scheduler, interval_minutes=60)
    kwargs = cap["kwargs"]
    assert kwargs["id"] == "observable_batch"
    assert kwargs["minutes"] == 60
    assert kwargs["replace_existing"] is True
    _assert_immediate(kwargs["next_run_time"])


def test_watcher_scheduler_first_run_is_immediate(monkeypatch):
    from app.services.watcher_job import start_watcher_scheduler

    cap = _capture_add_job(monkeypatch, start_watcher_scheduler, interval_seconds=60)
    kwargs = cap["kwargs"]
    assert kwargs["id"] == "watcher_batch"
    assert kwargs["seconds"] == 60
    assert kwargs["replace_existing"] is True
    _assert_immediate(kwargs["next_run_time"])
