"""Tests for the ADV (Adversarial Probe Detection) module."""
from __future__ import annotations

import hashlib
import os
import random
import uuid
from datetime import datetime, timedelta


# Set DB_URL BEFORE any app imports — engine is built at import time.
_TMP_DB_PATH = f"/tmp/_metalins_adv_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Pure function tests                                                         #
# --------------------------------------------------------------------------- #

def test_choose_malformation_probability():
    """At rate 0.07, over 10k samples we should see ~700 plans, ±100σ."""
    from app.services.adv import choose_malformation

    rng = random.Random(42)
    plans = sum(1 for _ in range(10_000) if choose_malformation(rng) is not None)
    # Allow generous slack; this is just a sanity check.
    assert 500 <= plans <= 900, f"Expected ~700 plans, got {plans}"


def test_choose_malformation_returns_plan_with_known_kind():
    from app.services.adv import choose_malformation, MALFORMATION_KINDS

    rng = random.Random(0)
    # Force the random.random() to return < 0.07 by exhausting predictable
    # values. Use a controlled seed and just verify the kind is in the set.
    for _ in range(100):
        plan = choose_malformation(rng)
        if plan is not None:
            assert plan.kind in MALFORMATION_KINDS
            return
    # If we somehow got 100 None in a row, the rng is busted.
    raise AssertionError("Expected at least one plan in 100 draws")


def test_apply_malformation_short_nonce_truncates():
    from app.services.adv import apply_malformation_to_probe, MalformationPlan

    class FakeProbe:
        is_malformed = False
        nonce = "a" * 64
        target_event_count = 100
        refusal_reason = None
    p = FakeProbe()
    apply_malformation_to_probe(p, MalformationPlan("short_nonce"))
    assert p.is_malformed is True
    assert p.nonce == "a" * 8
    # Other fields untouched.
    assert p.target_event_count == 100


def test_apply_malformation_event_count_out_of_range():
    from app.services.adv import apply_malformation_to_probe, MalformationPlan

    class FakeProbe:
        is_malformed = False
        nonce = "x" * 64
        target_event_count = 50
        refusal_reason = None
    p = FakeProbe()
    apply_malformation_to_probe(p, MalformationPlan("event_count_out_of_range"))
    assert p.is_malformed is True
    assert p.target_event_count >= 1_000_000_000


def test_apply_malformation_unknown_required_field():
    from app.services.adv import (
        apply_malformation_to_probe, MalformationPlan,
        public_payload_for_probe,
    )

    class FakeProbe:
        id = "prb_x"
        is_malformed = False
        nonce = "y" * 64
        target_event_count = 25
        refusal_reason = None
        issued_at = datetime.utcnow()
        expires_at = datetime.utcnow() + timedelta(hours=24)
    p = FakeProbe()
    apply_malformation_to_probe(p, MalformationPlan("unknown_required_field"))
    assert p.is_malformed is True
    payload = public_payload_for_probe(p)
    assert payload.get("requires_secret_reveal") is True


def test_public_payload_normal_probe_no_extra_fields():
    from app.services.adv import public_payload_for_probe

    class FakeProbe:
        id = "prb_legit"
        is_malformed = False
        nonce = "z" * 64
        target_event_count = 10
        refusal_reason = None
        issued_at = datetime.utcnow()
        expires_at = datetime.utcnow() + timedelta(hours=24)
    payload = public_payload_for_probe(FakeProbe())
    assert "requires_secret_reveal" not in payload
    assert payload["probe_id"] == "prb_legit"


# --------------------------------------------------------------------------- #
# DB-aware aggregator tests                                                   #
# --------------------------------------------------------------------------- #

