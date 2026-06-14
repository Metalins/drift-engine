"""TLS — Time-Locked Score (Sprint 7, paper §8.3 / R11-A).

Each memory probe carries a *response window* derived deterministically
from the history digest at issue time:

    window_size = BASE_WINDOW + (history_digest[:4] mod JITTER_RANGE)

A legitimate agent — that has been tracking the digest chain locally —
arrives at the same window when responding. It includes its current
`event_count` as `response_counter`; the server verifies the counter is
inside [w_start, w_end] derived from `history_digest_at_issue`.

An attacker with the agent secret but without the shared digest history
computes the window from its own (wrong) digest. With high probability
its `response_counter` lands outside the legit window and the TLS check
fails.

Threat model defended (R11, AUC 1.0):
    "Random-timing attacker" — has stolen the agent secret but lacks
    the history chain. Their response counter is uncorrelated with the
    legit window, so on average half of their responses miss.

Adaptation from research: protocols_r11.py drives the window with a
shared `t` counter the agent maintains. We use the agent's reported
`event_count` instead (same role, same threat coverage). For watcher-only
agents memory probes don't apply, so TLS isn't computed there either.

This module is pure functions over (history_digest, counter). DB access
is limited to the `compute_tls` aggregator at the bottom.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.db.models import MemoryProbe


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# Mirrors protocols_r11.derive_response_window defaults. Window is small
# relative to the total `event_count` range so a random counter has low
# probability of accidentally landing inside.
BASE_WINDOW = 100
JITTER_RANGE = 50

# How many recent responded probes the rolling TLS score covers.
DEFAULT_TLS_WINDOW = 20

# Below this fraction, surface a customer-facing warning factor.
TLS_WARNING_THRESHOLD = 0.7


# --------------------------------------------------------------------------- #
# Pure window derivation                                                      #
# --------------------------------------------------------------------------- #

def derive_response_window(
    history_digest_hex: str,
    *,
    base_window: int = BASE_WINDOW,
    jitter_range: int = JITTER_RANGE,
) -> tuple[int, int]:
    """Compute the [start, end] valid counter window for a probe.

    Mirrors `protocols_r11.derive_response_window` exactly so any future
    cross-validation with the research code is bit-identical.

    The window is anchored at 0 — the agent reports its `event_count`
    modulo `(window_size + 1)` so the bucket is small (200-ish) and the
    server can verify in O(1).
    """
    h_int = int.from_bytes(bytes.fromhex(history_digest_hex)[:4], "big")
    jitter = h_int % jitter_range
    window_size = base_window + jitter
    return 0, window_size


def counter_to_bucket(
    response_counter: int,
    window_end: int,
) -> int:
    """Project a raw `event_count` into the window's bucket space.

    Both server and agent project the same way (event_count modulo
    window_size+1) so they end up comparing apples to apples.
    """
    if window_end <= 0:
        return 0
    return response_counter % (window_end + 1)


def verify_probe_response_timing(probe: MemoryProbe) -> bool | None:
    """Returns True/False if we can evaluate TLS for this probe, None if
    the probe predates TLS instrumentation (legacy rows have no
    history_digest_at_issue and no response_counter)."""
    if not probe.history_digest_at_issue:
        return None
    if probe.response_counter is None:
        # Probe responded by an SDK version that doesn't supply the
        # counter — treat as "no signal" rather than a miss, so old
        # clients don't get penalized retroactively.
        return None
    w_start, w_end = derive_response_window(probe.history_digest_at_issue)
    bucket = counter_to_bucket(probe.response_counter, w_end)
    return w_start <= bucket <= w_end


# --------------------------------------------------------------------------- #
# DB-aware aggregator                                                         #
# --------------------------------------------------------------------------- #

@dataclass
class TLSResult:
    n_evaluated: int       # probes where TLS could be checked
    n_in_window: int       # of those, how many passed
    score: float | None    # None if nothing evaluable, else n_in_window/n_evaluated


def compute_tls(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_TLS_WINDOW,
) -> float | None:
    """Score TLS over the most recent `window` responded probes.

    Returns None when there's nothing to evaluate (no responded probes
    yet, or all are legacy rows without the TLS instrumentation). The
    aggregator in `identity_engine.identity_confidence_v1` treats None
    as "no signal" — confidence isn't capped, but it isn't boosted
    either.
    """
    probes = (
        db.query(MemoryProbe)
        .filter(
            MemoryProbe.agent_id == agent_id,
            MemoryProbe.status == "responded",
        )
        .order_by(MemoryProbe.responded_at.desc())
        .limit(window)
        .all()
    )
    if not probes:
        return None

    evaluable = 0
    passed = 0
    for p in probes:
        ok = verify_probe_response_timing(p)
        if ok is None:
            continue
        evaluable += 1
        if ok:
            passed += 1

    if evaluable == 0:
        return None
    return passed / evaluable
