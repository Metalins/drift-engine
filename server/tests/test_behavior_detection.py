"""Tests for gh-77 — server-side auto-detection of agent behavior mode.

Three layers:
  1. Unit — `detect_behavior_mode` classifies deterministic / stochastic /
     unknown from EventLog-shaped objects.
  2. Mapping — `resolve_agent_profile` maps the detected mode onto the
     protections-catalog profile vocabulary.
  3. Integration — `_do_log_event` flips an agent's detected_behavior_mode
     once enough events accumulate, and `register_agent` ignores any
     declared profile.

Self-contained: SQLite temp DB seeded before any app import (mirrors
test_log_event.py).
"""
from __future__ import annotations

import hashlib
import os

import pytest

_TMP_DB_PATH = f"/tmp/_metalins_behavior_detect_{os.getpid()}.db"
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)
os.environ["METALINS_DB_URL"] = f"sqlite:///{_TMP_DB_PATH}"
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

class _Ev:
    """Minimal EventLog stand-in for the pure-function detector."""

    def __init__(self, input_hash, output_hash, lsh=None, length=None):
        self.input_hash = input_hash
        self.output_hash = output_hash
        beh = {}
        if lsh is not None:
            beh["token_bag_lsh"] = lsh
        if length is not None:
            beh["output_length_chars"] = length
        self.metadata_json = {"behavioral": beh} if beh else {}


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Unit — detect_behavior_mode                                                 #
# --------------------------------------------------------------------------- #

def test_too_few_events_is_unknown():
    from app.services.behavior_detection import detect_behavior_mode, MODE_UNKNOWN

    events = [_Ev(_h("a"), _h("b")) for _ in range(10)]
    assert detect_behavior_mode(events) == MODE_UNKNOWN


def test_no_repeated_inputs_is_unknown():
    """20 events but every input distinct → cannot separate det/stoch."""
    from app.services.behavior_detection import detect_behavior_mode, MODE_UNKNOWN

    events = [_Ev(_h(f"in{i}"), _h(f"out{i}")) for i in range(20)]
    assert detect_behavior_mode(events) == MODE_UNKNOWN


def test_single_repeated_input_consistent_is_deterministic():
    """One input answered identically 20× is strong determinism evidence."""
    from app.services.behavior_detection import (
        detect_behavior_mode,
        MODE_DETERMINISTIC,
    )

    events = [_Ev(_h("question"), _h("answer")) for _ in range(20)]
    assert detect_behavior_mode(events) == MODE_DETERMINISTIC


def test_repeated_inputs_consistent_is_deterministic():
    from app.services.behavior_detection import (
        detect_behavior_mode,
        MODE_DETERMINISTIC,
    )

    events = []
    for i in range(20):
        key = f"q{i % 4}"  # 4 distinct inputs, each seen 5×
        events.append(_Ev(_h(key), _h(f"a:{key}")))
    assert detect_behavior_mode(events) == MODE_DETERMINISTIC


def test_same_input_varying_outputs_is_stochastic():
    from app.services.behavior_detection import (
        detect_behavior_mode,
        MODE_STOCHASTIC,
    )

    events = []
    for i in range(20):
        key = f"q{i % 4}"
        # Different output every single time, with far-apart SimHashes so the
        # near-duplicate fallback does not rescue it.
        events.append(
            _Ev(_h(key), _h(f"a:{key}:{i}"), lsh=f"{(i * 0x9999) & 0xFFFFFFFFFFFFFFFF:016x}")
        )
    assert detect_behavior_mode(events) == MODE_STOCHASTIC


def test_near_duplicate_lsh_absorbs_jitter():
    """Same input, output_hash differs but SimHash is within a few bits and
    length is close → treated as deterministic (serving-side jitter)."""
    from app.services.behavior_detection import (
        detect_behavior_mode,
        MODE_DETERMINISTIC,
    )

    base = 0xABCDEF0123456789
    events = []
    for i in range(20):
        key = f"q{i % 4}"
        # Flip a single low bit half the time → Hamming distance 1.
        lsh_val = base ^ (i & 1)
        events.append(
            _Ev(_h(key), _h(f"out:{key}:{i}"), lsh=f"{lsh_val:016x}", length=100 + (i & 1))
        )
    assert detect_behavior_mode(events) == MODE_DETERMINISTIC


