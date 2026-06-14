"""Tests for gh-79 — full protections catalog for every agent.

The agent's detected behavior mode must no longer *hide* protections from
the customer checklist. Every agent (same integration surface) sees the
SAME total catalog; the behavior mode only changes whether a protection is
on that agent's activation path.

These exercise the pure derivation functions in
``app.services.protections_catalog`` — no DB needed.
"""
from __future__ import annotations

from app.services.protections_catalog import (
    PROFILE_DETERMINISTIC,
    PROFILE_STOCHASTIC,
    derive_protections,
    protection_summary,
)


def _derive(profile, *, mode=None, surface="mcp", events=5):
    return derive_protections(
        event_count=events,
        agent_profile=profile,
        integration_surface=surface,
        detected_mode=mode,
    )


# --------------------------------------------------------------------------- #
# Core gh-79 invariant: same total catalog regardless of behavior mode        #
# --------------------------------------------------------------------------- #

def test_same_total_catalog_for_deterministic_and_stochastic():
    det = _derive(PROFILE_DETERMINISTIC, mode="deterministic")
    sto = _derive(PROFILE_STOCHASTIC, mode="stochastic")

    # Same integration surface → identical set of protection slugs surfaced.
    assert {p["id"] for p in det} == {p["id"] for p in sto}
    assert len(det) == len(sto)

    det_summary = protection_summary(det)
    sto_summary = protection_summary(sto)
    # The headline requirement: total_count is identical; only activation
    # differs (active_count / applicable_count).
    assert det_summary["total_count"] == sto_summary["total_count"]
    assert det_summary["total_count"] > 3  # regression: stochastic used to see 3


def test_stochastic_agent_sees_deterministic_only_protections_as_gated():
    """The deterministic-only model-swap checks (proof_10/proof_11) must be
    VISIBLE to a stochastic agent — surfaced with a behavior note, not hidden,
    and not on an activation countdown."""
    sto = _derive(PROFILE_STOCHASTIC, mode="stochastic", events=10_000)
    by_id = {p["id"]: p for p in sto}

    for slug in ("proof_10", "proof_11"):
        assert slug in by_id, f"{slug} should be visible to a stochastic agent"
        item = by_id[slug]
        assert item["applies_to_behavior"] is False
        assert item["active"] is False
        assert item["events_to_activation"] is None
        assert item["behavior_note"]  # honest inline explanation present


def test_stochastic_agent_has_real_model_swap_moat():
    """proof_15/19/20 are the statistical model-swap variants — they MUST
    apply to (activate for) a stochastic agent, otherwise a stochastic agent
    has no model-swap coverage at all."""
    sto = _derive(PROFILE_STOCHASTIC, mode="stochastic", events=10_000)
    by_id = {p["id"]: p for p in sto}

    for slug in ("proof_15", "proof_19", "proof_20"):
        assert slug in by_id
        item = by_id[slug]
        assert item["applies_to_behavior"] is True
        assert item["active"] is True  # past their floors at 10k events


def test_deterministic_agent_activates_strict_checks():
    det = _derive(PROFILE_DETERMINISTIC, mode="deterministic", events=10_000)
    by_id = {p["id"]: p for p in det}
    for slug in ("proof_10", "proof_11"):
        assert by_id[slug]["applies_to_behavior"] is True
        assert by_id[slug]["active"] is True


def test_unknown_mode_notes_detection_in_progress():
    """An agent whose mode is still 'unknown' resolves to the deterministic
    default but should carry the in-progress note on profile-specific rows."""
    unk = _derive(PROFILE_DETERMINISTIC, mode="unknown", events=5)
    by_id = {p["id"]: p for p in unk}
    # proof_11 is profile-specific (deterministic-only) → note while unknown.
    assert by_id["proof_11"]["behavior_note"]
    # A universal protection (proof_01, all profiles) carries no behavior note.
    assert by_id["proof_01"]["behavior_note"] is None


def test_all_rows_carry_new_fields():
    for item in _derive(PROFILE_STOCHASTIC, mode="stochastic"):
        assert "behavior_note" in item
        assert "applies_to_behavior" in item
        # Internal identifiers never leak.
        assert "mechanism" not in item
        assert "internal_id" not in item


# --------------------------------------------------------------------------- #
# gh-88 — agent_probes_enabled: probes off by default + stochastic exclusion   #
# --------------------------------------------------------------------------- #

from types import SimpleNamespace  # noqa: E402

from app.services.protections_catalog import (  # noqa: E402
    agent_has_probe_client,
    agent_probes_enabled,
)


def _agent(*, probe_client=None, mode="unknown"):
    meta = {} if probe_client is None else {"probe_client": probe_client}
    return SimpleNamespace(metadata_json=meta, detected_behavior_mode=mode)


def test_probes_disabled_by_default():
    """No probe_client flag → probes off (gh-88 off-by-default)."""
    a = _agent(probe_client=None, mode="unknown")
    assert agent_has_probe_client(a) is False
    assert agent_probes_enabled(a) is False


def test_probes_enabled_for_deterministic_opt_in():
    """Opted in + deterministic → probes run."""
    assert agent_probes_enabled(_agent(probe_client=True, mode="deterministic")) is True


def test_probes_enabled_for_unknown_opt_in():
    """Opted in + still-detecting mode → probes run (unknown is eligible)."""
    assert agent_probes_enabled(_agent(probe_client=True, mode="unknown")) is True


def test_probes_never_run_for_stochastic_even_when_opted_in():
    """gh-88 #2 — a stochastic agent is hard-excluded regardless of the flag.

    This is the dogfood-v2 case: probe_client was incorrectly true on a
    stochastic LLM. The gate must still return False so no probes are issued
    and (since this boolean feeds explain_score as has_probe_client) the
    probes_failing factor is suppressed.
    """
    a = _agent(probe_client=True, mode="stochastic")
    assert agent_has_probe_client(a) is True  # flag is set...
    assert agent_probes_enabled(a) is False   # ...but probes still off


def test_probes_off_when_flag_false():
    assert agent_probes_enabled(_agent(probe_client=False, mode="deterministic")) is False