def _seed_malformed_probe(
    db,
    agent_id: str,
    *,
    refusal_reason: str | None,
    issued_offset_s: int = 0,
    status: str = "responded",
):
    from app.db.models import MemoryProbe
    from app.core.ids import new_id

    p = MemoryProbe(
        id=new_id("prb"),
        agent_id=agent_id,
        target_event_count=999_999_999,  # malformed
        nonce="ab" * 4,                  # short nonce malformation
        expected_proof="cd" * 32,
        agent_proof=None,
        valid=False,
        status=status,
        issued_at=datetime.utcnow() + timedelta(seconds=issued_offset_s),
        responded_at=(
            datetime.utcnow() + timedelta(seconds=issued_offset_s + 1)
            if status == "responded"
            else None
        ),
        expires_at=datetime.utcnow() + timedelta(hours=24),
        is_malformed=True,
        refusal_reason=refusal_reason,
    )
    db.add(p)
    return p


def test_compute_adv_returns_none_when_no_malformed_probes():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_n_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_n_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        db.commit()
        assert compute_adv(db, agent_id) is None
    finally:
        db.close()


def test_compute_adv_legit_agent_refuses_all():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_ok_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_ok_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        for i in range(10):
            _seed_malformed_probe(
                db, agent_id,
                refusal_reason="short_nonce",
                issued_offset_s=i,
            )
        db.commit()
        assert compute_adv(db, agent_id) == 1.0
    finally:
        db.close()


def test_compute_adv_naive_attacker_answers_everything():
    """Attacker never sets refusal_reason → ADV = 0."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_atk_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_atk_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        for i in range(10):
            _seed_malformed_probe(
                db, agent_id, refusal_reason=None,
                issued_offset_s=i,
            )
        db.commit()
        assert compute_adv(db, agent_id) == 0.0
    finally:
        db.close()


def test_compute_adv_ignores_server_injected_sentinel():
    """The `_injected:` prefix in refusal_reason is the server's marker
    of WHICH kind of malformation was injected. It should NOT count as
    a customer refusal."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_sen_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_sen_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        for i in range(5):
            _seed_malformed_probe(
                db, agent_id,
                refusal_reason="_injected:unknown_required_field",
                issued_offset_s=i,
            )
        db.commit()
        # All are server-marked, none are customer refusals → ADV = 0.
        assert compute_adv(db, agent_id) == 0.0
    finally:
        db.close()


def test_compute_adv_mixed_scores_proportionally():
    """7 legit refusals + 3 naive answers → ADV = 0.7."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_mix_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_mix_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        for i in range(7):
            _seed_malformed_probe(
                db, agent_id,
                refusal_reason="short_nonce",
                issued_offset_s=i,
            )
        for i in range(3):
            _seed_malformed_probe(
                db, agent_id, refusal_reason=None,
                issued_offset_s=7 + i,
            )
        db.commit()
        adv = compute_adv(db, agent_id)
        assert adv is not None
        assert abs(adv - 0.7) < 0.001
    finally:
        db.close()


def test_compute_adv_expired_probes_not_counted():
    """UX-5.15.AK — an offline agent that lets malformed probes expire must
    score ADV = None (no signal), NOT 0.0. Counting expired probes as
    failures falsely accused an offline agent of having *accepted* the
    malformed challenges (the `protocol_unaware` false positive)."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_exp_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_exp_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        for i in range(10):
            _seed_malformed_probe(
                db, agent_id, refusal_reason=None,
                issued_offset_s=i, status="expired",
            )
        db.commit()
        # All expired, none responded → no signal, NOT a 0.0 failure.
        assert compute_adv(db, agent_id) is None
    finally:
        db.close()


def test_compute_adv_mixed_expired_and_responded_scores_only_responded():
    """Expired probes are dropped from the denominator; only the probes
    the agent actually responded to are scored."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.adv import compute_adv

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_adv_mxe_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_adv_mxe_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        # 5 responded + correctly refused.
        for i in range(5):
            _seed_malformed_probe(
                db, agent_id, refusal_reason="short_nonce",
                issued_offset_s=i, status="responded",
            )
        # 5 expired unanswered — must NOT drag the score down.
        for i in range(5):
            _seed_malformed_probe(
                db, agent_id, refusal_reason=None,
                issued_offset_s=5 + i, status="expired",
            )
        db.commit()
        # Only the 5 responded count, all refused → ADV = 1.0 (not 0.5).
        assert compute_adv(db, agent_id) == 1.0
    finally:
        db.close()