def test_far_lsh_not_absorbed_is_stochastic():
    """Same inputs but SimHashes far apart → genuine variation → stochastic."""
    from app.services.behavior_detection import (
        detect_behavior_mode,
        MODE_STOCHASTIC,
    )

    events = []
    for i in range(20):
        key = f"q{i % 2}"  # 2 groups of 10
        # Alternate WITHIN each group between two 32-bit-apart hashes
        # (i // 2 advances once per same-group event).
        lsh = "ffffffff00000000" if (i // 2) % 2 else "00000000ffffffff"
        events.append(_Ev(_h(key), _h(f"out:{key}:{i}"), lsh=lsh, length=100))
    assert detect_behavior_mode(events) == MODE_STOCHASTIC


def test_hamming_helper():
    from app.services.behavior_detection import _hamming_hex

    assert _hamming_hex("0", "0") == 0
    assert _hamming_hex("0", "1") == 1
    assert _hamming_hex("ff", "00") == 8
    assert _hamming_hex("", "ff") is None
    assert _hamming_hex("zz", "00") is None


# --------------------------------------------------------------------------- #
# Mapping — resolve_agent_profile                                             #
# --------------------------------------------------------------------------- #

class _Agent:
    def __init__(self, mode):
        self.detected_behavior_mode = mode


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("deterministic", "deterministic"),
        ("stochastic", "stochastic"),
        ("unknown", "deterministic"),   # default = fuller moat
        (None, "deterministic"),
    ],
)
def test_resolve_agent_profile_maps_detected_mode(mode, expected):
    from app.services.protections_catalog import resolve_agent_profile

    assert resolve_agent_profile(_Agent(mode)) == expected


def test_resolve_agent_profile_ignores_metadata_declaration():
    """A declared profile in metadata must no longer influence the result."""
    from app.services.protections_catalog import resolve_agent_profile

    agent = _Agent("unknown")
    agent.metadata_json = {"agent_profile": "stochastic"}
    # Detected mode is unknown → deterministic default; the declaration is
    # ignored entirely.
    assert resolve_agent_profile(agent) == "deterministic"


def test_resolve_agent_profile_none_is_default():
    from app.services.protections_catalog import resolve_agent_profile

    assert resolve_agent_profile(None) == "deterministic"


# --------------------------------------------------------------------------- #
# Integration — log_event hook + register strips declared profile            #
# --------------------------------------------------------------------------- #

@pytest.fixture
def seeded_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.session import Base
    import app.db.models  # noqa: F401 — register models on Base

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


def _log(db, api_key, in_str, out_str):
    from app.api.mcp_endpoints import _do_log_event

    return _do_log_event(
        {
            "agent_id": "agt_test",
            "input_hash": _h(in_str),
            "output_hash": _h(out_str),
            "metadata": {},
        },
        api_key,
        db,
    )


def test_new_agent_starts_unknown(seeded_db):
    from app.db.models import Agent

    db, _ = seeded_db
    agent = db.query(Agent).filter(Agent.id == "agt_test").first()
    assert agent.detected_behavior_mode == "unknown"


def test_log_event_detects_deterministic(seeded_db):
    from app.db.models import Agent

    db, api_key = seeded_db
    # 4 distinct inputs, each answered identically; 20 events total → at
    # event 20 the detection hook runs.
    for i in range(20):
        key = f"q{i % 4}"
        _log(db, api_key, key, f"answer:{key}")

    agent = db.query(Agent).filter(Agent.id == "agt_test").first()
    assert agent.detected_behavior_mode == "deterministic"


def test_log_event_detects_stochastic(seeded_db):
    from app.db.models import Agent

    db, api_key = seeded_db
    for i in range(20):
        key = f"q{i % 4}"
        # Same inputs recur but every output is unique → stochastic.
        _log(db, api_key, key, f"answer:{key}:{i}")

    agent = db.query(Agent).filter(Agent.id == "agt_test").first()
    assert agent.detected_behavior_mode == "stochastic"


def test_log_event_stays_unknown_before_floor(seeded_db):
    from app.db.models import Agent

    db, api_key = seeded_db
    for i in range(19):  # one short of the floor / interval
        _log(db, api_key, f"q{i % 4}", f"answer:q{i % 4}")

    agent = db.query(Agent).filter(Agent.id == "agt_test").first()
    assert agent.detected_behavior_mode == "unknown"


def test_register_ignores_declared_profile(seeded_db):
    """REST register must strip any declared profile and start unknown."""
    from app.api.agents import _strip_declared_profile

    cleaned = _strip_declared_profile(
        {"agent_profile": "stochastic", "profile": "deterministic",
         "behavior_mode": "x", "agent_type": "y", "keep": "me"}
    )
    assert cleaned == {"keep": "me"}
