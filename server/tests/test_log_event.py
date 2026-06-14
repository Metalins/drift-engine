"""Tests for behavioral metadata validation on log_event (#63).

Two layers:
  1. Unit — `validate_behavioral` accepts a well-formed blob (normalizing
     it) and rejects malformed shapes.
  2. Integration — `_do_log_event` persists a valid behavioral blob into
     `EventLog.metadata_json`, rejects a malformed one with HTTP 400, and
     leaves legacy events (no behavioral key) untouched.

Self-contained: SQLite temp DB seeded before any app import.
"""
from __future__ import annotations

import hashlib
import os

import pytest

_TMP_DB_PATH = f"/tmp/_metalins_log_event_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Unit — validate_behavioral                                                  #
# --------------------------------------------------------------------------- #

def _valid_blob() -> dict:
    return {
        "output_length_chars": 120,
        "output_length_tokens": 30,
        "had_code_block": True,
        "had_list": False,
        "had_markdown": True,
        "input_length_chars": 15,
        "sentence_count_output": 3,
        "mean_sentence_length_output": 8.5,
        "tool_calls": ["search", "fetch"],
        "latency_ms": 250.0,
        "error_class": "none",
        "format_markers": {"code": True, "list": False, "markdown": True, "json": False},
        "token_bag_lsh": "deadbeefcafef00d",
    }


def test_validate_accepts_well_formed_blob():
    from app.kappa.behavioral_schema import validate_behavioral

    out = validate_behavioral(_valid_blob())
    assert out["output_length_chars"] == 120
    assert out["tool_calls"] == ["search", "fetch"]
    assert out["error_class"] == "none"


def test_validate_coerces_unknown_error_class():
    from app.kappa.behavioral_schema import validate_behavioral

    blob = _valid_blob()
    blob["error_class"] = "explosion"
    assert validate_behavioral(blob)["error_class"] == "none"


def test_validate_stringifies_tool_calls():
    from app.kappa.behavioral_schema import validate_behavioral

    blob = _valid_blob()
    blob["tool_calls"] = [1, "search"]
    assert validate_behavioral(blob)["tool_calls"] == ["1", "search"]


def test_validate_latency_may_be_none():
    from app.kappa.behavioral_schema import validate_behavioral

    blob = _valid_blob()
    blob["latency_ms"] = None
    assert validate_behavioral(blob)["latency_ms"] is None


def test_validate_preserves_unknown_keys():
    from app.kappa.behavioral_schema import validate_behavioral

    blob = _valid_blob()
    blob["future_feature"] = 42
    assert validate_behavioral(blob)["future_feature"] == 42


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update({"output_length_chars": "long"}),
        lambda b: b.update({"output_length_chars": -5}),
        lambda b: b.update({"had_code_block": "yes"}),
        lambda b: b.update({"tool_calls": "search"}),
        lambda b: b.update({"format_markers": {"code": "true"}}),
        lambda b: b.update({"token_bag_lsh": "nothex!!"}),
        lambda b: b.update({"error_class": 5}),
    ],
)
def test_validate_rejects_malformed(mutate):
    from app.kappa.behavioral_schema import (
        BehavioralSchemaError,
        validate_behavioral,
    )

    blob = _valid_blob()
    mutate(blob)
    with pytest.raises(BehavioralSchemaError):
        validate_behavioral(blob)


def test_validate_rejects_non_object():
    from app.kappa.behavioral_schema import (
        BehavioralSchemaError,
        validate_behavioral,
    )

    with pytest.raises(BehavioralSchemaError):
        validate_behavioral(["not", "a", "dict"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update({"token_bag_lsh": "a" * 64}),          # oversized LSH
        lambda b: b.update({"tool_calls": ["t"] * 500}),          # too many tools
        lambda b: b.update({"tool_calls": ["x" * 1000]}),         # tool name too long
        lambda b: b.update({"format_markers": {f"k{i}": True for i in range(100)}}),  # too many markers
        lambda b: b.update({f"junk{i}": "v" for i in range(50)}), # too many unknown keys
        lambda b: b.update({"sneaky": "z" * 5000}),               # oversized unknown string
    ],
)
def test_validate_rejects_oversized_fields(mutate):
    """Bounds on attacker-controlled fields (storage / CPU DoS surface)."""
    from app.kappa.behavioral_schema import (
        BehavioralSchemaError,
        validate_behavioral,
    )

    blob = _valid_blob()
    mutate(blob)
    with pytest.raises(BehavioralSchemaError):
        validate_behavioral(blob)


