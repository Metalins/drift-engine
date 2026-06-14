"""Tests for the PRS (Predictive Reliability Score) module."""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta


# Set DB_URL BEFORE any app imports — engine is built at import time.
_TMP_DB_PATH = f"/tmp/_metalins_prs_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Validation tests                                                            #
# --------------------------------------------------------------------------- #

def test_validate_distribution_accepts_well_formed():
    from app.services.prs import validate_distribution

    dist = [1.0 / 32] * 32
    validate_distribution(dist)  # no exception


def test_validate_distribution_rejects_wrong_length():
    from app.services.prs import validate_distribution, PredictionValidationError

    try:
        validate_distribution([0.5, 0.5])
    except PredictionValidationError as e:
        assert "length" in e.reason
    else:
        raise AssertionError("expected PredictionValidationError")


def test_validate_distribution_rejects_negative():
    from app.services.prs import validate_distribution, PredictionValidationError

    dist = [0.5, -0.1] + [0.6 / 30] * 30
    try:
        validate_distribution(dist)
    except PredictionValidationError as e:
        assert "non-negative" in e.reason
    else:
        raise AssertionError("expected PredictionValidationError")


def test_validate_distribution_rejects_bad_sum():
    from app.services.prs import validate_distribution, PredictionValidationError

    dist = [0.0] * 32
    dist[0] = 2.0
    try:
        validate_distribution(dist)
    except PredictionValidationError as e:
        assert "1.0" in e.reason
    else:
        raise AssertionError("expected PredictionValidationError")


def test_validate_distribution_tolerates_float_drift():
    from app.services.prs import validate_distribution

    # 32 entries each 1/32 won't sum to exactly 1.0 in float — confirm
    # the tolerance accepts it.
    dist = [1.0 / 32] * 32
    validate_distribution(dist)
    # And explicit drift inside tolerance.
    dist[0] += 0.03
    validate_distribution(dist)


# --------------------------------------------------------------------------- #
# Pure scoring                                                                #
# --------------------------------------------------------------------------- #

def test_score_prediction_hit_in_top_3():
    from app.services.prs import score_prediction

    dist = [0.0] * 32
    dist[5] = 0.5
    dist[10] = 0.3
    dist[15] = 0.2
    # top-3 = {5, 10, 15}
    assert score_prediction(dist, 10) == 1.0
    assert score_prediction(dist, 15) == 1.0
    assert score_prediction(dist, 0) == 0.0


def test_score_prediction_top_k_param():
    from app.services.prs import score_prediction

    dist = [0.0] * 32
    dist[1] = 0.4
    dist[2] = 0.3
    dist[3] = 0.2
    dist[4] = 0.1
    # top-1 = {1}, top-3 = {1,2,3}
    assert score_prediction(dist, 4, top_k=1) == 0.0
    assert score_prediction(dist, 1, top_k=1) == 1.0
    assert score_prediction(dist, 4, top_k=4) == 1.0


# --------------------------------------------------------------------------- #
# submit_prediction + resolve_pending_predictions + compute_prs               #
# --------------------------------------------------------------------------- #

def _seed_event(db, agent_id: str, event_count: int, output_hash: str):
    from app.db.models import EventLog
    from app.core.ids import new_id

    db.add(EventLog(
        id=new_id("evt"),
        agent_id=agent_id,
        event_count=event_count,
        input_hash="00" * 32,
        output_hash=output_hash,
        history_digest="ab" * 32,
        signature="cd" * 32,
        metadata_json={},
        ts=datetime.utcnow(),
    ))


def test_submit_prediction_persists_row():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, PredictionSubmission
    from app.services.prs import submit_prediction

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_prs_p_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_prs_p_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="p@p.local", label="p",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="p", is_active=True))
        db.commit()

        dist = [1.0 / 32] * 32
        sub = submit_prediction(db, agent_id, 100, dist)
        assert sub.target_event_count == 105
        loaded = db.query(PredictionSubmission).filter_by(id=sub.id).first()
        assert loaded is not None
        assert loaded.resolved_at is None
        assert loaded.score is None
    finally:
        db.close()


