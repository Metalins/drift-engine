"""Auto-detection of an agent's behavior mode (gh-77).

Until gh-77 the customer *declared* an ``agent_profile`` at registration
(``deterministic`` / ``low_stochastic`` / ``stochastic``) and that choice
gated which protections applied. That was a leaky abstraction: a customer
(e.g. Diana) cannot reliably know whether her own agent samples freely, and
a wrong declaration either silenced real protections or mis-fired them.

gh-77 removes the declaration. The engine instead *observes* the agent's
first events and decides for itself. The verdict lives on
``Agent.detected_behavior_mode`` and is consumed by
``protections_catalog.resolve_agent_profile``.

The signal
----------
An agent is *deterministic* iff identical inputs reliably produce the same
output, and *stochastic* iff identical inputs produce diverging outputs.
That is the only sound way to separate the two — diversity across *different*
inputs tells you nothing (a temperature-0 agent answering 20 distinct
questions still emits 20 distinct outputs).

So we group events by ``input_hash`` and look only at inputs that were seen
more than once (the SDK hashes the exact prompt, and real agents — e.g. the
dogfood agent cycling a fixed question set — repeat inputs naturally). For
each repeated input we ask: were the outputs the same?

  * Exact match on ``output_hash`` → consistent.
  * Otherwise we fall back to the behavioral features the SDK ships in
    ``metadata['behavioral']`` (gh-77 brief): ``token_bag_lsh`` (a 64-bit
    SimHash of the output token bag) and ``output_length_chars``. Two
    outputs that are near-duplicates (small SimHash Hamming distance and
    similar length) count as consistent — this absorbs the small
    serving-side jitter a genuinely temperature-0 model still exhibits,
    without treating a freely-sampling agent as deterministic.

A repeated input whose outputs are neither exact nor near-duplicate is
"varying" — hard evidence of stochastic sampling.

Aggregation across repeated-input groups:
  * fewer than ``MIN_REPEATED_OBSERVATIONS`` events that share an input with
    another event → ``unknown`` (not enough reproducibility evidence;
    ``resolve_agent_profile`` maps unknown to the deterministic default so
    the fuller moat applies meanwhile). One input answered identically 20×
    clears this; a single coincidental pair does not.
  * fraction of repeated-input groups that *varied* ≥
    ``STOCHASTIC_VARYING_FRACTION`` → ``stochastic``.
  * otherwise → ``deterministic``.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional


MODE_UNKNOWN = "unknown"
MODE_DETERMINISTIC = "deterministic"
MODE_STOCHASTIC = "stochastic"

VALID_MODES = frozenset({MODE_UNKNOWN, MODE_DETERMINISTIC, MODE_STOCHASTIC})

# Detection only runs once an agent has at least this many events — mirrors
# the gh-77 brief ("después de 20+ eventos").
MIN_EVENTS_FOR_DETECTION = 20

# How often (in event_count) the post-event hook re-evaluates. Keeps the
# scan off the hot path of every single log_event at high throughput.
DETECTION_INTERVAL = 20

# Cap how many recent events we scan per evaluation.
RECENT_WINDOW = 500

# Need at least this many events that share an input with another event
# (i.e. reproducibility evidence) before we commit to a verdict. One input
# answered repeatedly clears this; a single coincidental pair (2) does not.
MIN_REPEATED_OBSERVATIONS = 4

# SimHash (token_bag_lsh) is 64-bit. Two near-duplicate outputs differ by
# only a handful of bits; unrelated outputs differ by ~32. Anything within
# this Hamming distance is treated as the same output (absorbs temp-0 jitter).
LSH_NEAR_DUP_MAX_BITS = 6

# Relative tolerance on output_length_chars for two outputs to count as the
# same shape.
LENGTH_REL_TOL = 0.10

# A repeated-input agent is called stochastic once at least this fraction of
# its repeated inputs produced varying outputs.
STOCHASTIC_VARYING_FRACTION = 0.34


def _hamming_hex(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Bit Hamming distance between two equal-purpose hex SimHash strings.

    Returns None when either side is missing/empty or not valid hex, so the
    caller can fall back to a different signal rather than guess.
    """
    if not a or not b:
        return None
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except ValueError:
        return None


