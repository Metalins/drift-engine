"""RKS — Re-Keyed Signature verifier (Sprint 7, paper §8.2 / R10-A).

Every `EventLog` row carries a signature produced at write-time by
`mcp_endpoints.log_event` with a *rotating* HMAC secret that depends on
the running history digest:

    new_digest      = SHA256(prior_digest_bytes || input_hash || output_hash)
    rotating_secret = HMAC(agent_secret, new_digest)
    sig             = HMAC(rotating_secret, f"{input_hash}|{output_hash}|{event_count}")

That signature is produced by the server itself today, so it's tautological
to verify the server's own output. The point of this module is to give us
the verifier that **a downstream consumer (or an audit) could use to detect
forks of the chain** — and, importantly, to gate the score so any chain
inconsistency lights up as a red flag.

Threat model defended (R10, AUC 1.0):
    "Secret-only attacker" — possesses `agent_secret` but lacks the shared
    history digest. They sign new events with their own (forked) digest,
    so when we replay the chain from the legitimate anchor we recompute
    a different `expected_digest` for the forked event, the rotating
    secret derived from it doesn't match, and `sig` fails verification.
    The failure also cascades: every event after the fork point fails
    because our reconstructed chain has diverged from the attacker's.

This module is pure functions over (events, secret, anchor). DB access is
limited to the `compute_rks` aggregator at the bottom.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import AgentState, EventLog


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# How many recent events the rolling window covers. Matches the order of
# magnitude of MVS / observable windows so the score reacts on the same
# time-scale as the rest of the engine.
DEFAULT_RKS_WINDOW = 200

# Threshold below which RKS triggers a customer-facing warning factor.
# Legitimate signature failure rate should be 0% — any non-trivial drop is
# a real signal. We pick 0.95 so transient single-event hiccups don't
# trip the warning, but a sustained fork does.
RKS_WARNING_THRESHOLD = 0.95


# --------------------------------------------------------------------------- #
# Pure crypto primitives                                                      #
# --------------------------------------------------------------------------- #

def initial_history_digest(agent_secret_hex: str) -> str:
    """Reconstruct the anchor digest that `mcp_endpoints.register_agent` /
    `agents.register_agent` write at registration time.

    This must match exactly:

        initial_digest = sha256(bytes.fromhex(agent_secret) + b"init").hex()

    If you change that init formula anywhere in the codebase, change it
    here too — the verifier needs to start from the same anchor.
    """
    return hashlib.sha256(
        bytes.fromhex(agent_secret_hex) + b"init"
    ).hexdigest()


def advance_digest(prior_digest_hex: str, input_hash: str, output_hash: str) -> str:
    """Reproduce one step of the digest chain.

    Mirrors `mcp_endpoints._do_log_event` exactly:

        h.update(bytes.fromhex(prior_digest))
        h.update(input_hash.encode())
        h.update(output_hash.encode())

    Returning hex for storage symmetry with `AgentState.history_digest`.
    """
    h = hashlib.sha256()
    h.update(bytes.fromhex(prior_digest_hex))
    h.update(input_hash.encode())
    h.update(output_hash.encode())
    return h.hexdigest()


def derive_rotating_secret(agent_secret_hex: str, current_digest_hex: str) -> bytes:
    """Derive the rotating per-event signing key from the current digest."""
    return hmac.new(
        bytes.fromhex(agent_secret_hex),
        bytes.fromhex(current_digest_hex),
        hashlib.sha256,
    ).digest()


def expected_signature(
    *,
    rotating_secret: bytes,
    input_hash: str,
    output_hash: str,
    event_count: int,
) -> str:
    """Reproduce the signature `log_event` would emit."""
    msg = f"{input_hash}|{output_hash}|{event_count}".encode()
    return hmac.new(rotating_secret, msg, hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- #
# Chain replay verifier                                                       #
# --------------------------------------------------------------------------- #

@dataclass
class VerifiedEvent:
    """Outcome of verifying one event in the replayed chain."""
    event_count: int
    digest_match: bool   # reconstructed digest matches stored history_digest
    signature_match: bool


@dataclass
class ChainVerification:
    """Outcome of replaying a window of events."""
    n_events: int
    n_signature_valid: int
    n_digest_valid: int
    first_failure_event_count: int | None  # earliest break, if any
    per_event: list[VerifiedEvent]

    @property
    def rks(self) -> float:
        """Re-Keyed Signature score in [0, 1]. 1.0 = perfect chain.

        We use signature validity as the score (not digest validity)
        because that's what R10 measures. Note that in practice the two
        almost always agree: digest match fails first, signature follows
        because the rotating secret derives from the digest.
        """
        if self.n_events == 0:
            return 1.0
        return self.n_signature_valid / self.n_events


def verify_event_chain(
    events: list[EventLog],
    agent_secret_hex: str,
    anchor_digest_hex: str,
) -> ChainVerification:
    """Replay a contiguous chain of events from `anchor_digest_hex`.

    `events` must be sorted ascending by `event_count` and start at the
    event whose prior digest is `anchor_digest_hex`. The caller is
    responsible for picking the right anchor — for window-based scoring
    where the window doesn't cover event #1, see `_pick_anchor` below.

    The verifier is strict: at the first digest mismatch we still keep
    going (replaying from our own reconstructed chain, NOT the attacker's
    forked one) so subsequent events also fail. This is the point — a
    fork at event N cascades.
    """
    per_event: list[VerifiedEvent] = []
    first_failure: int | None = None
    current_digest = anchor_digest_hex
    sig_valid = 0
    digest_valid = 0

    for ev in events:
        reconstructed = advance_digest(current_digest, ev.input_hash, ev.output_hash)
        digest_ok = hmac.compare_digest(reconstructed, ev.history_digest or "")

        rotating = derive_rotating_secret(agent_secret_hex, reconstructed)
        exp_sig = expected_signature(
            rotating_secret=rotating,
            input_hash=ev.input_hash,
            output_hash=ev.output_hash,
            event_count=ev.event_count,
        )
        sig_ok = hmac.compare_digest(exp_sig, ev.signature or "")

        per_event.append(VerifiedEvent(
            event_count=ev.event_count,
            digest_match=digest_ok,
            signature_match=sig_ok,
        ))
        if digest_ok:
            digest_valid += 1
        if sig_ok:
            sig_valid += 1
        if (not digest_ok or not sig_ok) and first_failure is None:
            first_failure = ev.event_count

        # Always advance with OUR reconstructed digest so a fork cascades.
        current_digest = reconstructed

    return ChainVerification(
        n_events=len(events),
        n_signature_valid=sig_valid,
        n_digest_valid=digest_valid,
        first_failure_event_count=first_failure,
        per_event=per_event,
    )


# --------------------------------------------------------------------------- #
# DB-aware aggregator                                                         #
# --------------------------------------------------------------------------- #

def _pick_anchor(
    db: Session,
    agent_id: str,
    agent_secret_hex: str,
    window_start_event_count: int,
) -> str | None:
    """Find the digest the chain had just BEFORE the window's first event.

    Two cases:
      - Window covers event #1 → anchor is the registration init digest.
      - Window starts at event N > 1 → anchor is the `history_digest`
        stored on event N-1 (we trust the stored chain up to the
        window boundary; the verifier scores ONLY events inside the
        window). This is the right trade-off for a rolling window:
        we're not re-verifying all of history every batch.

    Returns the hex digest, or None if the prior-event row is missing
    (shouldn't happen unless rows were deleted — caller can handle by
    falling back to an empty score).
    """
    if window_start_event_count <= 1:
        return initial_history_digest(agent_secret_hex)
    prior = (
        db.query(EventLog)
        .filter(
            EventLog.agent_id == agent_id,
            EventLog.event_count == window_start_event_count - 1,
        )
        .first()
    )
    return prior.history_digest if prior is not None else None


def compute_rks(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_RKS_WINDOW,
) -> float | None:
    """Replay the most recent `window` events for one agent and return RKS.

    Returns None when there are no events to verify (rather than 1.0) so
    the caller can distinguish "no data" from "perfect score". v1 of the
    confidence aggregator treats both the same, but downstream consumers
    (explain_score, dashboard) may want the distinction.
    """
    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if state is None or not state.agent_secret:
        return None

    events = (
        db.query(EventLog)
        .filter(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.desc())
        .limit(window)
        .all()
    )
    if not events:
        return None
    # We fetched desc to limit; verify in chronological order.
    events.sort(key=lambda e: e.event_count)

    anchor = _pick_anchor(
        db, agent_id, state.agent_secret,
        window_start_event_count=events[0].event_count,
    )
    if anchor is None:
        return None

    verification = verify_event_chain(events, state.agent_secret, anchor)
    return verification.rks