def test_resolve_pending_predictions_scores_hits_and_misses():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, PredictionSubmission
    from app.services.prs import (
        submit_prediction, resolve_pending_predictions, compute_prs,
        _hash_to_bucket,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_prs_r_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_prs_r_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="r@r.local", label="r",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="r", is_active=True))
        db.commit()

        # Submit prediction at event_count=10, target=15.
        # Build a distribution that concentrates mass on a specific bucket.
        hit_output = hashlib.sha256(b"will_hit").hexdigest()
        miss_output = hashlib.sha256(b"will_miss").hexdigest()
        hit_bucket = _hash_to_bucket(hit_output)
        miss_bucket = _hash_to_bucket(miss_output)
        assert hit_bucket != miss_bucket  # sanity

        dist_hit = [0.0] * 32
        dist_hit[hit_bucket] = 1.0
        dist_miss = [0.0] * 32
        # Predict THREE buckets that all differ from the realized one.
        # Pick 3 buckets that aren't miss_bucket.
        other_buckets = [b for b in range(32) if b != miss_bucket][:3]
        for b in other_buckets:
            dist_miss[b] = 1 / 3

        submit_prediction(db, agent_id, 10, dist_hit)
        submit_prediction(db, agent_id, 20, dist_miss)

        # Seed events that resolve those predictions.
        _seed_event(db, agent_id, 15, hit_output)
        _seed_event(db, agent_id, 25, miss_output)
        db.commit()

        n = resolve_pending_predictions(db, agent_id)
        assert n == 2

        rows = db.query(PredictionSubmission).filter_by(agent_id=agent_id).all()
        scores = sorted(r.score for r in rows)
        assert scores == [0.0, 1.0]

        # PRS = average over the window = (1.0 + 0.0) / 2 = 0.5
        prs = compute_prs(db, agent_id)
        assert prs == 0.5
    finally:
        db.close()


def test_resolve_pending_skips_unresolved_predictions():
    """Predictions whose target hasn't arrived stay pending."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, PredictionSubmission
    from app.services.prs import submit_prediction, resolve_pending_predictions

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_prs_u_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_prs_u_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="u@u.local", label="u",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="u", is_active=True))
        db.commit()

        dist = [1.0 / 32] * 32
        submit_prediction(db, agent_id, 50, dist)
        # No events at target 55 — should stay pending.
        n = resolve_pending_predictions(db, agent_id)
        assert n == 0
        loaded = db.query(PredictionSubmission).filter_by(agent_id=agent_id).first()
        assert loaded.resolved_at is None
    finally:
        db.close()


def test_compute_prs_returns_none_with_no_resolved():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.prs import compute_prs

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_prs_n_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_prs_n_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="n@n.local", label="n",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="n", is_active=True))
        db.commit()
        assert compute_prs(db, agent_id) is None
    finally:
        db.close()


def test_compute_prs_legit_high_attacker_low():
    """Replicates R10 scenario: legit predictor (concentrated mass on the
    real bucket) vs informed attacker (uniform marginals)."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.prs import (
        submit_prediction, resolve_pending_predictions, compute_prs,
        _hash_to_bucket,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_prs_l_{uuid.uuid4().hex[:8]}"
        agent_legit = f"agt_prs_l_{uuid.uuid4().hex[:8]}"
        agent_atk = f"agt_prs_a_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="l@l.local", label="l",
        ))
        db.add(Agent(id=agent_legit, api_key_id=key_id, name="l", is_active=True))
        db.add(Agent(id=agent_atk, api_key_id=key_id, name="a", is_active=True))
        db.commit()

        N = 30
        for i in range(N):
            ev_hash = hashlib.sha256(f"e{i}".encode()).hexdigest()
            target_bucket = _hash_to_bucket(ev_hash)
            # Legit: concentrate mass on the actual bucket.
            dist_legit = [0.0] * 32
            dist_legit[target_bucket] = 1.0
            submit_prediction(db, agent_legit, i * 10, dist_legit)
            _seed_event(db, agent_legit, i * 10 + 5, ev_hash)
            # Attacker: uniform → top-3 hit ≈ 3/32 ≈ 9%.
            dist_atk = [1.0 / 32] * 32
            submit_prediction(db, agent_atk, i * 10, dist_atk)
            _seed_event(db, agent_atk, i * 10 + 5, ev_hash)
        db.commit()

        resolve_pending_predictions(db, agent_legit)
        resolve_pending_predictions(db, agent_atk)

        prs_legit = compute_prs(db, agent_legit)
        prs_atk = compute_prs(db, agent_atk)
        # Legit hits every time → 1.0
        assert prs_legit == 1.0
        # Random predictor: any of 32 buckets could be top-3 ties; the
        # tiebreak (sorted by negative value, index ascending) means
        # buckets 0..2 are always "top-3". So ATK hits only when target
        # bucket ∈ {0, 1, 2}. With 30 trials this is roughly 9% (~3
        # hits). Assert a reasonable upper bound.
        assert prs_atk is not None
        assert prs_atk < 0.5, f"attacker should score low, got {prs_atk}"
    finally:
        db.close()
