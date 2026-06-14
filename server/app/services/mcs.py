"""MCS — Multi-agent Corroboration Score (Sprint 7, paper §8.4 / R11-B).

Two of a customer's agents form a "mesh pair". Every
CORROBORATION_INTERVAL events, each agent submits a co-signature over
its own current state plus its understanding of the partner's state:

    co_sig_self = HMAC(secret_self, state_self || state_partner)

The server holds the row open until both sides submit for the same
cycle, then verifies:
  1. Each side's co_sig is correct under its own secret.
  2. Both sides agree on (state_a, state_b) — neither lies about the
     partner's state.

If A is compromised, the attacker has secret_A but doesn't know
state_B's actual evolution (they only see B's I/O traces, not its
internal state hash). So their `partner_state` claim diverges from
what B itself reports, and the verification fails.

Threat model defended (R11, AUC 1.0):
    "Single-agent compromise in a mesh" — attacker fully owns one
    agent's secret + observed traces but doesn't have the partner's
    internal state.

V1 scope (D-PROD.18): same-customer mesh only. Cross-customer is V2 —
needs authorization, billing, more invasive trust model.

UI scope: dashboard pairing flow lives in a separate task (Sprint
7.5b). For V1 backend, customers create pairs via API directly.

This module is pure scoring + a DB-aware aggregator and resolver. The
endpoints live in api/mcs_endpoints.py.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import AgentMeshPair, AgentState, CorroborationPoint


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# Mirrors `protocols_r11.py:run_multiagent_baseline` corroboration cadence
# (`t % 50 == 0`). At one cycle per 50 events the rolling window covers
# the most recent ~500 events of activity.
CORROBORATION_INTERVAL = 50

# How many recent resolved cycles the aggregator reads.
DEFAULT_MCS_WINDOW = 10

# Below this fraction, surface a customer-facing warning factor.
MCS_WARNING_THRESHOLD = 0.7


# --------------------------------------------------------------------------- #
# Canonical pair ordering                                                     #
# --------------------------------------------------------------------------- #

def canonical_pair(agent_x: str, agent_y: str) -> tuple[str, str]:
    """Return (a, b) with a < b lexicographically. The DB CHECK
    constraint enforces this — we sort here so callers don't have to.
    """
    if agent_x == agent_y:
        raise ValueError("cannot pair an agent with itself")
    return (agent_x, agent_y) if agent_x < agent_y else (agent_y, agent_x)


# --------------------------------------------------------------------------- #
# Pair management                                                             #
# --------------------------------------------------------------------------- #

def create_mesh_pair(
    db: Session,
    customer_id: str,
    agent_x: str,
    agent_y: str,
) -> AgentMeshPair:
    """Create a mesh pair between two agents owned by the same customer.

    Idempotent — if the canonical pair already exists, returns the
    existing row without raising.

    Caller is responsible for verifying both agents belong to
    `customer_id` before invoking this.
    """
    a, b = canonical_pair(agent_x, agent_y)
    existing = (
        db.query(AgentMeshPair)
        .filter(
            AgentMeshPair.agent_a_id == a,
            AgentMeshPair.agent_b_id == b,
        )
        .first()
    )
    if existing is not None:
        return existing

    pair = AgentMeshPair(
        id=new_id("msh"),
        customer_id=customer_id,
        agent_a_id=a,
        agent_b_id=b,
    )
    db.add(pair)
    db.commit()
    db.refresh(pair)
    return pair


def find_pair_for_agent(db: Session, agent_id: str) -> Optional[AgentMeshPair]:
    """Look up the active (non-paused) mesh pair an agent participates in.

    V1 assumption: an agent is in at most one mesh pair at a time. If
    that ever changes we'll need a list-returning version.
    """
    return (
        db.query(AgentMeshPair)
        .filter(
            (AgentMeshPair.agent_a_id == agent_id)
            | (AgentMeshPair.agent_b_id == agent_id),
            AgentMeshPair.paused_at.is_(None),
        )
        .first()
    )


# --------------------------------------------------------------------------- #
# Pure crypto primitive                                                       #
# --------------------------------------------------------------------------- #

def compute_co_signature(
    agent_secret_hex: str,
    state_self_hex: str,
    state_partner_hex: str,
) -> str:
    """HMAC over (state_self || state_partner) with the agent's secret.

    State hex strings are decoded to raw bytes before concatenation
    (matches `protocols_r11.run_multiagent_baseline` which works in
    bytes throughout).
    """
    h = hmac.new(
        bytes.fromhex(agent_secret_hex),
        bytes.fromhex(state_self_hex) + bytes.fromhex(state_partner_hex),
        hashlib.sha256,
    )
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# Submission                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class CorroborationSubmissionError(Exception):
    reason: str

    def __str__(self) -> str:  # pragma: no cover
        return self.reason


def submit_corroboration(
    db: Session,
    submitting_agent_id: str,
    cycle: int,
    state_self_hex: str,
    state_partner_hex: str,
    co_sig_hex: str,
) -> CorroborationPoint:
    """Persist one side of a corroboration cycle. If the partner has
    already submitted for this cycle, attempts to resolve immediately.

    Raises `CorroborationSubmissionError` when:
      - the submitter isn't in a mesh pair
      - the (pair, cycle) row already has the submitter's side filled

    Returns the row (whether new or partially-filled), including the
    verified flag if both sides have arrived.
    """
    pair = find_pair_for_agent(db, submitting_agent_id)
    if pair is None:
        raise CorroborationSubmissionError(
            "agent is not part of any active mesh pair"
        )

    is_a = submitting_agent_id == pair.agent_a_id
    row = (
        db.query(CorroborationPoint)
        .filter(
            CorroborationPoint.mesh_pair_id == pair.id,
            CorroborationPoint.cycle == cycle,
        )
        .first()
    )
    now = datetime.utcnow()
    if row is None:
        row = CorroborationPoint(
            id=new_id("cor"),
            mesh_pair_id=pair.id,
            cycle=cycle,
        )
        db.add(row)

    if is_a:
        if row.a_co_sig is not None:
            raise CorroborationSubmissionError(
                "side A already submitted for this cycle"
            )
        row.a_state = state_self_hex
        row.a_partner_state = state_partner_hex
        row.a_co_sig = co_sig_hex
        row.a_submitted_at = now
    else:
        if row.b_co_sig is not None:
            raise CorroborationSubmissionError(
                "side B already submitted for this cycle"
            )
        row.b_state = state_self_hex
        row.b_partner_state = state_partner_hex
        row.b_co_sig = co_sig_hex
        row.b_submitted_at = now

    db.commit()
    db.refresh(row)

    # Try to resolve if both sides are now present.
    if row.a_co_sig is not None and row.b_co_sig is not None:
        _resolve_point(db, pair, row)

    return row


# --------------------------------------------------------------------------- #
# Resolution                                                                  #
# --------------------------------------------------------------------------- #

def _resolve_point(
    db: Session,
    pair: AgentMeshPair,
    row: CorroborationPoint,
) -> None:
    """Verify a (pair, cycle) where both sides have submitted.

    Sets row.verified True/False and resolved_at. Verification fails if:
      - either side's co_sig doesn't reproduce under its own secret
      - the two sides disagree on (state_a, state_b)
    """
    # Pull both agents' secrets.
    a_state = (
        db.query(AgentState).filter(AgentState.agent_id == pair.agent_a_id).first()
    )
    b_state = (
        db.query(AgentState).filter(AgentState.agent_id == pair.agent_b_id).first()
    )
    if a_state is None or b_state is None:
        # Defensive — the pair should not exist without both states.
        row.verified = False
        row.resolved_at = datetime.utcnow()
        db.commit()
        return

    # A's view: state_self == state_a, state_partner == B's state.
    # B's view: state_self == state_b, state_partner == A's state.
    # For agreement we need A's a_state == B's b_partner_state AND
    # A's a_partner_state == B's b_state.
    agreement = (
        row.a_state == row.b_partner_state
        and row.a_partner_state == row.b_state
    )

    sig_a_ok = hmac.compare_digest(
        row.a_co_sig or "",
        compute_co_signature(
            a_state.agent_secret, row.a_state or "", row.a_partner_state or "",
        ),
    )
    sig_b_ok = hmac.compare_digest(
        row.b_co_sig or "",
        compute_co_signature(
            b_state.agent_secret, row.b_state or "", row.b_partner_state or "",
        ),
    )

    row.verified = bool(agreement and sig_a_ok and sig_b_ok)
    row.resolved_at = datetime.utcnow()
    db.commit()


# --------------------------------------------------------------------------- #
# Aggregator                                                                  #
# --------------------------------------------------------------------------- #

def compute_mcs(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_MCS_WINDOW,
) -> Optional[float]:
    """Average verification rate over the most recent `window` resolved
    cycles for the agent's mesh pair.

    Returns None when the agent isn't in a mesh pair, or there are no
    resolved cycles yet. The aggregator in
    `identity_engine.identity_confidence_v1` treats None as "no signal".
    """
    pair = find_pair_for_agent(db, agent_id)
    if pair is None:
        return None

    rows = (
        db.query(CorroborationPoint)
        .filter(
            CorroborationPoint.mesh_pair_id == pair.id,
            CorroborationPoint.resolved_at.is_not(None),
        )
        .order_by(CorroborationPoint.resolved_at.desc())
        .limit(window)
        .all()
    )
    if not rows:
        return None
    verified_count = sum(1 for r in rows if bool(r.verified))
    return verified_count / len(rows)
