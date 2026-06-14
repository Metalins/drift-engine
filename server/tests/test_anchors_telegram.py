"""Tests for the Telegram-bio anchor flow (bug-r1-carlos-1).

Sprint UX-5.11 R2 / Round 2 Track A #2 (2026-05-18). Telegram becomes a
first-class anchor type — Carlos can prove he owns @his_signals_bot by
pasting a challenge token into the bot's bio, without first having to
connect Telegram as a watcher.

The verifier hits `https://t.me/<username>` (public preview page) and
greps for the challenge_token in the og:description meta tag and the
rendered description div. We monkeypatch the fetch helper end-to-end so
no real network is touched.

Endpoints under test:
  POST /v1/agents/{id}/anchors/telegram/start
  POST /v1/agents/{id}/anchors/telegram/verify
  GET  /v1/agents/{id}/anchors            (verified anchor appears)
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets
from datetime import datetime

import pytest


# Force a temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_telegram_anchor_{os.getpid()}.db"
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


def _seed_customer_agent() -> tuple[str, str, str]:
    """Returns (customer_id, agent_id, admin_raw_key)."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Agent, Customer

    customer_id = new_id("cust")
    agent_id = new_id("agt")
    admin_raw = "ml_test_" + py_secrets.token_urlsafe(16)
    admin_key_id = new_id("key")
    db = SessionLocal()
    try:
        db.add(Customer(
            id=customer_id,
            email=f"tg-anchor-{py_secrets.token_hex(4)}@example.com",
        ))
        db.flush()
        db.add(APIKey(
            id=admin_key_id,
            customer_id=customer_id,
            agent_id=None,
            key_hash=hashlib.sha256(admin_raw.encode()).hexdigest(),
            owner_email="tg-anchor-test@example.com",
            label="tg-anchor-test-admin",
            is_active=True,
            created_at=datetime.utcnow(),
        ))
        db.add(Agent(
            id=agent_id,
            api_key_id=admin_key_id,
            name="carlos-test-bot",
            model="claude-3-5-sonnet",
            framework="custom",
            metadata_json={},
            is_active=True,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    finally:
        db.close()
    return customer_id, agent_id, admin_raw


def _auth(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _telegram_html_with_token(username: str, token: str) -> str:
    """Realistic-ish t.me HTML stub that embeds the challenge token in
    both the og:description meta and the visible tgme_page_description.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta property="og:title" content="{username}">
<meta property="og:description" content="Crypto signals — verified by metalins. {token}">
</head>
<body>
<div class="tgme_page">
  <div class="tgme_page_title">{username}</div>
  <div class="tgme_page_description">Crypto signals — verified by metalins. {token}</div>
</div>
</body>
</html>
"""


def _telegram_html_without_token(username: str) -> str:
    return f"""<!DOCTYPE html>
<html><head>
<meta property="og:title" content="{username}">
<meta property="og:description" content="Crypto signals — clean bio with no token">
</head><body>
<div class="tgme_page">
  <div class="tgme_page_description">Crypto signals — clean bio with no token</div>
</div></body></html>
"""


def _telegram_html_generic_placeholder() -> str:
    """Telegram serves this when a username doesn't have a public preview."""
    return """<!DOCTYPE html>
<html><head>
<meta property="og:title" content="Telegram">
<meta property="og:description" content="If you have Telegram, you can contact @nonexistent right away.">
</head><body></body></html>
"""


def test_telegram_anchor_happy_path(http_client, monkeypatch):
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    # Step 1 — start.
    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anchor_id"].startswith("anc_")
    token = body["challenge_token"]
    assert token.startswith("metalins:")
    # Telegram bios are short; keep the token compact (~20 chars).
    assert len(token) <= 32
    assert "Add this exact token" in body["instructions"]

    # Step 2 — verify with HTML stub that contains the token.
    def fake_fetch(username: str) -> str:
        assert username == "carlos_signals_bot"
        return _telegram_html_with_token(username, token)

    monkeypatch.setattr(
        "app.api.anchors._fetch_telegram_profile_html", fake_fetch
    )

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "@carlos_signals_bot",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["type"] == "telegram"
    assert out["method"] == "bio"
    assert out["value"] == "@carlos_signals_bot"
    assert out["verified_at"] is not None

    # And the list endpoint sees it.
    r = client.get(
        f"/internal/v1/agents/{agent_id}/anchors", headers=_auth(admin_raw)
    )
    assert r.status_code == 200
    rows = r.json()["anchors"]
    assert any(
        a["type"] == "telegram" and a["value"] == "@carlos_signals_bot"
        for a in rows
    )


def test_telegram_anchor_token_missing_in_bio(http_client, monkeypatch):
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    body = r.json()

    monkeypatch.setattr(
        "app.api.anchors._fetch_telegram_profile_html",
        lambda u: _telegram_html_without_token(u),
    )

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "carlos_signals_bot",
        },
    )
    assert r.status_code == 400, r.text
    assert "wasn't found" in r.json()["detail"]


def test_telegram_anchor_handles_url_input(http_client, monkeypatch):
    """Username field accepts @user, user, t.me/user, https://t.me/user."""
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    body = r.json()
    token = body["challenge_token"]

    seen: list[str] = []

    def fake_fetch(username: str) -> str:
        seen.append(username)
        return _telegram_html_with_token(username, token)

    monkeypatch.setattr(
        "app.api.anchors._fetch_telegram_profile_html", fake_fetch
    )

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "https://t.me/carlos_url_form",
        },
    )
    assert r.status_code == 200, r.text
    assert seen == ["carlos_url_form"]
    assert r.json()["value"] == "@carlos_url_form"


