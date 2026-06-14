"""Tests for the κ-engine active-flow stub (Fase 1).

These cover the enrolment + challenge/response stubs still used by
agents.py (registration) and verify.py. The V2 passive behavioral DNA
learner has its own coverage in test_kappa_engine.py.
"""
from app.kappa import fingerprint_baseline, compare_to_baseline, generate_challenges


def test_fingerprint_is_deterministic():
    metadata = {"model": "claude-sonnet-4.5", "framework": "langchain"}
    samples = [{"challenge_id": "c1", "response": "ok"}]
    a = fingerprint_baseline(metadata, samples)
    b = fingerprint_baseline(metadata, samples)
    assert a["fingerprint_hash"] == b["fingerprint_hash"]
    assert a["enrolment_score"] > 0


def test_fingerprint_changes_with_data():
    metadata = {"model": "claude-sonnet-4.5"}
    a = fingerprint_baseline(metadata, [{"challenge_id": "c1", "response": "ok"}])
    b = fingerprint_baseline(metadata, [{"challenge_id": "c1", "response": "different"}])
    assert a["fingerprint_hash"] != b["fingerprint_hash"]


def test_generate_challenges_returns_n():
    challenges = generate_challenges(baseline={}, n=3)
    assert len(challenges) == 3
    assert all("id" in c and "payload" in c for c in challenges)
    # Multi-step linkage
    assert challenges[0]["depends_on"] is None
    assert challenges[1]["depends_on"] == challenges[0]["id"]


def test_compare_passes_with_valid_responses():
    result = compare_to_baseline(
        baseline={"fingerprint_hash": "abc"},
        metadata={},
        responses=[{"challenge_id": "c1", "response": "ok"}],
        steps=1,
    )
    assert result["verified"] is True
    assert result["score"] >= 0.7


def test_compare_fails_with_no_responses():
    result = compare_to_baseline(
        baseline={"fingerprint_hash": "abc"},
        metadata={},
        responses=[],
        steps=1,
    )
    assert result["verified"] is False
    assert result["score"] == 0.0


def test_compare_multi_step_more_strict():
    """Multi-step verifies penalize less-than-perfect responses more."""
    responses_partial = [
        {"challenge_id": "c1", "response": "ok"},
        {"bad": "shape"},  # invalid
    ]
    single = compare_to_baseline(baseline={}, metadata={}, responses=responses_partial, steps=1)
    multi = compare_to_baseline(baseline={}, metadata={}, responses=responses_partial, steps=5)
    assert multi["score"] != single["score"]
