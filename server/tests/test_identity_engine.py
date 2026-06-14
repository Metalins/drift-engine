"""Unit tests for the Trinity observables identity engine.

These are sanity tests on the math, not the AUC-level validation from
R4-R12. The goal is: prove the engine functions return sensible values
on canonical traces.
"""
from __future__ import annotations

import hashlib
import random

import pytest

from app.services.identity_engine import (
    BEHAVIORAL_ICR_FLOOR,
    DEFAULT_ALPHABET,
    compute_icr,
    compute_ttm,
    compute_trinity,
    compute_twc,
    events_to_traces,
    identity_confidence_v0,
)


# --------------------------------------------------------------------------- #
# ICR — Sprint UX-5.12 contract                                               #
# --------------------------------------------------------------------------- #
#
# Sprint UX-5.12 changed the contract of compute_icr:
#   - Below BEHAVIORAL_ICR_FLOOR samples, returns None ("not enough data")
#     instead of fabricating a number from a biased estimator. Callers
#     translate None into "behavioral baseline: building" in the UI.
#   - At or above the floor, applies Miller-Madow finite-sample bias
#     correction. Random/independent traffic now lands close to 0 instead
#     of the inflated 0.4-0.6 it used to produce at N=200.
#   - Negative corrected values are clamped to 0; values are clamped to
#     [0, 1] since they're conceptually a ratio.
# See docs/product/TWO-LAYER-TRUST-DESIGN.md §5 + the Exp-CvD verdict.

def test_icr_identity_is_one_above_floor():
    """y = x at N >= FLOOR → MI(X, Y) ≈ H(X) → ICR ≈ 1.0."""
    rng = random.Random(0)
    X = [rng.randint(0, 31) for _ in range(BEHAVIORAL_ICR_FLOOR)]
    Y = X[:]
    icr = compute_icr(X, Y)
    assert icr is not None
    # With perfect coupling at N=FLOOR, the Miller-Madow correction
    # subtracts a tiny ~0.008 bias from the raw ICR of 1.0; clamp keeps
    # it ≤ 1.0. We just assert ≥ 0.99 — far above any noise floor.
    assert icr >= 0.99, f"expected ICR ≈ 1.0, got {icr}"


def test_icr_deterministic_function_is_high_above_floor():
    """y = f(x) deterministic at N >= FLOOR → ICR ≈ 1.0."""
    rng = random.Random(0)
    X = [rng.randint(0, 31) for _ in range(BEHAVIORAL_ICR_FLOOR)]
    Y = [(7 * x + 3) % 32 for x in X]
    icr = compute_icr(X, Y)
    assert icr is not None
    assert icr >= 0.99, f"expected high ICR, got {icr}"


def test_icr_independent_is_near_zero_after_correction():
    """y independent of x → ICR ≈ 0 after Miller-Madow correction.

    Pre-Sprint UX-5.12 this returned ~0.16 at N=1000 due to finite-sample
    MI bias. With the correction in place, the residual is well under
    the 0.05 dead-zone threshold even at the floor.
    """
    rng = random.Random(0)
    X = [rng.randint(0, 31) for _ in range(BEHAVIORAL_ICR_FLOOR)]
    Y = [rng.randint(0, 31) for _ in range(BEHAVIORAL_ICR_FLOOR)]
    icr = compute_icr(X, Y)
    assert icr is not None
    assert 0.0 <= icr < 0.10, f"expected small post-correction ICR, got {icr}"


def test_icr_below_floor_returns_none():
    """N below the floor MUST return None — we don't fake a number when
    the sample is too small to trust the estimator. This is the central
    Sprint UX-5.12 contract change.
    """
    rng = random.Random(0)
    for n in (0, 2, 100, 500, BEHAVIORAL_ICR_FLOOR - 1):
        X = [rng.randint(0, 31) for _ in range(n)]
        Y = X[:]  # perfect coupling — would have been ICR=1.0 pre-5.12
        assert compute_icr(X, Y) is None, (
            f"N={n}: expected None below floor, got {compute_icr(X, Y)}"
        )


def test_icr_returns_none_on_length_mismatch():
    """Mismatched-length inputs are a caller bug; return None, never fake."""
    assert compute_icr([1, 2, 3], [1, 2]) is None


# --------------------------------------------------------------------------- #
# TWC                                                                         #
# --------------------------------------------------------------------------- #

def test_twc_returns_finite_with_enough_data():
    rng = random.Random(0)
    n = 1500
    X = [rng.randint(0, 31) for _ in range(n)]
    Y = [(x + rng.randint(0, 1)) % 32 for x in X]
    twc, beta = compute_twc(X, Y)
    assert beta > 0
    assert twc != 0 or beta == 1.0  # may be 0 if Crooks data degenerate