def test_telegram_anchor_invalid_username(http_client):
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    body = r.json()

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "bad name with spaces",
        },
    )
    assert r.status_code == 400
    # And too-short:
    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "@abc",
        },
    )
    assert r.status_code == 400


def test_telegram_anchor_generic_placeholder_rejected(http_client, monkeypatch):
    """If t.me returns the generic 'If you have Telegram' page (no real
    account), we must reject — even if the token coincidentally appears
    in some unrelated bio elsewhere."""
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    body = r.json()

    monkeypatch.setattr(
        "app.api.anchors._fetch_telegram_profile_html",
        lambda u: _telegram_html_generic_placeholder(),
    )

    r = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={
            "anchor_id": body["anchor_id"],
            "telegram_username": "nonexistent_bot",
        },
    )
    assert r.status_code == 404, r.text


def test_telegram_anchor_start_is_idempotent(http_client):
    _, agent_id, admin_raw = _seed_customer_agent()
    client = http_client

    r1 = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    r2 = client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    assert r1.json()["anchor_id"] == r2.json()["anchor_id"]
    assert r1.json()["challenge_token"] == r2.json()["challenge_token"]


# --------------------------------------------------------------------------- #
# claim-slug endpoint — Sprint UX-5.11 R2 / R2.3b                              #
# --------------------------------------------------------------------------- #


def _verify_telegram_anchor(http_client, agent_id, admin_raw, username,
                            monkeypatch):
    """Helper: spin up a pending anchor, verify it, return the anchor_id."""
    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    body = r.json()
    token = body["challenge_token"]
    monkeypatch.setattr(
        "app.api.anchors._fetch_telegram_profile_html",
        lambda u: _telegram_html_with_token(u, token),
    )
    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/verify",
        headers=_auth(admin_raw),
        json={"anchor_id": body["anchor_id"], "telegram_username": username},
    )
    assert r.status_code == 200
    return body["anchor_id"]


def test_claim_slug_happy_path(http_client, monkeypatch):
    """Verifying a Telegram anchor, then calling claim-slug, gives the
    agent a /v/<derived-from-username> public_slug."""
    _, agent_id, admin_raw = _seed_customer_agent()
    anchor_id = _verify_telegram_anchor(
        http_client, agent_id, admin_raw, "carlos_signals_bot", monkeypatch
    )

    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/claim-slug",
        headers=_auth(admin_raw),
        json={"anchor_id": anchor_id},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    # slugify("@carlos_signals_bot") → "carlos-signals-bot"
    assert out["slug"] == "carlos-signals-bot"
    # Previous slug was None because new register_agent doesn't allocate.
    assert out["previous_slug"] is None


def test_claim_slug_rejects_unverified_anchor(http_client):
    _, agent_id, admin_raw = _seed_customer_agent()
    # Start an anchor but don't verify it.
    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/anchors/telegram/start",
        headers=_auth(admin_raw),
    )
    anchor_id = r.json()["anchor_id"]

    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/claim-slug",
        headers=_auth(admin_raw),
        json={"anchor_id": anchor_id},
    )
    assert r.status_code == 400, r.text
    assert "not verified" in r.json()["detail"].lower()


def test_claim_slug_rejects_anchor_from_another_agent(http_client, monkeypatch):
    """Even if anchor_id is valid, it must belong to the URL agent_id —
    otherwise a customer could claim another customer's anchor."""
    # Customer 1 with verified anchor.
    _, agent_a, admin_a = _seed_customer_agent()
    anchor_a = _verify_telegram_anchor(
        http_client, agent_a, admin_a, "owner_a_bot", monkeypatch
    )
    # Customer 2 with their own agent.
    _, agent_b, admin_b = _seed_customer_agent()

    # Customer 2 tries to claim using customer 1's anchor.
    r = http_client.post(
        f"/internal/v1/agents/{agent_b}/claim-slug",
        headers=_auth(admin_b),
        json={"anchor_id": anchor_a},
    )
    assert r.status_code == 404, r.text


def test_claim_slug_appends_suffix_on_legitimate_collision(http_client, monkeypatch):
    """Two different customers both verify Telegram handles that
    slugify to the same value. The second claim gets `-2`."""
    _, agent_a, admin_a = _seed_customer_agent()
    anchor_a = _verify_telegram_anchor(
        http_client, agent_a, admin_a, "popular_bot", monkeypatch
    )
    r = http_client.post(
        f"/internal/v1/agents/{agent_a}/claim-slug",
        headers=_auth(admin_a),
        json={"anchor_id": anchor_a},
    )
    assert r.json()["slug"] == "popular-bot"

    _, agent_b, admin_b = _seed_customer_agent()
    # Use a handle that slugifies to the same value as customer A's
    # (case difference). Different rendering, same canonical slug.
    anchor_b = _verify_telegram_anchor(
        http_client, agent_b, admin_b, "Popular_Bot", monkeypatch
    )
    r = http_client.post(
        f"/internal/v1/agents/{agent_b}/claim-slug",
        headers=_auth(admin_b),
        json={"anchor_id": anchor_b},
    )
    # The allocator walks past "popular-bot" (taken by A) to "popular-bot-2".
    assert r.status_code == 200
    assert r.json()["slug"] == "popular-bot-2"
