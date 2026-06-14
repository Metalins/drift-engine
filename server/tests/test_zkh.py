"""Unit + integration tests for the ZKH (Zero-Knowledge History) module.

Covers:
  - Pure Merkle primitives (root, path, verification, edge cases).
  - DB-aware challenge/response lifecycle (issue, verify, reject).
  - Adversarial scenarios mirroring research/R12.

Honest framing reminder (audit §7): in V1 ZKH overlaps significantly
with MVS because I/O hashes are persisted server-side. The tests still
validate the canonical commit-reveal shape end-to-end so the layer is
ready when we relax the server-side digest assumption.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta


# Set DB_URL BEFORE any app imports — engine is built at import time.
_TMP_DB_PATH = f"/tmp/_metalins_zkh_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Pure Merkle tests                                                           #
# --------------------------------------------------------------------------- #

def test_merkle_root_empty_is_sha256_of_empty():
    from app.services.zkh import merkle_root

    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_merkle_root_single_leaf_equals_leaf():
    from app.services.zkh import merkle_root

    leaf = hashlib.sha256(b"only").hexdigest()
    assert merkle_root([leaf]) == leaf


def test_merkle_root_two_leaves_matches_manual():
    """Manual verification of the 2-leaf case so we know our encoding."""
    from app.services.zkh import merkle_root

    a = hashlib.sha256(b"a").hexdigest()
    b = hashlib.sha256(b"b").hexdigest()
    expected = hashlib.sha256(
        bytes.fromhex(a) + bytes.fromhex(b)
    ).hexdigest()
    assert merkle_root([a, b]) == expected


def test_merkle_root_odd_leaves_duplicates_last():
    """Bitcoin convention: odd levels duplicate the last node."""
    from app.services.zkh import merkle_root

    a = hashlib.sha256(b"a").hexdigest()
    b = hashlib.sha256(b"b").hexdigest()
    c = hashlib.sha256(b"c").hexdigest()
    # Level 0: [a, b, c] → odd, duplicate c → [a, b, c, c].
    # Level 1: [hash(a||b), hash(c||c)].
    # Root: hash(hash(a||b) || hash(c||c)).
    level1_left = hashlib.sha256(bytes.fromhex(a) + bytes.fromhex(b)).digest()
    level1_right = hashlib.sha256(bytes.fromhex(c) + bytes.fromhex(c)).digest()
    expected = hashlib.sha256(level1_left + level1_right).hexdigest()
    assert merkle_root([a, b, c]) == expected


def test_merkle_path_roundtrip_each_leaf():
    """For each leaf in a 6-leaf tree, the path must walk back to root."""
    from app.services.zkh import merkle_root, merkle_path, verify_merkle_path

    leaves = [hashlib.sha256(f"x{i}".encode()).hexdigest() for i in range(6)]
    root = merkle_root(leaves)
    for i, leaf in enumerate(leaves):
        path = merkle_path(leaves, i)
        assert verify_merkle_path(leaf, path, root), (
            f"path for leaf {i} should verify"
        )


def test_merkle_path_rejects_wrong_root():
    from app.services.zkh import merkle_path, verify_merkle_path

    leaves = [hashlib.sha256(f"y{i}".encode()).hexdigest() for i in range(4)]
    path = merkle_path(leaves, 2)
    bogus_root = "00" * 32
    assert verify_merkle_path(leaves[2], path, bogus_root) is False


def test_merkle_path_rejects_tampered_sibling():
    from app.services.zkh import merkle_root, merkle_path, verify_merkle_path

    leaves = [hashlib.sha256(f"z{i}".encode()).hexdigest() for i in range(8)]
    root = merkle_root(leaves)
    path = merkle_path(leaves, 5)
    # Flip one sibling.
    path[0] = {"sibling": "ff" * 32, "side": path[0]["side"]}
    assert verify_merkle_path(leaves[5], path, root) is False


def test_merkle_path_rejects_bad_side_field():
    from app.services.zkh import merkle_root, merkle_path, verify_merkle_path

    leaves = [hashlib.sha256(f"q{i}".encode()).hexdigest() for i in range(4)]
    root = merkle_root(leaves)
    path = merkle_path(leaves, 1)
    path[0]["side"] = "X"  # not L or R
    assert verify_merkle_path(leaves[1], path, root) is False


def test_merkle_path_out_of_range_raises():
    from app.services.zkh import merkle_path

    leaves = [hashlib.sha256(b"a").hexdigest()]
    try:
        merkle_path(leaves, 5)
    except IndexError:
        pass
    else:
        raise AssertionError("expected IndexError")


# --------------------------------------------------------------------------- #
# DB-aware test helpers                                                       #
# --------------------------------------------------------------------------- #

def _seed_customer_and_agent(db, *, n_events: int = 0):
    """Create a customer + agent with `n_events` chained events.

    Returns (customer_id, agent_id, agent_secret_hex, leaves) where
    `leaves` is the ordered list of history_digest hex values (so tests
    can build the agent-side Merkle tree directly).
    """
    from app.db.models import APIKey, Agent, AgentState, Customer, EventLog
    from app.core.ids import new_id

    customer_id = f"cust_{uuid.uuid4().hex[:8]}"
    db.add(Customer(id=customer_id, email=f"{customer_id}@t.local"))

    key_id = f"key_zkh_{uuid.uuid4().hex[:8]}"
    db.add(APIKey(
        id=key_id, customer_id=customer_id,
        key_hash=uuid.uuid4().hex * 2,
        owner_email=f"{customer_id}@t.local", label="z",
    ))

    agent_id = f"agt_zkh_{uuid.uuid4().hex[:6]}"
    db.add(Agent(id=agent_id, api_key_id=key_id, name="z", is_active=True))

    secret_hex = (b"\xc3" * 32).hex()
    anchor = hashlib.sha256(bytes.fromhex(secret_hex) + b"init").hexdigest()
    db.add(AgentState(
        agent_id=agent_id, agent_secret=secret_hex,
        history_digest=anchor, event_count=n_events,
    ))

    leaves: list[str] = []
    current_digest = anchor
    base_ts = datetime.utcnow()
    for i in range(n_events):
        ih = hashlib.sha256(f"ih{i}".encode()).hexdigest()
        oh = hashlib.sha256(f"oh{i}".encode()).hexdigest()
        h = hashlib.sha256()
        h.update(bytes.fromhex(current_digest))
        h.update(ih.encode())
        h.update(oh.encode())
        current_digest = h.hexdigest()
        leaves.append(current_digest)

        rotating = hmac.new(
            bytes.fromhex(secret_hex),
            bytes.fromhex(current_digest),
            hashlib.sha256,
        ).digest()
        sig = hmac.new(
            rotating,
            f"{ih}|{oh}|{i + 1}".encode(),
            hashlib.sha256,
        ).hexdigest()

        db.add(EventLog(
            id=new_id("evt"),
            agent_id=agent_id,
            event_count=i + 1,
            input_hash=ih,
            output_hash=oh,
            history_digest=current_digest,
            signature=sig,
            metadata_json={},
            ts=base_ts + timedelta(seconds=i),
        ))
    db.commit()
    return customer_id, agent_id, secret_hex, leaves


# --------------------------------------------------------------------------- #
# Server-side root reconstruction                                             #
# --------------------------------------------------------------------------- #

def test_server_compute_merkle_root_matches_pure():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import merkle_root, server_compute_merkle_root

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=8)
        server_root, n = server_compute_merkle_root(db, agent_id)
        assert n == 8
        assert server_root == merkle_root(leaves)
    finally:
        db.close()


def test_server_get_digest_at_returns_correct_leaf():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import server_get_digest_at

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=5)
        for i, expected in enumerate(leaves, start=1):
            assert server_get_digest_at(db, agent_id, i) == expected
        assert server_get_digest_at(db, agent_id, 999) is None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Challenge / response lifecycle                                              #
# --------------------------------------------------------------------------- #

def test_issue_zkh_rejects_no_events():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import issue_zkh_challenge, ZKHChallengeError

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, _ = _seed_customer_and_agent(db, n_events=0)
        try:
            issue_zkh_challenge(db, agent_id, "ff" * 32)
        except ZKHChallengeError as e:
            assert "no events" in e.reason
        else:
            raise AssertionError("expected ZKHChallengeError")
    finally:
        db.close()


def test_issue_zkh_rejects_wrong_commit():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import issue_zkh_challenge, ZKHChallengeError

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, _ = _seed_customer_and_agent(db, n_events=4)
        try:
            issue_zkh_challenge(db, agent_id, "00" * 32)
        except ZKHChallengeError as e:
            assert "commit root" in e.reason
        else:
            raise AssertionError("expected ZKHChallengeError")
    finally:
        db.close()


def test_issue_zkh_persists_row_on_valid_commit():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import ZKHProof
    from app.services.zkh import (
        issue_zkh_challenge, merkle_root, server_compute_merkle_root,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=6)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        assert server_root == merkle_root(leaves)

        proof = issue_zkh_challenge(db, agent_id, server_root)
        assert proof.commit_root == server_root
        assert proof.server_root_at_issue == server_root
        assert 1 <= proof.t_star <= len(leaves)
        assert len(proof.nonce) == 32
        # Row is persisted.
        row = db.query(ZKHProof).filter(ZKHProof.id == proof.id).first()
        assert row is not None
    finally:
        db.close()


def test_verify_zkh_full_roundtrip():
    """Honest agent: commit, get challenge, open path → verified."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, merkle_path, server_compute_merkle_root,
        verify_zkh_response,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=8)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        proof = issue_zkh_challenge(db, agent_id, server_root)

        # Agent side: open the path at the challenged leaf.
        leaf_idx = proof.t_star - 1  # t_star is 1-indexed
        claimed_digest = leaves[leaf_idx]
        path = merkle_path(leaves, leaf_idx)

        ok, reason = verify_zkh_response(
            db, proof.id, claimed_digest, path, agent_id=agent_id,
        )
        assert ok is True, f"expected verified, got {reason}"
        assert reason == "ok"
    finally:
        db.close()


