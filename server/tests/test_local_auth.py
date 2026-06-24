"""Tests for self-hosted local auth (gh-117) + first-run admin (gh-118).

Covers:
  * bcrypt hash/verify round-trip + edge cases.
  * Local JWT mint → require_auth accepts it (via GET /internal/v1/me).
  * POST /auth/login: success, wrong password, unknown email (no
    enumeration), must_change_password propagation.
  * POST /auth/change-password: success clears the flag; wrong current
    password / too-short / unchanged are rejected; API-key callers refused.
  * first_run.bootstrap_admin: creates admin, flags default password,
    idempotent, custom password skips the flag, promotes an existing row.
"""
from __future__ import annotations

import os

import pytest

# Force a temp SQLite before any app imports — same pattern as the other
# auth tests. Pin the admin env so the bootstrap is deterministic.
_TMP_DB_PATH = f"/tmp/_metalins_local_auth_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")
# A fixed JWT secret keeps tokens stable regardless of key-derivation paths.
os.environ["METALINS_AUTH_JWT_SECRET"] = "test-local-auth-secret"


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


def _make_customer(email: str, password: str | None, **kwargs):
    """Insert a customer (optionally with a bcrypt password) and return its id."""
    from app.core import local_auth
    from app.core.ids import new_id
    from app.db.models import Customer
    from app.db.session import SessionLocal

    cid = new_id("cust")
    db = SessionLocal()
    try:
        db.add(
            Customer(
                id=cid,
                email=email.lower(),
                password_hash=(
                    local_auth.hash_password(password) if password else None
                ),
                **kwargs,
            )
        )
        db.commit()
    finally:
        db.close()
    return cid


# --------------------------------------------------------------------------- #
# Password hashing primitives                                                 #
# --------------------------------------------------------------------------- #


def test_password_hash_roundtrip():
    from app.core import local_auth

    h = local_auth.hash_password("correct horse battery staple")
    assert h and h != "correct horse battery staple"
    assert local_auth.verify_password("correct horse battery staple", h)
    assert not local_auth.verify_password("wrong", h)


def test_verify_password_handles_missing_and_malformed():
    from app.core import local_auth

    assert not local_auth.verify_password("anything", None)
    assert not local_auth.verify_password("anything", "")
    assert not local_auth.verify_password("anything", "not-a-bcrypt-hash")


def test_hash_password_rejects_overlong():
    from app.core import local_auth

    with pytest.raises(ValueError):
        local_auth.hash_password("x" * 100)


def test_local_jwt_roundtrip():
    from app.core import local_auth

    tok = local_auth.mint_access_token("cust_abc", "a@b.com")
    claims = local_auth.decode_access_token(tok)
    assert claims["sub"] == "cust_abc"
    assert claims["email"] == "a@b.com"
    assert claims["iss"] == local_auth.LOCAL_ISSUER


# --------------------------------------------------------------------------- #
# Login + require_auth integration                                            #
# --------------------------------------------------------------------------- #


def test_login_success_token_authorizes_me(http_client):
    _make_customer("user1@example.com", "s3cret-password")

    r = http_client.post(
        "/auth/login",
        json={"email": "user1@example.com", "password": "s3cret-password"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["must_change_password"] is False
    token = body["access_token"]

    # The minted token must satisfy require_auth on a protected endpoint.
    me = http_client.get(
        "/internal/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "user1@example.com"
    assert me.json()["auth_type"] == "jwt"
    assert me.json()["must_change_password"] is False


def test_login_wrong_password_401(http_client):
    _make_customer("user2@example.com", "right-password")
    r = http_client.post(
        "/auth/login",
        json={"email": "user2@example.com", "password": "wrong-password"},
    )
    assert r.status_code == 401


def test_login_unknown_email_401_same_message(http_client):
    _make_customer("user3@example.com", "right-password")
    unknown = http_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "whatever"},
    )
    wrong = http_client.post(
        "/auth/login",
        json={"email": "user3@example.com", "password": "nope"},
    )
    assert unknown.status_code == 401 and wrong.status_code == 401
    # No account-enumeration oracle: identical detail either way.
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_login_email_case_insensitive(http_client):
    _make_customer("mixedcase@example.com", "pw-pw-pw-pw")
    r = http_client.post(
        "/auth/login",
        json={"email": "MixedCase@Example.com", "password": "pw-pw-pw-pw"},
    )
    assert r.status_code == 200, r.text


def test_legacy_customer_without_password_cannot_login(http_client):
    # A Supabase-era row (no password_hash) must not be loginnable here.
    _make_customer("legacy@example.com", None)
    r = http_client.post(
        "/auth/login",
        json={"email": "legacy@example.com", "password": ""},
    )
    assert r.status_code == 401


def test_must_change_password_propagates(http_client):
    _make_customer(
        "needschange@example.com", "default-pw", must_change_password=True
    )
    r = http_client.post(
        "/auth/login",
        json={"email": "needschange@example.com", "password": "default-pw"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True
    token = r.json()["access_token"]
    me = http_client.get(
        "/internal/v1/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.json()["must_change_password"] is True


# --------------------------------------------------------------------------- #
# Change password                                                             #
# --------------------------------------------------------------------------- #


def test_change_password_flow(http_client):
    _make_customer(
        "changer@example.com", "old-password", must_change_password=True
    )
    login = http_client.post(
        "/auth/login",
        json={"email": "changer@example.com", "password": "old-password"},
    )
    token = login.json()["access_token"]

    # Too short → 400.
    short = http_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "old-password", "new_password": "short"},
    )
    assert short.status_code == 400

    # Wrong current → 401.
    wrong = http_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "nope", "new_password": "brand-new-password"},
    )
    assert wrong.status_code == 401

    # Same as current → 400.
    same = http_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"current_password": "old-password", "new_password": "old-password"},
    )
    assert same.status_code == 400

    # Valid change → 200, flag cleared, new password works, old doesn't.
    ok = http_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "old-password",
            "new_password": "brand-new-password",
        },
    )
    assert ok.status_code == 200, ok.text

    relogin = http_client.post(
        "/auth/login",
        json={"email": "changer@example.com", "password": "brand-new-password"},
    )
    assert relogin.status_code == 200
    assert relogin.json()["must_change_password"] is False

    old = http_client.post(
        "/auth/login",
        json={"email": "changer@example.com", "password": "old-password"},
    )
    assert old.status_code == 401


