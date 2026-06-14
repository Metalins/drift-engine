"""Tests for the public-registration gate (gh-95).

After the research-lab pivot, api.metalins.ai is a private instance: public
registration is closed by default. We cover:

  - POST /v1/auth/signup → 403 while registration is disabled (the default).
  - POST /auth/signup (alias) → 403 too.
  - GET /v1/auth/registration → {"enabled": False} by default.
  - When registration_enabled is flipped on, signup succeeds and the probe
    reports enabled:true — proving the switch is honored at call time.
  - The 403 detail points the caller at self-hosting (open source).
"""
from __future__ import annotations

import os

import pytest

# Force a temp SQLite before any app imports — same pattern as the other
# endpoint tests in this suite.
_TMP_DB_PATH = f"/tmp/_metalins_reg_gate_{os.getpid()}.db"
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


def test_signup_forbidden_by_default(http_client):
    r = http_client.post("/v1/auth/signup", json={"email": "new@example.com"})
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "self-host" in detail.lower()
    assert "github.com/Metalins" in detail


def test_signup_alias_path_also_forbidden(http_client):
    r = http_client.post("/auth/signup", json={"email": "new@example.com"})
    assert r.status_code == 403


def test_signup_works_without_body(http_client):
    # No body at all still 403s — we never read the body while closed.
    r = http_client.post("/v1/auth/signup")
    assert r.status_code == 403


def test_registration_probe_disabled_by_default(http_client):
    r = http_client.get("/v1/auth/registration")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_signup_succeeds_when_enabled(http_client, monkeypatch):
    import app.api.auth_registration as reg
    monkeypatch.setattr(reg.settings, "registration_enabled", True)

    probe = http_client.get("/v1/auth/registration")
    assert probe.json() == {"enabled": True}

    r = http_client.post("/v1/auth/signup", json={"email": "new@example.com"})
    assert r.status_code == 200
    assert r.json()["registration"] == "open"
