"""Memory Verifier — MVS (Memory Verification Score) protocol.

Ported from `research/R4-computational-validation/code/memory_verification.py`
(R7.b — PASS perfecto, AUC 1.0 contra clone perfecto).

Concept (from R7.b VEREDICTO):
  An agent's identity = logical_id + accumulated history. A clone with the
  same params + secret but different history cannot reproduce digests from
  before the takeover. We exploit this by asking the agent to prove it
  knows its local_digest at a random past event_count.

Protocol:
  1. Server picks a random past event_count target_t and a fresh nonce.
  2. Server computes expected_proof = sha256(digest_at_t || nonce || secret)
     using its own copy of digest_at_t (persisted in EventLog.history_digest)
     and the agent's secret (AgentState.agent_secret).
  3. Server records the probe with status=pending; agent fetches pending
     probes via API and responds with its own computed proof.
  4. Server verifies agent_proof vs expected_proof.
  5. MVS = fraction of recent probes that passed.

Honest agent: stores digest_history locally → MVS = 1.0.
Fresh clone: doesn't have digests from before takeover → MVS << 1.0.
"""
from __future__ import annotations

import hashlib
import hmac as hmac_module
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import AgentState, EventLog, MemoryProbe

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Tunables                                                                    #
# --------------------------------------------------------------------------- #

# How long an unanswered probe stays valid before being marked expired.
DEFAULT_PROBE_TTL = timedelta(hours=24)

# Minimum events required before we start issuing probes (avoid edge cases).
MIN_EVENTS_FOR_PROBE = 10

# How many recent responded probes to include in the MVS window.
DEFAULT_MVS_WINDOW = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hex_to_bytes(s: str) -> bytes:
    """Tolerant hex decode (strips 0x prefix if present)."""
    s = s.strip()
    if s.startswith("0x"):
        s = s[2:]
    return bytes.fromhex(s)


def compute_proof(history_digest_hex: str, nonce_hex: str, secret_hex: str) -> str:
    """Compute the canonical MVS proof.

      proof = sha256(history_digest_bytes || nonce_bytes || secret_bytes)

    All inputs are hex strings; output is hex string. This MUST match the
    SDK / agent-side computation exactly (the agent computes the same value
    over its own local digest history; mismatch = clone signal).
    """
    h = hashlib.sha256()
    h.update(_hex_to_bytes(history_digest_hex))
    h.update(_hex_to_bytes(nonce_hex))
    h.update(_hex_to_bytes(secret_hex))
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Probe issuance                                                              #
# --------------------------------------------------------------------------- #

def issue_probe(
    db: Session,
    agent_id: str,
    ttl: timedelta = DEFAULT_PROBE_TTL,
) -> Optional[MemoryProbe]:
    """Generate a fresh memory probe for `agent_id` and persist it.

    Returns None if there isn't enough history or the agent has no state.
    The returned probe has status='pending' and includes the expected_proof
    (kept server-side — the agent does NOT receive expected_proof, only
    target_event_count and nonce).
    """
    state = db.query(AgentState).filter_by(agent_id=agent_id).first()
    if state is None:
        return None
    if state.event_count is None or state.event_count < MIN_EVENTS_FOR_PROBE:
        return None

    # Pick a random target_t in [1, event_count].
    target_t = secrets.randbelow(state.event_count) + 1

    # Find the event_log row to get the digest_at_t the server recorded.
    event = (
        db.query(EventLog)
        .filter(EventLog.agent_id == agent_id, EventLog.event_count == target_t)
        .first()
    )
    if event is None or not event.history_digest:
        # Server doesn't have a digest for this t — skip rather than fail.
        return None

    nonce = secrets.token_hex(16)  # 16 bytes
    expected = compute_proof(event.history_digest, nonce, state.agent_secret)

    probe = MemoryProbe(
        id=new_id("prb"),
        agent_id=agent_id,
        target_event_count=target_t,
        nonce=nonce,
        expected_proof=expected,
        status="pending",
        issued_at=_utcnow(),
        expires_at=_utcnow() + ttl,
        # Sprint 7 / TLS — record the digest at issue time so both server
        # and (legit) agent can derive the same response window. The
        # current digest in AgentState IS the chain head, which is what
        # the agent will also see.
        history_digest_at_issue=state.history_digest,
    )

    # Sprint 7 / ADV — with probability ADV_MALFORMED_PROBABILITY, alter
    # the probe so a protocol-aware agent detects and refuses. The
    # `expected_proof` is already pinned to the canonical data above, so
    # forged proofs over malformed payloads can never validate.
    import random as _random
    from app.services.adv import (
        choose_malformation, apply_malformation_to_probe,
    )
    plan = choose_malformation(_random.SystemRandom())
    if plan is not None:
        apply_malformation_to_probe(probe, plan)

    db.add(probe)
    db.commit()
    db.refresh(probe)
    return probe


