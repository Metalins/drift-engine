"""End-to-end test for the MVS loop using the real server + SDK.

Flow:
  1. Bootstrap an API key (admin endpoint).
  2. Register an agent via the SDK -> AgentSession with secret captured.
  3. Log N events; the local digest chain mirrors the server.
  4. Trigger the batch (which issues a probe).
  5. Call log_event again — the response carries the pending probe and
     the session auto-responds with a correct proof.
  6. compute_mvs -> 1.0 (honest agent).
  7. Build a "clone" session that doesn't know the digest history;
     have it respond -> proof fails -> MVS drops.
"""
from __future__ import annotations

import os
import sys
import secrets as py_secrets
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_TMP_DB_PATH = f"/tmp/_metalins_e2e_mvs_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")
# NOTE: we do NOT set METALINS_MASTER_TOKEN globally — that would contaminate
# other tests (test_admin's "disabled when no token" case). Instead we patch
# settings.master_token directly inside the api_key fixture below.

# Make sdk-python importable.
_SDK_PATH = Path(__file__).resolve().parents[2] / "sdk-python"
sys.path.insert(0, str(_SDK_PATH))


@pytest.fixture(autouse=True)
def _no_adv_malformation(monkeypatch):
    """Pin ADV malformation OFF for every test in this module.

    The engine deliberately malforms a probe ~7% of the time (ADV — see
    app/services/adv.py, ADV_MALFORMED_PROBABILITY). An honest agent
    correctly declines / fails a malformed probe, which is genuine
    behavior — but it makes a fixed `MVS == 1.0` honest-agent assertion
    flaky ~7% of runs. This module tests the honest MVS happy-path
    loop; ADV has its own dedicated coverage in test_adv.py. Patching
    `choose_malformation` to always return None makes the loop here
    deterministic. `issue_probe` re-imports the symbol at call time, so
    the monkeypatch on the module attribute takes effect.
    """
    monkeypatch.setattr(
        "app.services.adv.choose_malformation", lambda rng: None
    )


@pytest.fixture
def http_client():
    """Fresh TestClient per test, with SQLAlchemy engine rebuilt to point
    at THIS module's `_TMP_DB_PATH`.

    Sprint UX-5.15.U — `app.db.session.engine` + `SessionLocal` are bound
    at module import time from `settings.db_url`. If ANY earlier test
    module imported `app.config` before this file's `os.environ`-level
    `METALINS_DB_URL` override ran (which is what conftest.py's
    `pytest_configure` triggers via `from app.config import settings`),
    SessionLocal stays bound to the wrong (default) DB and our event
    writes + MVS reads target different files. The result is a probe
    that "responded" against one DB but `compute_mvs` looks at the
    other → MVS=0.0 honest-agent regression. We rebuild the engine here
    and refresh the Settings singleton so the test always sees its own
    DB.
    """
    import importlib
    from fastapi.testclient import TestClient

    # 1. Update the live settings singleton's db_url IN PLACE. We MUST
    # NOT replace `cfg_mod.settings` with a new Settings() instance —
    # `app/api/admin.py` (and others) cached the singleton reference
    # via `from app.config import settings` at module import time, and
    # rebinding `cfg_mod.settings` would leave those imports pointing
    # at the OLD object. The `api_key` fixture below sets
    # `settings.master_token` — if we replace the singleton, the admin
    # router never sees it and 503's the bootstrap endpoint.
    from app.config import settings as live_settings
    live_settings.db_url = _TMP_DB_PATH and f"sqlite:///{_TMP_DB_PATH}"

    # 2. Rebuild the engine + SessionLocal against the new URL.
    import app.db.session as session_mod
    session_mod.engine = session_mod._build_engine()
    from sqlalchemy.orm import sessionmaker
    session_mod.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=session_mod.engine,
    )
    # Re-create tables in the fresh DB.
    session_mod.Base.metadata.create_all(bind=session_mod.engine)

    # 3. `app.db.__init__` re-exports `engine` via `from app.db.session
    # import engine`. Python rebinds at import time — the namespace
    # entry is now stale relative to our rebuilt engine. Refresh.
    import app.db as db_pkg
    db_pkg.engine = session_mod.engine

    # 4. Services that did `from app.db.session import SessionLocal`
    # captured the OLD factory in their module namespace. Patch them.
    # Currently: observable_job (used by `_maybe_issue_fresh_probe`)
    # and watcher_job (background scheduler — disabled in tests but
    # keep it consistent).
    import app.services.observable_job as oj_mod
    oj_mod.SessionLocal = session_mod.SessionLocal
    try:
        import app.services.watcher_job as wj_mod
        wj_mod.SessionLocal = session_mod.SessionLocal
    except Exception:
        pass

    # 5. Reload `app.main` LAST so it re-wires its router dependencies
    # against the freshly-rebuilt SessionLocal (line 16 of main.py runs
    # `Base.metadata.create_all(bind=engine)` again, harmlessly).
    import app.main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


