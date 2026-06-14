"""Tests for the synthetic-user bypass auth path (Sprint UX-5.11 Phase A).

The bypass-auth flow lets the synthetic persona runner authenticate as the
canonical sandbox tenant `testing@metalins.local` without minting real
Supabase JWTs. See `docs/product/SYNTHETIC-USER-VALIDATION-FRAMEWORK.md` §8
for the design and `server/app/core/auth.py` for the implementation.

What we cover here:

* Header present + env var unset → behaves as if the bypass path doesn't
  exist. The request falls through to the standard Bearer-token path and
  401s for lack of credentials.
* Header present + valid HMAC + customer row present → 200 with the
  test customer scoped in the response.
* Header present + wrong HMAC → 401, even when the env var is set.
* Header absent + env var set → ordinary auth path still works (legacy
  API-key calls must not be affected by the bypass code).
* Header valid but customer row missing → 500, so a missing migration is
  surfaced loudly instead of silently authenticating an unknown identity.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets as py_secrets

import pytest

# Force a temp SQLite before any app imports — same pattern as
# tests/test_agents_list_detail.py.
_TMP_DB_PATH = f"/tmp/_metalins_bypass_auth_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


TEST_SECRET = "test-bypass-secret-do-not-use-in-prod"
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_EMAIL = "testing@metalins.local"


def _signature(secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        TEST_USER_EMAIL.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    from app.db import Base
    from app.db.session import engine
    Base.metadata.create_all(bind=engine)
    yield


def _set_bypass_secret_everywhere(value):
    """Set `test_user_bypass_secret` on every `settings` reference in app modules.

    Cross-module reloads (e.g. `tests/test_admin.py` reloads `app.config`) can
    leave stale `settings` references inside modules that imported the
    singleton at load time, like `app.core.auth`. Mutating only the canonical
    one in `app.config` isn't enough — we have to mirror the change onto each
    binding the request handler will actually read from.
    """
    from app import config as config_mod
    from app.core import auth as auth_mod

    config_mod.settings.test_user_bypass_secret = value
    # auth.py does `from app.config import settings`, so it holds its own
    # binding. Patch that one too — `_validate_bypass` reads
    # `settings.test_user_bypass_secret` from auth_mod.settings.
    auth_mod.settings.test_user_bypass_secret = value


@pytest.fixture
def http_client_with_bypass():
    """TestClient with the bypass secret set on every `settings` reference."""
    import importlib
    from fastapi.testclient import TestClient
    from app import config as config_mod
    from app.core import auth as auth_mod
    import app.main as main_mod

    original_cfg = config_mod.settings.test_user_bypass_secret
    original_auth = auth_mod.settings.test_user_bypass_secret
    _set_bypass_secret_everywhere(TEST_SECRET)
    importlib.reload(main_mod)
    try:
        yield TestClient(main_mod.app)
    finally:
        config_mod.settings.test_user_bypass_secret = original_cfg
        auth_mod.settings.test_user_bypass_secret = original_auth


@pytest.fixture
def http_client_no_bypass():
    """TestClient with the bypass secret unset (production-like deploy)."""
    import importlib
    from fastapi.testclient import TestClient
    from app import config as config_mod
    from app.core import auth as auth_mod
    import app.main as main_mod

    original_cfg = config_mod.settings.test_user_bypass_secret
    original_auth = auth_mod.settings.test_user_bypass_secret
    _set_bypass_secret_everywhere(None)
    importlib.reload(main_mod)
    try:
        yield TestClient(main_mod.app)
    finally:
        config_mod.settings.test_user_bypass_secret = original_cfg
        auth_mod.settings.test_user_bypass_secret = original_auth


@pytest.fixture
def seed_test_customer():
    """Ensure the sandbox customer row exists for the bypass to resolve to."""
    from app.db.models import Customer
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(Customer).filter(Customer.id == TEST_USER_ID).first()
        if existing is None:
            db.add(Customer(
                id=TEST_USER_ID,
                email=TEST_USER_EMAIL,
                plan="free",
                metadata_json={"synthetic_user": True},
            ))
            db.commit()
        yield
    finally:
        db.close()


@pytest.fixture
def remove_test_customer():
    """Inverse of seed_test_customer — used to exercise the 500 path."""
    from app.db.models import Customer
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        existing = db.query(Customer).filter(Customer.id == TEST_USER_ID).first()
        if existing is not None:
            db.delete(existing)
            db.commit()
        yield
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_valid_bypass_returns_test_user(http_client_with_bypass, seed_test_customer):
    """Valid signature + secret configured + customer row present → 200."""
    sig = _signature(TEST_SECRET)
    r = http_client_with_bypass.get(
        "/internal/v1/me",
        headers={"X-Metalins-Test-Bypass": sig},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["email"] == TEST_USER_EMAIL
    assert data["customer_id"] == TEST_USER_ID
    # The bypass should look JWT-equivalent to downstream consumers so the
    # dashboard's auth_type-driven UI doesn't misclassify it as a key.
    assert data["auth_type"] == "jwt"
    assert data["api_key_id"] is None


def test_valid_bypass_lists_empty_agents(http_client_with_bypass, seed_test_customer):
    """After authenticating via bypass we should be able to call agent endpoints
    scoped to the test tenant. Fresh tenant → empty list."""
    sig = _signature(TEST_SECRET)
    r = http_client_with_bypass.get(
        "/internal/v1/agents",
        headers={"X-Metalins-Test-Bypass": sig},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["agents"] == []
    assert data["count"] == 0


# --------------------------------------------------------------------------- #
# Wrong / missing signatures                                                  #
# --------------------------------------------------------------------------- #


def test_wrong_bypass_signature_is_rejected(http_client_with_bypass, seed_test_customer):
    """A signature minted with a different secret must be rejected even when
    the bypass path is enabled."""
    wrong = _signature("not-the-real-secret")
    r = http_client_with_bypass.get(
        "/internal/v1/me",
        headers={"X-Metalins-Test-Bypass": wrong},
    )
    assert r.status_code == 401
    assert "bypass" in r.json().get("detail", "").lower()


def test_garbage_bypass_signature_is_rejected(http_client_with_bypass, seed_test_customer):
    r = http_client_with_bypass.get(
        "/internal/v1/me",
        headers={"X-Metalins-Test-Bypass": "obviously-not-a-hex-digest"},
    )
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# Defense-in-depth: env var disabled                                          #
# --------------------------------------------------------------------------- #


def test_bypass_header_ignored_when_secret_unset(http_client_no_bypass, seed_test_customer):
    """If the env var is not configured the backend must pretend the header
    doesn't exist — falling through to the standard Bearer path and 401-ing."""
    sig = _signature(TEST_SECRET)
    r = http_client_no_bypass.get(
        "/internal/v1/me",
        headers={"X-Metalins-Test-Bypass": sig},
    )
    assert r.status_code == 401
    # Important: the rejection should be the missing-Bearer one, NOT an
    # invalid-bypass one. That confirms the bypass code never ran.
    detail = r.json().get("detail", "")
    assert "Bearer" in detail