def test_verify_zkh_rejects_path_invalid():
    """Wrong path → path_invalid even if digest is correct."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, server_compute_merkle_root, verify_zkh_response,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=4)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        proof = issue_zkh_challenge(db, agent_id, server_root)
        leaf_idx = proof.t_star - 1
        claimed_digest = leaves[leaf_idx]

        bogus_path = [{"sibling": "aa" * 32, "side": "R"}]
        ok, reason = verify_zkh_response(
            db, proof.id, claimed_digest, bogus_path, agent_id=agent_id,
        )
        assert ok is False
        assert "path_invalid" in reason
    finally:
        db.close()


def test_verify_zkh_rejects_digest_mismatch():
    """Right path but claimed digest is something we never stored."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, merkle_path, merkle_root,
        server_compute_merkle_root, verify_zkh_response,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=4)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        proof = issue_zkh_challenge(db, agent_id, server_root)
        leaf_idx = proof.t_star - 1

        # Build a tree where the challenged leaf has been swapped, but
        # the rest is identical. The path will verify against the NEW
        # tree's root — but that root won't match the server's commit,
        # so the path check fails. We want to specifically isolate the
        # digest_mismatch path, so we commit the SAME tree but submit
        # a different claimed digest with its corresponding (wrong-for-
        # this-leaf) path. Simpler: submit the digest at leaf_idx XOR 1
        # with that leaf's correct path — both checks fail, reason will
        # be "path_invalid_and_digest_mismatch".
        wrong_idx = (leaf_idx + 1) % len(leaves)
        wrong_digest = leaves[wrong_idx]
        wrong_path = merkle_path(leaves, wrong_idx)
        ok, reason = verify_zkh_response(
            db, proof.id, wrong_digest, wrong_path, agent_id=agent_id,
        )
        # The path verifies to the same root (wrong_digest is a real
        # leaf), but the digest at t_star doesn't match → digest_mismatch.
        assert ok is False
        assert reason == "digest_mismatch"
    finally:
        db.close()