@pytest.fixture
def api_key(http_client):
    """Bootstrap a fresh API key. Forces settings.master_token because other
    tests reload config without restoring it."""
    from app.config import settings
    prev = settings.master_token
    settings.master_token = "test-master-token"
    try:
        r = http_client.post(
            "/v1/admin/bootstrap-api-key",
            json={"owner_email": "e2e@example.com", "label": "e2e-mvs"},
            headers={"X-Master-Token": "test-master-token"},
        )
        assert r.status_code == 200, r.text
        raw_key = r.json()["api_key"]
        # Link the bootstrapped key to a customer. The developer API
        # (UX-5.17.API1) requires customer-scoped keys — prod keys always
        # have one; the bare bootstrap key does not.
        from app.core.auth import _hash_key
        from app.db.models import APIKey as _APIKey, Customer as _Customer
        from app.db.session import SessionLocal as _SL

        # Unique per invocation — the module's tmp DB persists rows
        # across tests in the file.
        _cust_id = f"cust_e2e_{py_secrets.token_hex(4)}"
        _db = _SL()
        try:
            _db.add(
                _Customer(id=_cust_id, email=f"{_cust_id}@example.com")
            )
            _db.flush()
            _row = (
                _db.query(_APIKey)
                .filter(_APIKey.key_hash == _hash_key(raw_key))
                .first()
            )
            _row.customer_id = _cust_id
            _db.commit()
        finally:
            _db.close()
        yield raw_key
    finally:
        settings.master_token = prev


def _make_sdk_client(http_client, api_key):
    """Build a metalins_drift.Client that routes via the FastAPI TestClient.

    The Client uses httpx internally — we monkey-patch its `_http` to the
    TestClient (which is a compatible request interface).
    """
    from metalins_drift.client import Client

    c = Client(api_key=api_key, base_url="http://testserver", timeout=10.0)
    c._http.close()
    c._http = http_client
    # The TestClient already accepts the bearer in request headers — set them.
    http_client.headers.update({"Authorization": f"Bearer {api_key}"})
    return c


def test_full_mvs_loop_honest_agent(http_client, api_key):
    from app.db.session import SessionLocal
    from app.services import memory_verifier
    from app.services.observable_job import _maybe_issue_fresh_probe

    sdk = _make_sdk_client(http_client, api_key)

    # 1. Register via the developer API; the server assigns the agent_id.
    session = sdk.start_session(name="e2e-honest")
    agent_id = session.agent_id
    assert session.agent_secret
    assert session.digest_history[0]
    assert session.event_count == 0

    # 2. Log >= MIN_EVENTS_FOR_PROBE (10) so the server can issue a probe.
    for i in range(15):
        r = session.log_event(input_data=f"q{i}", output_data=f"a{i}")
        assert r["event_count"] == i + 1
    assert session.event_count == 15

    # 3. Force the server to issue a probe.
    db = SessionLocal()
    try:
        # has_mcp_activity=True forces issuance; Sprint 6.4 / #574 made
        # probes MCP-only and the developer-API agent logs without an
        # MCP surface, so the flag is passed explicitly.
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
    finally:
        db.close()

    # 4. Log one more — the response carries the pending check; the
    #    session auto-answers it with a correct proof.
    r = session.log_event(input_data="trigger", output_data="response")
    pending = r.get("pending_checks") or []
    assert pending, "expected a pending check to be surfaced"

    # 5. MVS should be 1.0 — the auto-answer computed the right proof.
    db = SessionLocal()
    try:
        mvs = memory_verifier.compute_mvs(db, agent_id)
    finally:
        db.close()
    assert mvs == 1.0, f"honest agent should pass all checks, got MVS={mvs}"


