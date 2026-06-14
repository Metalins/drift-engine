"""Protections catalog — server-side authoritative list per D-PROD.24.

Sprint UX-5.16 / UX-5.15.A.

This module is the **single source of truth** for the 22 protections
discovered in the calibration sweep (Sprint UX-5.16). It is consumed by:

  - `GET /v1/agents/{id}/protections` — customer surface checklist
  - `derive_protections()` — also called inline by `GET /v1/agents/{id}`

IP boundary (per D-PROD.24 + Jose 2026-05-19 directive):

  - **Internal data** (mechanism names like "B1.bulk_swap", thresholds,
    mathematical observables, attack-model details) STAYS in this file.
    These never appear in the customer JSON response.

  - **Customer surface** uses opaque slugs (e.g. `protection_07`) and
    sanitized customer copy (no "ICR", "Miller-Madow", "MVS", "TWC", etc).

  - The CI guard (#597) extends to grep this module's internal names
    if they ever leak to the customer bundle. Internal names live ONLY
    in this module and in `docs/research/`.

Source of truth: `docs/research/PROTECTIONS-CATALOG.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# --------------------------------------------------------------------------- #
# Agent profile classification                                                #
# --------------------------------------------------------------------------- #

PROFILE_DETERMINISTIC = "deterministic"     # temperature ≈ 0, same input → same output
PROFILE_LOW_STOCHASTIC = "low_stochastic"   # temperature ≤ 0.5, mostly consistent
PROFILE_STOCHASTIC = "stochastic"           # temperature > 0.5, freely sampling

VALID_PROFILES = {PROFILE_DETERMINISTIC, PROFILE_LOW_STOCHASTIC, PROFILE_STOCHASTIC}

DEFAULT_PROFILE = PROFILE_DETERMINISTIC


def resolve_agent_profile(agent) -> str:
    """Resolve the profile that gates this agent's protections.

    gh-77: the customer no longer declares a profile. The engine detects
    the agent's behavior from its first events and stores the verdict on
    ``Agent.detected_behavior_mode`` (see app.services.behavior_detection).
    We map that verdict onto the protections-catalog profile vocabulary:

      - ``deterministic``  → PROFILE_DETERMINISTIC
      - ``stochastic``     → PROFILE_STOCHASTIC
      - ``unknown`` / None → DEFAULT_PROFILE (deterministic)

    ``unknown`` defaults to deterministic on purpose: that is the *fuller*
    moat (it lights up the strict functional-violation protections), and it
    matches the pre-gh-77 behavior for agents that declared nothing. Once
    detection has enough evidence it narrows the agent to its real band.

    Accepts the Agent row (or anything exposing ``detected_behavior_mode``).
    A bare ``None`` resolves to the default.
    """
    mode = getattr(agent, "detected_behavior_mode", None)
    if mode == "stochastic":
        return PROFILE_STOCHASTIC
    if mode == "deterministic":
        return PROFILE_DETERMINISTIC
    return DEFAULT_PROFILE


def agent_has_probe_client(agent) -> bool:
    """Whether this agent runs a client capable of answering challenges.

    Round-trip mechanisms — MVS / ADV probes, ZKH commits, PRS
    predictions, mesh corroboration — need a deterministic client that
    fetches a challenge and computes its proof. A V1 MCP-prompt agent
    has no such client: the LLM only calls `log_event`, and an LLM can
    neither be relied on to poll for challenges nor compute an HMAC
    proof in-context. So in V1 this is False for every agent and the
    score rests on the event-stream layer (signed chain / RKS / ICR).

    V2's SDK/daemon client registers with `probe_client: true` in
    `metadata_json` and flips this on, lighting up the round-trip
    mechanisms for real. See D-PROD.27.
    """
    meta = getattr(agent, "metadata_json", None) or {}
    return bool(meta.get("probe_client"))


def agent_probes_enabled(agent) -> bool:
    """Whether the server should actively run memory probes for this agent.

    gh-88: hash-based memory probes (the MVS round-trip) only make sense for
    *deterministic* agents — same input → same digest → a reproducible proof.
    A stochastic agent (an LLM) produces a different output for the same input,
    so a probe can never validate; emitting probes to it just piles up
    expirations and surfaces a permanent, meaningless ``probes_failing`` alarm.
    The behavioral κ-engine is the right mechanism for stochastic agents.

    So probes run only when BOTH hold:
      - the agent opted in (``probe_client`` — set via the Settings toggle, or
        explicitly at registration), AND
      - the agent is not detected as stochastic.

    The opt-in is off by default (gh-88): registration no longer auto-stamps
    ``probe_client``. ``unknown`` / ``deterministic`` modes are eligible once
    opted in; only ``stochastic`` is hard-excluded regardless of the flag.

    This gates BOTH probe issuance (observable_job) and, because the same
    boolean is passed to ``explain_score`` as ``has_probe_client``, the
    ``probes_failing`` factor (reinforcing the gh-80 suppression gate).
    """
    if not agent_has_probe_client(agent):
        return False
    mode = getattr(agent, "detected_behavior_mode", None)
    return mode != "stochastic"


# --------------------------------------------------------------------------- #
# Protection record                                                           #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Protection:
    # Internal identifiers — never returned to the customer
    internal_id: str             # e.g. "B1.bulk_swap"
    mechanism: str               # e.g. "B1"

    # Customer-facing identifiers
    customer_slug: str           # opaque, stable across deploys
    customer_name: str           # short label for UI badges
    customer_description: str    # longer description shown on hover/expand
    customer_caveat: Optional[str]  # honest limitation (e.g., "requires watcher")

    # Activation criteria
    floor_events: int            # event_count threshold (1 for cripto-immediate)
    applies_to_profiles: frozenset  # which agent_profiles this protection applies to
    requires_integration: Optional[str]  # "watcher" | "mesh" | None
    requires_mcp: bool = True    # most need MCP-instrumented agent

    # Tier label for grouping in UI (purely cosmetic — see D-PROD.24)
    tier: str = "T1"             # T0/T1/T2/T3


# --------------------------------------------------------------------------- #
# The catalog                                                                 #
# --------------------------------------------------------------------------- #
# Order matches docs/research/PROTECTIONS-CATALOG.md.
#
# IMPORTANT — customer_slug values are stable. Once a slug is published
# the customer dashboard pins it; never re-number. If a protection is
# deprecated, leave its slot empty rather than renumbering.

ALL_PROFILES = frozenset({PROFILE_DETERMINISTIC, PROFILE_LOW_STOCHASTIC, PROFILE_STOCHASTIC})
DETERMINISTIC_ONLY = frozenset({PROFILE_DETERMINISTIC})
COUPLING_TOLERANT = frozenset({PROFILE_DETERMINISTIC, PROFILE_LOW_STOCHASTIC})


# UX-5.15.AL — mechanisms whose protections need a probe-capable client
# (they depend on the agent actively answering a challenge). For an agent
# without such a client these protections are not applicable and are not
# surfaced at all. See agent_has_probe_client / D-PROD.27.
#   C2 MVS, B4 ADV  → respond_probe
#   B2 PRS          → predict_response
#   C5 ZKH          → request_zkh_challenge / submit_zkh_proof
#   B3 TLS          → scored from memory-probe response timing
#   C4 MCS          → submit_corroboration
# Event-stream mechanisms (C1, C3, C6, B1 ICR) are NOT here — they are
# verified from the logged event stream with no agent round-trip.
_PROBE_CLIENT_MECHANISMS = frozenset({"C2", "B4", "B2", "C5", "B3", "C4"})


PROTECTIONS: list[Protection] = [
    # ----- T0 — cryptographic anchors (1 event) -----
    Protection(
        internal_id="C1.signature_forgery",
        mechanism="C1",
        customer_slug="proof_01",
        customer_name="Signed event chain",
        customer_description="Every event your agent posts is signed with a private key. Forgery without the key is mathematically impossible.",
        customer_caveat=None,
        floor_events=1,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T0",
    ),
    Protection(
        internal_id="C6.protocol_violation",
        mechanism="C6",
        customer_slug="proof_02",
        customer_name="Protocol check",
        customer_description="Catches naive impersonators that post as agents but don't follow the integration protocol correctly.",
        customer_caveat=None,
        floor_events=1,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T0",
    ),
    Protection(
        internal_id="C3.secret_only_fork",
        mechanism="C3",
        customer_slug="proof_03",
        customer_name="Signature chain check",
        customer_description="Every event your agent signs is chained to its running history. An attacker who holds the key but forked the history produces a wrong signature on the first forged event.",
        customer_caveat=None,
        floor_events=1,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T0",
    ),
    Protection(
        internal_id="C5.history_length_fake",
        mechanism="C5",
        customer_slug="proof_04",
        customer_name="History proof",
        customer_description="The agent can prove the length and structure of its event history without revealing the events themselves. A clone without the history cannot fake this proof.",
        customer_caveat=None,
        floor_events=1,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T0",
    ),
    # ----- T1 — early behavioral (3-20 events) -----
    Protection(
        internal_id="B5.mcp_lies_no_watcher_match",
        mechanism="B5",
        customer_slug="proof_05",
        customer_name="External witness check",
        customer_description="Each event your agent reports is cross-checked against an external observer. Claims without corroboration are flagged immediately.",
        customer_caveat="Requires a watcher (Telegram bot, etc.) to be configured for this agent.",
        floor_events=3,
        applies_to_profiles=ALL_PROFILES,
        requires_integration="watcher",
        tier="T1",
    ),
    Protection(
        internal_id="B5.watcher_silenced",
        mechanism="B5",
        customer_slug="proof_06",
        customer_name="Watcher channel check",
        customer_description="Detects when an attacker disables your external observer (e.g., removes the bot) while continuing to fabricate activity through the main channel.",
        customer_caveat="Requires a watcher configured for this agent.",
        floor_events=3,
        applies_to_profiles=ALL_PROFILES,
        requires_integration="watcher",
        tier="T1",
    ),
    Protection(
        internal_id="B3.bot_uniform_cadence",
        mechanism="B3",
        customer_slug="proof_07",
        customer_name="Bot cadence",
        customer_description="Detects when your agent's request rhythm collapses to fixed bot-like intervals (e.g., 100ms per event). Humans pause; bots don't.",
        customer_caveat=None,
        floor_events=5,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T1",
    ),
    Protection(
        internal_id="B3.burst_attack",
        mechanism="B3",
        customer_slug="proof_08",
        customer_name="Burst takeover",
        customer_description="Detects when many events arrive in rapid succession — characteristic of automated scraping or compromised agent.",
        customer_caveat=None,
        floor_events=5,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T1",
    ),
    Protection(
        internal_id="B3.regular_too_periodic",
        mechanism="B3",
        customer_slug="proof_09",
        customer_name="Metronome bot",
        customer_description="Catches sophisticated bots that match the average human pace but lack natural variability in their timing.",
        customer_caveat=None,
        floor_events=5,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T1",
    ),
    Protection(
        internal_id="B1.functional_violation_crypto_random",
        mechanism="B1",
        customer_slug="proof_10",
        customer_name="Random-output attack",
        customer_description="Catches an attacker with your key emitting outputs unrelated to their inputs. Detected on the first contradiction.",
        customer_caveat="Only available for deterministic agents (e.g., Claude Code, Cursor at temperature 0).",
        floor_events=10,
        applies_to_profiles=DETERMINISTIC_ONLY,
        requires_integration=None,
        tier="T1",
    ),
    Protection(
        internal_id="B1.functional_violation_drift",
        mechanism="B1",
        customer_slug="proof_11",
        customer_name="Model swap detection — early",
        customer_description="Detects when the underlying AI model is replaced with a different one. Activates as early as 20 events.",
        customer_caveat="Only available for deterministic agents.",
        floor_events=20,
        applies_to_profiles=DETERMINISTIC_ONLY,
        requires_integration=None,
        tier="T1",
    ),
    # ----- T2 — mid-range (50-200 events) -----
    Protection(
        internal_id="C2.stolen_key_random_proof",
        mechanism="C2",
        customer_slug="proof_12",
        customer_name="Memory check — random bluff",
        customer_description="Catches an attacker who stole your key but lacks your event history. A bluffed answer to a memory probe is rejected.",
        customer_caveat=None,
        floor_events=50,  # ~1 probe at current schedule
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T2",
    ),
    Protection(
        internal_id="C2.stolen_key_no_response",
        mechanism="C2",
        customer_slug="proof_13",
        customer_name="Memory check — non-response",
        customer_description="Catches a clone that received your key but refuses to engage with memory checks.",
        customer_caveat=None,
        floor_events=50,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T2",
    ),
    Protection(
        internal_id="B2.cannot_predict_own_response",
        mechanism="B2",
        customer_slug="proof_14",
        customer_name="Internal-model check",
        customer_description="Your agent must predict its next response. A clone without the internal model cannot — but the real agent can.",
        customer_caveat=None,
        floor_events=50,
        applies_to_profiles=COUPLING_TOLERANT,
        requires_integration=None,
        tier="T2",
    ),
    Protection(
        internal_id="C4.clone_full_replace",
        mechanism="C4",
        customer_slug="proof_17",
        customer_name="Multi-agent corroboration",
        customer_description="When two of your agents are paired, an attacker who clones only one of them fails the next mutual checkpoint between them.",
        customer_caveat="Requires mesh pairing (available for multi-agent configurations).",
        floor_events=50,  # ~1 mesh corroboration cycle
        applies_to_profiles=ALL_PROFILES,
        requires_integration="mesh",
        tier="T2",
    ),
    Protection(
        internal_id="C4.clone_mid_takeover",
        mechanism="C4",
        customer_slug="proof_21",
        customer_name="Mesh takeover check",
        customer_description="Catches a takeover of a mesh-paired agent that happens after a long history of agreeing checkpoints — it takes a few corroboration cycles for the disagreement to outweigh the clean history.",
        customer_caveat="Requires mesh pairing (available for multi-agent configurations).",
        floor_events=200,  # ~4 mesh corroboration cycles
        applies_to_profiles=ALL_PROFILES,
        requires_integration="mesh",
        tier="T2",
    ),
    Protection(
        internal_id="B1.bulk_swap",
        mechanism="B1",
        customer_slug="proof_15",
        customer_name="Model swap detection — broad",
        customer_description="Statistical model-swap detection that works for agents whose outputs vary across runs (typical LLM sampling).",
        customer_caveat="Tolerates moderate model noise; finer detection comes with longer history.",
        floor_events=100,
        # gh-79: this is the statistical model-swap detector — it explicitly
        # works for sampling agents, so it must apply to stochastic agents
        # too (it is the stochastic-side counterpart of the deterministic-only
        # B1.functional_violation_drift). Previously COUPLING_TOLERANT, which
        # silently excluded pure stochastic agents and left them with no
        # model-swap moat at all.
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T2",
    ),
    # ----- T3 — full suite (500-2000+ events) -----
    Protection(
        internal_id="C2.partial_history_clone",
        mechanism="C2",
        customer_slug="proof_18",
        customer_name="History completeness check",
        customer_description="Catches an attacker that imported only part of your event history. Memory probes referencing any later event expose the gap.",
        customer_caveat=None,
        floor_events=500,
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T3",
    ),
    Protection(
        internal_id="B4.naive_attacker",
        mechanism="B4",
        customer_slug="proof_16",
        customer_name="Malformed-probe check",
        customer_description="Metalins mixes a small fraction of deliberately malformed checks into the probe stream. A conformant agent inspects and refuses them; an attacker that only holds the key answers them anyway and fails.",
        customer_caveat=None,
        floor_events=700,  # ~1 malformed probe at the 7% injection rate
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T3",
    ),
    Protection(
        internal_id="B4.partial_one_third",
        mechanism="B4",
        customer_slug="proof_22",
        customer_name="Partial-protocol check",
        customer_description="Catches an attacker that implemented only part of the protocol — it refuses the obvious malformed checks but misses the subtler ones.",
        customer_caveat=None,
        floor_events=3500,  # ~5 malformed probes at the 7% injection rate
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T3",
    ),
    Protection(
        internal_id="B1.subtle_drift",
        mechanism="B1",
        customer_slug="proof_19",
        customer_name="Subtle drift detection",
        customer_description="Detects sophisticated attackers that try to fly under the radar by partially preserving your agent's behavior. Requires more history to gain resolution.",
        customer_caveat=None,
        floor_events=2000,
        # gh-79: statistical drift detection — applies to stochastic agents too.
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T3",
    ),
    Protection(
        internal_id="B1.crypto_independent",
        mechanism="B1",
        customer_slug="proof_20",
        customer_name="Statistical backstop",
        customer_description="Statistical fallback that catches random-output attacks even when the agent samples freely (high-temperature sampling, no fixed output for the same input).",
        customer_caveat=None,
        floor_events=2000,
        # gh-79: this is explicitly the high-temperature / freely-sampling
        # fallback — it must apply to stochastic agents (its whole purpose).
        applies_to_profiles=ALL_PROFILES,
        requires_integration=None,
        tier="T3",
    ),
]


# --------------------------------------------------------------------------- #
# Derivation                                                                  #
# --------------------------------------------------------------------------- #


def _integration_applicable(
    p: Protection,
    *,
    integration_surface: str,
    is_mesh_paired: bool,
    has_probe_client: bool,
) -> bool:
    """Whether a protection's *integration* requirements are met for this agent.

    This is the hard gate: a protection whose integration can never fire
    (no watcher, no mesh pairing, no probe-capable client, no MCP activity)
    is genuinely unavailable and is dropped from the checklist.

    gh-79: note this NO LONGER considers the agent's behavior profile. The
    behavior axis is handled separately (see ``_behavior_applicable``) so
    that profile-specific protections are *surfaced* rather than hidden —
    every agent sees the full catalog; the profile only changes whether a
    given protection is on its activation path.
    """
    # UX-5.15.AL — round-trip mechanisms need a probe-capable client.
    # Checked before the requires_mcp block below so it also gates the
    # crypto-immediate exception (C5 ZKH is round-trip despite being a
    # cryptographic mechanism).
    if p.mechanism in _PROBE_CLIENT_MECHANISMS and not has_probe_client:
        return False
    if p.requires_integration == "watcher" and integration_surface != "watcher":
        return False
    if p.requires_integration == "mesh" and not is_mesh_paired:
        return False
    if p.requires_mcp and integration_surface == "none":
        # Strict crypto (C1 / C3 / C6) applies via key registration alone,
        # before any MCP activity. C5 is cryptographic too but round-trip,
        # so it was already filtered above for non-probe-capable agents.
        if p.mechanism in {"C1", "C3", "C5", "C6"}:
            return True
        return False
    return True


def _behavior_applicable(p: Protection, *, agent_profile: str) -> bool:
    """Whether this protection's detection actually fires for the agent's
    detected behavior mode. A protection can be visible (in the catalog)
    but not behavior-applicable — e.g. the deterministic-only model-swap
    checks on a stochastic agent, which is instead covered by the broad
    statistical variant. See gh-79."""
    return agent_profile in p.applies_to_profiles


def _is_applicable(
    p: Protection,
    *,
    agent_profile: str,
    integration_surface: str,
    is_mesh_paired: bool,
    has_probe_client: bool,
) -> bool:
    """Back-compat helper: True only when BOTH integration and behavior
    requirements are met. Retained for callers/tests that asked the old
    single-axis question."""
    return _integration_applicable(
        p,
        integration_surface=integration_surface,
        is_mesh_paired=is_mesh_paired,
        has_probe_client=has_probe_client,
    ) and _behavior_applicable(p, agent_profile=agent_profile)


# gh-79 — honest inline copy for protections that are in the catalog but
# whose detection does not fire for this agent's behavior mode. No internal
# mechanism names; customer-safe language only.
_BEHAVIOR_NOTE_DETERMINISTIC_ONLY = (
    "Applies to deterministic agents (same input → same output). Your agent's "
    "outputs vary between runs, so it's covered by the broad statistical "
    "model-swap detection instead."
)
_BEHAVIOR_NOTE_UNKNOWN = (
    "Your agent's behavior is still being learned from its first events. This "
    "protection activates if your agent turns out to be deterministic; "
    "otherwise the statistical variant covers you. Either way you're protected."
)


def derive_protections(
    *,
    event_count: int,
    agent_profile: str,
    integration_surface: str,
    is_mesh_paired: bool = False,
    has_probe_client: bool = False,
    detected_mode: Optional[str] = None,
) -> list[dict]:
    """Build the customer-facing protections checklist for one agent.

    Returns a list of dicts shaped:
      { id, name, description, caveat, behavior_note, active,
        events_to_activation, applicable, applies_to_behavior, tier }

    gh-79 — every agent now sees the FULL catalog (subject only to hard
    integration gating below). The agent's behavior profile no longer
    *hides* protections; it only decides whether a given protection is on
    this agent's activation path:

      - ``applies_to_behavior=True``  → normal active / pending-with-countdown.
      - ``applies_to_behavior=False`` → shown with an honest inline
        ``behavior_note`` explaining that an equivalent variant covers the
        agent instead. ``active`` is False and ``events_to_activation`` is
        None (no misleading countdown for a protection that won't fire for
        this mode).

    UX-5.15.AL still applies on the *integration* axis: protections whose
    integration can never fire for this agent (watcher-only, mesh-only, or
    round-trip mechanisms on a non-probe-capable agent) are NOT included.
    ``applicable`` therefore reflects integration availability and is True
    on every returned row; the key is kept for API back-compat.

    ``detected_mode`` is the raw ``Agent.detected_behavior_mode`` verdict
    ("unknown" | "deterministic" | "stochastic" | None). It is used only to
    tailor the inline note while detection is still in progress.

    Internal identifiers (`mechanism`, `internal_id`) are NEVER returned.
    """
    profile = agent_profile if agent_profile in VALID_PROFILES else DEFAULT_PROFILE
    mode_unknown = detected_mode in (None, "unknown")
    out: list[dict] = []
    for p in PROTECTIONS:
        if not _integration_applicable(
            p,
            integration_surface=integration_surface,
            is_mesh_paired=is_mesh_paired,
            has_probe_client=has_probe_client,
        ):
            # UX-5.15.AL — don't surface protections the agent's
            # integration can never activate.
            continue

        applies_to_behavior = _behavior_applicable(p, agent_profile=profile)
        profile_specific = p.applies_to_profiles != ALL_PROFILES
        behavior_note: Optional[str] = None

        if applies_to_behavior:
            active = event_count >= p.floor_events
            delta = max(0, p.floor_events - event_count)
            events_to_activation = delta
            # While behavior detection is still warming up, profile-specific
            # protections that resolve to the (deterministic) default are
            # shown as pending with a note that the verdict may yet narrow.
            if mode_unknown and profile_specific:
                behavior_note = _BEHAVIOR_NOTE_UNKNOWN
        else:
            # Behavior-gated: in the catalog, visible, but not on this
            # agent's activation path. Surface honestly, no countdown.
            active = False
            events_to_activation = None
            behavior_note = (
                _BEHAVIOR_NOTE_UNKNOWN if mode_unknown
                else _BEHAVIOR_NOTE_DETERMINISTIC_ONLY
            )

        out.append({
            "id": p.customer_slug,
            "name": p.customer_name,
            "description": p.customer_description,
            "caveat": p.customer_caveat,
            "behavior_note": behavior_note,
            "active": active,
            "events_to_activation": events_to_activation,
            "applicable": True,
            "applies_to_behavior": applies_to_behavior,
            "tier": p.tier,
        })
    return out


def protection_summary(items: list[dict]) -> dict:
    """Tiny rollup for badges in the agent list view.

    gh-79 — ``applicable_count`` ("available") counts protections that are
    on this agent's activation path (integration- AND behavior-applicable).
    ``total_count`` is the full catalog the agent can see, so two agents
    with the same integration surface but different behavior modes report
    the same ``total_count`` — only ``active_count`` / ``applicable_count``
    differ. (See gh-79 QA: stochastic agent shows the same total as a
    deterministic demo.)
    """
    active = sum(1 for x in items if x["active"])
    applicable = sum(
        1 for x in items if x["applicable"] and x.get("applies_to_behavior", True)
    )
    total = len(items)
    return {
        "active_count": active,
        "applicable_count": applicable,
        "total_count": total,
    }
