"""Tests for the κ-engine V2 behavioral DNA learner (#62).

Covers the three contract cases from board.json #62:
  (1) baseline + identical window        → drift_score ~0
  (2) baseline + simulated model swap    → drift_score > 0.7
  (3) baseline + moderate concept drift  → drift_score in [0.2, 0.5]

Exercised through the real DB API (fingerprint_baseline → persist
AgentBaseline → compare_to_baseline), plus pure-function unit tests of
the statistics core. Self-contained SQLite temp DB.
"""
from __future__ import annotations

import hashlib
import os

import pytest

_TMP_DB_PATH = f"/tmp/_metalins_kappa_engine_{os.getpid()}.db"
os.environ.setdefault("METALINS_DB_URL", f"sqlite:///{_TMP_DB_PATH}")
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Behavioral sample helpers                                                   #
# --------------------------------------------------------------------------- #

def _beh(
    chars: int,
    *,
    tokens: int = 40,
    code: bool = False,
    error: str = "none",
    tools=None,
    lsh: str = "0" * 16,
    latency: float = 100.0,
) -> dict:
    """Build one behavioral feature blob with controllable knobs."""
    return {
        "output_length_chars": chars,
        "output_length_tokens": tokens,
        "input_length_chars": 50,
        "sentence_count_output": 5,
        "mean_sentence_length_output": 12.0,
        "latency_ms": latency,
        "had_code_block": code,
        "had_list": False,
        "had_markdown": code,
        "error_class": error,
        "tool_calls": list(tools) if tools else [],
        "format_markers": {"code": code, "list": False, "markdown": code, "json": False},
        "token_bag_lsh": lsh,
    }


def _identical_samples(n: int, offset: int = 0) -> list[dict]:
    """Deterministic samples; chars cycle 150..199 (+offset)."""
    return [_beh(150 + offset + (i % 50)) for i in range(n)]


# --------------------------------------------------------------------------- #
# Pure-function core: the three contract cases (no DB)                        #
# --------------------------------------------------------------------------- #

def test_case1_identical_window_near_zero_drift():
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions(_identical_samples(200))
    window = _identical_samples(50)
    verdict = compare_distributions(baseline, window)

    assert verdict["drift_score"] < 0.1
    assert verdict["verified"] is True


def test_case2_model_swap_high_drift():
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions(_identical_samples(200))
    # Output lengths jump 10x — a model swap signature.
    window = [_beh(1500 + (i % 50)) for i in range(50)]
    verdict = compare_distributions(baseline, window)

    assert verdict["drift_score"] > 0.7
    assert verdict["verified"] is False
    assert verdict["dominant_feature"] == "output_length_chars"


def test_case3_moderate_concept_drift():
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions(_identical_samples(200))
    # Shift the length distribution by +15 over a width-50 range → KS ~0.30.
    window = _identical_samples(50, offset=15)
    verdict = compare_distributions(baseline, window)

    assert 0.2 <= verdict["drift_score"] < 0.5
    assert verdict["dominant_feature"] == "output_length_chars"


def test_categorical_drift_error_class_spike():
    """A surge of errors in the window registers as drift."""
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions([_beh(160, error="none") for _ in range(200)])
    window = [_beh(160, error="tool_error") for _ in range(50)]
    verdict = compare_distributions(baseline, window)
    assert verdict["drift_score"] > 0.7
    assert verdict["dominant_feature"] == "error_class"


def test_lsh_drift_on_vocabulary_change():
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions([_beh(160, lsh="ffffffffffffffff") for _ in range(50)])
    # Bit-flipped fingerprint → max hamming distance.
    window = [_beh(160, lsh="0000000000000000") for _ in range(20)]
    verdict = compare_distributions(baseline, window)
    assert verdict["scores"]["token_bag_lsh"] == pytest.approx(1.0, abs=1e-6)


def test_empty_baseline_yields_no_features():
    from app.kappa.engine import build_distributions, compare_distributions

    verdict = compare_distributions(build_distributions([]), _identical_samples(10))
    assert verdict["reason"] == "no_comparable_features"
    assert verdict["drift_score"] == 0.0


def test_identical_agent_with_varying_booleans_stays_low():
    """Regression for the chi2 1-p_value false-positive defect.

    An identical (non-drifted) agent whose boolean format markers vary
    randomly at a stable rate must NOT be flagged as drifted. The earlier
    chi2 significance score produced ~45% false positives here; total
    variation distance keeps it low.
    """
    import random
    from app.kappa.engine import build_distributions, compare_distributions

    rng = random.Random(1234)

    def sample(p_code, p_list):
        return _beh(
            160,
            code=rng.random() < p_code,
        ) | {"had_list": rng.random() < p_list}

    baseline = build_distributions([sample(0.5, 0.3) for _ in range(200)])
    # Worst case across 20 fresh windows from the SAME distribution.
    worst = 0.0
    for _ in range(20):
        window = [sample(0.5, 0.3) for _ in range(50)]
        worst = max(worst, compare_distributions(baseline, window)["drift_score"])
    assert worst < 0.35, f"identical agent flagged with drift_score={worst}"


