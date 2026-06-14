"""Integration test for the batch observable job against a real DB session.

Uses SQLite in-memory so the test is self-contained — no external deps.
"""
from __future__ import annotations

import hashlib
import os
import random
import tempfile
from datetime import datetime, timedelta

import pytest


# Set DB_URL BEFORE any app imports — engine is built at import time.
# Use /tmp explicitly: TMPDIR may point to a mount sqlite can't lock on.
_TMP_DB_PATH = f"/tmp/_metalins_test_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


def _make_event_rows(
    agent_id: str,
    n: int,
    coupled: bool,
    agent_secret_hex: str | None = None,
):
    """Build EventLog instances for an agent with deterministic input/output.

    Sprint 7 — also constructs a valid digest chain and rotating signatures
    so RKS evaluates to 1.0 on synthetic data. If `agent_secret_hex` is
    None we derive a deterministic dummy secret so old call sites don't
    break.
    """
    import hmac
    from app.core.ids import new_id
    from app.db.models import EventLog

    rng = random.Random(7 if coupled else 11)
    rows: list[EventLog] = []
    base = datetime.utcnow()

    secret_hex = agent_secret_hex or (b"\x42" * 32).hex()
    # Match mcp_endpoints.register_agent's init formula.
    current_digest_hex = hashlib.sha256(
        bytes.fromhex(secret_hex) + b"init"
    ).hexdigest()

    for i in range(n):
        c = rng.randint(0, 31)
        r = (5 * c + 1) % 32 if coupled else rng.randint(0, 31)
        input_hash = hashlib.sha256(f"ch{c}".encode()).hexdigest()
        output_hash = hashlib.sha256(f"rs{r}".encode()).hexdigest()

        # Advance digest chain — must mirror mcp_endpoints._do_log_event.
        h = hashlib.sha256()
        h.update(bytes.fromhex(current_digest_hex))
        h.update(input_hash.encode())
        h.update(output_hash.encode())
        current_digest_hex = h.hexdigest()

        rotating = hmac.new(
            bytes.fromhex(secret_hex),
            bytes.fromhex(current_digest_hex),
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
            history_digest=current_digest_hex,
            signature=sig,
            metadata_json={},
            ts=base + timedelta(seconds=i),
        ))
    return rows


def test_compute_for_agent_writes_observable_row():
    """End-to-end: events → compute_for_agent → AgentObservable row persisted."""
    import uuid
    # Imports must happen after env var set
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent, AgentObservable
    from app.services.observable_job import compute_for_agent

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Unique IDs so state pollution from sibling test files doesn't
        # collide on the UNIQUE(key_hash) constraint. Sprint 7 — we now
        # have multiple test modules all sharing the same in-memory SQLite
        # because METALINS_DB_URL is fixed at import time. Worth fixing
        # globally (#496), but cheap to dodge per-test here.
        key_id = f"key_obs_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_obs_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t@t.local", label="t",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t", is_active=True))
        # Sprint UX-5.12: ICR floor is 2000 events. Use 2200 so ICR is
        # reported, not None. With deterministic coupling the value is
        # well above the bias-correction noise floor.
        n = 2200
        for r in _make_event_rows(agent_id, n, coupled=True):
            db.add(r)
        db.commit()

        row = compute_for_agent(db, agent_id)
        assert row is not None, f"should have computed for {n} events"
        # compute_for_agent caps at DEFAULT_WINDOW (~2000). Past that,
        # n_events reflects the window, not the seeded count.
        assert row.n_events >= 2000, f"got n_events={row.n_events}"
        assert row.icr is not None and row.icr > 0.5
        assert row.ttm is not None
        assert row.identity_confidence > 0.2

        persisted = db.query(AgentObservable).filter_by(agent_id=agent_id).all()
        assert len(persisted) == 1
    finally:
        db.close()


def test_compute_for_agent_skips_when_too_few_events():
    import uuid
    from app.db.session import engine, SessionLocal
    from app.db import Base
    from app.db.models import APIKey, Agent
    from app.services.observable_job import compute_for_agent

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        key_id = f"key_skip_{uuid.uuid4().hex[:8]}"
        agent_id = f"agt_skip_{uuid.uuid4().hex[:8]}"
        db.add(APIKey(
            id=key_id, key_hash=uuid.uuid4().hex * 2,
            owner_email="t2@t.local", label="t2",
        ))
        db.add(Agent(id=agent_id, api_key_id=key_id, name="t2", is_active=True))
        for r in _make_event_rows(agent_id, 5, coupled=True):
            db.add(r)
        db.commit()

        row = compute_for_agent(db, agent_id)
        assert row is None, "should skip below MIN_EVENTS_FOR_COMPUTE"
    finally:
        db.close()
