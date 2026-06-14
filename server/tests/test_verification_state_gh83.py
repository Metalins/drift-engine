"""Unit tests for gh-83 — last_probe_at uses actual probe timestamp.

Issue #77 (Jose, 2026-06-11): the dashboard showed "Jan 31" as the
last-probe date for dogfood-v2 (created June 11) because `last_probe_at`
was taken from `latest_obs.ts` — the moment the observable job ran —
rather than from the MemoryProbe's `issued_at`. When the observable is
stale (or, for a re-registered agent, from a prior observable), this
produces a wrong date entirely unrelated to actual probe activity.

Fix (gh-83): `derive_trust` accepts an optional `latest_probe_at`
parameter (the probe's `issued_at`). Callers that have DB access pass
it in; `last_probe_at` in the response reflects when the actual
cryptographic check occurred, not when the bookkeeping job ran.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services.verification_state import derive_trust


def _make_agent():
    return SimpleNamespace(
        is_active=True,
        revoked_at=None,
        created_at=datetime(2026, 6, 11),
    )


def _make_state(event_count: int = 200):
    return SimpleNamespace(event_count=event_count, last_event_at=None)


def _make_obs(ts: datetime, *, score_factors: list | None = None):
    return SimpleNamespace(
        ts=ts,
        details_json={"score_factors": score_factors or []},
    )


def test_last_probe_at_uses_probe_timestamp_not_obs_ts():
    """When latest_probe_at is supplied it wins over latest_obs.ts."""
    stale_obs_ts = datetime(2026, 1, 31, 12, 0, 0)
    probe_issued = datetime(2026, 6, 11, 22, 15, 0)

    obs = _make_obs(stale_obs_ts)
    trust = derive_trust(
        _make_agent(),
        _make_state(),
        obs,
        latest_probe_at=probe_issued,
    )
    assert trust["cryptographic"]["last_probe_at"] == "2026-06-11T22:15:00Z"


def test_last_probe_at_falls_back_to_obs_ts_when_no_probe():
    """When no probe has ever been issued, fall back to latest_obs.ts."""
    obs_ts = datetime(2026, 6, 11, 10, 0, 0)
    obs = _make_obs(obs_ts)
    trust = derive_trust(_make_agent(), _make_state(), obs, latest_probe_at=None)
    assert trust["cryptographic"]["last_probe_at"] == "2026-06-11T10:00:00Z"


def test_last_probe_at_is_null_when_no_obs_and_no_probe():
    """Both absent → null, not a crash."""
    trust = derive_trust(_make_agent(), _make_state(), None, latest_probe_at=None)
    assert trust["cryptographic"]["last_probe_at"] is None


def test_last_probe_at_probe_overrides_even_when_obs_is_more_recent():
    """The probe timestamp always wins when explicitly supplied.

    The probe's issued_at represents actual cryptographic check activity —
    it is always more semantically correct than the observable-job run time.
    """
    recent_obs_ts = datetime(2026, 6, 12, 0, 0, 0)
    earlier_probe = datetime(2026, 6, 11, 8, 0, 0)

    obs = _make_obs(recent_obs_ts)
    trust = derive_trust(
        _make_agent(),
        _make_state(),
        obs,
        latest_probe_at=earlier_probe,
    )
    assert trust["cryptographic"]["last_probe_at"] == "2026-06-11T08:00:00Z"
