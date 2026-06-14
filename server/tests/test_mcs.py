"""Tests for the MCS (Multi-agent Corroboration Score) module."""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime


# Set DB_URL BEFORE any app imports — engine is built at import time.
_TMP_DB_PATH = f"/tmp/_metalins_mcs_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _seed_customer_with_two_agents(db, *, with_states: bool = True):
    """Create a customer + two agents with deterministic secrets.
    Returns (customer_id, agent_a_id, agent_b_id, secret_a, secret_b).
    """
    from app.db.models import APIKey, Agent, AgentState, Customer

    # The Customer table must exist (it's an FK target on AgentMeshPair).
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"
    db.add(Customer(id=customer_id, email=f"{customer_id}@t.local"))

    key_id = f"key_mcs_{uuid.uuid4().hex[:8]}"
    db.add(APIKey(
        id=key_id, customer_id=customer_id,
        key_hash=uuid.uuid4().hex * 2,
        owner_email=f"{customer_id}@t.local", label="m",
    ))
    # Agent IDs need to be lexicographically distinct so canonical
    # ordering puts agent_a before agent_b.
    suffix_a = uuid.uuid4().hex[:6]
    suffix_b = uuid.uuid4().hex[:6]
    agent_a_id = f"agt_a_{suffix_a}"
    agent_b_id = f"agt_b_{suffix_b}"
    db.add(Agent(id=agent_a_id, api_key_id=key_id, name="a", is_active=True))
    db.add(Agent(id=agent_b_id, api_key_id=key_id, name="b", is_active=True))

    secret_a = (b"\xa1" * 32).hex()
    secret_b = (b"\xb2" * 32).hex()
    if with_states:
        anchor_a = hashlib.sha256(bytes.fromhex(secret_a) + b"init").hexdigest()
        anchor_b = hashlib.sha256(bytes.fromhex(secret_b) + b"init").hexdigest()
        db.add(AgentState(
            agent_id=agent_a_id, agent_secret=secret_a,
            history_digest=anchor_a, event_count=0,
        ))
        db.add(AgentState(
            agent_id=agent_b_id, agent_secret=secret_b,
            history_digest=anchor_b, event_count=0,
        ))
    db.commit()
    return customer_id, agent_a_id, agent_b_id, secret_a, secret_b


# --------------------------------------------------------------------------- #
# Pure function tests                                                         #
# --------------------------------------------------------------------------- #

def test_canonical_pair_orders_lexicographically():
    from app.services.mcs import canonical_pair

    assert canonical_pair("agt_z", "agt_a") == ("agt_a", "agt_z")
    assert canonical_pair("agt_a", "agt_z") == ("agt_a", "agt_z")


def test_canonical_pair_rejects_self_pair():
    from app.services.mcs import canonical_pair

    try:
        canonical_pair("agt_x", "agt_x")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for self-pair")


def test_compute_co_signature_reproducible():
    from app.services.mcs import compute_co_signature

    secret = "aa" * 32
    state_self = "11" * 32
    state_partner = "22" * 32
    s1 = compute_co_signature(secret, state_self, state_partner)
    s2 = compute_co_signature(secret, state_self, state_partner)
    assert s1 == s2
    assert len(s1) == 64


def test_compute_co_signature_uses_concat_bytes():
    """Manual verification: HMAC over (state_self || state_partner)."""
    from app.services.mcs import compute_co_signature

    secret = "cc" * 32
    a = "33" * 32
    b = "44" * 32
    expected = hmac.new(
        bytes.fromhex(secret),
        bytes.fromhex(a) + bytes.fromhex(b),
        hashlib.sha256,
    ).hexdigest()
    assert compute_co_signature(secret, a, b) == expected


# --------------------------------------------------------------------------- #
# Pair management tests                                                       #
# --------------------------------------------------------------------------- #

def test_create_mesh_pair_idempotent():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import create_mesh_pair

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        customer_id, agent_a, agent_b, _, _ = _seed_customer_with_two_agents(db)
        p1 = create_mesh_pair(db, customer_id, agent_a, agent_b)
        # Call again with reversed order — should return same row.
        p2 = create_mesh_pair(db, customer_id, agent_b, agent_a)
        assert p1.id == p2.id
        assert p1.agent_a_id < p1.agent_b_id
    finally:
        db.close()


