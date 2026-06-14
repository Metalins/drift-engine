"""Tests for POST /v1/agents/{id}/issue-proof — Sprint 6-A2A 6.1.

Validates that:
  - Auth is required (no key → 401/403).
  - TTL must be one of the allowed values.
  - Inactive / missing agents → 404 / 409.
  - Happy path: returns a signed JWT that the public /v1/verify-proof
    endpoint accepts as valid.
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime, timedelta

import pytest


# Force a temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_issue_proof_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# Sprint UX-5.11 R2.S2 follow-up — keypair seed moved to
# tests/conftest.py so it runs once at session start, before any test
# module imports app.config. The inline seed here was racy when other
# modules loaded first.


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    from app.db import Base
    from app.db.session import engine
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def http_client():
    import importlib
    from fastapi.testclient import TestClient
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


@pytest.fixture
def api_key():
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    raw = "ml_test_" + py_secrets.token_urlsafe(16)
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    key_id = new_id("key")
    customer_id = new_id("cust")

    db = SessionLocal()
    try:
        db.add(Customer(id=customer_id, email=f"{customer_id}@t.local"))
        db.add(APIKey(
            id=key_id, key_hash=key_hash, customer_id=customer_id,
            owner_email="issue-proof-test@example.com",
            label="issue-proof-test", is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    return raw, key_id, customer_id


def _seed_agent(api_key_id: str, agent_id: str, is_active: bool = True,
                with_observable: bool = True):
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import Agent, AgentState, AgentObservable

    db = SessionLocal()
    try:
        db.add(Agent(
            id=agent_id, api_key_id=api_key_id, name=agent_id,
            is_active=is_active, metadata_json={},
        ))
        secret = py_secrets.token_hex(32)
        anchor = hashlib.sha256(bytes.fromhex(secret) + b"init").hexdigest()
        db.add(AgentState(
            agent_id=agent_id, history_digest=anchor, event_count=0,
            agent_secret=secret,
        ))
        if with_observable:
            db.add(AgentObservable(
                id=new_id("obs"), agent_id=agent_id,
                ts=datetime.utcnow(),
                window_start=datetime.utcnow() - timedelta(hours=1),
                window_end=datetime.utcnow(),
                identity_confidence=0.87,
                n_events=0,
                details_json={},
            ))
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Auth / validation                                                            #
# --------------------------------------------------------------------------- #

def test_issue_proof_requires_auth(http_client, api_key):
    raw, key_id, customer_id = api_key
    _seed_agent(key_id, "agt_auth_test")
    r = http_client.post(
        "/internal/v1/agents/agt_auth_test/issue-proof",
        json={"ttl_seconds": 3600},
        # no Authorization header
    )
    assert r.status_code in (401, 403)


def test_issue_proof_invalid_ttl(http_client, api_key):
    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_bad_ttl")
    r = http_client.post(
        "/internal/v1/agents/agt_bad_ttl/issue-proof",
        json={"ttl_seconds": 99999},  # not in allowed set
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 422
    assert "ttl_seconds" in r.json().get("detail", "")


def test_issue_proof_missing_agent(http_client, api_key):
    raw, key_id, _ = api_key
    r = http_client.post(
        "/internal/v1/agents/nonexistent/issue-proof",
        json={"ttl_seconds": 3600},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 404


def test_issue_proof_revoked_agent(http_client, api_key):
    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_revoked", is_active=False)
    r = http_client.post(
        "/internal/v1/agents/agt_revoked/issue-proof",
        json={"ttl_seconds": 3600},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #

def test_lookup_proof_by_id(http_client, api_key):
    """Sprint UX-5.11 R2 / R2.7 — short-URL shortener path.
    GET /v1/public/proofs/{proof_id} should return the full JWT so the
    verify page can resolve `?p=<id>` URLs without embedding the
    700-char JWT in the shared link."""
    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_shortener")
    r = http_client.post(
        "/internal/v1/agents/agt_shortener/issue-proof",
        json={"ttl_seconds": 300, "scope": "cucumber-42"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200, r.text
    issued = r.json()
    proof_id = issued["proof_id"]
    jwt_token = issued["kappa_proof"]

    # Public lookup — no auth.
    r2 = http_client.get(f"/v1/public/proofs/{proof_id}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["proof_id"] == proof_id
    assert body["agent_id"] == "agt_shortener"
    assert body["kappa_proof"] == jwt_token
    assert body["scope"] == "cucumber-42"

    # Chain into the regular verify-proof flow.
    r3 = http_client.post(
        "/v1/verify-proof", json={"kappa_proof": body["kappa_proof"]}
    )
    assert r3.status_code == 200
    assert r3.json()["valid"] is True
    assert r3.json()["scope"] == "cucumber-42"


def test_lookup_proof_by_id_not_found(http_client):
    """Unknown proof_id returns 404 (verify page renders 'invalid')."""
    r = http_client.get("/v1/public/proofs/prf_doesnotexist")
    assert r.status_code == 404


def test_issue_proof_then_verify_publicly(http_client, api_key):
    """Mint a claim; the public /v1/verify-proof endpoint accepts it."""
    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_happy")

    # Issue
    r = http_client.post(
        "/internal/v1/agents/agt_happy/issue-proof",
        json={"ttl_seconds": 3600, "scope": "marketplace-listing"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == "agt_happy"
    assert body["scope"] == "marketplace-listing"
    assert body["score"] == 0.87
    token = body["kappa_proof"]
    assert isinstance(token, str) and token.count(".") == 2

    # Verify publicly — should be valid
    r2 = http_client.post("/v1/verify-proof", json={"kappa_proof": token})
    assert r2.status_code == 200, r2.text
    v = r2.json()
    assert v["valid"] is True
    assert v["agent_id"] == "agt_happy"
    assert v["scope"] == "marketplace-listing"
    assert v["still_active"] is True


def test_issue_proof_default_ttl_is_1h(http_client, api_key):
    """If req omits ttl_seconds, default is 3600s."""
    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_default_ttl")
    r = http_client.post(
        "/internal/v1/agents/agt_default_ttl/issue-proof",
        json={},  # no ttl
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200
    issued = datetime.fromisoformat(r.json()["issued_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(r.json()["expires_at"].replace("Z", "+00:00"))
    delta = (expires - issued).total_seconds()
    assert 3590 < delta < 3610


def test_issue_proof_persists_verification(http_client, api_key):
    """A Verification row is written so the panel can show audit history."""
    from app.db.session import SessionLocal
    from app.db.models import Verification

    raw, key_id, _ = api_key
    _seed_agent(key_id, "agt_persist")
    r = http_client.post(
        "/internal/v1/agents/agt_persist/issue-proof",
        json={"ttl_seconds": 300, "scope": "audit-trail-test"},
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200
    proof_id = r.json()["proof_id"]

    db = SessionLocal()
    try:
        row = db.query(Verification).filter(Verification.id == proof_id).first()
        assert row is not None
        assert row.agent_id == "agt_persist"
        assert row.scope == "audit-trail-test"
        assert row.verified is True
    finally:
        db.close()
