"""Tests for POST /v1/me/delete — account deletion.

Covers:
  - A blank reason → 400 (the reason is mandatory).
  - A valid deletion wipes the customer's account-level rows
    (customer, API keys, email preferences) and writes exactly one
    `account_deletions` audit row with the email + reason.

The per-agent cascade is the same wipe list as `agents.revoke_agent`
(exercised by that endpoint's own tests); this test focuses on the
customer-level wipe, the audit row, and the mandatory reason.
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets

import pytest


_TMP_DB_PATH = f"/tmp/_metalins_acctdel_{os.getpid()}.db"
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


@pytest.fixture
def account():
    """A customer + an active API key + an email-preferences row.
    Returns the raw key and the customer_id."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer, EmailPreferences

    raw = "ml_test_" + py_secrets.token_urlsafe(16)
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    customer_id = new_id("cust")
    key_id = new_id("key")
    db = SessionLocal()
    try:
        db.add(Customer(id=customer_id, email=f"{customer_id}@t.local"))
        db.add(
            APIKey(
                id=key_id,
                key_hash=key_hash,
                customer_id=customer_id,
                owner_email=f"{customer_id}@t.local",
                name="test",
                is_active=True,
            )
        )
        db.add(EmailPreferences(customer_id=customer_id))
        db.commit()
    finally:
        db.close()
    return {"raw": raw, "customer_id": customer_id}


def _auth(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def test_delete_requires_a_reason(http_client, account):
    r = http_client.post(
        "/internal/v1/me/delete",
        json={"reason": "   "},
        headers=_auth(account["raw"]),
    )
    assert r.status_code == 400


def test_delete_wipes_account_and_writes_one_audit_row(http_client, account):
    from app.db.session import SessionLocal
    from app.db.models import (
        AccountDeletion,
        APIKey,
        Customer,
        EmailPreferences,
    )

    reason = "Just testing it out — not for me."
    r = http_client.post(
        "/internal/v1/me/delete",
        json={"reason": reason},
        headers=_auth(account["raw"]),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    cid = account["customer_id"]
    db = SessionLocal()
    try:
        # Everything tied to the customer is gone.
        assert db.query(Customer).filter(Customer.id == cid).count() == 0
        assert (
            db.query(APIKey).filter(APIKey.customer_id == cid).count() == 0
        )
        assert (
            db.query(EmailPreferences)
            .filter(EmailPreferences.customer_id == cid)
            .count()
            == 0
        )
        # Exactly one audit row survives, with the email + reason.
        audit = (
            db.query(AccountDeletion)
            .filter(AccountDeletion.email == f"{cid}@t.local")
            .all()
        )
        assert len(audit) == 1
        assert audit[0].reason == reason
    finally:
        db.close()
