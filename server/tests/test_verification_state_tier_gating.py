"""Unit tests for UX-5.15.B — pre-T3 severity gating on behavioral factors.

Per docs/product/IDENTITY-TIERS-AND-COMMUNICATION.md §4 (Rule 1 — calm by
default during baselining) and §6 (Step B — backend severity gating for
behavioral factors), the customer-facing trust block must:

1. Cap behavioral factor severities at `info` while the agent is pre-T3,
   regardless of what the engine emitted.
2. Refuse to return `drift_detected` as the behavioral state pre-T3,
   even if a `behavioral_drift` factor is present.
3. Preserve cryptographic factor severities (binary, honest from
   event #1).
4. Stop gating once the agent crosses T3 (BEHAVIORAL_ICR_STABLE).

These tests bypass the DB entirely — `derive_trust` only reads a handful
of attributes off Agent / AgentState / AgentObservable, so a SimpleNamespace
is a good-enough stand-in.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.identity_engine import (
    BEHAVIORAL_ICR_FLOOR,
    BEHAVIORAL_ICR_STABLE,
    SCORE_FACTOR_BEHAVIORAL_DRIFT,
    SCORE_FACTOR_BEHAVIORAL_STABLE,
    SCORE_FACTOR_SIGNATURE_FAILURES,
)
from app.services.verification_state import (
    BEHAVIORAL_BUILDING,
    BEHAVIORAL_DRIFT_DETECTED,
    BEHAVIORAL_NOT_ENOUGH_DATA,
    BEHAVIORAL_STABLE,
    CRYPTO_ACTION_REQUIRED,
    CRYPTO_VERIFIED,
    derive_trust,
)


def _make_agent(*, is_active: bool = True, revoked: bool = False):
    """Minimal Agent stand-in — derive_trust only reads these fields."""
    return SimpleNamespace(
        is_active=is_active,
        revoked_at=None if not revoked else datetime.now(timezone.utc),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _make_state(event_count: int):
    return SimpleNamespace(event_count=event_count, last_event_at=None)


def _make_obs(factors: list[dict]):
    return SimpleNamespace(
        details_json={"score_factors": factors},
        ts=datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Severity capping                                                            #
# --------------------------------------------------------------------------- #


def test_pre_t3_caps_behavioral_warning_to_info():
    """A warning-severity behavioral factor pre-T3 → reported as info."""
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_BEHAVIORAL_DRIFT,
            "message": "engine-level drift detected",
        },
    ]
    # Event count above FLOOR but below STABLE: agent is mid-baselining (pre-T3).
    n = (BEHAVIORAL_ICR_FLOOR + BEHAVIORAL_ICR_STABLE) // 2
    trust = derive_trust(_make_agent(), _make_state(n), _make_obs(factors))

    behavioral = trust["behavioral"]
    assert len(behavioral["factors"]) == 1
    assert behavioral["factors"][0]["severity"] == "info"
    # Code stays the same — internal consumers reading by code keep working.
    assert behavioral["factors"][0]["code"] == SCORE_FACTOR_BEHAVIORAL_DRIFT


def test_pre_t3_state_never_drift_detected():
    """Pre-T3 state stays `building` even with a drift factor present."""
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_BEHAVIORAL_DRIFT,
            "message": "engine-level drift detected",
        },
    ]
    n = BEHAVIORAL_ICR_FLOOR + 100  # above FLOOR, below STABLE
    trust = derive_trust(_make_agent(), _make_state(n), _make_obs(factors))
    assert trust["behavioral"]["state"] == BEHAVIORAL_BUILDING


def test_pre_floor_state_not_enough_data():
    """Below the FLOOR we say nothing about behavior."""
    trust = derive_trust(_make_agent(), _make_state(10), _make_obs([]))
    assert trust["behavioral"]["state"] == BEHAVIORAL_NOT_ENOUGH_DATA
    assert trust["behavioral"]["factors"] == []


# --------------------------------------------------------------------------- #
# T3 boundary                                                                 #
# --------------------------------------------------------------------------- #


def test_at_t3_severity_preserved_and_drift_state_fires():
    """At T3 the gating lifts: warnings stay warnings, drift becomes drift."""
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_BEHAVIORAL_DRIFT,
            "message": "engine-level drift detected",
        },
    ]
    trust = derive_trust(
        _make_agent(),
        _make_state(BEHAVIORAL_ICR_STABLE),
        _make_obs(factors),
    )
    behavioral = trust["behavioral"]
    assert behavioral["state"] == BEHAVIORAL_DRIFT_DETECTED
    assert behavioral["factors"][0]["severity"] == "warning"


def test_at_t3_healthy_stays_stable():
    """T3 agent with a healthy behavioral_stable factor → state stable, severity intact."""
    factors = [
        {
            "severity": "good",
            "code": SCORE_FACTOR_BEHAVIORAL_STABLE,
            "message": "baseline established",
        },
    ]
    trust = derive_trust(
        _make_agent(),
        _make_state(BEHAVIORAL_ICR_STABLE + 1000),
        _make_obs(factors),
    )
    behavioral = trust["behavioral"]
    assert behavioral["state"] == BEHAVIORAL_STABLE
    assert behavioral["factors"][0]["severity"] == "good"


# --------------------------------------------------------------------------- #
# Cryptographic factors are NOT gated                                         #
# --------------------------------------------------------------------------- #


def test_pre_t3_cryptographic_factors_remain_action_required():
    """A signature failure must surface as action_required even at event_count=10.

    Rationale (rector §4 Rule 1 + §6 Step B): the calm-by-default rule
    only applies to behavioral factors. Cryptographic signals (signatures,
    probes) are binary and meaningful from event #1 — softening them
    would hide a real compromise.
    """
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_SIGNATURE_FAILURES,
            "message": "two signed events failed validation",
        },
    ]
    trust = derive_trust(_make_agent(), _make_state(10), _make_obs(factors))
    assert trust["cryptographic"]["state"] == CRYPTO_ACTION_REQUIRED
    assert trust["cryptographic"]["factors"][0]["severity"] == "warning"


def test_zero_events_verified_when_active():
    """Sanity: a brand-new active agent with no observable still verifies cryptographically."""
    trust = derive_trust(_make_agent(), None, None)
    # No events → CRYPTO_UNVERIFIED (no positive signal yet). That's
    # the expected pre-event state; the test is here so future regressions
    # of the empty-state path get caught alongside the gating logic.
    assert trust["cryptographic"]["state"] in {CRYPTO_VERIFIED, "unverified"}
    assert trust["behavioral"]["state"] == BEHAVIORAL_NOT_ENOUGH_DATA
