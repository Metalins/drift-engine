"""Unit tests for gh-82 — cryptographic onboarding window.

Issue #76 (Jose, 2026-06-11): a brand-new agent looked identical to a
compromised one — a big red "Not trusted" — because the memory-probe
round-trip factors (probes_failing / probes_unanswered / probes_pending)
escalate the cryptographic state before the agent has had any fair chance
to answer its first memory checks.

The fix gates those probe round-trip factors below
`CRYPTO_ONBOARDING_EVENT_FLOOR` (== TIER_T2_FLOOR, 50 events): during the
onboarding window the agent reads as `unverified` ("Setting up") and the
probe factors are calmed to `info`. Genuine tamper signals
(signature_failures) are NEVER softened — a forgery is unambiguous at any
age.

These tests bypass the DB — `derive_trust` only reads a handful of
attributes, so SimpleNamespace stand-ins are sufficient (same approach as
test_verification_state_tier_gating.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.identity_engine import (
    SCORE_FACTOR_PROBES_FAILING,
    SCORE_FACTOR_PROBES_HEALTHY,
    SCORE_FACTOR_PROBES_PENDING,
    SCORE_FACTOR_SIGNATURE_FAILURES,
)
from app.services.verification_state import (
    CRYPTO_ACTION_REQUIRED,
    CRYPTO_ONBOARDING_EVENT_FLOOR,
    CRYPTO_UNVERIFIED,
    CRYPTO_VERIFIED,
    derive_trust,
)


def _make_agent(*, is_active: bool = True, revoked: bool = False):
    return SimpleNamespace(
        is_active=is_active,
        revoked_at=None if not revoked else datetime.now(timezone.utc),
        created_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )


def _make_state(event_count: int):
    return SimpleNamespace(event_count=event_count, last_event_at=None)


def _make_obs(factors: list[dict]):
    return SimpleNamespace(
        details_json={"score_factors": factors},
        ts=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
    )


_ONBOARDING_N = max(1, CRYPTO_ONBOARDING_EVENT_FLOOR - 1)  # inside the window


# --------------------------------------------------------------------------- #
# Probe round-trip factors are gated during onboarding                        #
# --------------------------------------------------------------------------- #


def test_onboarding_probes_failing_reads_setting_up_not_compromised():
    """A failing memory probe during onboarding → `unverified` (Setting up).

    This is the core gh-82 regression: pre-fix this surfaced as
    `action_required` ("Not trusted") on a brand-new agent.
    """
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_PROBES_FAILING,
            "message": "Recent memory checks are failing.",
        },
    ]
    trust = derive_trust(_make_agent(), _make_state(_ONBOARDING_N), _make_obs(factors))
    crypto = trust["cryptographic"]
    assert crypto["state"] == CRYPTO_UNVERIFIED
    # And the customer-facing factor severity is calmed to info so the
    # "Why this score?" list doesn't read as a red alarm.
    pf = next(f for f in crypto["factors"] if f["code"] == SCORE_FACTOR_PROBES_FAILING)
    assert pf["severity"] == "info"


def test_onboarding_probes_pending_reads_setting_up():
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_PROBES_PENDING,
            "message": "memory check pending.",
        },
    ]
    trust = derive_trust(_make_agent(), _make_state(_ONBOARDING_N), _make_obs(factors))
    assert trust["cryptographic"]["state"] == CRYPTO_UNVERIFIED


def test_onboarding_clean_agent_is_setting_up_not_verified():
    """A fresh agent with no positive probe signal stays `unverified`.

    We no longer optimistically claim `verified` off the bare signed-event
    chain during onboarding — the honest state is "Setting up".
    """
    trust = derive_trust(_make_agent(), _make_state(5), _make_obs([]))
    assert trust["cryptographic"]["state"] == CRYPTO_UNVERIFIED


def test_onboarding_probes_healthy_graduates_to_verified():
    """A clean probe answer during onboarding is a real positive → verified."""
    factors = [
        {
            "severity": "good",
            "code": SCORE_FACTOR_PROBES_HEALTHY,
            "message": "memory checks healthy.",
        },
    ]
    trust = derive_trust(_make_agent(), _make_state(_ONBOARDING_N), _make_obs(factors))
    assert trust["cryptographic"]["state"] == CRYPTO_VERIFIED


# --------------------------------------------------------------------------- #
# Genuine tamper is NEVER softened by onboarding                              #
# --------------------------------------------------------------------------- #


def test_onboarding_signature_failure_still_action_required():
    """A forged signature escalates from event #1 — onboarding is no excuse."""
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_SIGNATURE_FAILURES,
            "message": "signed events failed validation.",
        },
    ]
    trust = derive_trust(_make_agent(), _make_state(_ONBOARDING_N), _make_obs(factors))
    crypto = trust["cryptographic"]
    assert crypto["state"] == CRYPTO_ACTION_REQUIRED
    # Tamper severity is preserved (not calmed).
    sf = next(
        f for f in crypto["factors"] if f["code"] == SCORE_FACTOR_SIGNATURE_FAILURES
    )
    assert sf["severity"] == "warning"


# --------------------------------------------------------------------------- #
# The gate lifts once the agent crosses the onboarding floor                  #
# --------------------------------------------------------------------------- #


def test_past_onboarding_probes_failing_escalates_again():
    """At/above the onboarding floor a failing probe is a real signal again."""
    factors = [
        {
            "severity": "warning",
            "code": SCORE_FACTOR_PROBES_FAILING,
            "message": "Recent memory checks are failing.",
        },
    ]
    trust = derive_trust(
        _make_agent(),
        _make_state(CRYPTO_ONBOARDING_EVENT_FLOOR),
        _make_obs(factors),
    )
    crypto = trust["cryptographic"]
    assert crypto["state"] == CRYPTO_ACTION_REQUIRED
    pf = next(f for f in crypto["factors"] if f["code"] == SCORE_FACTOR_PROBES_FAILING)
    assert pf["severity"] == "warning"
