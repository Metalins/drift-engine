"""ZKH — Zero-Knowledge History (Sprint 7, paper §8.5 / R12).

Merkle commit-reveal variant. The agent commits to a Merkle root over
its full local history-digest chain BEFORE the server picks the
challenge index. After commit, the server samples a random t_star and
asks the agent to open the path at that leaf.

Verification: the path must (a) lead from the agent's claimed digest at
t_star to the committed root, AND (b) the claimed digest must match the
server's own stored history_digest at that event_count.

Honest V1 framing (audit §7): in our threat model the I/O hashes are
persisted server-side and the digest chain is fully reconstructible from
them, so ZKH coverage overlaps with MVS. The commit-before-challenge
shape adds: (i) the agent must show it has a coherent local tree before
being challenged, and (ii) lying about the commit root is rejected
immediately, before any proof is granted. Useful but not strictly
adding new threat coverage in V1.

Pure functions live in this module; DB integration via the issuer /
verifier / aggregator at the bottom.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import AgentState, EventLog, ZKHProof


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# Window for the rolling MCS-style aggregator.
DEFAULT_ZKH_WINDOW = 20

# Threshold for the warning factor. Like RKS, a legitimate agent should
# basically always pass — non-trivial failures are a smoking gun.
ZKH_WARNING_THRESHOLD = 0.9

# How long the agent has to submit the path after receiving the
# challenge. 5 minutes is generous for a real agent (HMAC + tree walk)
# and tight enough that issued-but-unanswered challenges expire fast.
ZKH_CHALLENGE_TTL = timedelta(minutes=5)


# --------------------------------------------------------------------------- #
# Pure Merkle primitives                                                      #
# --------------------------------------------------------------------------- #

def _node_hash(left: bytes, right: bytes) -> bytes:
    """Standard binary Merkle internal-node hash. SHA256 over the raw
    concatenation of two children. Same as Bitcoin / RFC 6962-ish but
    without the leaf/node domain separation tag — we don't need
    second-preimage hardening for V1.
    """
    return hashlib.sha256(left + right).digest()


def merkle_root(leaves_hex: Sequence[str]) -> str:
    """Compute the Merkle root over an ordered list of hex-encoded leaves.

    For empty input we return the SHA256 of the empty string (a
    well-defined sentinel — collides with no real digest because real
    history starts from sha256(secret + b"init") which is never the
    sha256 of empty bytes).

    Odd-length levels duplicate the last node, matching Bitcoin
    convention. Documented here so the agent side knows what to do.
    """
    if not leaves_hex:
        return hashlib.sha256(b"").hexdigest()
    level = [bytes.fromhex(leaf) for leaf in leaves_hex]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0].hex()


def merkle_path(leaves_hex: Sequence[str], idx: int) -> list[dict]:
    """Compute the Merkle path from leaf `idx` (0-indexed) up to the
    root. Returns a list of `{"sibling": "<hex>", "side": "L"|"R"}`
    entries, ordered leaf-to-root.

    "side" = "L" means the sibling is on the LEFT of the current node;
    "R" means right. Useful for the verifier to know which way to
    concatenate.

    Same odd-level duplication as `merkle_root`.
    """
    if idx < 0 or idx >= len(leaves_hex):
        raise IndexError(f"idx {idx} out of range for {len(leaves_hex)} leaves")
    path: list[dict] = []
    level = [bytes.fromhex(leaf) for leaf in leaves_hex]
    current = idx
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        sibling_idx = current ^ 1  # XOR 1 toggles the lowest bit
        sibling = level[sibling_idx]
        side = "L" if sibling_idx < current else "R"
        path.append({"sibling": sibling.hex(), "side": side})
        # Promote to next level.
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        current = current // 2
    return path


def verify_merkle_path(
    leaf_hex: str,
    path: Sequence[dict],
    expected_root_hex: str,
) -> bool:
    """Walk up the path; assert the resulting root matches."""
    current = bytes.fromhex(leaf_hex)
    for entry in path:
        try:
            sibling = bytes.fromhex(entry["sibling"])
            side = entry["side"]
        except (KeyError, TypeError, ValueError):
            return False
        if side == "L":
            current = _node_hash(sibling, current)
        elif side == "R":
            current = _node_hash(current, sibling)
        else:
            return False
    return hmac.compare_digest(current.hex(), expected_root_hex)


# --------------------------------------------------------------------------- #
# Server-side root reconstruction                                             #
# --------------------------------------------------------------------------- #

def server_compute_merkle_root(db: Session, agent_id: str) -> tuple[str, int]:
    """Recompute the Merkle root from the server's EventLog rows.

    Returns (root_hex, n_events). Used to validate the agent's commit
    at challenge issuance.

    Note: for an agent with millions of events this becomes expensive.
    For V1 we accept the O(N) cost — once we hit a customer with that
    volume we'll cache the root in `agent_states.history_merkle_root`
    and only recompute the new leaves.
    """
    rows = (
        db.query(EventLog.history_digest)
        .filter(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.asc())
        .all()
    )
    leaves = [r[0] for r in rows if r[0]]
    return merkle_root(leaves), len(leaves)


def server_get_digest_at(
    db: Session,
    agent_id: str,
    event_count: int,
) -> Optional[str]:
    """Look up `history_digest` at a specific event_count."""
    row = (
        db.query(EventLog.history_digest)
        .filter(
            EventLog.agent_id == agent_id,
            EventLog.event_count == event_count,
        )
        .first()
    )
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# Challenge / response flow                                                   #
# --------------------------------------------------------------------------- #

@dataclass
class ZKHChallengeError(Exception):
    reason: str

    def __str__(self) -> str:  # pragma: no cover
        return self.reason


def issue_zkh_challenge(
    db: Session,
    agent_id: str,
    agent_commit_root_hex: str,
) -> ZKHProof:
    """Validate the agent's commit and persist a challenge row.

    Raises `ZKHChallengeError` if the agent has too few events to
    challenge, or if the commit root doesn't match what the server
    computes from its own EventLog rows.
    """
    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if state is None or (state.event_count or 0) < 1:
        raise ZKHChallengeError("agent has no events to challenge")

    server_root, n_events = server_compute_merkle_root(db, agent_id)
    if not hmac.compare_digest(
        server_root.lower(), (agent_commit_root_hex or "").strip().lower(),
    ):
        raise ZKHChallengeError(
            "commit root does not match the server's view of the chain"
        )

    # Pick a random 1-indexed event_count in [1, n_events].
    t_star = secrets.randbelow(n_events) + 1
    nonce = secrets.token_hex(16)

    proof = ZKHProof(
        id=new_id("zkh"),
        agent_id=agent_id,
        commit_root=server_root,
        server_root_at_issue=server_root,
        t_star=t_star,
        nonce=nonce,
    )
    db.add(proof)
    db.commit()
    db.refresh(proof)
    return proof


def verify_zkh_response(
    db: Session,
    proof_id: str,
    claimed_digest_hex: str,
    path: Sequence[dict],
    agent_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Verify the agent's path response. Mutates the row and returns
    (verified, reason).

    Verification is strict: BOTH (a) the path walks from claimed_digest
    up to the committed root AND (b) the claimed digest matches the
    server's stored history_digest at t_star. Either failure marks
    verified=False.
    """
    proof = db.query(ZKHProof).filter(ZKHProof.id == proof_id).first()
    if proof is None:
        return False, "zkh_not_found"
    if agent_id is not None and proof.agent_id != agent_id:
        return False, "zkh_agent_mismatch"
    if proof.resolved_at is not None:
        return False, f"zkh_already_{'verified' if proof.verified else 'rejected'}"
    if proof.issued_at and (
        datetime.utcnow() - proof.issued_at > ZKH_CHALLENGE_TTL
    ):
        proof.verified = False
        proof.rejection_reason = "expired"
        proof.resolved_at = datetime.utcnow()
        db.commit()
        return False, "zkh_expired"

    # Step 1: path → committed root.
    path_ok = verify_merkle_path(
        (claimed_digest_hex or "").strip().lower(),
        path,
        proof.commit_root,
    )

    # Step 2: claimed digest matches server's stored value at t_star.
    server_digest = server_get_digest_at(db, proof.agent_id, proof.t_star)
    digest_ok = bool(
        server_digest and hmac.compare_digest(
            server_digest.lower(),
            (claimed_digest_hex or "").strip().lower(),
        )
    )

    proof.claimed_digest = (claimed_digest_hex or "").strip().lower()
    proof.merkle_path = list(path) if path else []
    proof.submitted_at = datetime.utcnow()
    proof.resolved_at = datetime.utcnow()
    proof.verified = bool(path_ok and digest_ok)
    if not proof.verified:
        if not path_ok and not digest_ok:
            proof.rejection_reason = "path_invalid_and_digest_mismatch"
        elif not path_ok:
            proof.rejection_reason = "path_invalid"
        else:
            proof.rejection_reason = "digest_mismatch"
    db.commit()
    return proof.verified, "ok" if proof.verified else (proof.rejection_reason or "fail")


# --------------------------------------------------------------------------- #
# Aggregator                                                                  #
# --------------------------------------------------------------------------- #

def compute_zkh(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_ZKH_WINDOW,
) -> Optional[float]:
    """Fraction of recent resolved ZKH proofs that verified.

    Returns None when there are no resolved proofs yet — propagates as
    "no signal" in the identity_confidence aggregator.
    """
    rows = (
        db.query(ZKHProof)
        .filter(
            ZKHProof.agent_id == agent_id,
            ZKHProof.resolved_at.is_not(None),
        )
        .order_by(ZKHProof.resolved_at.desc())
        .limit(window)
        .all()
    )
    if not rows:
        return None
    verified = sum(1 for r in rows if bool(r.verified))
    return verified / len(rows)