def test_clone_session_fails_mvs(http_client, api_key):
    """A clone that wakes up mid-stream and DOESN'T know prior digests fails."""
    from app.db.session import SessionLocal
    from app.services import memory_verifier
    from app.services.observable_job import _maybe_issue_fresh_probe
    from metalins_drift.mcp_session import AgentSession

    sdk = _make_sdk_client(http_client, api_key)

    # Register & log 20 events as the original honest agent.
    session = sdk.start_session(name="e2e-clone")
    agent_id = session.agent_id
    for i in range(20):
        session.log_event(input_data=f"q{i}", output_data=f"a{i}")

    # The "clone" wakes up at this point — it only knows the agent_secret
    # (assume leaked) but has an EMPTY digest_history. It cannot reconstruct
    # past digests, so any check targeting t<20 will fail.
    clone = AgentSession(
        agent_id=agent_id,
        agent_secret=session.agent_secret,
        event_count=session.event_count,
        digest_history={},  # critical: clone has no history
        _client=sdk,
    )

    # Force a probe, then surface it via a log_event WITHOUT auto-answering
    # so the clone — not the honest session — gets to answer it.
    db = SessionLocal()
    try:
        # has_mcp_activity=True forces issuance; Sprint 6.4 / #574 made
        # probes MCP-only and the developer-API agent logs without an MCP
        # surface, so the flag is passed explicitly.
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
    finally:
        db.close()

    r = session.log_event(
        input_data="trigger", output_data="response", auto_answer_checks=False
    )
    pending = r.get("pending_checks") or []
    assert pending, "expected a pending check"

    for check in pending:
        clone.answer_check(check)

    # MVS should drop (likely to 0.0, since the only decided check failed).
    db = SessionLocal()
    try:
        mvs = memory_verifier.compute_mvs(db, agent_id)
    finally:
        db.close()
    assert mvs is not None and mvs < 0.5, f"clone should fail MVS, got {mvs}"


def test_refused_malformed_probe_excluded_from_mvs(http_client, api_key):
    """A correctly-refused ADV honeypot must NOT drag MVS down.

    A malformed probe is an adversarial-detection test, not a memory
    check. A conformant agent REFUSES it — and a refusal is stored as
    `status='responded', valid=False`. UX-5.17.9 (the SDK V2
    probe-capable E2E) surfaced that `compute_mvs` was counting that
    refusal as a failed memory check: an honest agent that did exactly
    the right thing got MVS dragged to 0.0 → a false "memory checks
    failing" / compromise verdict. `_mvs_window_rows` now excludes
    `is_malformed` probes; this pins the fix.
    """
    from app.db.session import SessionLocal
    from app.services import memory_verifier
    from app.services.adv import MalformationPlan, apply_malformation_to_probe
    from app.services.memory_verifier import issue_probe, verify_probe

    sdk = _make_sdk_client(http_client, api_key)
    session = sdk.start_session(name="e2e-malformed-refusal")
    agent_id = session.agent_id
    for i in range(15):
        session.log_event(input_data=f"q{i}", output_data=f"a{i}")

    db = SessionLocal()
    try:
        probe = issue_probe(db, agent_id)
        assert probe is not None, "expected a probe to be issued"
        # Force the probe into an ADV honeypot, then have the agent do
        # the correct thing: recognize it and refuse.
        apply_malformation_to_probe(probe, MalformationPlan(kind="short_nonce"))
        db.commit()
        verify_probe(
            db,
            probe.id,
            agent_proof_hex="",
            refusal_reason="declined: nonce too short",
        )
        # The refused honeypot is ADV's domain — never an MVS check. With
        # no well-formed decided probe, MVS has no signal yet → None.
        # Pre-fix this returned 0.0 (a false compromise verdict).
        mvs = memory_verifier.compute_mvs(db, agent_id)
        assert mvs is None, f"a refused honeypot dragged MVS to {mvs}"
        breakdown = memory_verifier.compute_mvs_breakdown(db, agent_id)
        assert breakdown.total == 0, breakdown
    finally:
        db.close()


