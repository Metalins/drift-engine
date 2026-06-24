#!/usr/bin/env python3
"""se-68 — end-to-end validation of κ-engine V2 behavioral drift detection.

The product's prueba de fuego. It exercises the WHOLE pipeline through the
real HTTP surface, exactly as a customer's SDK would:

  1. Create an agent                         POST /v1/agents
  2. Send a consistent baseline of traffic   POST /v1/agents/{id}/events   (×200)
  3. Force the baseline to be learned        POST /internal/v1/agents/{id}/recompute
  4. Send a drifted window (10x longer)      POST /v1/agents/{id}/events   (×50)
  5. Force the drift comparison              POST /internal/v1/agents/{id}/recompute
  6. Read the verdict                        GET  /internal/v1/agents/{id}/drift-events
  7. Assert drift_score > 0.5 and report PASS/FAIL + the dominant feature.

Why two recomputes: the engine is PASSIVE — it can only compare a fresh
window against a FIXED baseline. Recompute #1 (after the 200 clean events)
learns the baseline; recompute #2 (after the 50 drifted events) compares the
most-recent 50-event window against it. Building the baseline first is what
keeps the drift window out of the baseline it's measured against.

Auth: pass a Bearer `ml_*` API key via --api-key or METALINS_API_KEY. With
neither, the script self-provisions a throwaway customer + key directly in
the server's database (it runs on the same host as the server) so a bare
`python server/scripts/validate_drift_detection.py` works out of the box.

No third-party dependencies — stdlib urllib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Config                                                                      #
# --------------------------------------------------------------------------- #

DEFAULT_BASE_URL = os.environ.get("METALINS_BASE_URL", "http://localhost:8000")

N_BASELINE_EVENTS = 200      # consistent baseline window
N_DRIFT_EVENTS = 50          # drifted window (matches engine COMPARE_WINDOW_SIZE)
BASELINE_LEN_RANGE = (100, 200)     # output_length_chars for the baseline
DRIFT_LEN_RANGE = (2000, 3000)      # output_length_chars for the drift window
PASS_THRESHOLD = 0.5         # se-68 acceptance bar: drift_score must exceed this
TARGET_FEATURE = "output_length_chars"


# --------------------------------------------------------------------------- #
# Tiny HTTP client (stdlib)                                                    #
# --------------------------------------------------------------------------- #

class HttpError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


def _request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise HttpError(exc.code, body) from None
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"\n✗ Cannot reach the server at {url}\n  {exc}\n"
            f"  Is it running?  (uvicorn app.main:app --port 8000)"
        ) from None


# --------------------------------------------------------------------------- #
# Behavioral feature blobs                                                     #
# --------------------------------------------------------------------------- #

def _behavioral(output_chars: int) -> dict:
    """One event's structural features. Only output_length_chars varies
    between baseline and drift, so it is the unambiguous dominant feature;
    every other feature is held constant to keep the verdict clean."""
    return {
        "output_length_chars": output_chars,
        "output_length_tokens": 40,
        "input_length_chars": 50,
        "sentence_count_output": 5,
        "mean_sentence_length_output": 12.0,
        "latency_ms": 100.0,
        "had_code_block": False,
        "had_list": False,
        "had_markdown": False,
        "error_class": "none",
        "tool_calls": [],
        "format_markers": {"code": False, "list": False, "markdown": False, "json": False},
        "token_bag_lsh": "0" * 16,
    }


def _send_events(base_url: str, token: str, agent_id: str, n: int, length_range, tag: str) -> None:
    lo, hi = length_range
    for i in range(n):
        beh = _behavioral(random.randint(lo, hi))
        nonce = f"{tag}-{i}-{random.random()}"
        body = {
            "input_hash": hashlib.sha256(f"in-{nonce}".encode()).hexdigest(),
            "output_hash": hashlib.sha256(f"out-{nonce}".encode()).hexdigest(),
            "metadata": {"behavioral": beh},
        }
        _request("POST", f"{base_url}/v1/agents/{agent_id}/events", token, body)
        if (i + 1) % 50 == 0:
            print(f"    … {i + 1}/{n} {tag} events sent")


def _recompute(base_url: str, token: str, agent_id: str, label: str) -> None:
    """POST recompute, transparently waiting out the per-agent cooldown (60s)."""
    url = f"{base_url}/internal/v1/agents/{agent_id}/recompute"
    while True:
        try:
            _request("POST", url, token)
            print(f"  ✓ recompute ({label}) done")
            return
        except HttpError as exc:
            if exc.status == 429:
                retry = 5
                try:
                    detail = json.loads(exc.body).get("detail", "")
                    for tok in detail.replace("s", " ").split():
                        if tok.isdigit():
                            retry = int(tok)
                            break
                except Exception:
                    pass
                wait = retry + 2
                print(f"  … recompute cooldown active, waiting {wait}s ({label})")
                time.sleep(wait)
                continue
            raise


# --------------------------------------------------------------------------- #
# API-key resolution                                                          #
# --------------------------------------------------------------------------- #

def _provision_api_key() -> str:
    """Mint a throwaway customer + API key straight in the server DB.

    Used only when no key was supplied. Imports the server package (the
    script ships inside it) and reuses the exact key-hash function the auth
    layer validates against, so the minted `ml_*` key authenticates over
    HTTP like any real one.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    server_root = os.path.dirname(here)
    if server_root not in sys.path:
        sys.path.insert(0, server_root)

    from app.core.auth import _hash_key
    from app.core.ids import new_id
    from app.db.models import APIKey, Customer
    from app.db.session import SessionLocal

    raw_key = "ml_live_validate_" + hashlib.sha256(os.urandom(16)).hexdigest()[:24]
    db = SessionLocal()
    try:
        cust_id = new_id("cust")
        email = f"drift-validate-{cust_id}@example.com"
        db.add(Customer(id=cust_id, email=email))
        db.flush()
        db.add(APIKey(
            id=new_id("key"),
            customer_id=cust_id,
            key_hash=_hash_key(raw_key),
            owner_email=email,
            is_active=True,
        ))
        db.commit()
    finally:
        db.close()
    return raw_key


