"""Integration test — verify /demo page fixture agents are in expected states.

These 4 agents are permanent fixtures used by the public /demo page.
If any of them drifts from its expected state, the /demo page shows
wrong data. This test catches that.

Runs only when METALINS_INTEGRATION_API_KEY is set (CI or explicit run).
Skip in unit-test mode (no env var → pytest.skip).

Usage:
    METALINS_INTEGRATION_API_KEY=ml_live_... pytest server/tests/test_demo_fixtures.py -v
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES_PATH = Path(__file__).parent.parent.parent / "scripts" / "demo_fixtures.json"

API_KEY = os.getenv("METALINS_INTEGRATION_API_KEY")
API_URL = os.getenv("METALINS_API_URL", "https://api.metalins.ai")

# Expected crypto state per fixture slot
EXPECTED_CRYPTO = {
    "verified": "verified",
    "learning": "verified",   # crypto verified, behavioral is not_enough_data
    "caution": "caution",
    "action_required": "action_required",
}


@pytest.fixture(scope="module")
def fixtures():
    assert FIXTURES_PATH.exists(), f"demo_fixtures.json not found at {FIXTURES_PATH}"
    return json.loads(FIXTURES_PATH.read_text())


@pytest.fixture(scope="module")
def http():
    if not API_KEY:
        pytest.skip("METALINS_INTEGRATION_API_KEY not set — skipping demo fixture integration test")
    import httpx
    return httpx.Client(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=15,
    )


@pytest.mark.parametrize("slot", ["verified", "learning", "caution", "action_required"])
def test_demo_fixture_state(slot, fixtures, http):
    """Each demo fixture agent must be in its expected trust state."""
    agent_id = fixtures[slot]["agent_id"]
    r = http.get(f"/v1/agents/{agent_id}")
    assert r.status_code == 200, f"agent {agent_id} ({slot}) returned {r.status_code}"
    data = r.json()
    trust = data.get("trust", {})
    crypto_state = trust.get("cryptographic", {}).get("state")
    assert crypto_state == EXPECTED_CRYPTO[slot], (
        f"Demo fixture '{slot}' (agent {agent_id}): "
        f"expected crypto state '{EXPECTED_CRYPTO[slot]}', got '{crypto_state}'. "
        f"The /demo page is showing incorrect data — fix the fixture agent."
    )


def test_demo_fixtures_file_complete(fixtures):
    """demo_fixtures.json must have all 4 slots with agent_id."""
    for slot in ("verified", "learning", "caution", "action_required"):
        assert slot in fixtures, f"Missing slot '{slot}' in demo_fixtures.json"
        assert fixtures[slot].get("agent_id"), f"Missing agent_id for slot '{slot}'"
