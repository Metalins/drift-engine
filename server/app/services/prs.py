"""PRS — Predictive Reliability Score (Sprint 7, paper §8.1 / R10-D).

The agent pre-commits to a distribution over its OWN next response
K events in the future. When the target event lands, the server
verifies whether the realized response bucket falls inside the top-K of
the predicted distribution.

A legitimate agent — that has access to its own internal state machine
(HMM transition + emission matrices in the synthetic case; the actual
LLM internals for a real Metalins customer) — produces calibrated
predictions and lands inside top-K most of the time.

An informed passive attacker — observed traces, has the agent secret,
but lacks the agent's internal model — can only predict from observed
marginals. With a 32-bucket alphabet and a top-3 hit criterion, random
guessing scores ~3/32 ≈ 9%. Calibrated agents land in the 50-80% range.

Threat model defended (R10, AUC 0.8875):
    "Informed passive attacker" — knows past I/O, has stolen secret,
    but doesn't have the internal model the agent used to generate
    them.

Reality check for Metalins V1:
    Only meaningful for MCP-integrated agents (the SDK exposes
    `predict_response`). Watcher-only agents have no surface to submit
    predictions, so PRS is silently skipped — None propagates through.

This module is pure scoring + a DB-aware resolver and aggregator.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import EventLog, PredictionSubmission


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# K events in the future. Matches `protocols_r10.K_offset = 5`.
PRS_K_OFFSET = 5

# Top-N hit threshold for scoring. With alphabet=32 a random guesser
# hits top-3 ~9% of the time; calibrated agents hit ~50-80%.
PRS_TOP_K = 3

# Customer-facing warning surfaces below this. PRS is the only mechanism
# with a low natural baseline (0.5-ish for honest LLM agents because LLMs
# aren't perfectly self-predicting), so we lower the bar vs RKS / MVS.
PRS_WARNING_THRESHOLD = 0.4

# How many recent resolved predictions the aggregator looks at.
DEFAULT_PRS_WINDOW = 50

# Distribution length must equal DEFAULT_ALPHABET in identity_engine.
# Hard-coded here too so this module stays a pure scorer with no import
# of the engine.
DISTRIBUTION_LENGTH = 32

# Numerical tolerance for distribution-sums-to-1.0 check.
SUM_TOLERANCE = 0.05


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class PredictionValidationError(Exception):
    """Raised by submit_prediction when the payload is malformed."""
    reason: str

    def __str__(self) -> str:  # pragma: no cover
        return self.reason


def validate_distribution(dist: Sequence[float]) -> None:
    """Reject malformed predictions early. Defensive — bad inputs are a
    client bug we want to surface, not a silent zero score.
    """
    if not isinstance(dist, (list, tuple)):
        raise PredictionValidationError(
            f"distribution must be a list of floats, got {type(dist).__name__}"
        )
    if len(dist) != DISTRIBUTION_LENGTH:
        raise PredictionValidationError(
            f"distribution length must be {DISTRIBUTION_LENGTH}, got {len(dist)}"
        )
    if any((not isinstance(x, (int, float))) or x < 0 for x in dist):
        raise PredictionValidationError(
            "distribution entries must be non-negative numbers"
        )
    total = sum(dist)
    if total <= 0:
        raise PredictionValidationError(
            "distribution must sum to a positive value (got 0)"
        )
    if abs(total - 1.0) > SUM_TOLERANCE:
        raise PredictionValidationError(
            f"distribution must sum to ~1.0 (got {total:.3f}); "
            "we accept ±0.05 to tolerate floating-point drift but anything "
            "further is a normalization bug"
        )


# --------------------------------------------------------------------------- #
# Pure scoring                                                                #
# --------------------------------------------------------------------------- #

def score_prediction(
    predicted_distribution: Sequence[float],
    realized_bucket: int,
    top_k: int = PRS_TOP_K,
) -> float:
    """1.0 if `realized_bucket` is in the top-`top_k` of the predicted
    distribution, else 0.0.

    Why hit/miss instead of log-likelihood? Three reasons:
      1. Replicates the research's tolerance check
         (`protocols_r10.run_predictive_trace` uses `predicted == actual`).
      2. Hard to game: log-likelihood lets an attacker concentrate mass
         on one bucket and dodge detection by occasionally hitting it.
      3. Easy to explain customer-facing.
    """
    if not predicted_distribution:
        return 0.0
    indexed = sorted(
        range(len(predicted_distribution)),
        key=lambda i: -predicted_distribution[i],
    )
    return 1.0 if realized_bucket in indexed[:top_k] else 0.0


# --------------------------------------------------------------------------- #
# Submission                                                                  #
# --------------------------------------------------------------------------- #

def submit_prediction(
    db: Session,
    agent_id: str,
    submitted_at_event_count: int,
    predicted_distribution: Sequence[float],
    k_offset: int = PRS_K_OFFSET,
) -> PredictionSubmission:
    """Persist a fresh prediction. Caller is responsible for ensuring
    `agent_id` belongs to the calling customer.

    Raises `PredictionValidationError` on malformed input.
    """
    validate_distribution(predicted_distribution)
    target = submitted_at_event_count + k_offset
    sub = PredictionSubmission(
        id=new_id("prd"),
        agent_id=agent_id,
        submitted_at_event_count=submitted_at_event_count,
        target_event_count=target,
        predicted_distribution=list(predicted_distribution),
        submitted_at=datetime.utcnow(),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


# --------------------------------------------------------------------------- #
# Resolution                                                                  #
# --------------------------------------------------------------------------- #

def _hash_to_bucket(hex_hash: str, modulus: int = DISTRIBUTION_LENGTH) -> int:
    """Same projection as `identity_engine._hash_to_symbol`. Duplicated
    here to keep the modules decoupled; if we ever change the bucket
    projection we must change both — but they should always agree."""
    import hashlib
    h = (hex_hash or "").strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    try:
        n = int(h[:8], 16)
    except ValueError:
        n = int(hashlib.sha256(h.encode("utf-8")).hexdigest()[:8], 16)
    return n % modulus


def resolve_pending_predictions(db: Session, agent_id: str) -> int:
    """For every unresolved submission whose target_event_count has
    arrived, look up the realized response bucket and score the
    submission. Returns the number of newly resolved rows.

    Idempotent — already-resolved submissions are skipped.
    """
    pending = (
        db.query(PredictionSubmission)
        .filter(
            PredictionSubmission.agent_id == agent_id,
            PredictionSubmission.resolved_at.is_(None),
        )
        .all()
    )
    if not pending:
        return 0

    # Bulk-fetch all relevant events. We pull every event with
    # event_count IN the target set rather than N queries.
    target_counts = [p.target_event_count for p in pending]
    events = {
        e.event_count: e
        for e in db.query(EventLog)
        .filter(
            EventLog.agent_id == agent_id,
            EventLog.event_count.in_(target_counts),
        )
        .all()
    }

    now = datetime.utcnow()
    n_resolved = 0
    for sub in pending:
        ev = events.get(sub.target_event_count)
        if ev is None:
            continue  # target hasn't happened yet
        realized = _hash_to_bucket(ev.output_hash)
        sub.realized_response_bucket = realized
        sub.score = score_prediction(sub.predicted_distribution, realized)
        sub.resolved_at = now
        n_resolved += 1
    if n_resolved:
        db.commit()
    return n_resolved


# --------------------------------------------------------------------------- #
# DB-aware aggregator                                                         #
# --------------------------------------------------------------------------- #

def compute_prs(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_PRS_WINDOW,
) -> Optional[float]:
    """Average score over the most recent `window` resolved submissions.

    Returns None when there are no resolved submissions yet (typical
    until at least K_OFFSET events have flowed after the first submit).
    The aggregator in `identity_engine.identity_confidence_v1` treats
    None as "no signal" — confidence isn't capped.
    """
    rows = (
        db.query(PredictionSubmission)
        .filter(
            PredictionSubmission.agent_id == agent_id,
            PredictionSubmission.resolved_at.is_not(None),
            PredictionSubmission.score.is_not(None),
        )
        .order_by(PredictionSubmission.resolved_at.desc())
        .limit(window)
        .all()
    )
    if not rows:
        return None
    return sum(float(r.score or 0.0) for r in rows) / len(rows)