def test_twc_too_short_returns_neutral():
    twc, beta = compute_twc([1, 2, 3], [1, 2, 3])
    assert twc == 0.0
    assert beta == 1.0


# --------------------------------------------------------------------------- #
# TTM                                                                         #
# --------------------------------------------------------------------------- #

def test_ttm_iid_uniform_has_high_gap():
    """An iid uniform sequence has transition matrix ≈ uniform-row → gap ≈ 1."""
    rng = random.Random(0)
    Y = [rng.randint(0, 31) for _ in range(3000)]
    gap = compute_ttm(Y)
    assert gap > 0.5, f"expected high gap for iid uniform, got {gap}"


def test_ttm_perfectly_periodic_is_zero_gap():
    """Period-4 sequence has eigenvalue ≈ ±1 → gap ≈ 0."""
    Y = [i % 4 for i in range(2000)]
    gap = compute_ttm(Y)
    assert gap < 0.05, f"expected near-zero gap for periodic, got {gap}"


def test_ttm_too_short_returns_zero():
    assert compute_ttm([1, 2, 3, 4]) == 0.0


# --------------------------------------------------------------------------- #
# Aggregator + Identity Confidence                                            #
# --------------------------------------------------------------------------- #

def _make_events(n: int, coupled: bool, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    events: list[dict] = []
    for i in range(n):
        c = rng.randint(0, 31)
        r = (7 * c + 3) % 32 if coupled else rng.randint(0, 31)
        events.append({
            "input_hash": hashlib.sha256(f"ch{c}".encode()).hexdigest(),
            "output_hash": hashlib.sha256(f"rs{r}".encode()).hexdigest(),
        })
    return events


def test_compute_trinity_empty():
    res = compute_trinity([])
    assert res.icr is None
    assert res.twc is None
    assert res.ttm is None
    assert res.n_events == 0
    assert res.identity_confidence == 0.0


def test_compute_trinity_short_window():
    """Sprint UX-5.12: at low N, ICR is None ("not enough data"), not a number.
    That's the whole point of the floor.
    """
    events = _make_events(10, coupled=True)
    res = compute_trinity(events)
    assert res.icr is None
    assert res.ttm is None
    assert res.twc is None


def test_compute_trinity_full_window_coupled():
    """At N >= BEHAVIORAL_ICR_FLOOR with deterministic coupling, ICR is
    strong and identity_confidence climbs out of the dead zone.
    """
    events = _make_events(BEHAVIORAL_ICR_FLOOR, coupled=True)
    res = compute_trinity(events)
    # ICR after hash-bucketing isn't 1.0 (sha256 mod-32 isn't bijective with
    # the original c→r function), but the deterministic coupling still gives
    # strong MI — well above the post-correction noise floor.
    assert res.icr is not None and res.icr > 0.5, f"got icr={res.icr}"
    assert res.ttm is not None
    assert res.identity_confidence > 0.2


def test_compute_trinity_separates_coupled_from_independent():
    """The whole point: coupled traces score higher than independent ones,
    AND the bias-corrected baseline lets us see the gap clearly.
    """
    coupled = compute_trinity(
        _make_events(BEHAVIORAL_ICR_FLOOR, coupled=True, seed=1)
    )
    independent = compute_trinity(
        _make_events(BEHAVIORAL_ICR_FLOOR, coupled=False, seed=1)
    )
    assert coupled.icr is not None and independent.icr is not None
    assert coupled.icr > independent.icr + 0.2, (
        f"coupled.icr={coupled.icr} vs independent.icr={independent.icr}"
    )
    assert coupled.identity_confidence > independent.identity_confidence


def test_events_to_traces_deterministic():
    e = [
        {"input_hash": "deadbeef00", "output_hash": "cafe1234"},
        {"input_hash": "deadbeef00", "output_hash": "cafe1234"},
    ]
    X1, Y1 = events_to_traces(e)
    X2, Y2 = events_to_traces(e)
    assert X1 == X2 and Y1 == Y2
    assert X1[0] == X1[1]  # same hash → same symbol


# --------------------------------------------------------------------------- #
# Identity Confidence v0                                                      #
# --------------------------------------------------------------------------- #

def test_identity_confidence_zero_at_zero_events():
    assert identity_confidence_v0(1.0, 1.0, 1.0, 0) == 0.0


def test_identity_confidence_grows_with_events():
    low = identity_confidence_v0(0.8, 1.0, 0.3, 50)
    mid = identity_confidence_v0(0.8, 1.0, 0.3, 500)
    hi = identity_confidence_v0(0.8, 1.0, 0.3, 5000)
    assert low < mid < hi


def test_identity_confidence_zero_signals_is_zero():
    assert identity_confidence_v0(0.0, 0.0, 0.0, 1000) == 0.0


def test_identity_confidence_bounded():
    c = identity_confidence_v0(1.0, 2.0, 0.5, 100_000)
    assert 0.0 <= c <= 1.0


# --------------------------------------------------------------------------- #
# explain_score — probe-capability gate (gh-80)                               #
# --------------------------------------------------------------------------- #
#
# Round-trip mechanisms (MVS/C2, ADV/B4, PRS/B2, ZKH/C5, TLS/B3, MCS/C4)
# only produce signal when the agent runs a probe-capable client. For a V1
# MCP-prompt agent (has_probe_client=False) these layers are structurally
# absent and explain_score must emit NO factor for them — matching what the
# protections catalog hides. Event-stream layers (RKS signatures, ICR
# behavioral) are never probe-gated.

# Codes that depend on a probe-capable client.
_PROBE_DEPENDENT_CODES = {
    "probes_failing",
    "probes_unanswered",
    "probes_pending",
    "probes_healthy",
    "protocol_unaware",   # ADV
    "low_self_prediction",  # PRS
    "mesh_disagreement",  # MCS
    "timing_drift",       # TLS
    "history_integrity",  # ZKH
}


def _failing_probe_inputs():
    """Scalars that would each trip a round-trip warning factor."""
    return dict(
        icr=None, twc=None, ttm=None,
        mvs=0.1,                  # < MVS_VETO_THRESHOLD → probes_failing
        n_events=100,
        pending_probes_count=3,   # → probes_pending (if mcp activity)
        identity_confidence=0.5,
        has_mcp_activity=True,
        adv=0.1,                  # < 0.7 → protocol_unaware
        prs=0.1,                  # < 0.4 → low_self_prediction
        mcs=0.1,                  # < 0.7 → mesh_disagreement
        tls=0.1,                  # < 0.7 → timing_drift
        zkh=0.1,                  # < 0.9 → history_integrity
    )


def test_explain_score_suppresses_probe_factors_without_probe_client():
    """gh-80 — an agent without a probe-capable client must never see any
    round-trip factor, even when every underlying score looks 'failing'."""
    from app.services.identity_engine import explain_score

    factors = explain_score(has_probe_client=False, **_failing_probe_inputs())
    codes = {(f or {}).get("code") for f in factors}
    assert not (codes & _PROBE_DEPENDENT_CODES), (
        f"probe-dependent factors leaked without a probe client: "
        f"{codes & _PROBE_DEPENDENT_CODES}"
    )


def test_explain_score_emits_probe_factors_with_probe_client():
    """The same failing scores DO surface once the agent has a probe client —
    proves the gate suppresses, not the thresholds being unreachable."""
    from app.services.identity_engine import explain_score

    factors = explain_score(has_probe_client=True, **_failing_probe_inputs())
    codes = {(f or {}).get("code") for f in factors}
    assert codes & _PROBE_DEPENDENT_CODES, (
        "expected round-trip factors with a probe client, got none"
    )


def test_explain_score_signature_factor_not_probe_gated():
    """RKS (signature failures) is an event-stream layer — it must surface
    regardless of probe-client status."""
    from app.services.identity_engine import explain_score

    base = dict(
        icr=None, twc=None, ttm=None, mvs=None,
        n_events=100, pending_probes_count=0,
        identity_confidence=0.5, rks=0.5,  # < 0.95 → signature_failures
    )
    factors = explain_score(has_probe_client=False, **base)
    codes = {(f or {}).get("code") for f in factors}
    assert "signature_failures" in codes


# --------------------------------------------------------------------------- #
# factor_guidance — learn_more context (gh-81)                                #
# --------------------------------------------------------------------------- #
#
# Every warning factor a customer can see must carry a `learn_more` triplet
# (what it means / is it a real problem / next step) so the dashboard and the
# developer API can explain the alert instead of leaving a lone sentence.


# Warning codes that explain_score can emit to the customer-facing surface.
_GUIDED_WARNING_CODES = {
    "behavioral_drift",
    "profile_mismatch",
    "probes_unanswered",
    "probes_failing",
    "signature_failures",
    "timing_drift",
    "protocol_unaware",
    "low_self_prediction",
    "mesh_disagreement",
    "history_integrity",
}


def test_factor_guidance_shape_for_every_warning_code():
    """gh-81 — each warning code resolves to a learn_more triplet with all
    three non-empty pieces."""
    from app.services.identity_engine import factor_guidance

    for code in _GUIDED_WARNING_CODES:
        g = factor_guidance(code)
        assert g is not None, f"no guidance for warning code {code!r}"
        assert set(g) == {"what", "self_resolving", "action"}, code
        assert all(isinstance(v, str) and v.strip() for v in g.values()), code


def test_factor_guidance_unknown_and_positive_codes_return_none():
    """Codes with nothing to advise — unknown, or the positive
    `probes_healthy` / `behavioral_stable` — return None, not an empty dict."""
    from app.services.identity_engine import factor_guidance

    assert factor_guidance(None) is None
    assert factor_guidance("") is None
    assert factor_guidance("not_a_real_code") is None
    assert factor_guidance("probes_healthy") is None
    assert factor_guidance("behavioral_stable") is None


def test_factor_guidance_returns_a_copy():
    """Callers attach the guidance to factor dicts; mutating one result must
    not corrupt the shared catalog."""
    from app.services.identity_engine import factor_guidance

    a = factor_guidance("probes_failing")
    a["action"] = "mutated"
    b = factor_guidance("probes_failing")
    assert b["action"] != "mutated"


def test_explain_score_warning_factors_have_guidance_available():
    """Every warning factor explain_score emits for a probe-capable agent has
    curated guidance — i.e. the catalog stays in sync with the engine."""
    from app.services.identity_engine import explain_score, factor_guidance

    factors = explain_score(has_probe_client=True, **_failing_probe_inputs())
    warnings = [f for f in factors if (f or {}).get("severity") == "warning"]
    assert warnings, "expected at least one warning factor"
    for f in warnings:
        assert factor_guidance(f.get("code")) is not None, (
            f"warning factor {f.get('code')!r} has no learn_more guidance"
        )


# --------------------------------------------------------------------------- #
# gh-84 — behavioral_drift SDK gate                                            #
# --------------------------------------------------------------------------- #
#
# SDK agents (has_probe_client=True) log events through the SDK API, not
# through an MCP conversation channel. ICR-based I/O coupling is designed for
# chat/MCP-style request→response pairs; SDK agents have a different event
# structure and low ICR is not evidence of drift. behavioral_drift must NOT
# be emitted for them regardless of the ICR value.


def _sdk_agent_low_icr_inputs():
    """Inputs for an SDK agent that would trigger behavioral_drift without
    the gh-84 gate: ICR well below _COUPLING_DEAD, enough events to pass
    BEHAVIORAL_ICR_FLOOR, and has_mcp_activity=True (as _detect_integration
    mistakenly sets for SDK agents whose events exceed watcher_events=0)."""
    from app.services.identity_engine import BEHAVIORAL_ICR_FLOOR
    return dict(
        icr=0.0,                          # dead coupling — would normally trip drift
        twc=None, ttm=None, mvs=None,
        n_events=BEHAVIORAL_ICR_FLOOR + 100,
        pending_probes_count=0,
        identity_confidence=0.4,
        has_watcher=False,
        has_mcp_activity=True,            # mis-set by _detect_integration for SDK agents
    )


def test_behavioral_drift_suppressed_for_sdk_agent():
    """gh-84 — SDK agents (has_probe_client=True) must never emit
    behavioral_drift, even when ICR is dead-zero and has_mcp_activity is
    mis-set to True by _detect_integration."""
    from app.services.identity_engine import explain_score

    factors = explain_score(has_probe_client=True, **_sdk_agent_low_icr_inputs())
    codes = {(f or {}).get("code") for f in factors}
    assert "behavioral_drift" not in codes, (
        "behavioral_drift must be suppressed for SDK agents (has_probe_client=True)"
    )


def test_behavioral_drift_still_fires_for_mcp_agent():
    """gh-84 — the gate must NOT suppress behavioral_drift for genuine MCP
    agents (has_probe_client=False). Regression guard."""
    from app.services.identity_engine import explain_score

    factors = explain_score(has_probe_client=False, **_sdk_agent_low_icr_inputs())
    codes = {(f or {}).get("code") for f in factors}
    assert "behavioral_drift" in codes, (
        "behavioral_drift must still fire for MCP agents (has_probe_client=False)"
    )


def test_behavioral_drift_no_mcp_message_for_sdk_agent():
    """gh-84 — when an SDK agent somehow still emits a factor (future change),
    it must not contain MCP-specific copy. Belt-and-suspenders: if the gate
    ever gets removed, the message must also not blame MCP."""
    from app.services.identity_engine import explain_score

    factors = explain_score(has_probe_client=True, **_sdk_agent_low_icr_inputs())
    for f in factors:
        if (f or {}).get("code") == "behavioral_drift":
            msg = (f or {}).get("message", "")
            assert "MCP-logged activity" not in msg, (
                "MCP-specific drift copy must not appear for an SDK agent"
            )
