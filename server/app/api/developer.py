"""Developer API — the public, API-key-authenticated surface.

Sprint UX-5.17.API1 (see docs/product/PUBLIC-API-DESIGN.md). This is the
plane that customers — developers running their own agents (Diana,
Carlos, n8n, custom runtimes) — call directly, and that the SDK wraps.

It is deliberately separate from:
  - the dashboard BFF endpoints (JWT/session auth, internal contract),
  - the MCP tool shim (`/v1/mcp/*`, a different integration for LLM
    clients),
  - the no-auth relying-party plane (`/v1/public/*`, `/v1/verify-proof`).

This module re-surfaces logic that already exists in the service layer;
it does not re-derive anything. Auth is API key only (`require_api_key`)
— a programmatic caller never has a browser session.

API1a scope: the action endpoints (register, log an event, answer a
verification check). The read endpoints (list / status) and the
dashboard namespace migration are API1b.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.agents import (
    get_agent,
    issue_proof,
    list_agents,
    register_agent,
    revoke_agent,
)
from app.api.mcp_endpoints import (
    _do_get_status,
    _do_log_event,
    _do_respond_probe,
)
from app.api.schemas import (
    IssueProofRequest,
    RegisterAgentRequest,
    RevokeAgentRequest,
)
from app.core.auth import AuthContext, require_api_key
from app.db import get_db
from app.db.models import AgentState, APIKey, Customer

router = APIRouter(prefix="/v1/agents", tags=["developer-api"])


# --------------------------------------------------------------------------- #
# Request bodies                                                              #
# --------------------------------------------------------------------------- #

class LogEventBody(BaseModel):
    """An interaction the agent wants on the record.

    The caller sends sha256 hex digests, never raw text — raw input and
    output never leave the customer's process.
    """

    input_hash: str
    output_hash: str
    metadata: dict | None = None


class IssueProofBody(BaseModel):
    """Optional knobs for an identity proof.

    `ttl_seconds` must be one of 300 / 3600 / 86400 — long-lived tokens
    are deliberately not allowed. `scope` is a short free-form string the
    relying party interprets; the server only embeds it.
    """

    ttl_seconds: int = 3600
    scope: str | None = None


class AnswerCheckBody(BaseModel):
    """The agent's response to a verification check.

    Either `answer` (the computed value) or `decline_reason` (when the
    agent recognizes a malformed check and refuses it) — not both.
    `progress` is the agent's own event count at answer time; optional.
    """

    answer: str | None = None
    decline_reason: str | None = None
    progress: int | None = None


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _clean_check(probe: dict) -> dict:
    """Map an internal pending-probe payload to the public check shape."""
    out = {
        "check_id": probe.get("probe_id"),
        "target_event_count": probe.get("target_event_count"),
        "nonce": probe.get("nonce"),
        "issued_at": probe.get("issued_at"),
        "expires_at": probe.get("expires_at"),
    }
    # Forwarded verbatim so a conforming client can spot a malformed
    # check and decline it.
    if probe.get("requires_secret_reveal"):
        out["requires_secret_reveal"] = probe["requires_secret_reveal"]
    return out


def _auth_ctx(api_key: APIKey, db: Session) -> AuthContext:
    """Build an AuthContext for an API-key caller so the developer API can
    reuse the customer-scoped query helpers the existing handlers expect.
    """
    customer = (
        db.query(Customer).filter(Customer.id == api_key.customer_id).first()
    )
    if customer is None:
        raise HTTPException(500, "API key references a missing customer")
    return AuthContext(
        auth_type="api_key",
        customer_id=api_key.customer_id,
        customer_email=customer.email,
        api_key=api_key,
    )


def _verification(trust: dict | None) -> dict:
    """Project the two-layer trust block down to the two public verdict
    words. The product does not have a single combined score — the two
    layers are reported independently and honestly."""
    trust = trust or {}
    crypto = trust.get("cryptographic") or {}
    behavioral = trust.get("behavioral") or {}
    return {
        "cryptographic": crypto.get("state"),
        "behavioral": behavioral.get("state"),
    }


def _attention(trust: dict | None) -> list[dict]:
    """Customer-facing items for anything that needs the owner's
    attention — the 'warning'-severity factors across both layers. Plain
    English; no internal mechanism names (D-PROD.18).

    gh-81 — each item is an object, not a bare string:
        {
          "message":    the one-line summary of what we observed,
          "code":       stable factor code (analytics / i18n),
          "learn_more": { "what", "self_resolving", "action" } | null
        }
    `learn_more` carries the 'what does this mean / is it a real problem /
    what do I do next' triplet so an integrator polling the API gets the
    same context the dashboard shows, instead of a lone sentence. It is
    null for the rare warning factor with no curated guidance.
    """
    trust = trust or {}
    items: list[dict] = []
    for layer in ("cryptographic", "behavioral"):
        for factor in (trust.get(layer) or {}).get("factors") or []:
            if factor.get("severity") == "warning" and factor.get("message"):
                items.append({
                    "message": factor["message"],
                    "code": factor.get("code"),
                    "learn_more": factor.get("learn_more"),
                })
    return items


def _lean_tier(obj: dict) -> str | None:
    """The short tier label ('T3') from the fat tier object, or None."""
    return (obj.get("tier") or {}).get("tier")


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #

@router.post("", status_code=201)
def create_agent(
    req: RegisterAgentRequest,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Register a new agent.

    Returns the `agent_id` and, **once**, the `agent_secret` — the secret
    the agent uses to answer verification checks. The caller must store
    it; it is never returned again.

    Wraps the existing registration logic and additionally returns the
    secret. gh-88 — memory probes (the round-trip half) are OFF by default;
    registration no longer auto-enables them (see below).
    """
    # gh-88 — memory probes are OFF by default. We no longer auto-stamp
    # `probe_client` at registration. Hash-based probes only make sense for
    # deterministic agents; for stochastic LLMs they always fail and produce a
    # permanent false `probes_failing` alarm. Opt-in is explicit now: the agent
    # owner enables "Memory probes" in the dashboard Settings (deterministic
    # agents only), or passes `metadata.probe_client = true` at registration.
    # A caller that already set the flag is honored as-is.
    res = register_agent(req, auth=_auth_ctx(api_key, db), db=db)

    state = (
        db.query(AgentState)
        .filter(AgentState.agent_id == res.agent_id)
        .first()
    )
    if state is None:
        raise HTTPException(500, "Agent state was not initialized")

    return {
        "agent_id": res.agent_id,
        "agent_secret": state.agent_secret,
        "created_at": (
            res.created_at.isoformat() + "Z" if res.created_at else None
        ),
        "secret_warning": (
            "Store agent_secret now — it is shown only once and is "
            "required for the agent to answer verification checks."
        ),
    }