def test_find_pair_returns_active_only():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import create_mesh_pair, find_pair_for_agent

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        customer_id, agent_a, agent_b, _, _ = _seed_customer_with_two_agents(db)
        pair = create_mesh_pair(db, customer_id, agent_a, agent_b)
        assert find_pair_for_agent(db, agent_a) is not None
        # Pause the pair → find returns None.
        pair.paused_at = datetime.utcnow()
        db.commit()
        assert find_pair_for_agent(db, agent_a) is None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Submission + resolution tests                                               #
# --------------------------------------------------------------------------- #

def test_submit_corroboration_legit_pair_resolves_verified():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import (
        create_mesh_pair, submit_corroboration, compute_co_signature, compute_mcs,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        customer_id, agent_a, agent_b, sec_a, sec_b = (
            _seed_customer_with_two_agents(db)
        )
        create_mesh_pair(db, customer_id, agent_a, agent_b)

        # Both agents see the same shared (state_a, state_b).
        state_a = "11" * 32
        state_b = "22" * 32
        co_sig_a = compute_co_signature(sec_a, state_a, state_b)
        co_sig_b = compute_co_signature(sec_b, state_b, state_a)

        row_a = submit_corroboration(db, agent_a, 1, state_a, state_b, co_sig_a)
        assert row_a.verified is None  # still waiting on B
        row_b = submit_corroboration(db, agent_b, 1, state_b, state_a, co_sig_b)
        assert row_b.verified is True
        assert row_b.resolved_at is not None

        mcs = compute_mcs(db, agent_a)
        assert mcs == 1.0
    finally:
        db.close()


def test_submit_corroboration_compromised_a_fails():
    """R11 scenario: agent A is compromised, attacker doesn't have
    agent B's actual internal state. A's `partner_state` claim won't
    match what B reports for its own state → verification fails."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import (
        create_mesh_pair, submit_corroboration, compute_co_signature, compute_mcs,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        customer_id, agent_a, agent_b, sec_a, sec_b = (
            _seed_customer_with_two_agents(db)
        )
        create_mesh_pair(db, customer_id, agent_a, agent_b)

        # B's real state. A (compromised) doesn't know it and guesses.
        state_b_real = "bb" * 32
        state_b_attacker_guess = "00" * 32  # wrong

        state_a = "aa" * 32
        # A signs with its (still-real) secret over its WRONG view.
        co_sig_a = compute_co_signature(sec_a, state_a, state_b_attacker_guess)
        # B signs honestly: state_self = state_b_real, partner = state_a.
        co_sig_b = compute_co_signature(sec_b, state_b_real, state_a)

        submit_corroboration(
            db, agent_a, 1, state_a, state_b_attacker_guess, co_sig_a,
        )
        row = submit_corroboration(
            db, agent_b, 1, state_b_real, state_a, co_sig_b,
        )
        assert row.verified is False, "agreement check should fail"
        mcs = compute_mcs(db, agent_a)
        assert mcs == 0.0
    finally:
        db.close()


def test_compute_mcs_returns_none_when_unpaired():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import compute_mcs

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_a, _, _, _ = _seed_customer_with_two_agents(db)
        # No mesh pair created.
        assert compute_mcs(db, agent_a) is None
    finally:
        db.close()


def test_compute_mcs_aggregates_mixed_cycles():
    """5 verified + 5 unverified cycles → MCS = 0.5."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import CorroborationPoint
    from app.core.ids import new_id
    from app.services.mcs import create_mesh_pair, compute_mcs

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        customer_id, agent_a, agent_b, _, _ = _seed_customer_with_two_agents(db)
        pair = create_mesh_pair(db, customer_id, agent_a, agent_b)
        for i in range(10):
            db.add(CorroborationPoint(
                id=new_id("cor"),
                mesh_pair_id=pair.id,
                cycle=i,
                verified=(i < 5),  # first 5 valid
                resolved_at=datetime.utcnow(),
            ))
        db.commit()
        mcs = compute_mcs(db, agent_a, window=10)
        assert mcs == 0.5
    finally:
        db.close()


def test_submit_corroboration_rejects_unpaired_agent():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.mcs import (
        submit_corroboration, CorroborationSubmissionError,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_a, _, _, _ = _seed_customer_with_two_agents(db)
        try:
            submit_corroboration(
                db, agent_a, 1, "00" * 32, "11" * 32, "22" * 32,
            )
        except CorroborationSubmissionError as e:
            assert "not part" in e.reason
        else:
            raise AssertionError("expected CorroborationSubmissionError")
    finally:
        db.close()