def test_developer_api_register_returns_secret(http_client, api_key):
    """Sprint UX-5.17.API1 — POST /v1/agents (the developer API) returns
    the agent_secret, which the legacy /v1/agents/register never did."""
    r = http_client.post(
        "/v1/agents",
        json={"name": f"dev-api-{py_secrets.token_hex(3)}"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent_id"]
    assert body["agent_secret"] and len(body["agent_secret"]) == 64
    assert body["created_at"]


def test_developer_api_log_event(http_client, api_key):
    """POST /v1/agents/{id}/events records an event and returns the
    running count + a pending_checks list."""
    import hashlib

    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-api-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    r = http_client.post(
        f"/v1/agents/{agent_id}/events",
        json={
            "input_hash": hashlib.sha256(b"q1").hexdigest(),
            "output_hash": hashlib.sha256(b"a1").hexdigest(),
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == agent_id
    assert body["event_count"] == 1
    assert isinstance(body["pending_checks"], list)


def test_developer_api_full_loop_register_log_answer(http_client, api_key):
    """End-to-end through the developer router: register, log events,
    surface a verification check, answer it."""
    import hashlib
    from app.db.session import SessionLocal
    from app.services.observable_job import _maybe_issue_fresh_probe

    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-api-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    for i in range(15):
        http_client.post(
            f"/v1/agents/{agent_id}/events",
            json={
                "input_hash": hashlib.sha256(f"q{i}".encode()).hexdigest(),
                "output_hash": hashlib.sha256(f"a{i}".encode()).hexdigest(),
            },
            headers=headers,
        )

    db = SessionLocal()
    try:
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
    finally:
        db.close()

    # One more event — the response should now carry the pending check.
    r = http_client.post(
        f"/v1/agents/{agent_id}/events",
        json={
            "input_hash": hashlib.sha256(b"trigger").hexdigest(),
            "output_hash": hashlib.sha256(b"response").hexdigest(),
        },
        headers=headers,
    )
    checks = r.json()["pending_checks"]
    assert checks, "expected a pending check to be surfaced"
    check_id = checks[0]["check_id"]
    assert check_id

    # Answer it through the developer endpoint (decline path — exercises
    # the plumbing without reconstructing the digest chain in the test).
    ans = http_client.post(
        f"/v1/agents/{agent_id}/checks/{check_id}",
        json={"decline_reason": "test decline"},
        headers=headers,
    )
    assert ans.status_code == 200, ans.text
    assert ans.json()["check_id"] == check_id


def test_developer_api_list_checks(http_client, api_key):
    """GET /v1/agents/{id}/checks surfaces pending checks WITHOUT logging
    an event — the poll path the SDK's background worker uses so a quiet
    agent still answers its checks before they expire (UX-5.17.6)."""
    import hashlib
    from app.db.session import SessionLocal
    from app.services.observable_job import _maybe_issue_fresh_probe

    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-checks-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    # Unknown agent — resolution / ownership gate returns 404.
    assert (
        http_client.get("/v1/agents/nope-nope/checks", headers=headers)
        .status_code
        == 404
    )

    # Fresh agent — nothing to answer yet, but the field is always present.
    empty = http_client.get(f"/v1/agents/{agent_id}/checks", headers=headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["checks"] == []

    # gh-88 — polling does NOT auto-enable probes anymore. Memory probes are
    # off by default and opt-in (dashboard Settings / explicit metadata). A
    # bare registration + poll must leave probe_client unset.
    from app.db.models import Agent as AgentModel

    db = SessionLocal()
    try:
        a = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
        assert not (a.metadata_json or {}).get("probe_client")
    finally:
        db.close()

    for i in range(15):
        http_client.post(
            f"/v1/agents/{agent_id}/events",
            json={
                "input_hash": hashlib.sha256(f"q{i}".encode()).hexdigest(),
                "output_hash": hashlib.sha256(f"a{i}".encode()).hexdigest(),
            },
            headers=headers,
        )

    db = SessionLocal()
    try:
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
    finally:
        db.close()

    # Poll — the check is now visible without logging another event.
    r = http_client.get(f"/v1/agents/{agent_id}/checks", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_id"] == agent_id
    checks = body["checks"]
    assert checks, "poll should surface the pending check"
    check = checks[0]
    assert check["check_id"]
    assert check["nonce"]
    assert check["target_event_count"]


def test_developer_api_list_and_read(http_client, api_key):
    """Sprint UX-5.17.API1 — GET /v1/agents (lean list) + GET
    /v1/agents/{id} (lean status). The lean developer-API read
    endpoints; not the dashboard's fat payload."""
    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-api-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    # Lean list.
    lst = http_client.get("/v1/agents", headers=headers)
    assert lst.status_code == 200, lst.text
    body = lst.json()
    assert body["count"] >= 1
    row = next(a for a in body["agents"] if a["agent_id"] == agent_id)
    assert row["name"]
    assert "cryptographic" in row["verification"]
    assert "behavioral" in row["verification"]
    assert isinstance(row["needs_attention"], bool)
    assert "tier" in row

    # Lean detail.
    det = http_client.get(f"/v1/agents/{agent_id}", headers=headers)
    assert det.status_code == 200, det.text
    d = det.json()
    assert d["agent_id"] == agent_id
    assert d["verification"]["cryptographic"]  # a state word, non-empty
    assert isinstance(d["attention"], list)
    assert "created_at" in d
    # No internal payload leaked into the lean contract.
    assert "trust" not in d and "protections" not in d

    # Unknown agent → 404.
    assert (
        http_client.get("/v1/agents/nope-nope", headers=headers).status_code
        == 404
    )


def test_developer_api_proofs_and_revoke(http_client, api_key):
    """Sprint UX-5.17.API1 — POST /v1/agents/{id}/proofs (issue an A2A
    identity proof) + DELETE /v1/agents/{id} (revoke)."""
    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-api-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    # Issue a proof.
    pr = http_client.post(
        f"/v1/agents/{agent_id}/proofs",
        json={"ttl_seconds": 3600, "scope": "verify-only"},
        headers=headers,
    )
    assert pr.status_code == 201, pr.text
    proof = pr.json()
    assert proof["proof_id"]
    assert proof["proof"]  # the signed token
    assert proof["agent_id"] == agent_id
    assert proof["scope"] == "verify-only"

    # A bad TTL is rejected.
    bad = http_client.post(
        f"/v1/agents/{agent_id}/proofs",
        json={"ttl_seconds": 999},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text

    # Revoke the agent.
    rv = http_client.delete(f"/v1/agents/{agent_id}", headers=headers)
    assert rv.status_code == 200, rv.text
    assert rv.json()["agent_id"] == agent_id
    assert rv.json()["revoked_at"]

    # The agent is gone — a follow-up read 404s.
    assert (
        http_client.get(f"/v1/agents/{agent_id}", headers=headers).status_code
        == 404
    )


def test_get_status_surfaces_pending_probes(http_client, api_key):
    """Sprint UX-5.17.1 — the MCP `metalins_get_status` tool returns pending
    probes so an MCP client can poll for challenges WITHOUT logging an event.

    This exercises the MCP plane directly (not the SDK, which speaks the
    developer API): `pending_probes` must always be present, must surface a
    freshly issued probe, and must clear once the probe is answered.
    """
    from app.db.session import SessionLocal
    from app.services.observable_job import _maybe_issue_fresh_probe
    from metalins_drift import compute_check_answer

    sdk = _make_sdk_client(http_client, api_key)

    # Register + log through the developer API; the SDK session mirrors the
    # digest chain locally, which we use below to compute a valid proof.
    session = sdk.start_session(name="e2e-status")
    agent_id = session.agent_id

    def get_status() -> dict:
        resp = http_client.post(
            "/v1/mcp/tools/metalins_get_status", json={"agent_id": agent_id}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    # Before any probe is issued, get_status carries an empty list.
    status0 = get_status()
    assert "pending_probes" in status0, "get_status must always carry the field"
    assert status0["pending_probes"] == []

    # Log enough events for the server to be able to issue a probe.
    for i in range(15):
        session.log_event(
            input_data=f"q{i}", output_data=f"a{i}", auto_answer_checks=False
        )

    # Force a probe — but do NOT log another event (that is the whole point:
    # the client must be able to discover the probe without logging).
    db = SessionLocal()
    try:
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
    finally:
        db.close()

    # get_status alone surfaces the probe.
    status1 = get_status()
    pending = status1["pending_probes"]
    assert pending, "get_status should surface the pending probe"

    probe = pending[0]
    assert "probe_id" in probe
    assert "target_event_count" in probe
    assert "nonce" in probe
    # Must NEVER leak the expected proof — that would let any caller pass.
    assert "expected_proof" not in probe

    # The probe is answerable end-to-end: compute the proof from the locally
    # mirrored digest chain and submit it via the MCP plane.
    target_t = int(probe["target_event_count"])
    proof = compute_check_answer(
        session.digest_history[target_t], probe["nonce"], session.agent_secret
    )
    resp = http_client.post(
        "/v1/mcp/tools/metalins_respond_probe",
        json={
            "agent_id": agent_id,
            "probe_id": probe["probe_id"],
            "agent_proof": proof,
        },
    )
    assert resp.status_code == 200, resp.text

    status2 = get_status()
    answered_ids = {p["probe_id"] for p in status2["pending_probes"]}
    assert probe["probe_id"] not in answered_ids, "answered probe should clear"


def test_dashboard_register_returns_secret(http_client, api_key):
    """UX-5.17 #931 — the dashboard register path
    (/internal/v1/agents/register) now returns the agent_secret, so a
    dashboard-created agent can be connected via the SDK without a
    re-key."""
    r = http_client.post(
        "/internal/v1/agents/register",
        json={"name": f"reg-secret-{py_secrets.token_hex(3)}", "metadata": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["agent_id"]
    assert body["agent_secret"] and len(body["agent_secret"]) == 64


def test_reissue_secret_rekeys_agent(http_client, api_key):
    """UX-5.17 #505 — reissue-secret hands back a fresh secret, restarts
    the digest chain (event_count → 0, genesis re-derived), wipes the
    verification history, and keeps the agent's identity."""
    import hashlib

    from app.db.session import SessionLocal
    from app.db.models import AgentState, EventLog

    headers = {"Authorization": f"Bearer {api_key}"}
    name = f"rekey-{py_secrets.token_hex(3)}"
    reg = http_client.post("/v1/agents", json={"name": name}, headers=headers)
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]
    old_secret = reg.json()["agent_secret"]

    # Log a few events so there's a chain + EventLog rows to wipe.
    for i in range(5):
        http_client.post(
            f"/v1/agents/{agent_id}/events",
            json={
                "input_hash": hashlib.sha256(f"q{i}".encode()).hexdigest(),
                "output_hash": hashlib.sha256(f"a{i}".encode()).hexdigest(),
            },
            headers=headers,
        )

    # Wrong confirmation name → 422, no re-key.
    bad = http_client.post(
        f"/internal/v1/agents/{agent_id}/reissue-secret",
        json={"confirmation_name": "not the name"},
        headers=headers,
    )
    assert bad.status_code == 422, bad.text

    # Correct confirmation → full re-key.
    r = http_client.post(
        f"/internal/v1/agents/{agent_id}/reissue-secret",
        json={"confirmation_name": name},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    new_secret = r.json()["agent_secret"]
    assert new_secret and len(new_secret) == 64
    assert new_secret != old_secret
    assert r.json()["reissued_at"]

    # The chain restarted: event_count back to 0, EventLog wiped, the
    # state re-keyed and the genesis re-derived from the new secret.
    db = SessionLocal()
    try:
        state = db.query(AgentState).filter(
            AgentState.agent_id == agent_id
        ).first()
        assert state.agent_secret == new_secret
        assert state.event_count == 0
        assert state.history_digest == hashlib.sha256(
            bytes.fromhex(new_secret) + b"init"
        ).hexdigest()
        assert (
            db.query(EventLog).filter(EventLog.agent_id == agent_id).count()
            == 0
        )
    finally:
        db.close()

    # Re-key is NOT a delete — the agent still exists.
    det = http_client.get(f"/v1/agents/{agent_id}", headers=headers)
    assert det.status_code == 200, det.text


# --------------------------------------------------------------------------- #
# gh-88 — probes off by default + admin cleanup                                #
# --------------------------------------------------------------------------- #

def _agent_meta(agent_id: str) -> dict:
    from app.db.session import SessionLocal
    from app.db.models import Agent as AgentModel

    db = SessionLocal()
    try:
        a = db.query(AgentModel).filter(AgentModel.id == agent_id).first()
        return dict(a.metadata_json or {})
    finally:
        db.close()


def test_developer_registration_probes_off_by_default(http_client, api_key):
    """gh-88 — POST /v1/agents no longer auto-stamps probe_client."""
    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={"name": f"dev-off-{py_secrets.token_hex(3)}"},
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    assert not _agent_meta(reg.json()["agent_id"]).get("probe_client")


def test_developer_registration_honors_explicit_opt_in(http_client, api_key):
    """gh-88 — probes are still opt-in: an explicit metadata flag is honored."""
    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={
            "name": f"dev-on-{py_secrets.token_hex(3)}",
            "metadata": {"probe_client": True},
        },
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    assert _agent_meta(reg.json()["agent_id"]).get("probe_client") is True


def test_admin_disable_probes_expires_pending_and_turns_flag_off(
    http_client, api_key
):
    """gh-88 — POST /v1/admin/agents/{id}/disable-probes is the dogfood-v2
    cleanup: it expires pending probes and sets probe_client=false. Idempotent.
    """
    import hashlib
    from app.db.session import SessionLocal
    from app.db.models import MemoryProbe
    from app.services.observable_job import _maybe_issue_fresh_probe

    headers = {"Authorization": f"Bearer {api_key}"}
    reg = http_client.post(
        "/v1/agents",
        json={
            "name": f"df-clean-{py_secrets.token_hex(3)}",
            "metadata": {"probe_client": True},
        },
        headers=headers,
    )
    assert reg.status_code == 201, reg.text
    agent_id = reg.json()["agent_id"]

    for i in range(15):
        http_client.post(
            f"/v1/agents/{agent_id}/events",
            json={
                "input_hash": hashlib.sha256(f"i{i}".encode()).hexdigest(),
                "output_hash": hashlib.sha256(f"o{i}".encode()).hexdigest(),
            },
            headers=headers,
        )

    db = SessionLocal()
    try:
        _maybe_issue_fresh_probe(db, agent_id, has_mcp_activity=True)
        pending = (
            db.query(MemoryProbe)
            .filter(
                MemoryProbe.agent_id == agent_id,
                MemoryProbe.status == "pending",
            )
            .count()
        )
        assert pending >= 1, "a probe should be pending before cleanup"
    finally:
        db.close()

    admin_headers = {"X-Master-Token": "test-master-token"}
    r = http_client.post(
        f"/v1/admin/agents/{agent_id}/disable-probes", headers=admin_headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["probe_client_was"] is True
    assert body["probe_client_now"] is False
    assert body["pending_probes_expired"] >= 1

    assert _agent_meta(agent_id).get("probe_client") is False
    db = SessionLocal()
    try:
        still_pending = (
            db.query(MemoryProbe)
            .filter(
                MemoryProbe.agent_id == agent_id,
                MemoryProbe.status == "pending",
            )
            .count()
        )
        assert still_pending == 0
    finally:
        db.close()

    # Idempotent — second call is a no-op.
    r2 = http_client.post(
        f"/v1/admin/agents/{agent_id}/disable-probes", headers=admin_headers
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["pending_probes_expired"] == 0

    # Unknown agent → 404.
    assert (
        http_client.post(
            "/v1/admin/agents/nope-nope/disable-probes", headers=admin_headers
        ).status_code
        == 404
    )