@router.post("/{agent_id}/events")
def log_event(
    agent_id: str,
    body: LogEventBody,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Record one interaction for an agent.

    Returns the running `event_count` and `pending_checks` — any
    verification checks the server wants the agent to answer (via
    POST /v1/agents/{id}/checks/{check_id}).
    """
    result = _do_log_event(
        {
            "agent_id": agent_id,
            "input_hash": body.input_hash,
            "output_hash": body.output_hash,
            "metadata": body.metadata or {},
        },
        api_key,
        db,
    )
    return {
        "agent_id": result["agent_id"],
        "event_count": result["event_count"],
        "pending_checks": [
            _clean_check(p) for p in (result.get("pending_probes") or [])
        ],
    }


@router.post("/{agent_id}/checks/{check_id}")
def answer_check(
    agent_id: str,
    check_id: str,
    body: AnswerCheckBody,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Answer a verification check the server issued for this agent.

    Send `answer` for a well-formed check, or `decline_reason` when the
    agent recognizes the check is malformed and refuses to answer it.
    """
    if not body.answer and not body.decline_reason:
        raise HTTPException(
            400, "Provide either 'answer' or 'decline_reason'."
        )
    args: dict = {"agent_id": agent_id, "probe_id": check_id}
    if body.answer:
        args["agent_proof"] = body.answer
    if body.decline_reason:
        args["refusal_reason"] = body.decline_reason
    if body.progress is not None:
        args["response_counter"] = body.progress

    result = _do_respond_probe(args, api_key, db)
    return {
        "check_id": result.get("probe_id", check_id),
        "accepted": result.get("valid"),
        "detail": result.get("reason"),
    }


@router.get("/{agent_id}/checks")
def list_checks_endpoint(
    agent_id: str,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """List the verification checks currently awaiting this agent's answer.

    `log_event` returns `pending_checks` riding on its response, but an
    agent that goes quiet would never see — and so never answer — a
    check issued in the meantime. This endpoint lets a client poll for
    pending checks on its own cadence, independent of event logging, so
    they get answered before they expire. Same check shape as
    `log_event`'s `pending_checks`. Empty list when there is nothing to
    answer.
    """
    status = _do_get_status({"agent_id": agent_id}, api_key, db)
    canonical_id = status.get("agent_id", agent_id)

    # gh-88 — polling no longer auto-stamps `probe_client`. Memory probes are
    # opt-in (off by default): the agent owner enables them in dashboard
    # Settings (deterministic agents only). When probes are disabled the server
    # issues no checks, so this poll simply returns an empty list — harmless for
    # the SDK's background CheckWorker. Previously a poll flipped the flag on,
    # which silently opted stochastic LLM agents into a check they could never
    # answer (the dogfood-v2 false-positive root cause).
    return {
        "agent_id": canonical_id,
        "checks": [
            _clean_check(p) for p in (status.get("pending_probes") or [])
        ],
    }


@router.get("")
def list_agents_endpoint(
    limit: int = 50,
    offset: int = 0,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """List the agents owned by the calling account.

    A lean, stable summary per agent — the verification verdict, the
    tier and recent activity. Deliberately NOT the dashboard's internal
    payload.
    """
    fat = list_agents(
        limit=limit, offset=offset, include_revoked=False,
        auth=_auth_ctx(api_key, db), db=db,
    )
    agents = []
    for a in fat.get("agents", []):
        trust = a.get("trust")
        agents.append({
            "agent_id": a.get("agent_id"),
            "name": a.get("name"),
            "event_count": a.get("event_count"),
            "last_active": a.get("last_event_at"),
            "tier": _lean_tier(a),
            "verification": _verification(trust),
            "needs_attention": len(_attention(trust)) > 0,
        })
    return {"agents": agents, "count": len(agents)}


@router.get("/{agent_id}")
def get_agent_endpoint(
    agent_id: str,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Read one agent's verification status — the lean, stable contract.

    The product reports two independent layers (a cryptographic verdict
    and a behavioral one); there is no single combined score. `attention`
    carries plain-English messages for anything the owner should look at.
    """
    detail = get_agent(agent_id, auth=_auth_ctx(api_key, db), db=db)
    trust = detail.get("trust")
    return {
        "agent_id": detail.get("agent_id"),
        "name": detail.get("name"),
        "created_at": detail.get("created_at"),
        "event_count": detail.get("event_count"),
        "last_active": detail.get("last_event_at"),
        "tier": _lean_tier(detail),
        "verification": _verification(trust),
        "attention": _attention(trust),
    }


@router.post("/{agent_id}/proofs", status_code=201)
def issue_proof_endpoint(
    agent_id: str,
    body: IssueProofBody,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Issue a signed identity proof for an agent (agent-to-agent).

    The proof is a signed token the agent can hand to another party,
    who checks it with the public `POST /v1/verify-proof` endpoint (or
    resolves the short `proof_id` via `/v1/public/proofs/{proof_id}`).
    """
    result = issue_proof(
        agent_id,
        IssueProofRequest(ttl_seconds=body.ttl_seconds, scope=body.scope),
        auth=_auth_ctx(api_key, db),
        db=db,
    )
    return {
        "proof_id": result.proof_id,
        "agent_id": result.agent_id,
        "proof": result.kappa_proof,
        "issued_at": result.issued_at,
        "expires_at": result.expires_at,
        "scope": result.scope,
    }


@router.delete("/{agent_id}")
def revoke_agent_endpoint(
    agent_id: str,
    reason: str | None = None,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Revoke an agent. Permanent: the agent and its data are removed,
    and any proof it issued resolves as no-longer-active. Pass an
    optional `?reason=` for the audit record."""
    result = revoke_agent(
        RevokeAgentRequest(agent_id=agent_id, reason=reason),
        auth=_auth_ctx(api_key, db),
        db=db,
    )
    return {"agent_id": result.agent_id, "revoked_at": result.revoked_at}
