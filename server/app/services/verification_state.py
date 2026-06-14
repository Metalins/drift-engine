"""Two-layer trust derivation — single source of truth.

Sprint UX-5.12 replaces the old single-state machine (6 states from
empty→verified) with two independent layers, per
docs/product/TWO-LAYER-TRUST-DESIGN.md.

Sprint UX-5.15.B layers a calm-by-default rule on top: behavioral-
layer factor severities are capped at `info` while the agent is
pre-T3, and the behavioral state machine refuses to emit
`drift_detected` until the stable-baseline floor is crossed. Internal
consumers (alert pipeline, webhooks, score history persisted in
`details_json`) keep the raw severities; only the customer-facing
`trust.behavioral.factors` field gets the gated values. See
docs/product/IDENTITY-TIERS-AND-COMMUNICATION.md §4 (Rule 1) and §6
(Step B).

Layer 1 — Cryptographic identity (MVS / RKS / ZKH / mesh / probes)
  state ∈ {verified, unverified, caution, action_required, revoked}
  Binary signal. Available from event #1. Never susceptible to
  finite-sample bias because it's driven by cryptographic checks,
  not statistical estimators.

Layer 2 — Behavioral baseline (ICR / TWC / TTM, bias-corrected)
  state ∈ {not_enough_data, building, stable, drift_detected}
  Gradual signal. Honest about needing samples — refuses to make
  claims below BEHAVIORAL_ICR_FLOOR events. Drift detection only
  fires once we're in the `stable` regime.

The two states never compose into a single score. The dashboard shows
them side-by-side. See §3 of the design doc for the cross-cutting rules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.models import Agent, AgentObservable, AgentState
from app.services.identity_engine import (
    BEHAVIORAL_ICR_FLOOR,
    BEHAVIORAL_ICR_STABLE,
    LAYER_BEHAVIORAL,
    LAYER_CRYPTOGRAPHIC,
    LAYER_OF_FACTOR,
    SCORE_FACTOR_BEHAVIORAL_DRIFT,
    SCORE_FACTOR_PROBES_FAILING,
    SCORE_FACTOR_PROBES_PENDING,
    SCORE_FACTOR_PROBES_UNANSWERED,
    SCORE_FACTOR_SIGNATURE_FAILURES,
    SCORE_FACTOR_MESH_DISAGREEMENT,
    SCORE_FACTOR_HISTORY_INTEGRITY,
    factor_guidance,
)


# State string constants — exported so api/public.py and downstream
# clients can reason about them without hard-coding strings.

# Cryptographic layer
CRYPTO_VERIFIED = "verified"
CRYPTO_UNVERIFIED = "unverified"
CRYPTO_CAUTION = "caution"
CRYPTO_ACTION_REQUIRED = "action_required"
CRYPTO_REVOKED = "revoked"

# Behavioral layer
BEHAVIORAL_NOT_ENOUGH_DATA = "not_enough_data"
BEHAVIORAL_BUILDING = "building"
BEHAVIORAL_STABLE = "stable"
BEHAVIORAL_DRIFT_DETECTED = "drift_detected"


# Severities that promote a cryptographic factor to `action_required`.
# Anything `warning` lands the agent in `caution` instead.
_ACTION_REQUIRED_CODES = {
    SCORE_FACTOR_PROBES_FAILING,
    SCORE_FACTOR_SIGNATURE_FAILURES,
}


# gh-82 — onboarding window for the cryptographic layer.
#
# Issue #76 (Jose, 2026-06-11): a brand-new agent looked identical to a
# compromised one — big red "Not trusted", because the memory-probe
# round-trip factors (probes_failing / probes_unanswered / probes_pending)
# escalate the cryptographic state to `action_required`/`caution` before
# the agent has had any fair chance to establish its memory baseline.
#
# Below TIER_T2_FLOOR (50 events — "first memory probe, behavioral signals
# emerging") the probe machinery hasn't meaningfully kicked in yet, so an
# early missed or mismatched probe is far more likely to be onboarding /
# integration noise than a real compromise. During this window we keep the
# agent at `unverified` ("Setting up") instead of screaming compromise, and
# we calm the probe factors' customer-facing severity to `info`.
#
# Crucially this gate is SCOPED to probe round-trip factors. A forged
# `signature_failures` (and mesh/history-integrity tamper signals) is
# unambiguous at any age and still escalates from event #1 — onboarding is
# never an excuse to hide a genuine cryptographic forgery.
CRYPTO_ONBOARDING_EVENT_FLOOR = 50  # == TIER_T2_FLOOR

# Probe round-trip factors — the ones whose meaning depends on the agent
# having accumulated enough history for a memory check to be fair.
_PROBE_ROUNDTRIP_CODES = {
    SCORE_FACTOR_PROBES_FAILING,
    SCORE_FACTOR_PROBES_UNANSWERED,
    SCORE_FACTOR_PROBES_PENDING,
}


# Sprint UX-5.15.B — severity gating for behavioral factors.
#
# Per docs/product/IDENTITY-TIERS-AND-COMMUNICATION.md §4 Rule 1 (calm by
# default during baselining) and §6 Step B: pre-T3, behavioral factors
# max out at severity `info`. The factor codes stay the same — internal
# consumers (alert pipeline, webhooks, score history, observable rows)
# don't break; only the customer-visible rendering changes.
#
# T3 corresponds to the engine's stable-baseline floor. Below that point
# the behavioral fingerprint is not yet trustworthy enough for a
# `warning` or `action` severity to be honest — the rector explicitly
# forbids "Drift detected" / "Something changed worth a look" pre-T3.
#
# Cryptographic-layer factors are NOT gated. Signature failures and
# probe failures are binary and meaningful from event #1; surfacing them
# as `action_required` on a brand-new agent is the right behavior.
_PRE_T3_BEHAVIORAL_SEVERITY_CAP = "info"
_GATED_BEHAVIORAL_SEVERITIES = {"warning", "action"}


def _has_reached_t3(event_count: int) -> bool:
    """Whether the agent has crossed the T3 floor (Full coverage).

    T3 is the highest tier — the point at which the behavioral baseline
    is stable enough to support drift claims. The threshold is the same
    one `_derive_behavioral_state` uses to gate `BEHAVIORAL_STABLE`, so
    severity gating and state derivation stay in lockstep.
    """
    return event_count >= BEHAVIORAL_ICR_STABLE


def _gate_behavioral_severity(
    factors: list[dict],
    *,
    pre_t3: bool,
) -> list[dict]:
    """Cap behavioral factor severities at `info` when the agent is pre-T3.

    Sprint UX-5.15.B. Returns a NEW list (caller's input is not mutated)
    so callers persisting the engine-level severity in `details_json`
    keep the raw value. Only the customer-facing copy is downgraded.
    """
    if not pre_t3:
        return factors
    capped: list[dict] = []
    for f in factors:
        sev = (f or {}).get("severity")
        if sev in _GATED_BEHAVIORAL_SEVERITIES:
            new_f = dict(f)
            new_f["severity"] = _PRE_T3_BEHAVIORAL_SEVERITY_CAP
            capped.append(new_f)
        else:
            capped.append(f)
    return capped


def _gate_probe_severity_onboarding(
    factors: list[dict],
    *,
    onboarding: bool,
) -> list[dict]:
    """Calm probe round-trip factor severities to `info` during onboarding.

    gh-82. The companion to the cryptographic state gate in
    `_derive_cryptographic_state`: when the agent is still onboarding we
    not only keep the headline at "Setting up", we also downgrade the
    customer-facing severity of the probe round-trip factors
    (probes_failing / probes_unanswered / probes_pending) from
    `warning`/`action` to `info`, so the "Why this score?" list reads as
    calm setup context rather than red alarms.

    Returns a NEW list — the persisted `details_json.score_factors` and any
    internal consumer keep the raw engine severity. Non-probe cryptographic
    factors (signature_failures et al.) are never touched.
    """
    if not onboarding:
        return factors
    calmed: list[dict] = []
    for f in factors:
        code = (f or {}).get("code")
        sev = (f or {}).get("severity")
        if code in _PROBE_ROUNDTRIP_CODES and sev in _GATED_BEHAVIORAL_SEVERITIES:
            new_f = dict(f)
            new_f["severity"] = _PRE_T3_BEHAVIORAL_SEVERITY_CAP
            calmed.append(new_f)
        else:
            calmed.append(f)
    return calmed


def _partition_factors_by_layer(
    factors: list[dict[str, Any]],
) -> tuple[list[dict], list[dict]]:
    """Split factors into (cryptographic, behavioral) lists.

    Anything missing from LAYER_OF_FACTOR is treated as internal-only
    and dropped from BOTH lists. This is how Sprint UX-5.12 hides
    `no_io_coupling` / `weak_io_coupling` / `low_volume` /
    `well_established` from the customer surface — they have a layer
    of None and get filtered out here.
    """
    crypto: list[dict] = []
    behavioral: list[dict] = []
    for f in factors:
        code = (f or {}).get("code")
        if not code:
            continue
        layer = LAYER_OF_FACTOR.get(code)
        if layer == LAYER_CRYPTOGRAPHIC:
            crypto.append(f)
        elif layer == LAYER_BEHAVIORAL:
            behavioral.append(f)
        # else: internal-only — drop.
    return crypto, behavioral


def _attach_guidance(factors: list[dict]) -> list[dict]:
    """Attach the gh-81 `learn_more` triplet to each factor by its code.

    Read-time enrichment: returns NEW dicts so persisted `score_factors`
    rows are never mutated, and the guidance always reflects the current
    copy (independent of when the factor was computed and stored). Factors
    whose code has no curated guidance — e.g. the positive `probes_healthy`
    / `behavioral_stable` factors — pass through unchanged with no
    `learn_more` key.
    """
    enriched: list[dict] = []
    for f in factors:
        guidance = factor_guidance((f or {}).get("code"))
        if guidance is None:
            enriched.append(f)
        else:
            enriched.append({**f, "learn_more": guidance})
    return enriched


def _derive_cryptographic_state(
    agent: Agent,
    crypto_factors: list[dict],
    event_count: int,
) -> str:
    """Layer 1 state machine.

    Revocation is the strongest signal (always wins). After that, the
    severity of the cryptographic factors decides between verified /
    caution / action_required. An agent with zero events and no probes
    yet sits at `unverified` until the first successful probe.
    """
    if not agent.is_active or agent.revoked_at is not None:
        return CRYPTO_REVOKED

    # `event_count` is the baseline-reset-adjusted count passed by
    # derive_trust — the SAME value used for the customer-facing severity
    # gating, so the derived state and the calmed factor list never
    # disagree near the onboarding boundary (CR feedback, PR #78).
    onboarding = event_count < CRYPTO_ONBOARDING_EVENT_FLOOR

    # gh-82 — during onboarding, drop the probe round-trip factors from
    # the escalation decision. A fresh agent that hasn't answered its
    # first memory checks yet should read as "Setting up", not "Not
    # trusted". Genuine tamper signals (signature_failures and, when
    # present, mesh/history-integrity) stay in `factors_for_state` and
    # still escalate from event #1.
    factors_for_state = crypto_factors
    if onboarding:
        factors_for_state = [
            f
            for f in crypto_factors
            if (f or {}).get("code") not in _PROBE_ROUNDTRIP_CODES
        ]

    has_action = any(
        (f or {}).get("code") in _ACTION_REQUIRED_CODES
        and (f or {}).get("severity") in ("warning", "action")
        for f in factors_for_state
    )
    if has_action:
        return CRYPTO_ACTION_REQUIRED

    has_warning = any(
        (f or {}).get("severity") == "warning" for f in factors_for_state
    )
    if has_warning:
        return CRYPTO_CAUTION

    # A `good`-severity factor (e.g. probes_healthy) is the trigger for
    # `verified`. Without any positive signal we stay at `unverified`,
    # which is what fresh agents look like for the first few minutes
    # until the bootstrap probe answers come back.
    has_good = any(
        (f or {}).get("severity") == "good" for f in factors_for_state
    )
    if has_good:
        return CRYPTO_VERIFIED

    # gh-82 — while onboarding (and absent any positive probe signal),
    # hold at `unverified` ("Setting up") instead of optimistically
    # claiming `verified` off the bare signed-event chain. The agent is
    # still establishing its identity; the memory probes that earn a real
    # `verified` haven't come back yet. Once it crosses the onboarding
    # floor (or a probe answers cleanly) it graduates to `verified`.
    if onboarding:
        return CRYPTO_UNVERIFIED

    # No positive signal yet, no warnings either, AND the agent has
    # logged enough events → we trust the registration + signed event
    # chain enough to call it `verified`. The MVS bootstrap probe will
    # replace this with a stronger guarantee on its next pass.
    if event_count > 0:
        return CRYPTO_VERIFIED
    return CRYPTO_UNVERIFIED


def _derive_behavioral_state(
    event_count: int,
    behavioral_factors: list[dict],
) -> str:
    """Layer 2 state machine.

    Sample-size driven. Below BEHAVIORAL_ICR_FLOOR we say nothing.
    Between FLOOR and STABLE we say "building" — the engine has a
    number but it's a soft signal. At/above STABLE we either say
    `stable` (no drift) or `drift_detected` (a behavioral_drift
    factor has been emitted by explain_score).

    Sprint UX-5.15.B — pre-T3 (event_count < BEHAVIORAL_ICR_STABLE) we
    never return `drift_detected`. The rector (IDENTITY-TIERS-AND-
    COMMUNICATION.md §4) is explicit: "Drift detected" is forbidden
    pre-T3, even if true at the engine level, because the baseline
    isn't yet trustworthy enough for the call to be honest. The drift
    factor code stays in the underlying list (internal consumers still
    see it), but the customer-facing state stays at `building`.
    """
    if event_count < BEHAVIORAL_ICR_FLOOR:
        return BEHAVIORAL_NOT_ENOUGH_DATA

    # Pre-T3 short-circuit. Even if explain_score emitted a drift
    # factor, we don't elevate the state — the baseline is too young
    # for the verdict to be defensible.
    if event_count < BEHAVIORAL_ICR_STABLE:
        return BEHAVIORAL_BUILDING

    has_drift = any(
        (f or {}).get("code") == SCORE_FACTOR_BEHAVIORAL_DRIFT
        for f in behavioral_factors
    )
    if has_drift:
        return BEHAVIORAL_DRIFT_DETECTED
    return BEHAVIORAL_STABLE


def derive_trust(
    agent: Agent,
    state: AgentState | None,
    latest_obs: AgentObservable | None,
    *,
    latest_probe_at: datetime | None = None,
) -> dict[str, Any]:
    """Produce the full two-layer `trust` block for one agent.

    This is the only shape the customer sees. The dashboard, public
    verify page, and badge all consume it identically.

    Shape (per design doc §4.1):
      {
        "cryptographic": {
          "state": one of CRYPTO_*,
          "since": iso8601 | null,
          "last_probe_at": iso8601 | null,
          "factors": [{code, severity, message}, ...],
        },
        "behavioral": {
          "state": one of BEHAVIORAL_*,
          "events_observed": int,
          "events_floor": BEHAVIORAL_ICR_FLOOR,
          "events_stable": BEHAVIORAL_ICR_STABLE,
          "descriptor": "consistent" | "drifting" | null,
          "factors": [{code, severity, message}, ...],
        },
      }
    """
    # UX-5.15.P / D-PROD.25 — after a baseline reset, the behavioral
    # state machine should re-enter `not_enough_data` → `building` →
    # `stable` as if the agent were fresh. The physical event_count on
    # AgentState keeps counting (used by the digest chain and audit
    # log) but the behavioral layer counts only events accumulated
    # since the last reset.
    physical_count = state.event_count if state else 0
    reset_offset = (
        getattr(state, "baseline_reset_event_count", None) if state else None
    ) or 0
    event_count = max(0, physical_count - reset_offset)
    factors_all = (
        (latest_obs.details_json or {}).get("score_factors", [])
        if latest_obs is not None
        else []
    ) or []
    crypto_factors, behavioral_factors = _partition_factors_by_layer(factors_all)

    # Sprint UX-5.15.B — cap behavioral severities at `info` pre-T3.
    # Cryptographic factors are NOT gated (binary signals, honest from
    # event #1). The behavioral state machine reads the unmodified
    # factor list — it does its own pre-T3 gating in
    # `_derive_behavioral_state` and we keep that decision separate
    # from the customer-visible severity field.
    pre_t3 = not _has_reached_t3(event_count)
    behavioral_factors_customer = _gate_behavioral_severity(
        behavioral_factors, pre_t3=pre_t3
    )

    # gh-82 — calm the probe round-trip factors while onboarding so the
    # customer-facing crypto factor list matches the "Setting up" headline.
    onboarding = event_count < CRYPTO_ONBOARDING_EVENT_FLOOR
    crypto_factors_customer = _gate_probe_severity_onboarding(
        crypto_factors, onboarding=onboarding
    )

    crypto_state = _derive_cryptographic_state(agent, crypto_factors, event_count)
    behavioral_state = _derive_behavioral_state(event_count, behavioral_factors)

    # `since` for cryptographic: first time we believed in the agent.
    # Today the cleanest proxy is `agent.created_at` when the state is
    # `verified`. Future: track the timestamp of the first successful
    # MVS probe and use that instead. Null when the agent is unverified
    # or revoked — we don't want to imply trust we don't have.
    if crypto_state == CRYPTO_VERIFIED and agent.created_at is not None:
        since = agent.created_at.isoformat() + "Z"
    else:
        since = None

    # `last_probe_at`: timestamp of the most recent memory probe issued
    # to this agent. Using the actual probe timestamp (passed by callers
    # that have DB access) is more accurate than latest_obs.ts — the
    # observable is computed periodically and its ts can lag behind the
    # actual probe activity, or (for agents with old observables from
    # before a re-registration) reflect a completely wrong date.
    # gh-83: fall back to latest_obs.ts only when no probe timestamp is
    # available (e.g. agents that have never had a probe issued).
    last_probe_at: str | None = None
    if latest_probe_at is not None:
        # DB stores naive datetimes (UTC) — strip tz info to get a clean
        # isoformat() without "+00:00" before appending the "Z" suffix.
        last_probe_at = latest_probe_at.replace(tzinfo=None).isoformat() + "Z"
    elif latest_obs is not None and latest_obs.ts is not None:
        last_probe_at = latest_obs.ts.isoformat() + "Z"

    if behavioral_state == BEHAVIORAL_STABLE:
        descriptor = "consistent"
    elif behavioral_state == BEHAVIORAL_DRIFT_DETECTED:
        descriptor = "drifting"
    else:
        descriptor = None

    return {
        "cryptographic": {
            "state": crypto_state,
            "since": since,
            "last_probe_at": last_probe_at,
            # gh-81 — each customer-facing factor carries a `learn_more`
            # triplet (what it means / is it a problem / next step) so the
            # dashboard and developer API can explain the alert instead of
            # leaving Diana to guess.
            "factors": _attach_guidance(crypto_factors_customer),
        },
        "behavioral": {
            "state": behavioral_state,
            "events_observed": event_count,
            "events_floor": BEHAVIORAL_ICR_FLOOR,
            "events_stable": BEHAVIORAL_ICR_STABLE,
            "descriptor": descriptor,
            # Sprint UX-5.15.B — customer-visible factor list with
            # severities capped at `info` while the agent is pre-T3.
            # Engine-level severities are preserved in the underlying
            # observable row (`details_json.score_factors`) for
            # internal consumers; only this customer-facing field gets
            # the calm-by-default treatment.
            # gh-81 — same `learn_more` enrichment as the cryptographic
            # layer.
            "factors": _attach_guidance(behavioral_factors_customer),
        },
    }


# --------------------------------------------------------------------------- #
# Tier derivation (UX-5.15.A / UX-5.16)                                        #
# --------------------------------------------------------------------------- #
#
# A tier is a convenience label for *which protections are active* at a given
# event count (D-PROD.24) — the contract is the protection catalog, not this
# number. The floors below come from the UX-5.16 calibration sweeps; see
# docs/research/CALIBRATION-RIGOR.md (Synthesis) and
# docs/product/IDENTITY-TIERS-AND-COMMUNICATION.md §11.
#
# T3 is pinned to BEHAVIORAL_ICR_FLOOR (2000) — the calibrated floor at which
# subtle behavioral-drift detection becomes defensible (Jose, 2026-05-21:
# "align T3 with the calibration"). NOTE this differs from the engine's
# BEHAVIORAL_ICR_STABLE (5000) gate that drives the behavioral `stable` state
# and drift alarms — so between 2000 and 5000 events the tier badge can read
# "T3 — Fully baselined" while the behavioral panel still reads "building".
# That divergence is an accepted product decision, not a bug.

TIER_T1_FLOOR = 1                       # first signed event — crypto identity verified
TIER_T2_FLOOR = 50                      # first memory probe — behavioral signals emerging
TIER_T3_FLOOR = BEHAVIORAL_ICR_FLOOR    # 2000 — fully baselined (calibrated)

_TIER_NAMES = {
    "T0": "Identity registered",
    "T1": "Cryptographic identity verified",
    "T2": "Behavioral signature emerging",
    "T3": "Fully baselined",
    "T4": "Full mesh corroboration",
}

# Ladder rungs, lowest → highest.
_TIER_LADDER = ("T0", "T1", "T2", "T3", "T4")


def derive_tier(event_count: int, is_mesh_paired: bool = False) -> dict[str, Any]:
    """Customer-facing tier for one agent — a pure event-count derivation.

    Monotonic under honest usage: `event_count` is the physical event
    count (it only grows, even across a baseline reset), so the tier never
    goes backwards. The crypto/behavioral alarm story is carried by the
    `trust` block — `tier` is purely "how much have we observed / how much
    of the protection catalog is active".

    Shape:
      {
        "tier": "T0".."T4",
        "name": human-readable tier name,
        "next_tier": "T1".."T4" | None,
        "next_tier_name": str | None,
        "events_observed": int,
        "events_to_next": int | None,   # None at the top tier, or when the
                                        # next rung needs a non-event step
                                        # (T3 → T4 requires a mesh pair).
      }
    """
    n = max(0, event_count or 0)
    if n >= TIER_T3_FLOOR and is_mesh_paired:
        tier = "T4"
    elif n >= TIER_T3_FLOOR:
        tier = "T3"
    elif n >= TIER_T2_FLOOR:
        tier = "T2"
    elif n >= TIER_T1_FLOOR:
        tier = "T1"
    else:
        tier = "T0"

    idx = _TIER_LADDER.index(tier)
    next_tier = _TIER_LADDER[idx + 1] if idx + 1 < len(_TIER_LADDER) else None

    events_to_next: int | None = None
    if next_tier == "T1":
        events_to_next = max(0, TIER_T1_FLOOR - n)
    elif next_tier == "T2":
        events_to_next = max(0, TIER_T2_FLOOR - n)
    elif next_tier == "T3":
        events_to_next = max(0, TIER_T3_FLOOR - n)
    # next_tier == "T4" → gated on mesh pairing, not an event count → None.

    return {
        "tier": tier,
        "name": _TIER_NAMES[tier],
        "next_tier": next_tier,
        "next_tier_name": _TIER_NAMES[next_tier] if next_tier else None,
        "events_observed": n,
        "events_to_next": events_to_next,
    }