def test_verify_zkh_rejects_expired_challenge():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import ZKHProof
    from app.services.zkh import (
        issue_zkh_challenge, merkle_path, server_compute_merkle_root,
        verify_zkh_response, ZKH_CHALLENGE_TTL,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=4)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        proof = issue_zkh_challenge(db, agent_id, server_root)
        # Backdate the issued_at past the TTL.
        proof.issued_at = datetime.utcnow() - (ZKH_CHALLENGE_TTL + timedelta(seconds=1))
        db.commit()

        leaf_idx = proof.t_star - 1
        path = merkle_path(leaves, leaf_idx)
        ok, reason = verify_zkh_response(
            db, proof.id, leaves[leaf_idx], path, agent_id=agent_id,
        )
        assert ok is False
        assert reason == "zkh_expired"
        row = db.query(ZKHProof).filter(ZKHProof.id == proof.id).first()
        assert row.verified is False
        assert row.rejection_reason == "expired"
    finally:
        db.close()


def test_verify_zkh_rejects_double_submission():
    """Once resolved, a proof can't be re-verified."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, merkle_path, server_compute_merkle_root,
        verify_zkh_response,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=4)
        server_root, _ = server_compute_merkle_root(db, agent_id)
        proof = issue_zkh_challenge(db, agent_id, server_root)
        leaf_idx = proof.t_star - 1

        ok1, _ = verify_zkh_response(
            db, proof.id, leaves[leaf_idx],
            merkle_path(leaves, leaf_idx), agent_id=agent_id,
        )
        assert ok1 is True

        ok2, reason2 = verify_zkh_response(
            db, proof.id, leaves[leaf_idx],
            merkle_path(leaves, leaf_idx), agent_id=agent_id,
        )
        assert ok2 is False
        assert "already" in reason2
    finally:
        db.close()


def test_verify_zkh_rejects_wrong_agent():
    """Agent A can't open a challenge issued to agent B."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, merkle_path, server_compute_merkle_root,
        verify_zkh_response,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_a, _, leaves_a = _seed_customer_and_agent(db, n_events=4)
        _, agent_b, _, _ = _seed_customer_and_agent(db, n_events=4)
        server_root_a, _ = server_compute_merkle_root(db, agent_a)
        proof = issue_zkh_challenge(db, agent_a, server_root_a)
        leaf_idx = proof.t_star - 1

        ok, reason = verify_zkh_response(
            db, proof.id, leaves_a[leaf_idx],
            merkle_path(leaves_a, leaf_idx), agent_id=agent_b,
        )
        assert ok is False
        assert reason == "zkh_agent_mismatch"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Aggregator                                                                  #
