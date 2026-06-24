"""Tests for the customer-level keys endpoints.

Sprint UX-5.11 / bug-andrea-3 (2026-05-17). Andrea v2.1 minted a key
via `/agents/[id]/keys` (which defaults to customer-wide), traffic
authenticated through that key, but the agent-scoped listing returned
"0 keys". These tests cement the new customer-level endpoints so the
regression can't return.

Endpoints under test:
  GET  /v1/customers/me/api-keys   — lists customer-wide + agent-scoped
  POST /v1/customers/me/api-keys   — creates customer-wide directly
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime

import pytest


# Force a temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_customer_keys_{os.getpid()}.db"
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
    import importlib
    from fastapi.testclient import TestClient
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _seed_customer_and_admin_key() -> tuple[str, str, str]:
    """Returns (customer_id, admin_raw_key, admin_key_id).

    The admin key is itself customer-wide (agent_id=None) — that's the
    same shape the bootstrap key has, and it's what the dashboard's
    Bearer would be after Supabase login (well, the JWT path; for the
    test we use the static-key path which exercises the same auth code).
    """
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
            email=f"customer-keys-{py_secrets.token_hex(4)}@example.com",
        ))
        db.flush()
        db.add(APIKey(
            id=admin_key_id,
            customer_id=customer_id,
            agent_id=None,  # customer-wide admin key — survives /keys listing
            key_hash=hashlib.sha256(admin_raw.encode()).hexdigest(),
            owner_email="customer-keys-test@example.com",
            label="customer-keys-test-admin",
            is_active=True,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    finally:
        db.close()
    return customer_id, admin_raw, admin_key_id


def _seed_agent(customer_id: str, admin_key_id: str, name: str = "test-agent") -> str:
    """Create an agent owned by the customer via admin_key_id (api_key_id FK)."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import Agent

    agent_id = new_id("agt")
    db = SessionLocal()
    try:
        db.add(Agent(
            id=agent_id,
            api_key_id=admin_key_id,
            name=name,
            is_active=True,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    finally:
        db.close()
    return agent_id


def test_list_returns_empty_when_only_admin_key_exists(http_client):
    """Admin/bootstrap key counts itself — list returns 1 (the admin key).

    The endpoint doesn't hide the calling key from its own listing;
    that's a UX decision left to the dashboard.
    """
    _, admin_raw, _ = _seed_customer_and_admin_key()
    res = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["count"] == 1
    # The admin key is customer-wide.
    assert body["keys"][0]["scope"] == "customer-wide"
    assert body["keys"][0]["agent_id"] is None
    assert body["keys"][0]["agent_name"] is None
    # Never leaks secrets.
    assert "secret" not in body["keys"][0]
    assert "key_hash" not in body["keys"][0]


def test_create_returns_secret_once_and_is_customer_wide(http_client):
    """POST returns raw secret once, with scope=customer-wide."""
    _, admin_raw, _ = _seed_customer_and_admin_key()
    res = http_client.post(
        "/internal/v1/customers/me/api-keys",
        json={"name": "ci-bot", "description": "CI/CD deploys"},
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "ci-bot"
    assert body["scope"] == "customer-wide"
    assert body["agent_id"] is None
    assert body["agent_name"] is None
    assert body["secret"].startswith("ml_live_")
    assert "warning" in body
    # ISO ends with Z (bug-andrea-1 defense).
    assert body["created_at"].endswith("Z")


def test_list_after_create_returns_both_keys(http_client):
    """Cement bug-andrea-3 regression: customer-wide keys are visible."""
    _, admin_raw, _ = _seed_customer_and_admin_key()
    # Mint a new customer-wide key.
    create = http_client.post(
        "/internal/v1/customers/me/api-keys",
        json={"name": "andrea-laptop"},
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert create.status_code == 201

    res = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 2
    names = {k["name"] for k in body["keys"]}
    assert "andrea-laptop" in names
    # Both are customer-wide in this scenario.
    assert all(k["scope"] == "customer-wide" for k in body["keys"])


def test_list_includes_agent_scoped_with_agent_name(http_client):
    """Agent-scoped key shows up alongside customer-wide, with agent_name."""
    customer_id, admin_raw, admin_key_id = _seed_customer_and_admin_key()
    agent_id = _seed_agent(customer_id, admin_key_id, name="andrea-claude-code-laptop")

    # Mint an agent-scoped key via the nested endpoint.
    scoped = http_client.post(
        f"/internal/v1/agents/{agent_id}/api-keys",
        json={"name": "andrea-laptop-scoped", "scope_to_agent": True},
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert scoped.status_code == 201, scoped.text

    res = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert res.status_code == 200
    body = res.json()
    by_name = {k["name"]: k for k in body["keys"]}
    assert "andrea-laptop-scoped" in by_name
    scoped_row = by_name["andrea-laptop-scoped"]
    assert scoped_row["scope"] == "agent-scoped"
    assert scoped_row["agent_id"] == agent_id
    assert scoped_row["agent_name"] == "andrea-claude-code-laptop"


def test_cross_customer_isolation(http_client):
    """Customer A's bearer can never list Customer B's keys."""
    _, a_raw, _ = _seed_customer_and_admin_key()
    _, b_raw, _ = _seed_customer_and_admin_key()

    # Customer A mints a key.
    http_client.post(
        "/internal/v1/customers/me/api-keys",
        json={"name": "a-only"},
        headers={"Authorization": f"Bearer {a_raw}"},
    )
    # Customer B mints a key.
    http_client.post(
        "/internal/v1/customers/me/api-keys",
        json={"name": "b-only"},
        headers={"Authorization": f"Bearer {b_raw}"},
    )

    a_keys = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {a_raw}"},
    ).json()
    b_keys = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {b_raw}"},
    ).json()

    a_names = {k["name"] for k in a_keys["keys"]}
    b_names = {k["name"] for k in b_keys["keys"]}
    assert "a-only" in a_names and "b-only" not in a_names
    assert "b-only" in b_names and "a-only" not in b_names


def test_auth_required(http_client):
    """No bearer → 401 on both endpoints."""
    assert http_client.get("/internal/v1/customers/me/api-keys").status_code == 401
    assert (
        http_client.post(
            "/internal/v1/customers/me/api-keys", json={"name": "x"}
        ).status_code
        == 401
    )


def test_revoked_keys_hidden_by_default(http_client):
    """Revoked keys don't appear unless include_revoked=true."""
    _, admin_raw, _ = _seed_customer_and_admin_key()
    create = http_client.post(
        "/internal/v1/customers/me/api-keys",
        json={"name": "to-be-revoked"},
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    key_id = create.json()["id"]
    rev = http_client.post(
        f"/internal/v1/api-keys/{key_id}/revoke",
        headers={"Authorization": f"Bearer {admin_raw}"},
    )
    assert rev.status_code == 200

    # Default — revoked key NOT in list.
    default = http_client.get(
        "/internal/v1/customers/me/api-keys",
        headers={"Authorization": f"Bearer {admin_raw}"},
    ).json()
    assert "to-be-revoked" not in {k["name"] for k in default["keys"]}

    # include_revoked=true — IS in list.
    with_rev = http_client.get(
        "/internal/v1/customers/me/api-keys?include_revoked=true",
        headers={"Authorization": f"Bearer {admin_raw}"},
    ).json()
    assert "to-be-revoked" in {k["name"] for k in with_rev["keys"]}
