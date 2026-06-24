"""Tests for the anti-abuse auth-email endpoints — phase-2 flow.

Covers:
  - GET /v1/auth-email/status — false for an address never reported.
  - POST /v1/auth-email/report-unsolicited — a Turnstile-verified
    report flags the address; status then reads true; lookup is
    case-insensitive.
  - A report with a failing Turnstile check is rejected (400) and
    records nothing.
  - The report is idempotent.

Turnstile verification (`_verify_turnstile`) makes a network call, so
it is monkeypatched — the tests exercise the endpoint logic, not
Cloudflare.
"""
from __future__ import annotations

import os

import pytest


# Force a temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_abuse_{os.getpid()}.db"
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


def _force_turnstile(monkeypatch, ok: bool):
    """Make the Turnstile check deterministically pass/fail."""
    import app.api.abuse as abuse
    monkeypatch.setattr(abuse, "_verify_turnstile", lambda _token: ok)


def test_status_is_false_for_unreported_address(http_client):
    r = http_client.get(
        "/v1/auth-email/status", params={"email": "nobody@example.com"}
    )
    assert r.status_code == 200
    assert r.json() == {"flagged": False}


def test_report_flags_address_and_status_reflects_it(http_client, monkeypatch):
    _force_turnstile(monkeypatch, True)
    r = http_client.post(
        "/v1/auth-email/report-unsolicited",
        json={"email": "Victim@Example.com", "turnstile_token": "tok"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # Stored lowercased; the status lookup is case-insensitive.
    r2 = http_client.get(
        "/v1/auth-email/status", params={"email": "victim@example.com"}
    )
    assert r2.json() == {"flagged": True}


def test_report_rejected_when_turnstile_fails(http_client, monkeypatch):
    _force_turnstile(monkeypatch, False)
    r = http_client.post(
        "/v1/auth-email/report-unsolicited",
        json={"email": "scripted@example.com", "turnstile_token": "bad"},
    )
    assert r.status_code == 400
    # Nothing was recorded.
    r2 = http_client.get(
        "/v1/auth-email/status", params={"email": "scripted@example.com"}
    )
    assert r2.json() == {"flagged": False}


def test_report_is_idempotent(http_client, monkeypatch):
    _force_turnstile(monkeypatch, True)
    body = {"email": "dup@example.com", "turnstile_token": "tok"}
    assert (
        http_client.post(
            "/v1/auth-email/report-unsolicited", json=body
        ).status_code
        == 200
    )
    assert (
        http_client.post(
            "/v1/auth-email/report-unsolicited", json=body
        ).status_code
        == 200
    )
    r = http_client.get(
        "/v1/auth-email/status", params={"email": "dup@example.com"}
    )
    assert r.json() == {"flagged": True}


def test_report_requires_valid_email(http_client, monkeypatch):
    _force_turnstile(monkeypatch, True)
    r = http_client.post(
        "/v1/auth-email/report-unsolicited",
        json={"email": "notanemail", "turnstile_token": "tok"},
    )
    assert r.status_code == 400
