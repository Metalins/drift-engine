"""ADV — Adversarial Probe Detection (Sprint 7, paper §8.6 / R12).

A fraction (~5–10%) of probes the server emits are *deliberately
malformed*. A legitimate AIP-conformant agent inspects the probe before
computing its proof, detects the violation, and calls `respond_probe`
with a `refusal_reason` instead of a proof. A naive attacker — one that
doesn't implement the protocol's structural checks — answers anyway.

Score: ADV = (# correctly refused) / (# malformed probes the agent
actually responded to). Probes the agent did NOT respond to — whether
still pending OR expired unanswered — do not count toward either the
numerator or the denominator. An agent that is simply offline must not
be scored as if it had *accepted* the malformed probes (UX-5.15.AK).

Threat model defended (R12, AUC 1.0):
    "Naive attacker" — has stolen credentials, can compute hashes, but
    doesn't know that some probe shapes are illegal. Responds to every
    probe → ADV drops sharply.

Malformation kinds we inject (V1):
    short_nonce: nonce truncated to 8 hex chars (legit nonce is 32+).
    event_count_out_of_range: target_event_count >= 1e9 (no agent has
        seen 1 billion events yet — clearly impossible).
    unknown_required_field: extra field {requires_secret_reveal: true}
        in the payload; the spec mandates refusing unknown REQUIRED keys.

Implementation note: the expected_proof on the probe row is computed
over the canonical (un-malformed) data, so the server never accepts a
proof for a malformed probe even if the attacker manages to produce one.
Malformation is purely a behavioural test of the agent's input
validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import MemoryProbe


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #

# Paper says 5–10%. Pick 7% as the centre of the band — high enough that
# even a small probe history produces a statistically meaningful ADV
# signal, low enough that legitimate agents aren't drowned in refusals.
ADV_MALFORMED_PROBABILITY = 0.07

# Score threshold below which a customer-facing warning surfaces.
ADV_WARNING_THRESHOLD = 0.7

# How many recent responded probes to consider when aggregating ADV.
# Mirrors the MVS / TLS window so the three move on the same time-scale.
DEFAULT_ADV_WINDOW = 50

# Recognised malformation tags. Used both server-side (when injecting)
# and conceptually on the agent side (what the agent should detect).
MALFORMATION_KINDS = (
    "short_nonce",
    "event_count_out_of_range",
    "unknown_required_field",
)


@dataclass
class MalformationPlan:
    """Describes a planned malformation applied to a probe payload.

    `kind` is one of MALFORMATION_KINDS. The fields of the probe are
    mutated in-place by `apply_malformation_to_probe` according to kind.
    """
    kind: str


# --------------------------------------------------------------------------- #
# Pure malformation primitives                                                #
# --------------------------------------------------------------------------- #

def choose_malformation(rng) -> Optional[MalformationPlan]:
    """With probability ADV_MALFORMED_PROBABILITY, return a malformation
    plan; otherwise return None.

    `rng` is anything implementing `.random()` (float in [0, 1)) and
    `.choice(seq)`. We accept it as a parameter so the issuer is the one
    in charge of seeding — tests use a deterministic RNG.
    """
    if rng.random() >= ADV_MALFORMED_PROBABILITY:
        return None
    kind = rng.choice(list(MALFORMATION_KINDS))
    return MalformationPlan(kind=kind)


def apply_malformation_to_probe(
    probe: MemoryProbe,
    plan: MalformationPlan,
) -> None:
    """Mutate the persisted probe row according to the plan.

    IMPORTANT: this is called AFTER `expected_proof` has been computed
    over the canonical data, so we never accept a forged proof for a
    malformed probe. The mutation only affects what the agent sees.

    Sets `is_malformed=True` so the verifier knows to score this row
    against ADV.
    """
    probe.is_malformed = True
    if plan.kind == "short_nonce":
        # Truncate to 8 hex chars; legit nonces are 32+.
        probe.nonce = probe.nonce[:8]
    elif plan.kind == "event_count_out_of_range":
        # Push target_event_count above any plausible real value. No
        # agent has logged 1 billion events.
        probe.target_event_count = 1_000_000_000 + (probe.target_event_count or 0)
    elif plan.kind == "unknown_required_field":
        # No actual schema change — the SDK is the one expected to see
        # the unknown field in the public payload and refuse. The server
        # only needs to remember that THIS probe was payload-decorated
        # so the public_payload() function below tacks the field on.
        # We mark intent via the refusal_reason staging slot. Yes, this
        # field is also used in the response payload — keep the value
        # something that won't be confused with a refusal reason from
        # the agent: the string "_injected:unknown_required_field".
        probe.refusal_reason = "_injected:unknown_required_field"
    # else: unknown kind → no-op (defensive).


def public_payload_for_probe(probe: MemoryProbe) -> dict:
    """Build the dict the agent sees when it calls list_pending_probes.

    For non-malformed probes this is just the standard payload. For
    malformed probes we add the malformation visibly so the agent can
    detect it.

    Mirrors `memory_verifier.list_pending_probes` shape (probe_id,
    target_event_count, nonce, issued_at, expires_at) but extended.
    """
    payload: dict = {
        "probe_id": probe.id,
        "target_event_count": probe.target_event_count,
        "nonce": probe.nonce,
        "issued_at": probe.issued_at.isoformat() if probe.issued_at else None,
        "expires_at": probe.expires_at.isoformat() if probe.expires_at else None,
    }
    if probe.is_malformed and probe.refusal_reason == "_injected:unknown_required_field":
        # Inject the unknown REQUIRED field. AIP-conformant agents
        # detect "I don't know this field" and refuse.
        payload["requires_secret_reveal"] = True
    return payload


# --------------------------------------------------------------------------- #
# DB-aware aggregator                                                         #
# --------------------------------------------------------------------------- #

def compute_adv(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_ADV_WINDOW,
) -> Optional[float]:
    """Score ADV over the most recent `window` malformed probes the agent
    ACTUALLY RESPONDED TO.

    Sprint UX-5.15.AK: expired probes (issued, never answered) are NOT
    counted. An offline agent that lets malformed probes expire was being
    scored ADV=0 — a false `protocol_unaware` accusation that it had
    "accepted" the malformed probes. Expiry is an operational signal (the
    MVS `probes_unanswered` story — see memory_verifier.MVSBreakdown), not
    an ADV failure. ADV only judges probes the agent engaged with.

    Returns None when there are no responded malformed probes yet (typical
    for brand-new agents — at 7% rate it takes a while to accumulate
    enough samples, and an offline agent never accumulates any). The
    aggregator in `identity_engine.identity_confidence_v1` treats None as
    "no signal".
    """
    probes = (
        db.query(MemoryProbe)
        .filter(
            MemoryProbe.agent_id == agent_id,
            MemoryProbe.is_malformed.is_(True),
            MemoryProbe.status == "responded",
        )
        .order_by(MemoryProbe.issued_at.desc())
        .limit(window)
        .all()
    )
    if not probes:
        return None

    refused_correctly = 0
    total = 0
    for p in probes:
        total += 1
        reason = (p.refusal_reason or "").strip()
        # Ignore server-injected sentinel; only customer-supplied tags count.
        if reason and not reason.startswith("_injected:"):
            refused_correctly += 1

    if total == 0:
        return None
    return refused_correctly / total
