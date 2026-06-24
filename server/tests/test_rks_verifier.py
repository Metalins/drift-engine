"""Unit + integration tests for the RKS (Re-Keyed Signature) verifier.

Replicates the adversarial scenarios from
`research/R4-computational-validation/code/protocols_r10.py` against the
production verifier in `app.services.rks_verifier`.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import random
from datetime import datetime, timedelta


# Set DB_URL BEFORE any app imports — engine is built at import time.
_TMP_DB_PATH = f"/tmp/_metalins_rks_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Test fixtures                                                               #
# --------------------------------------------------------------------------- #

def _make_legit_chain(
    agent_id: str,
    n: int,
    agent_secret_hex: str,
    rng_seed: int = 7,
):
    """Build n events that form a valid chain signed by the rotating
    secret derived from `agent_secret_hex` + history digest at each step.

    Mirrors mcp_endpoints._do_log_event byte-for-byte.
    """
    from app.core.ids import new_id
    from app.db.models import EventLog

    rng = random.Random(rng_seed)
    rows: list[EventLog] = []
    base = datetime.utcnow()

    # Anchor: same as register_agent.
    current_digest_hex = hashlib.sha256(
        bytes.fromhex(agent_secret_hex) + b"init"
    ).hexdigest()

    for i in range(n):
        c = rng.randint(0, 31)
        r = (5 * c + 1) % 32
        input_hash = hashlib.sha256(f"ch{c}_{i}".encode()).hexdigest()
        output_hash = hashlib.sha256(f"rs{r}_{i}".encode()).hexdigest()

        h = hashlib.sha256()
        h.update(bytes.fromhex(current_digest_hex))
        h.update(input_hash.encode())
        h.update(output_hash.encode())
        new_digest = h.hexdigest()

        rotating = hmac.new(
            bytes.fromhex(agent_secret_hex),
            bytes.fromhex(new_digest),
            hashlib.sha256,
        ).digest()
        msg = f"{input_hash}|{output_hash}|{i + 1}".encode()
        sig = hmac.new(rotating, msg, hashlib.sha256).hexdigest()

        rows.append(EventLog(
            id=new_id("evt"),
            agent_id=agent_id,
            event_count=i + 1,
            input_hash=input_hash,
            output_hash=output_hash,
            history_digest=new_digest,
            signature=sig,
            metadata_json={},
            ts=base + timedelta(seconds=i),
        ))
        current_digest_hex = new_digest

    return rows


def _make_forked_chain(
    agent_id: str,
    n_legit: int,
    n_forked: int,
    real_secret_hex: str,
    attacker_secret_hex: str | None = None,
    rng_seed: int = 11,
):
    """Build a chain where the first n_legit events are valid, then an
    attacker takes over for n_forked events. The attacker uses a WRONG
    history digest base (the all-zero anchor from protocols_r10's
    SecretOnlyAttacker) and even if they sign with the real secret the
    rotating-secret derivation diverges from what the server expects.
    """
    from app.core.ids import new_id
    from app.db.models import EventLog

    rng = random.Random(rng_seed)
    rows = _make_legit_chain(agent_id, n_legit, real_secret_hex, rng_seed)
    attacker_digest = b"\x00" * 32
    secret_hex = attacker_secret_hex or real_secret_hex
    base = datetime.utcnow() + timedelta(seconds=n_legit)

    for i in range(n_forked):
        event_count = n_legit + i + 1
        c = rng.randint(0, 31)
        r = rng.randint(0, 31)
        input_hash = hashlib.sha256(f"fch{c}_{i}".encode()).hexdigest()
        output_hash = hashlib.sha256(f"frs{r}_{i}".encode()).hexdigest()

        # Attacker advances ITS OWN (wrong) digest.
        h = hashlib.sha256()
        h.update(attacker_digest)
        h.update(input_hash.encode())
        h.update(output_hash.encode())
        attacker_digest_after = h.digest()

        rotating = hmac.new(
            bytes.fromhex(secret_hex),
            attacker_digest_after,
            hashlib.sha256,
        ).digest()
        msg = f"{input_hash}|{output_hash}|{event_count}".encode()
        sig = hmac.new(rotating, msg, hashlib.sha256).hexdigest()

        # IMPORTANT: the attacker writes its own (forked) history_digest
        # value into the row. The real server replay will diverge.
        rows.append(EventLog(
            id=new_id("evt"),
            agent_id=agent_id,
            event_count=event_count,
            input_hash=input_hash,
            output_hash=output_hash,
            history_digest=attacker_digest_after.hex(),
            signature=sig,
            metadata_json={},
            ts=base + timedelta(seconds=i),
        ))
        attacker_digest = attacker_digest_after

    return rows


# --------------------------------------------------------------------------- #
# Unit tests on pure functions                                                #
# --------------------------------------------------------------------------- #

def test_initial_digest_matches_register_formula():
    """The anchor formula has to stay locked to what register_agent writes."""
    from app.services.rks_verifier import initial_history_digest

    secret = (b"\x01" * 32).hex()
    expected = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
    assert initial_history_digest(secret) == expected


def test_advance_digest_mirrors_log_event():
    """The chain step must mirror mcp_endpoints._do_log_event byte-for-byte."""
    from app.services.rks_verifier import advance_digest

    prior = "ab" * 32
    input_hash = "ih"
    output_hash = "oh"
    h = hashlib.sha256()
    h.update(bytes.fromhex(prior))
    h.update(input_hash.encode())
    h.update(output_hash.encode())
    assert advance_digest(prior, input_hash, output_hash) == h.hexdigest()


def test_verify_chain_legit_returns_perfect_rks():
    """Honest agent → every signature verifies → RKS = 1.0."""
    from app.services.rks_verifier import (
        verify_event_chain, initial_history_digest,
    )

    secret = (b"\xaa" * 32).hex()
    events = _make_legit_chain("agt_legit", 50, secret)
    result = verify_event_chain(events, secret, initial_history_digest(secret))

    assert result.n_events == 50
    assert result.n_signature_valid == 50
    assert result.n_digest_valid == 50
    assert result.first_failure_event_count is None
    assert result.rks == 1.0


def test_verify_chain_fork_cascades():
    """Once the chain forks, every subsequent event fails (replay diverges)."""
    from app.services.rks_verifier import (
        verify_event_chain, initial_history_digest,
    )

    secret = (b"\xbb" * 32).hex()
    events = _make_forked_chain(
        "agt_fork", n_legit=30, n_forked=20, real_secret_hex=secret,
    )
    result = verify_event_chain(events, secret, initial_history_digest(secret))

    assert result.n_events == 50
    # First 30 valid; 20 forked invalid.
    assert result.n_signature_valid == 30
    assert result.first_failure_event_count == 31
    assert result.rks == 30 / 50


def test_verify_chain_secret_only_attacker_matches_R10_scenario():
    """Replicate protocols_r10.scenario_rekey_secret_only_attacker.

    Per the paper, swap-at-T/2 yields RKS ≈ 0.5 (legit half passes, forked
    half fails). AUC = 1.0 in research because the gap legit↔attacker is
    always 0.5 vs 1.0.
    """
    from app.services.rks_verifier import (
        verify_event_chain, initial_history_digest,
    )

    secret = (b"\xcc" * 32).hex()
    events = _make_forked_chain(
        "agt_swap", n_legit=100, n_forked=100, real_secret_hex=secret,
    )
    result = verify_event_chain(events, secret, initial_history_digest(secret))

    # Should be exactly 0.5 because we wrote 100 legit + 100 forked.
    assert 0.45 < result.rks < 0.55


# --------------------------------------------------------------------------- #
# DB-aware aggregator tests                                                   #
# --------------------------------------------------------------------------- #

def test_compute_rks_returns_none_when_no_events():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, AgentState
    from app.services.rks_verifier import compute_rks

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        secret = (b"\xdd" * 32).hex()
        db.add(APIKey(id="key_e", key_hash="x" * 64, owner_email="e@e.local", label="e"))
        db.add(Agent(id="agt_empty", api_key_id="key_e", name="e", is_active=True))
        db.add(AgentState(
            agent_id="agt_empty",
            agent_secret=secret,
            history_digest=hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest(),
            event_count=0,
        ))
        db.commit()

        assert compute_rks(db, "agt_empty") is None
    finally:
        db.close()


def test_compute_rks_perfect_for_legit_chain():
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, AgentState
    from app.services.rks_verifier import compute_rks

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        secret = (b"\xee" * 32).hex()
        anchor = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
        db.add(APIKey(id="key_p", key_hash="p" * 64, owner_email="p@p.local", label="p"))
        db.add(Agent(id="agt_perfect", api_key_id="key_p", name="p", is_active=True))
        db.add(AgentState(
            agent_id="agt_perfect",
            agent_secret=secret,
            history_digest=anchor,
            event_count=0,
        ))
        for ev in _make_legit_chain("agt_perfect", 30, secret):
            db.add(ev)
        db.commit()

        assert compute_rks(db, "agt_perfect") == 1.0
    finally:
        db.close()


def test_compute_rks_detects_secret_only_attacker():
    """End-to-end DB scenario: legit + forked events → RKS drops to ~0.5."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, AgentState
    from app.services.rks_verifier import compute_rks

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        secret = (b"\xff" * 32).hex()
        anchor = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
        db.add(APIKey(id="key_a", key_hash="a" * 64, owner_email="a@a.local", label="a"))
        db.add(Agent(id="agt_attacked", api_key_id="key_a", name="a", is_active=True))
        db.add(AgentState(
            agent_id="agt_attacked",
            agent_secret=secret,
            history_digest=anchor,
            event_count=0,
        ))
        for ev in _make_forked_chain(
            "agt_attacked", n_legit=80, n_forked=80, real_secret_hex=secret,
        ):
            db.add(ev)
        db.commit()

        rks = compute_rks(db, "agt_attacked", window=200)
        assert rks is not None
        # ~half valid (legit), ~half invalid (forked).
        assert 0.45 < rks < 0.55
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Integration test through compute_for_agent                                  #
# --------------------------------------------------------------------------- #

def test_compute_for_agent_includes_rks_in_details():
    """Sanity: when wired through the batch job, rks lands in details_json."""
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, AgentState
    from app.services.observable_job import compute_for_agent

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        secret = (b"\xab" * 32).hex()
        anchor = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
        db.add(APIKey(id="key_i", key_hash="i" * 64, owner_email="i@i.local", label="i"))
        db.add(Agent(id="agt_int", api_key_id="key_i", name="i", is_active=True))
        db.add(AgentState(
            agent_id="agt_int",
            agent_secret=secret,
            history_digest=anchor,
            event_count=0,
        ))
        # Sprint UX-5.12: ICR floor is 2000 events; use 2200 so the full
        # batch-job path (including ICR → identity_confidence) is
        # exercised, not skipped on "not enough data".
        for ev in _make_legit_chain("agt_int", 2200, secret):
            db.add(ev)
        db.commit()

        row = compute_for_agent(db, "agt_int")
        assert row is not None
        assert row.details_json.get("rks") == 1.0
        assert row.identity_confidence > 0
    finally:
        db.close()