# --------------------------------------------------------------------------- #

def test_compute_zkh_returns_none_without_proofs():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import compute_zkh

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, _ = _seed_customer_and_agent(db, n_events=2)
        assert compute_zkh(db, agent_id) is None
    finally:
        db.close()


def test_compute_zkh_aggregates_mixed():
    """3 verified + 2 rejected → 0.6."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import ZKHProof
    from app.core.ids import new_id
    from app.services.zkh import compute_zkh

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, _ = _seed_customer_and_agent(db, n_events=2)
        for i in range(5):
            db.add(ZKHProof(
                id=new_id("zkh"),
                agent_id=agent_id,
                commit_root="aa" * 32,
                server_root_at_issue="aa" * 32,
                t_star=1, nonce="bb" * 16,
                verified=(i < 3),
                resolved_at=datetime.utcnow(),
            ))
        db.commit()
        assert compute_zkh(db, agent_id) == 0.6
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Adversarial scenarios                                                       #
# --------------------------------------------------------------------------- #

def test_attacker_without_history_cannot_commit():
    """R12 scenario: an attacker holding only the agent's API credentials
    but not the local digest chain can't compute the right commit root.
    The challenge is rejected at issue time — no proof row is written."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import ZKHProof
    from app.services.zkh import (
        issue_zkh_challenge, ZKHChallengeError,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, _ = _seed_customer_and_agent(db, n_events=10)
        # Attacker guesses a root.
        attacker_guess = hashlib.sha256(b"guess").hexdigest()
        try:
            issue_zkh_challenge(db, agent_id, attacker_guess)
        except ZKHChallengeError as e:
            assert "commit root" in e.reason
        else:
            raise AssertionError("expected ZKHChallengeError")
        # No proof row was created.
        rows = db.query(ZKHProof).filter(ZKHProof.agent_id == agent_id).all()
        assert rows == []
    finally:
        db.close()


def test_attacker_with_stale_history_fails_at_path():
    """R12 scenario: attacker has a snapshot up to event N-3 but not the
    last 3 events. They can commit (server still has same root if they
    happen to lie about it — but they don't know the right root). If
    they DO somehow know the current root (e.g. shoulder-surfed), they
    still can't open the path at t_star when t_star lands inside the
    leaves they never saw.

    Here we model the simpler case: attacker has the OLD root from
    when there were only 7 events; server has 10. The commit check
    fails immediately because the trees differ.
    """
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.services.zkh import (
        issue_zkh_challenge, merkle_root, ZKHChallengeError,
    )

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _, agent_id, _, leaves = _seed_customer_and_agent(db, n_events=10)
        stale_root = merkle_root(leaves[:7])  # attacker's outdated tree
        try:
            issue_zkh_challenge(db, agent_id, stale_root)
        except ZKHChallengeError as e:
            assert "commit root" in e.reason
        else:
            raise AssertionError("expected ZKHChallengeError")
    finally:
        db.close()