def _resolve_token(explicit: str | None) -> str:
    token = explicit or os.environ.get("METALINS_API_KEY")
    if token:
        print("  • using API key from " + ("--api-key" if explicit else "METALINS_API_KEY"))
        return token
    print("  • no API key given — provisioning a throwaway one in the DB")
    return _provision_api_key()


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description="Validate κ-engine V2 drift detection end-to-end.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="server base URL")
    parser.add_argument("--api-key", default=None, help="Bearer ml_* API key (else env METALINS_API_KEY, else self-provision)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    base_url = args.base_url.rstrip("/")
    print(f"→ Drift detection validation against {base_url}")

    token = _resolve_token(args.api_key)

    # 1. Create the agent.
    created = _request("POST", f"{base_url}/v1/agents", token, {"name": "drift-validate-bot"})
    agent_id = created["agent_id"]
    print(f"  ✓ agent created: {agent_id}")

    # 2. Baseline traffic.
    print(f"  • sending {N_BASELINE_EVENTS} baseline events "
          f"(output_length_chars {BASELINE_LEN_RANGE[0]}–{BASELINE_LEN_RANGE[1]})")
    _send_events(base_url, token, agent_id, N_BASELINE_EVENTS, BASELINE_LEN_RANGE, "baseline")

    # 3. Learn the baseline.
    _recompute(base_url, token, agent_id, "learn baseline")

    # 4. Drifted traffic — same shape, 10x longer outputs.
    print(f"  • sending {N_DRIFT_EVENTS} drifted events "
          f"(output_length_chars {DRIFT_LEN_RANGE[0]}–{DRIFT_LEN_RANGE[1]})")
    _send_events(base_url, token, agent_id, N_DRIFT_EVENTS, DRIFT_LEN_RANGE, "drift")

    # 5. Compare the drift window against the baseline.
    _recompute(base_url, token, agent_id, "detect drift")

    # 6. Read the verdict from the drift-events timeline.
    events = _request("GET", f"{base_url}/internal/v1/agents/{agent_id}/drift-events", token)
    items = events.get("items", [])

    print()
    print("─" * 60)
    if not items:
        print("✗ FAIL — no drift event was recorded.")
        print(f"  Expected a DRIFT_DETECTED event on '{TARGET_FEATURE}'.")
        print("─" * 60)
        return 1

    top = max(items, key=lambda e: e.get("drift_score", 0.0))
    score = float(top.get("drift_score", 0.0))
    feature = top.get("dominant_feature")
    passed = score > PASS_THRESHOLD

    print(f"  dominant feature : {feature}")
    print(f"  drift_score      : {score:.4f}   (threshold > {PASS_THRESHOLD})")
    print(f"  baseline → now   : {top.get('baseline_value')} → {top.get('current_value')}")
    print(f"  alerted (email)  : {top.get('notified_email')}")
    print(f"  total events     : {len(items)} drift event(s) recorded")
    print("─" * 60)

    if passed:
        print(f"✓ PASS — drift detected with score {score:.4f} on '{feature}'.")
        return 0
    print(f"✗ FAIL — drift_score {score:.4f} did not exceed {PASS_THRESHOLD}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