def test_validate_accepts_empty_lsh():
    """Gated low-entropy outputs ship token_bag_lsh='' — must be accepted."""
    from app.kappa.behavioral_schema import validate_behavioral

    blob = _valid_blob()
    blob["token_bag_lsh"] = ""
    assert validate_behavioral(blob)["token_bag_lsh"] == ""


def test_schema_vocabulary_matches_sdk():
    """Server vocabulary must stay in lockstep with what the SDK emits —
    both ERROR_CLASSES and the full feature-name set."""
    import sys
    from pathlib import Path

    sdk_path = Path(__file__).resolve().parents[2] / "sdk-python"
    sys.path.insert(0, str(sdk_path))
    from metalins_drift.behavioral import (
        ERROR_CLASSES as sdk_classes,
        compute_behavioral_features,
    )
    from app.kappa.behavioral_schema import (
        ERROR_CLASSES as server_classes,
        ALL_FEATURE_NAMES,
    )

    assert set(sdk_classes) == set(server_classes)

    # Every key the SDK actually emits must be in the server's known
    # vocabulary — catches an SDK rename that would silently bypass
    # validation and blind the engine.
    sdk_keys = set(
        compute_behavioral_features("hello there friend", "a longer answer here now please")
    )
    assert sdk_keys == set(ALL_FEATURE_NAMES)


# --------------------------------------------------------------------------- #
# Integration — _do_log_event persists / rejects behavioral metadata          #
# --------------------------------------------------------------------------- #

@pytest.fixture
def seeded_db():
    """Fresh DB with a customer-wide API key, an agent, and its state.

    Builds a dedicated engine against this module's temp DB rather than
    reusing the module-global one: conftest's `pytest_configure` imports
    `app.config` before our `METALINS_DB_URL` override runs, so the global
    engine can already be bound to the stale default dev sqlite. We pass
    our own session straight into `_do_log_event`, so a local engine is
    enough and avoids patching global state.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base
    import app.db.models  # noqa: F401 — register models on Base

    # Recreate the file so each function-scoped run starts clean (the
    # temp path is shared across tests in this module).
    if os.path.exists(_TMP_DB_PATH):
        os.remove(_TMP_DB_PATH)
    engine = create_engine(
        f"sqlite:///{_TMP_DB_PATH}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    from app.db.models import APIKey, Agent, AgentState

    secret_hex = (b"\x42" * 32).hex()
    genesis = hashlib.sha256(bytes.fromhex(secret_hex) + b"init").hexdigest()

    api_key = APIKey(
        id="key_test",
        customer_id="cust_test",
        agent_id=None,
        key_hash="hash_test",
        owner_email="t@example.com",
        is_active=True,
    )
    agent = Agent(id="agt_test", api_key_id="key_test", name="tester")
    state = AgentState(
        agent_id="agt_test",
        history_digest=genesis,
        event_count=0,
        agent_secret=secret_hex,
    )
    db.add_all([api_key, agent, state])
    db.commit()

    yield db, api_key
    db.close()


def _args(metadata: dict) -> dict:
    return {
        "agent_id": "agt_test",
        "input_hash": hashlib.sha256(b"in").hexdigest(),
        "output_hash": hashlib.sha256(b"out").hexdigest(),
        "metadata": metadata,
    }


def test_log_event_persists_behavioral(seeded_db):
    from app.api.mcp_endpoints import _do_log_event
    from app.db.models import EventLog

    db, api_key = seeded_db
    resp = _do_log_event(_args({"behavioral": _valid_blob()}), api_key, db)
    assert resp["status"] == "logged"

    row = (
        db.query(EventLog)
        .filter(EventLog.agent_id == "agt_test")
        .order_by(EventLog.event_count.desc())
        .first()
    )
    assert row.metadata_json["behavioral"]["output_length_chars"] == 120
    # Normalized on the way in.
    assert row.metadata_json["behavioral"]["error_class"] == "none"


def test_log_event_rejects_malformed_behavioral(seeded_db):
    from fastapi import HTTPException
    from app.api.mcp_endpoints import _do_log_event

    db, api_key = seeded_db
    bad = _valid_blob()
    bad["output_length_chars"] = "huge"
    with pytest.raises(HTTPException) as exc:
        _do_log_event(_args({"behavioral": bad}), api_key, db)
    assert exc.value.status_code == 400
    assert "behavioral" in str(exc.value.detail)


def test_log_event_without_behavioral_still_works(seeded_db):
    """Legacy events (no behavioral key) remain valid."""
    from app.api.mcp_endpoints import _do_log_event

    db, api_key = seeded_db
    resp = _do_log_event(_args({"model": "claude"}), api_key, db)
    assert resp["status"] == "logged"
