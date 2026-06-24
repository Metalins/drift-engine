"""Tests for slug collision retry under race (R2.2b, 2026-05-18).

The partial UNIQUE index `agents_public_slug_unique` in production
catches concurrent INSERTs with the same `public_slug`. Without retry
the loser request would 500 the customer. `commit_with_slug_retry`
catches the IntegrityError and re-allocates.

We can't easily simulate Postgres-side concurrent INSERTs in a SQLite
test fixture (SQLite doesn't enforce partial unique indexes the same
way), so we test the retry helper directly by monkeypatching
`db.commit` to raise an IntegrityError on first call and succeed on
the second.
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime

import pytest


_TMP_DB_PATH = f"/tmp/_metalins_slug_race_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    from app.db import Base
    from app.db.session import engine
    Base.metadata.create_all(bind=engine)
    yield


def _seed_customer_and_admin_key():
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    customer_id = new_id("cust")
    admin_raw = "ml_test_" + py_secrets.token_urlsafe(16)
    admin_key_id = new_id("key")
    db = SessionLocal()
    try:
        db.add(Customer(
            id=customer_id,
            email=f"slug-race-{py_secrets.token_hex(4)}@example.com",
        ))
        db.flush()
        db.add(APIKey(
            id=admin_key_id,
            customer_id=customer_id,
            agent_id=None,
            key_hash=hashlib.sha256(admin_raw.encode()).hexdigest(),
            owner_email="slug-race-test@example.com",
            label="slug-race-test-admin",
            is_active=True,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    finally:
        db.close()
    return customer_id, admin_raw


def test_allocator_walks_past_taken_slug():
    """First customer's slug 'carlos-bot' is taken; second register
    with the same name produces 'carlos-bot-2'."""
    from app.core.ids import new_id
    from app.core.slug import allocate_public_slug
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Agent, Customer

    db = SessionLocal()
    try:
        # Seed an existing agent with slug "carlos-bot".
        c_id = new_id("cust")
        k_id = new_id("key")
        a_id = new_id("agt")
        db.add(Customer(id=c_id, email=f"first-{py_secrets.token_hex(4)}@example.com"))
        db.flush()
        db.add(APIKey(
            id=k_id, customer_id=c_id, agent_id=None,
            key_hash=hashlib.sha256(b"x").hexdigest(),
            owner_email="x@example.com", label="x",
            is_active=True, created_at=datetime.utcnow(),
        ))
        db.add(Agent(
            id=a_id, api_key_id=k_id, name="carlos-bot",
            model="m", framework="f", metadata_json={},
            is_active=True, created_at=datetime.utcnow(),
            public_slug="carlos-bot",
        ))
        db.commit()

        # Second customer asks for the same candidate.
        chosen = allocate_public_slug(db, candidate="carlos-bot")
        assert chosen == "carlos-bot-2"
    finally:
        db.close()


def test_commit_with_slug_retry_recovers_on_integrity_error(monkeypatch):
    """If the first commit() trips the UNIQUE index, the helper rolls
    back, re-allocates with suffix, and commits successfully."""
    from sqlalchemy.exc import IntegrityError
    from app.core.ids import new_id
    from app.core.slug import commit_with_slug_retry
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Agent, Customer

    db = SessionLocal()
    try:
        c_id = new_id("cust")
        k_id = new_id("key")
        db.add(Customer(id=c_id, email=f"retry-{py_secrets.token_hex(4)}@example.com"))
        db.flush()
        db.add(APIKey(
            id=k_id, customer_id=c_id, agent_id=None,
            key_hash=hashlib.sha256(b"r").hexdigest(),
            owner_email="r@example.com", label="r",
            is_active=True, created_at=datetime.utcnow(),
        ))
        # Seed an existing agent that will collide on first attempt.
        existing_id = new_id("agt")
        db.add(Agent(
            id=existing_id, api_key_id=k_id, name="seed",
            model="m", framework="f", metadata_json={},
            is_active=True, created_at=datetime.utcnow(),
            public_slug="contested-name",
        ))
        db.commit()

        # Now stage a new agent that wants the same slug.
        new_agent_id = new_id("agt")
        new_agent = Agent(
            id=new_agent_id, api_key_id=k_id, name="contested-name",
            model="m", framework="f", metadata_json={},
            is_active=True, created_at=datetime.utcnow(),
            public_slug=None,
        )
        db.add(new_agent)

        # Simulate the race: first commit raises a slug IntegrityError
        # even though allocator thought the slug was free (because of
        # the race window between SELECT and INSERT). After rollback
        # the allocator will see the seeded row and pick the -2 suffix.
        real_commit = db.commit
        calls = {"n": 0}

        def flaky_commit():
            calls["n"] += 1
            if calls["n"] == 1:
                # Fake the partial-unique-index violation. SQLAlchemy
                # wraps it as IntegrityError with the trigger message
                # in `orig`.
                raise IntegrityError(
                    "INSERT INTO agents ...",
                    {},
                    Exception("UNIQUE constraint failed: agents.public_slug"),
                )
            return real_commit()

        monkeypatch.setattr(db, "commit", flaky_commit)

        def _set_slug(slug):
            new_agent.public_slug = slug

        chosen = commit_with_slug_retry(
            db,
            candidate="contested-name",
            fallback=new_agent_id,
            set_slug=_set_slug,
            pending_objects=[new_agent],
        )

        # Should have retried at least once.
        assert calls["n"] >= 2
        # And the agent should now hold a non-colliding slug.
        assert chosen is not None
        # Restore for cleanup
        monkeypatch.setattr(db, "commit", real_commit)
        # Confirm DB sees it.
        committed = db.query(Agent).filter(Agent.id == new_agent_id).first()
        assert committed is not None
        assert committed.public_slug != "contested-name"
    finally:
        db.close()


def test_commit_with_slug_retry_does_not_swallow_non_slug_errors(monkeypatch):
    """An IntegrityError for a different constraint (e.g. FK violation)
    must propagate — we don't want to mask unrelated bugs."""
    from sqlalchemy.exc import IntegrityError
    from app.core.ids import new_id
    from app.core.slug import commit_with_slug_retry
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Agent, Customer

    db = SessionLocal()
    try:
        c_id = new_id("cust")
        k_id = new_id("key")
        db.add(Customer(id=c_id, email=f"unrelated-{py_secrets.token_hex(4)}@example.com"))
        db.flush()
        db.add(APIKey(
            id=k_id, customer_id=c_id, agent_id=None,
            key_hash=hashlib.sha256(b"u").hexdigest(),
            owner_email="u@example.com", label="u",
            is_active=True, created_at=datetime.utcnow(),
        ))
        db.commit()

        agent_id = new_id("agt")
        new_agent = Agent(
            id=agent_id, api_key_id=k_id, name="ok",
            model="m", framework="f", metadata_json={},
            is_active=True, created_at=datetime.utcnow(),
        )
        db.add(new_agent)

        def fk_error_commit():
            raise IntegrityError(
                "INSERT ...",
                {},
                Exception("FOREIGN KEY constraint failed"),
            )

        monkeypatch.setattr(db, "commit", fk_error_commit)

        with pytest.raises(IntegrityError):
            commit_with_slug_retry(
                db,
                candidate="ok",
                fallback=agent_id,
                set_slug=lambda s: setattr(new_agent, "public_slug", s),
            )
    finally:
        db.close()