def _behavioral(event) -> dict:
    meta = getattr(event, "metadata_json", None) or {}
    beh = meta.get("behavioral") if isinstance(meta, dict) else None
    return beh if isinstance(beh, dict) else {}


def _near_duplicate(ev_a, ev_b) -> bool:
    """Whether two events with the *same input* carry near-duplicate outputs,
    judged from the SDK behavioral features (token_bag_lsh + length)."""
    ba, bb = _behavioral(ev_a), _behavioral(ev_b)
    dist = _hamming_hex(ba.get("token_bag_lsh"), bb.get("token_bag_lsh"))
    if dist is None or dist > LSH_NEAR_DUP_MAX_BITS:
        return False
    la, lb = ba.get("output_length_chars"), bb.get("output_length_chars")
    if isinstance(la, (int, float)) and isinstance(lb, (int, float)):
        denom = max(la, lb, 1)
        if abs(la - lb) / denom > LENGTH_REL_TOL:
            return False
    return True


def _group_is_consistent(events: list) -> bool:
    """Given all events that share one input_hash, decide if the agent
    answered that input consistently. Exact output match wins immediately;
    otherwise every output must be a near-duplicate of the first."""
    output_hashes = {getattr(e, "output_hash", None) for e in events}
    if len(output_hashes) == 1:
        return True
    reference = events[0]
    return all(_near_duplicate(reference, e) for e in events[1:])


def detect_behavior_mode(events: Iterable) -> str:
    """Classify an agent from its events.

    ``events`` is any iterable of EventLog-like objects exposing
    ``input_hash``, ``output_hash`` and ``metadata_json``. Order does not
    matter. Returns one of ``unknown`` / ``deterministic`` / ``stochastic``.
    """
    usable = [
        e
        for e in events
        if getattr(e, "input_hash", None) and getattr(e, "output_hash", None)
    ]
    if len(usable) < MIN_EVENTS_FOR_DETECTION:
        return MODE_UNKNOWN

    by_input: dict[str, list] = defaultdict(list)
    for e in usable:
        by_input[e.input_hash].append(e)

    repeated_groups = [grp for grp in by_input.values() if len(grp) >= 2]
    repeated_observations = sum(len(grp) for grp in repeated_groups)
    if repeated_observations < MIN_REPEATED_OBSERVATIONS:
        # Not enough repeated-input evidence to tell deterministic from
        # stochastic. Stay unknown — the caller defaults to the fuller moat.
        return MODE_UNKNOWN

    varying = sum(1 for grp in repeated_groups if not _group_is_consistent(grp))
    varying_fraction = varying / len(repeated_groups)
    if varying_fraction >= STOCHASTIC_VARYING_FRACTION:
        return MODE_STOCHASTIC
    return MODE_DETERMINISTIC


def maybe_update_behavior_mode(db, agent) -> str:
    """Re-evaluate and persist ``agent.detected_behavior_mode`` if the
    evidence now supports a firmer verdict.

    Best-effort and idempotent: never downgrades a decided mode back to
    ``unknown`` (a quiet window shouldn't erase prior evidence), and only
    writes when the verdict actually changes. Returns the (possibly
    unchanged) current mode.
    """
    from app.db.models import EventLog

    current = getattr(agent, "detected_behavior_mode", None) or MODE_UNKNOWN

    events = (
        db.query(EventLog)
        .filter(EventLog.agent_id == agent.id)
        .order_by(EventLog.event_count.desc())
        .limit(RECENT_WINDOW)
        .all()
    )
    detected = detect_behavior_mode(events)

    if detected != MODE_UNKNOWN and detected != current:
        agent.detected_behavior_mode = detected
        db.commit()
        return detected
    return current