# --------------------------------------------------------------------------- #
# Defense-in-depth: standard auth still works alongside the bypass            #
# --------------------------------------------------------------------------- #


def test_api_key_path_unaffected_by_bypass(http_client_with_bypass, seed_test_customer):
    """Pre-existing API-key callers must keep working when the bypass is on,
    so the synthetic-user feature can coexist with real customers."""
    from app.core.ids import new_id
    from app.db.models import APIKey, Customer
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        cust_id = "cust-" + py_secrets.token_hex(8)
        db.add(Customer(id=cust_id, email=f"{cust_id}@example.com", plan="free"))
        raw = "ml_test_" + py_secrets.token_urlsafe(16)
        key_id = new_id("key")
        db.add(APIKey(
            id=key_id,
            customer_id=cust_id,
            key_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            owner_email=f"{cust_id}@example.com",
            label="bypass-coexist-test",
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()

    r = http_client_with_bypass.get(
        "/internal/v1/agents",
        headers={"Authorization": f"Bearer {raw}"},
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- #
# Missing migration → 500                                                     #
# --------------------------------------------------------------------------- #


def test_missing_customer_row_returns_500(http_client_with_bypass, remove_test_customer):
    """If the migration wasn't applied (or the row was deleted), the bypass
    path must fail loudly so the operator catches the misconfiguration."""
    sig = _signature(TEST_SECRET)
    r = http_client_with_bypass.get(
        "/internal/v1/me",
        headers={"X-Metalins-Test-Bypass": sig},
    )
    assert r.status_code == 500
    assert "migration" in r.json().get("detail", "").lower()