def expire_stale_probes(db: Session, agent_id: Optional[str] = None) -> int:
    """Mark pending probes past their expires_at as 'expired'.

    Counts toward MVS as failures (an honest agent should respond in time).
    Returns the number of probes expired.
    """
    now = _utcnow()
    q = db.query(MemoryProbe).filter(
        MemoryProbe.status == "pending",
        MemoryProbe.expires_at < now,
    )
    if agent_id is not None:
        q = q.filter(MemoryProbe.agent_id == agent_id)
    n = 0
    for p in q.all():
        p.status = "expired"
        p.valid = False
        n += 1
    if n:
        db.commit()
    return n


# --------------------------------------------------------------------------- #
# Probe verification                                                          #
# --------------------------------------------------------------------------- #

def verify_probe(
    db: Session,
    probe_id: str,
    agent_proof_hex: str,
    agent_id: Optional[str] = None,
    response_counter: Optional[int] = None,
    refusal_reason: Optional[str] = None,
) -> tuple[bool, str]:
    """Verify an agent's response to a probe.

    Returns (valid, reason). Side effects:
      - On success: marks probe responded, valid=True.
      - On mismatch: marks probe responded, valid=False (clone signal).
      - On unknown/expired/already-responded: returns False with reason,
        no DB state change.

    `agent_id` (optional) is the bearer-authenticated caller's agent_id;
    if provided, must match probe.agent_id (defense-in-depth).

    Sprint 7 / TLS — `response_counter` is the agent's `event_count` at
    the moment of crafting the proof. Stored alongside the probe so the
    batch job can derive the Time-Locked Score later. None values from
    older SDK versions are accepted (TLS just won't be evaluable for
    those probes).

    Sprint 7 / ADV — `refusal_reason`, when set, indicates the agent
    detected a protocol violation in the probe and refused to compute a
    proof. The probe is marked responded with valid=False (no proof was
    attempted). For malformed probes this is the correct behaviour
    (ADV win); for legit probes a refusal is a protocol violation by
    the agent and counts against ADV.
    """
    probe = db.query(MemoryProbe).filter_by(id=probe_id).first()
    if probe is None:
        return False, "probe_not_found"
    if agent_id is not None and probe.agent_id != agent_id:
        return False, "agent_id_mismatch"
    if probe.status != "pending":
        return False, f"probe_status_{probe.status}"
    if probe.expires_at and probe.expires_at < _utcnow():
        # Lazy expire if not already done.
        probe.status = "expired"
        probe.valid = False
        db.commit()
        return False, "probe_expired"

    # ----- Refusal path ----------------------------------------------------
    # Agent claims the probe is malformed and refuses to respond. We
    # accept the refusal regardless of whether the probe was actually
    # malformed; the ADV aggregator scores after the fact. Server-side
    # sentinels (refusal_reason starting with "_injected:") are reserved
    # for the malformation marker; we clear that and store the customer
    # reason instead.
    if refusal_reason and refusal_reason.strip():
        clean = refusal_reason.strip()[:120]  # cap length defensively
        # Don't let the customer write into our sentinel namespace.
        if clean.startswith("_injected:"):
            clean = "agent_refused"
        probe.refusal_reason = clean
        probe.agent_proof = None
        probe.valid = False
        probe.status = "responded"
        probe.responded_at = _utcnow()
        if response_counter is not None:
            probe.response_counter = int(response_counter)
        db.commit()
        return False, "refused_by_agent"

    valid = hmac_module.compare_digest(
        agent_proof_hex.strip().lower(),
        probe.expected_proof.lower(),
    )
    probe.agent_proof = agent_proof_hex.strip().lower()
    probe.valid = valid
    probe.status = "responded"
    probe.responded_at = _utcnow()
    if response_counter is not None:
        probe.response_counter = int(response_counter)
    db.commit()
    return valid, "ok" if valid else "proof_mismatch"


def list_pending_probes(db: Session, agent_id: str, limit: int = 10) -> list[dict]:
    """Return pending probes for an agent (oldest first). Public-safe payload.

    Does NOT leak the expected_proof — only target_event_count + nonce, which
    is exactly what the agent needs to compute its own proof.
    """
    rows = (
        db.query(MemoryProbe)
        .filter(MemoryProbe.agent_id == agent_id, MemoryProbe.status == "pending")
        .order_by(MemoryProbe.issued_at.asc())
        .limit(max(1, min(limit, 50)))
        .all()
    )
    return [
        # Sprint 7 / ADV — when the probe was server-mutated for the
        # adversarial-detection test, we expose the mutated payload here
        # so the agent has a chance to spot the violation and refuse.
        # public_payload_for_probe() handles both shapes (normal +
        # malformed).
        _adv_payload_for_probe(r)
        for r in rows
    ]