def test_tool_bigram_drift_detected():
    """A change in tool *ordering* (same tools, different transitions)
    registers as drift via the bigram distribution."""
    from app.kappa.engine import build_distributions, compare_distributions

    baseline = build_distributions(
        [_beh(160, tools=["search", "fetch", "summarize"]) for _ in range(100)]
    )
    # Same tool set, reversed order → different bigrams, same unigrams.
    window = [_beh(160, tools=["summarize", "fetch", "search"]) for _ in range(50)]
    verdict = compare_distributions(baseline, window)
    assert "tool_bigrams" in verdict["scores"]
    assert verdict["scores"]["tool_bigrams"] > 0.7


def test_end_to_end_real_sdk_features():
    """The engine must consume REAL SDK output, not just the _beh() helper.

    Guards against an SDK/engine key drift silently blinding detection:
    pipe genuine compute_behavioral_features() output through the engine.
    """
    import sys
    from pathlib import Path

    sdk_path = Path(__file__).resolve().parents[2] / "sdk-python"
    sys.path.insert(0, str(sdk_path))
    from metalins_drift.behavioral import compute_behavioral_features
    from app.kappa.engine import build_distributions, compare_distributions

    short = "The answer is four. It is a small number. Nothing more to add here."
    long = (
        "Here is a thorough, multi-paragraph explanation that goes on at "
        "considerable length about the topic, covering many distinct points "
        "and elaborating each one with several supporting sentences. "
    ) * 6

    baseline = build_distributions(
        [compute_behavioral_features("question?", short, lsh_salt="aa" * 32) for _ in range(60)]
    )
    # Same agent, consistent behavior → low drift.
    same = [compute_behavioral_features("question?", short, lsh_salt="aa" * 32) for _ in range(20)]
    assert compare_distributions(baseline, same)["drift_score"] < 0.2

    # Output length blows up → real drift detected.
    drifted = [compute_behavioral_features("question?", long, lsh_salt="aa" * 32) for _ in range(20)]
    verdict = compare_distributions(baseline, drifted)
    assert verdict["drift_score"] > 0.7


# --------------------------------------------------------------------------- #
# DB-backed API: fingerprint_baseline + compare_to_baseline                   #
# --------------------------------------------------------------------------- #

@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base
    import app.db.models  # noqa: F401

    if os.path.exists(_TMP_DB_PATH):
        os.remove(_TMP_DB_PATH)
    engine = create_engine(
        f"sqlite:///{_TMP_DB_PATH}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    yield session
    session.close()


def _seed_events(db, agent_id: str, samples: list[dict], start: int = 0) -> None:
    from app.db.models import EventLog

    for i, beh in enumerate(samples):
        n = start + i + 1
        ih = hashlib.sha256(f"in{agent_id}{n}".encode()).hexdigest()
        oh = hashlib.sha256(f"out{agent_id}{n}".encode()).hexdigest()
        db.add(EventLog(
            id=f"evt_{agent_id}_{n}",
            agent_id=agent_id,
            event_count=n,
            input_hash=ih,
            output_hash=oh,
            history_digest=hashlib.sha256(f"d{n}".encode()).hexdigest(),
            signature="sig",
            metadata_json={"behavioral": beh},
        ))
    db.commit()


def test_db_fingerprint_persists_baseline(db):
    from app.kappa.engine import fingerprint_behavioral_baseline
    from app.db.models import AgentBaseline

    _seed_events(db, "agt_a", _identical_samples(120))
    result = fingerprint_behavioral_baseline(db, "agt_a", n_events=200)
    assert result["n_events"] == 120

    row = db.query(AgentBaseline).filter(AgentBaseline.agent_id == "agt_a").first()
    assert row is not None
    assert row.n_events == 120
    assert "output_length_chars" in row.features_json["features"]["continuous"]


def test_db_compare_identical_low_drift(db):
    from app.kappa.engine import fingerprint_behavioral_baseline, compare_behavioral_to_baseline

    _seed_events(db, "agt_b", _identical_samples(200))
    fingerprint_behavioral_baseline(db, "agt_b", n_events=200)
    # The most-recent 50 events are part of the same identical stream.
    verdict = compare_behavioral_to_baseline(db, "agt_b", window_size=50)
    assert verdict["drift_score"] < 0.1
    assert verdict["verified"] is True


def test_db_compare_model_swap_high_drift(db):
    from app.kappa.engine import fingerprint_behavioral_baseline, compare_behavioral_to_baseline

    # 200 baseline events, then 50 NEWER events with 10x output length.
    _seed_events(db, "agt_c", _identical_samples(200))
    fingerprint_behavioral_baseline(db, "agt_c", n_events=200)
    _seed_events(db, "agt_c", [_beh(1600 + (i % 50)) for i in range(50)], start=200)

    verdict = compare_behavioral_to_baseline(db, "agt_c", window_size=50)
    assert verdict["drift_score"] > 0.7
    assert verdict["verified"] is False
    assert verdict["dominant_feature"] == "output_length_chars"
    assert verdict["attribution"]["feature_name"] == "output_length_chars"


def test_db_compare_no_baseline(db):
    from app.kappa.engine import compare_behavioral_to_baseline

    verdict = compare_behavioral_to_baseline(db, "agt_missing", window_size=50)
    assert verdict["reason"] == "no_baseline"
    assert verdict["verified"] is False
