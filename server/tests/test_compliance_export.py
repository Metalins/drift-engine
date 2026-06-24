"""Tests for GET /v1/agents/{id}/compliance-export — Issue #56.

Validates that:
  - A missing agent returns 404.
  - A valid key for a *different* customer returns 403.
  - An unauthenticated request returns 401.
  - Happy path: returns 200 with Content-Type application/zip and a ZIP
    containing events.json, compliance_mapping.json, agent_metadata.json.
  - The ZIP contents are valid JSON with the expected top-level keys.
  - An agent with no events still produces a valid bundle.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import secrets as py_secrets
import zipfile
from datetime import datetime, timezone

import pytest


# Force temp SQLite before any app imports.
_TMP_DB_PATH = f"/tmp/_metalins_compliance_export_{os.getpid()}.db"
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


@pytest.fixture(scope="module")
def http_client():
    import importlib
    from fastapi.testclient import TestClient
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def _make_api_key(label: str = "test") -> tuple[str, str, str]:
    """Create a customer + API key. Returns (raw_key, key_id, customer_id)."""
    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import APIKey, Customer

    raw = "ml_test_" + py_secrets.token_urlsafe(16)
    key_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    key_id = new_id("key")
    customer_id = new_id("cust")

    db = SessionLocal()
    try:
        db.add(Customer(id=customer_id, email=f"{label}-{customer_id}@t.local"))
        db.add(APIKey(
            id=key_id, key_hash=key_hash, customer_id=customer_id,
            owner_email=f"{label}@example.com", label=label, is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    return raw, key_id, customer_id


def _seed_agent(api_key_id: str, customer_id: str, with_events: bool = True) -> str:
    """Seed an agent (and optionally some event logs) for the given key/customer."""
    import hashlib as _hl
    import os as _os

    from app.core.ids import new_id
    from app.db.session import SessionLocal
    from app.db.models import Agent, AgentState, EventLog

    agent_id = new_id("agt")
    agent_secret = _os.urandom(32).hex()
    initial_digest = _hl.sha256(bytes.fromhex(agent_secret) + b"init").hexdigest()

    db = SessionLocal()
    try:
        db.add(Agent(
            id=agent_id,
            api_key_id=api_key_id,
            name="Test Compliance Agent",
            model="claude-3-opus",
            framework="langchain",
            metadata_json={"env": "test"},
            baseline_kappa={"enrolment_score": 0.92},
            enrolment_score=0.92,
            is_active=True,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.add(AgentState(
            agent_id=agent_id,
            history_digest=initial_digest,
            event_count=0 if not with_events else 3,
            agent_secret=agent_secret,
        ))

        if with_events:
            # Seed three synthetic event logs with a valid digest chain.
            digest = initial_digest
            for i in range(1, 4):
                in_hash = _hl.sha256(f"input-{i}".encode()).hexdigest()
                out_hash = _hl.sha256(f"output-{i}".encode()).hexdigest()
                chain_data = f"{in_hash}{out_hash}{i}".encode()
                new_digest = _hl.sha256(digest.encode() + chain_data).hexdigest()
                sig = _hl.sha256(
                    bytes.fromhex(agent_secret) + chain_data
                ).hexdigest()
                db.add(EventLog(
                    id=new_id("evt"),
                    agent_id=agent_id,
                    event_count=i,
                    input_hash=in_hash,
                    output_hash=out_hash,
                    history_digest=new_digest,
                    signature=sig,
                    metadata_json={"session": f"s{i}"},
                    ts=datetime.now(timezone.utc).replace(tzinfo=None),
                ))
                digest = new_digest

        db.commit()
    finally:
        db.close()

    return agent_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def owner_key_and_agent(http_client):
    raw_key, key_id, customer_id = _make_api_key("owner")
    agent_id = _seed_agent(key_id, customer_id, with_events=True)
    return raw_key, agent_id


@pytest.fixture(scope="module")
def other_key(http_client):
    raw_key, key_id, customer_id = _make_api_key("other")
    return raw_key


@pytest.fixture(scope="module")
def no_events_key_and_agent(http_client):
    raw_key, key_id, customer_id = _make_api_key("noevents")
    agent_id = _seed_agent(key_id, customer_id, with_events=False)
    return raw_key, agent_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_unauthenticated_returns_401(http_client, owner_key_and_agent):
    _, agent_id = owner_key_and_agent
    r = http_client.get(f"/v1/agents/{agent_id}/compliance-export")
    assert r.status_code == 401


def test_missing_agent_returns_404(http_client, owner_key_and_agent):
    raw_key, _ = owner_key_and_agent
    r = http_client.get(
        "/v1/agents/agt_nonexistent_000000000000000/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 404


def test_wrong_owner_returns_403(http_client, owner_key_and_agent, other_key):
    _, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {other_key}"},
    )
    assert r.status_code == 403


def test_happy_path_returns_zip(http_client, owner_key_and_agent):
    raw_key, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")


def test_zip_contains_required_files(http_client, owner_key_and_agent):
    raw_key, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        names = zf.namelist()

    assert "events.json" in names
    assert "compliance_mapping.json" in names
    assert "agent_metadata.json" in names


def test_events_json_has_audit_trail(http_client, owner_key_and_agent):
    raw_key, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        events_data = json.loads(zf.read("events.json"))

    assert events_data["agent_id"] == agent_id
    assert events_data["total_events"] == 3
    assert len(events_data["events"]) == 3

    # Each event must have required fields.
    for evt in events_data["events"]:
        assert "event_id" in evt
        assert "event_count" in evt
        assert "input_hash" in evt
        assert "output_hash" in evt
        assert "history_digest" in evt
        assert "signature" in evt
        assert "ts" in evt


def test_compliance_mapping_has_art12_and_art72(http_client, owner_key_and_agent):
    raw_key, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        mapping = json.loads(zf.read("compliance_mapping.json"))

    assert "articles" in mapping
    articles = mapping["articles"]
    assert "art_12_transparency_logging" in articles
    assert "art_72_post_market_monitoring" in articles

    # Art. 12 should report compliant (agent has 3 events).
    assert articles["art_12_transparency_logging"]["status"] == "compliant"
    # Art. 72 should report compliant (agent has baseline_kappa).
    assert articles["art_72_post_market_monitoring"]["status"] == "compliant"


def test_agent_metadata_json_fields(http_client, owner_key_and_agent):
    raw_key, agent_id = owner_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        meta = json.loads(zf.read("agent_metadata.json"))

    assert meta["agent"]["agent_id"] == agent_id
    assert meta["agent"]["name"] == "Test Compliance Agent"
    assert "state" in meta
    assert meta["state"]["event_count"] == 3


def test_no_events_agent_produces_valid_bundle(http_client, no_events_key_and_agent):
    """An agent with zero events should still produce a valid ZIP."""
    raw_key, agent_id = no_events_key_and_agent
    r = http_client.get(
        f"/v1/agents/{agent_id}/compliance-export",
        headers={"Authorization": f"Bearer {raw_key}"},
    )
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]

    buf = io.BytesIO(r.content)
    with zipfile.ZipFile(buf, "r") as zf:
        events_data = json.loads(zf.read("events.json"))
        mapping = json.loads(zf.read("compliance_mapping.json"))

    assert events_data["total_events"] == 0
    assert events_data["events"] == []
    # Art. 12 should report insufficient_data when no events.
    assert mapping["articles"]["art_12_transparency_logging"]["status"] == "insufficient_data"
