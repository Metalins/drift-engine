"""Tests for the new GET /v1/agents (list) + GET /v1/agents/{id} (detail) endpoints.

These power the dashboard's index page and per-agent detail page (Sprint 3a).
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime, timedelta

import pytest

# Force a temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_list_detail_{os.getpid()}.db"
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


@pytest.fixture
def http_client():
    """Fresh TestClient per test, with a reloaded app to avoid pollution."""
    import importlib
    from fastapi.testclient import TestClient
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


@pytest.fixture
def api_key():
    """Returns (raw_key, key_id). Persists an APIKey + parent Customer.

    Sprint 3a-auth (#525) made `customer_id` required on every API key —
    auth.py:_validate_api_key returns 409 for legacy customer_id=NULL
    rows. This fixture seeds the parent customer too so the test stays
    self-contained.
    """
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    raw = "ml_test_" + py_secrets.token_urlsafe(16)
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    key_id = new_id("key")
    customer_id = new_id("cust")

    db = SessionLocal()
    try:
        db.add(Customer(
            id=customer_id,
            email=f"list-detail-{py_secrets.token_hex(4)}@example.com",
        ))
        db.flush()
        db.add(APIKey(
            id=key_id,
            customer_id=customer_id,
            key_hash=key_hash,
            owner_email="list-detail-test@example.com",
            label="list-detail-test",
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    return raw, key_id


def _make_agent_with_history(api_key_id: str, agent_id: str, n_events: int,
                             with_observable: bool = True):
    """Seed an Agent + AgentState + N EventLog rows + optional AgentObservable."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import Agent, AgentState, EventLog, AgentObservable

    db = SessionLocal()
    try:
        db.add(Agent(
            id=agent_id, api_key_id=api_key_id, name=agent_id,
            framework="claude-code", model="claude-sonnet-4-6",
            is_active=True, metadata_json={"test": True},
        ))
        secret = py_secrets.token_hex(32)
        digest = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
        for i in range(1, n_events + 1):
            in_h = hashlib.sha256(f"in{i}".encode()).hexdigest()
            out_h = hashlib.sha256(f"out{i}".encode()).hexdigest()
            h = hashlib.sha256()
            h.update(bytes.fromhex(digest))
            h.update(in_h.encode())
            h.update(out_h.encode())
            digest = h.hexdigest()
            db.add(EventLog(
                id=new_id("evt"), agent_id=agent_id, event_count=i,
                input_hash=in_h, output_hash=out_h, history_digest=digest,
                signature="x" * 64, metadata_json={},
                ts=datetime.utcnow() + timedelta(seconds=i),
            ))
        db.add(AgentState(
            agent_id=agent_id, history_digest=digest, event_count=n_events,
            agent_secret=secret,
            last_event_at=datetime.utcnow() + timedelta(seconds=n_events),
        ))
        if with_observable:
            db.add(AgentObservable(
                id=new_id("obs"), agent_id=agent_id, ts=datetime.utcnow(),
                n_events=n_events, icr=0.81, twc=None, ttm=None,
                beta_crooks=None, identity_confidence=0.30,
                details_json={"mvs": 1.0, "alphabet": 32},
            ))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# GET /v1/agents (list)                                                       #
# --------------------------------------------------------------------------- #

def test_list_empty_for_new_key(http_client, api_key):
    raw, _ = api_key
    r = http_client.get("/internal/v1/agents", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    data = r.json()
    assert data["agents"] == []
    assert data["count"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_list_returns_agents_with_summary(http_client, api_key):
    raw, kid = api_key
    _make_agent_with_history(kid, "agt-list-1", n_events=20)
    r = http_client.get("/internal/v1/agents", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    a = data["agents"][0]
    assert a["agent_id"] == "agt-list-1"
    assert a["framework"] == "claude-code"
    assert a["is_active"] is True
    assert a["event_count"] == 20
    assert a["last_event_at"] is not None
    # Sprint UX-5.12.2a dropped latest_confidence in favour of the
    # two-layer `trust` block. With 20 events the agent is below
    # BEHAVIORAL_ICR_FLOOR so behavioral.state must be `not_enough_data`.
    # gh-82 — with 20 events (< CRYPTO_ONBOARDING_EVENT_FLOOR) and no
    # positive probe signal yet, the agent is still onboarding, so the
    # cryptographic state is `unverified` ("Setting up"), not `verified`.
    assert "trust" in a
    assert a["trust"]["cryptographic"]["state"] == "unverified"
    assert a["trust"]["behavioral"]["state"] == "not_enough_data"
    assert a["trust"]["behavioral"]["events_observed"] == 20


def test_list_requires_auth(http_client):
    r = http_client.get("/internal/v1/agents")
    assert r.status_code in (401, 403)


def test_list_only_returns_my_agents(http_client):
    """An API key cannot see another customer's agents."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    # Build TWO customer+key pairs: mine and someone else's. Sprint
    # 3a-auth scopes visibility by customer_id, not by api_key.id —
    # so the test needs two independent customers to exercise the
    # cross-tenant block.
    mine_raw = "ml_test_mine_" + py_secrets.token_urlsafe(8)
    other_raw = "ml_test_other_" + py_secrets.token_urlsafe(8)
    mine_id, other_id = new_id("key"), new_id("key")
    mine_cust = new_id("cust")
    other_cust = new_id("cust")

    db = SessionLocal()
    try:
        db.add(Customer(id=mine_cust, email=f"mine-{py_secrets.token_hex(4)}@example.com"))
        db.add(Customer(id=other_cust, email=f"other-{py_secrets.token_hex(4)}@example.com"))
        db.flush()
        db.add(APIKey(id=mine_id, customer_id=mine_cust,
                     key_hash=hashlib.sha256(mine_raw.encode()).hexdigest(),
                     owner_email="mine@example.com", label="mine", is_active=True))
        db.add(APIKey(id=other_id, customer_id=other_cust,
                     key_hash=hashlib.sha256(other_raw.encode()).hexdigest(),
                     owner_email="other@example.com", label="other", is_active=True))
        db.commit()
    finally:
        db.close()

    _make_agent_with_history(mine_id, "agt-mine", n_events=5)
    _make_agent_with_history(other_id, "agt-other", n_events=5)

    r = http_client.get("/internal/v1/agents", headers={"Authorization": f"Bearer {mine_raw}"})
    assert r.status_code == 200
    ids = [a["agent_id"] for a in r.json()["agents"]]
    assert "agt-mine" in ids
    assert "agt-other" not in ids


def test_list_pagination(http_client, api_key):
    raw, kid = api_key
    for i in range(5):
        _make_agent_with_history(kid, f"agt-page-{i}", n_events=3, with_observable=False)

    r = http_client.get("/internal/v1/agents?limit=2&offset=0",
                       headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


# --------------------------------------------------------------------------- #
# GET /v1/agents/{id} (detail)                                                #
# --------------------------------------------------------------------------- #

def test_detail_returns_full_summary(http_client, api_key):
    raw, kid = api_key
    _make_agent_with_history(kid, "agt-detail", n_events=37, with_observable=True)
    r = http_client.get("/internal/v1/agents/agt-detail",
                       headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200
    data = r.json()
    assert data["agent_id"] == "agt-detail"
    assert data["event_count"] == 37
    # Sprint UX-5.12.2a — `latest_confidence` and `identity_confidence`
    # were dropped from the customer-facing surface. The new two-layer
    # `trust` block is the source of truth.
    assert "latest_confidence" not in data
    # gh-82 — 37 events (< CRYPTO_ONBOARDING_EVENT_FLOOR) with no positive
    # probe signal → still onboarding → `unverified` ("Setting up").
    assert data["trust"]["cryptographic"]["state"] == "unverified"
    assert data["trust"]["behavioral"]["state"] == "not_enough_data"
    assert data["pending_probes_count"] == 0

    obs = data["latest_observables"]
    assert obs is not None
    assert "identity_confidence" not in obs  # dropped in UX-5.12.2a
    assert "icr" not in obs  # never exposed (D-PROD.18, internal IP)
    assert obs["n_events"] == 37
    assert "score_factors" in obs


def test_detail_404_for_missing(http_client, api_key):
    raw, _ = api_key
    r = http_client.get("/internal/v1/agents/does-not-exist",
                       headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 404


def test_detail_404_for_cross_tenant(http_client):
    """A key cannot see another customer's agent by ID either."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    mine_raw = "ml_test_d_mine_" + py_secrets.token_urlsafe(8)
    other_raw = "ml_test_d_other_" + py_secrets.token_urlsafe(8)
    mine_id, other_id = new_id("key"), new_id("key")
    mine_cust = new_id("cust")
    other_cust = new_id("cust")
    db = SessionLocal()
    try:
        db.add(Customer(id=mine_cust, email=f"dmine-{py_secrets.token_hex(4)}@example.com"))
        db.add(Customer(id=other_cust, email=f"dother-{py_secrets.token_hex(4)}@example.com"))
        db.flush()
        db.add(APIKey(id=mine_id, customer_id=mine_cust,
                     key_hash=hashlib.sha256(mine_raw.encode()).hexdigest(),
                     owner_email="dmine@example.com", label="dmine", is_active=True))
        db.add(APIKey(id=other_id, customer_id=other_cust,
                     key_hash=hashlib.sha256(other_raw.encode()).hexdigest(),
                     owner_email="dother@example.com", label="dother", is_active=True))
        db.commit()
    finally:
        db.close()
    _make_agent_with_history(other_id, "agt-tenant-other", n_events=5)

    r = http_client.get("/internal/v1/agents/agt-tenant-other",
                       headers={"Authorization": f"Bearer {mine_raw}"})
    assert r.status_code == 404