def _adv_payload_for_probe(probe: MemoryProbe) -> dict:
    """Thin wrapper around adv.public_payload_for_probe.

    Lives here so the listing loop above stays close to the call site,
    and so the import lives at function-call time (avoiding a circular
    dependency: adv imports MemoryProbe, memory_verifier owns the table).
    """
    from app.services.adv import public_payload_for_probe
    return public_payload_for_probe(probe)


# --------------------------------------------------------------------------- #
# MVS aggregation                                                             #
# --------------------------------------------------------------------------- #

def _mvs_window_rows(
    db: Session,
    agent_id: str,
    window: int,
) -> list[MemoryProbe]:
    """The recent N *decided* memory checks (responded or expired), newest
    first.

    Lazy-expires stale probes first, so an unanswered probe past its TTL
    counts as a decided outcome. Shared by `compute_mvs` and
    `compute_mvs_breakdown` so the score and its breakdown always agree
    on exactly the same window.

    A malformed (ADV honeypot) probe is excluded from MVS *only when the
    agent correctly REFUSED it*. A refusal stores a `refusal_reason` and
    is exactly the right behavior, so counting it as a failed memory
    check would be a false "memory checks failing" verdict — this is the
    UX-5.17.9 / #914 fix, and `compute_adv` is what scores refusals.

    But a malformed probe the agent ANSWERED (a computed `agent_proof`,
    no `refusal_reason`) is NOT excluded. Failing to recognize a honeypot
    and answering it is a genuine failure — and a strong clone signal,
    since a conformant agent would have refused — so it stays in the MVS
    window and counts. #914 originally excluded ALL malformed probes,
    which let a clone that answers a honeypot escape MVS entirely; the
    CAP-3 cloned-agent E2E ran flaky ~7% on exactly that gap (whenever
    the lone issued check happened to be a honeypot).
    """
    expire_stale_probes(db, agent_id=agent_id)
    return (
        db.query(MemoryProbe)
        .filter(
            MemoryProbe.agent_id == agent_id,
            MemoryProbe.status.in_(["responded", "expired"]),
            # Exclude a malformed (ADV honeypot) probe ONLY when it was
            # correctly refused — that refusal is ADV's domain, not a
            # memory failure. A malformed probe that was *answered*
            # (no refusal_reason) stays in the window and counts.
            ~(
                MemoryProbe.is_malformed.is_(True)
                & MemoryProbe.refusal_reason.isnot(None)
            ),
        )
        .order_by(MemoryProbe.issued_at.desc())
        .limit(max(1, min(window, 200)))
        .all()
    )


def compute_mvs(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_MVS_WINDOW,
) -> Optional[float]:
    """Fraction of recent N decided probes (responded or expired) that were valid.

    Returns None if there are no decided probes yet (agent is too young to
    have an MVS signal). 1.0 = perfect, 0.0 = total failure (clone signal).
    """
    rows = _mvs_window_rows(db, agent_id, window)
    if not rows:
        return None
    passed = sum(1 for r in rows if r.valid)
    return passed / len(rows)


@dataclass
class MVSBreakdown:
    """How the recent MVS window splits by outcome — Sprint UX-5.15.AJ.

    `compute_mvs` collapses the window into one fraction, which loses a
    distinction that matters a lot for the customer-facing verdict:

      • responded_invalid — the agent answered, and answered WRONG. A
        genuine "this might not be the same agent" signal → compromise.
      • expired — the agent never answered within the probe's window.
        It isn't responding to memory checks at all (offline, not wired
        up). An operational problem, NOT a compromise.

    explain_score uses this so an all-expiry window reads as "agent
    isn't answering" (caution) instead of "compromised" (action).
    """

    total: int
    passed: int
    responded_invalid: int
    expired: int


def compute_mvs_breakdown(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_MVS_WINDOW,
) -> MVSBreakdown:
    """Outcome breakdown of the same window `compute_mvs` scores."""
    rows = _mvs_window_rows(db, agent_id, window)
    passed = sum(1 for r in rows if r.status == "responded" and r.valid)
    responded_invalid = sum(
        1 for r in rows if r.status == "responded" and not r.valid
    )
    expired = sum(1 for r in rows if r.status == "expired")
    return MVSBreakdown(
        total=len(rows),
        passed=passed,
        responded_invalid=responded_invalid,
        expired=expired,
    )