def test_change_password_rejects_api_key(http_client):
    import hashlib
    import secrets as py_secrets

    from app.core.ids import new_id
    from app.db.models import APIKey, Customer
    from app.db.session import SessionLocal

    raw = "ml_test_" + py_secrets.token_urlsafe(16)
    cid = new_id("cust")
    db = SessionLocal()
    try:
        db.add(Customer(id=cid, email=f"apikey-{py_secrets.token_hex(3)}@example.com"))
        db.flush()
        db.add(
            APIKey(
                id=new_id("key"),
                customer_id=cid,
                key_hash=hashlib.sha256(raw.encode()).hexdigest(),
                owner_email="apikey@example.com",
                is_active=True,
            )
        )
        db.commit()
    finally:
        db.close()

    r = http_client.post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {raw}"},
        json={"current_password": "x", "new_password": "brand-new-password"},
    )
    assert r.status_code == 403


# --------------------------------------------------------------------------- #
# First-run bootstrap                                                         #
# --------------------------------------------------------------------------- #


def _isolated_session():
    """A SQLite session on its OWN throwaway engine, independent of the
    module-shared engine that other test modules mutate. bootstrap_admin
    only touches the session it's handed + the settings singleton, so this
    gives each bootstrap test a genuine clean-slate first run."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base

    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=eng)
    return sessionmaker(bind=eng)()


def test_bootstrap_admin_default_password_flags_change(monkeypatch):
    from app.config import settings
    from app.db.models import Customer
    from app.services import first_run

    monkeypatch.setattr(settings, "admin_email", "bootstrap-admin@localhost")
    monkeypatch.setattr(settings, "admin_password", "changeme")

    db = _isolated_session()
    try:
        admin = first_run.bootstrap_admin(db)
        assert admin is not None
        assert admin.is_admin is True
        assert admin.must_change_password is True

        # Idempotent: a second call is a no-op (an admin already exists).
        assert first_run.bootstrap_admin(db) is None

        count = (
            db.query(Customer)
            .filter(Customer.email == "bootstrap-admin@localhost")
            .count()
        )
        assert count == 1
    finally:
        db.close()


def test_bootstrap_admin_custom_password_no_flag(monkeypatch):
    from app.config import settings
    from app.core import local_auth
    from app.services import first_run

    monkeypatch.setattr(settings, "admin_email", "custom-admin@localhost")
    monkeypatch.setattr(settings, "admin_password", "a-strong-custom-password")

    db = _isolated_session()
    try:
        admin = first_run.bootstrap_admin(db)
        assert admin is not None
        assert admin.must_change_password is False
        assert local_auth.verify_password(
            "a-strong-custom-password", admin.password_hash
        )
    finally:
        db.close()


def test_bootstrap_admin_promotes_existing_row(monkeypatch):
    from app.config import settings
    from app.core.ids import new_id
    from app.db.models import Customer
    from app.services import first_run

    monkeypatch.setattr(settings, "admin_email", "promote-me@localhost")
    monkeypatch.setattr(settings, "admin_password", "changeme")

    db = _isolated_session()
    try:
        # A legacy (Supabase-era) row with no password / not admin.
        db.add(Customer(id=new_id("cust"), email="promote-me@localhost"))
        db.commit()

        admin = first_run.bootstrap_admin(db)
        assert admin is not None
        assert admin.is_admin is True
        assert admin.password_hash  # password was set on promotion
        # Only one row for that email — promoted, not duplicated.
        assert (
            db.query(Customer)
            .filter(Customer.email == "promote-me@localhost")
            .count()
            == 1
        )
    finally:
        db.close()
