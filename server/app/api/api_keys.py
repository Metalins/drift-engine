"""API keys management endpoints.

Per Sprint 3a-auth spec (Jose's feedback):
  - Keys are scoped to an agent (one agent can have multiple active keys).
  - The dashboard never sees the raw key after creation — only metadata.
  - Customer can revoke any of its keys.

Endpoints:
  GET    /v1/agents/{agent_id}/api-keys    — list metadata (no secrets)
  POST   /v1/agents/{agent_id}/api-keys    — create new key, return raw once
  POST   /v1/api-keys/{key_id}/revoke      — revoke a key
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, require_auth
from app.core.ids import new_id
from app.db import get_db
from app.db.models import APIKey, Agent


router = APIRouter(prefix="/v1", tags=["api-keys"])


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _generate_key() -> str:
    """`ml_live_<43 url-safe chars>` — ~256 bits of entropy."""
    return f"ml_live_{secrets.token_urlsafe(32)}"


def _ensure_agent_owned(agent_id: str, auth: AuthContext, db: Session) -> Agent:
    """Return the agent if the caller's customer owns it (via api_keys.customer_id)."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    # The agent's owning key must belong to this customer. We don't look at
    # auth.api_key.id here — instead we look at the agent's api_key's
    # customer_id — so a customer-wide JWT call sees all the customer's agents.
    creator_key = (
        db.query(APIKey).filter(APIKey.id == agent.api_key_id).first()
    )
    if not creator_key or creator_key.customer_id != auth.customer_id:
        raise HTTPException(404, "Agent not found")
    return agent


def _iso_utc(dt) -> str | None:
    """Serialize a naive UTC datetime as a real UTC ISO string.

    Bug-andrea-1 (Andrea Round 0 v2): `datetime.utcnow()` returns a naive
    datetime. `.isoformat()` on a naive datetime produces a string with
    no timezone suffix (e.g. "2026-05-17T22:00:00.123456"). JavaScript's
    `new Date()` parses such strings as LOCAL time, which then caused
    "created -10800s ago" rendering for users east/west of UTC.

    Fix: always emit with `Z` so downstream parsers know the canonical
    semantics. Cheap, surgical, idempotent (won't double-suffix if the
    string already carries `Z` or a +HH:MM / -HH:MM offset).
    """
    if dt is None:
        return None
    s = dt.isoformat()
    if s.endswith("Z"):
        return s
    # Detect a trailing `+HH:MM` or `-HH:MM` offset (aware datetime path).
    if len(s) >= 6 and s[-6] in "+-" and s[-3] == ":":
        return s
    return s + "Z"


def _key_summary(k: APIKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "description": k.description,
        "agent_id": k.agent_id,
        "is_active": k.is_active,
        "created_at": _iso_utc(k.created_at),
        "last_used_at": _iso_utc(k.last_used_at),
        "revoked_at": _iso_utc(k.revoked_at),
        # Never include key_hash or raw key.
    }


def _key_summary_with_scope(k: APIKey, agent_name: str | None = None) -> dict:
    """Same as _key_summary but adds explicit `scope` + optional `agent_name`.

    Sprint UX-5.11 / bug-andrea-3 (2026-05-17): Andrea v2.1 minted an
    `andrea-laptop` key from the agent-keys page, traffic flowed through
    it, but the /agents/[id]/keys page showed "0 keys". Root cause: the
    create flow defaults `scope_to_agent=False` (Sprint 6) so the new key
    is customer-wide (agent_id=NULL), but `list_agent_keys` filters by
    `agent_id == X` and never returns customer-wide keys. The new
    customer-level endpoints below let the dashboard surface both kinds
    of keys in one place and tag each with its scope so the user is
    never lied to about whether their key exists.
    """
    base = _key_summary(k)
    base["scope"] = "agent-scoped" if k.agent_id else "customer-wide"
    base["agent_name"] = agent_name
    return base


# --------------------------------------------------------------------------- #
# LIST                                                                        #
# --------------------------------------------------------------------------- #


@router.get("/agents/{agent_id}/api-keys")
def list_agent_keys(
    agent_id: str,
    include_revoked: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """List all API keys scoped to this agent (no secrets returned)."""
    _ensure_agent_owned(agent_id, auth, db)

    q = db.query(APIKey).filter(APIKey.agent_id == agent_id)
    if not include_revoked:
        q = q.filter(APIKey.is_active.is_(True))
    keys = q.order_by(APIKey.created_at.desc()).all()

    return {
        "agent_id": agent_id,
        "keys": [_key_summary(k) for k in keys],
        "count": len(keys),
    }


# --------------------------------------------------------------------------- #
# CREATE                                                                      #
# --------------------------------------------------------------------------- #


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    # Sprint 6 (2026-05-16): keys default to customer-wide. Pass true to
    # restrict the key to ONLY the agent in the URL (advanced — locks the
    # key so it can't act on the customer's other agents). The dashboard
    # mints customer-wide by default because MCP / SDK clients usually
    # juggle multiple agents under one Bearer.
    scope_to_agent: bool = False


@router.post("/agents/{agent_id}/api-keys", status_code=201)
def create_agent_key(
    agent_id: str,
    req: CreateKeyRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Create a new API key. Customer-wide by default; opt-in agent scope.

    The route is nested under /agents/{agent_id} for ownership verification
    (the caller must own this agent), but the resulting key is NOT bound
    to that agent unless `scope_to_agent=true` in the body.

    Returns the raw key ONCE.
    """
    agent = _ensure_agent_owned(agent_id, auth, db)

    raw_key = _generate_key()
    key = APIKey(
        id=new_id("key"),
        customer_id=auth.customer_id,
        agent_id=agent.id if req.scope_to_agent else None,
        key_hash=_hash_key(raw_key),
        owner_email=auth.customer_email,
        name=req.name,
        description=req.description,
        # `label` kept null for new keys — `name` supersedes it. We keep the
        # column for backward compat with the old bootstrap script's output.
        label=None,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    summary = _key_summary(key)
    summary["secret"] = raw_key  # ONLY in the create response
    summary["warning"] = (
        "Copy this secret now — it will not be shown again. "
        "If you lose it, revoke and create a new one."
    )
    return summary


# --------------------------------------------------------------------------- #
# REVOKE                                                                      #
# --------------------------------------------------------------------------- #


class RevokeKeyResponse(BaseModel):
    id: str
    is_active: bool
    revoked_at: str


@router.post("/api-keys/{key_id}/revoke", response_model=RevokeKeyResponse)
def revoke_key(
    key_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> RevokeKeyResponse:
    """Revoke an API key. Idempotent — re-revoking returns the same state."""
    key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if not key or key.customer_id != auth.customer_id:
        raise HTTPException(404, "API key not found")

    # Prevent revoking the key the caller used to authenticate — would lock
    # them out mid-request.
    if auth.api_key and auth.api_key.id == key.id:
        raise HTTPException(
            400,
            "Cannot revoke the key you used to authenticate this request. "
            "Sign in via magic-link and revoke from there.",
        )

    if key.is_active:
        key.is_active = False
        key.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(key)

    return RevokeKeyResponse(
        id=key.id,
        is_active=key.is_active,
        revoked_at=key.revoked_at.isoformat() if key.revoked_at else "",
    )


# --------------------------------------------------------------------------- #
# CUSTOMER-LEVEL ENDPOINTS — Sprint UX-5.11 / bug-andrea-3 (2026-05-17)        #
# --------------------------------------------------------------------------- #
#
# These endpoints exist because of a real Andrea-v2.1 finding: minting a key
# from /agents/[id]/keys creates a customer-wide key (Sprint 6 default), and
# the agent-scoped listing query never returned it — so /keys showed "0 keys"
# while events were authenticated by the very key the user just minted. From
# her own words: "as a user I'd be nervous I can't rotate or revoke later."
#
# The fix surfaces both kinds of keys (customer-wide + every agent's scoped
# keys) on a single /keys page in the dashboard. The agent-scoped listing
# stays as-is (it's correct for the per-agent view; we just add a banner
# pointing at /keys so users don't think their customer-wide key vanished).


@router.get("/customers/me/api-keys")
def list_customer_keys(
    include_revoked: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """List ALL keys for the authenticated customer (no secrets).

    Returns both customer-wide keys (agent_id=NULL) and agent-scoped keys,
    each tagged with a `scope` of "customer-wide" | "agent-scoped". For
    agent-scoped keys the response also includes `agent_name` so the
    dashboard can render "andrea-laptop · scoped to andrea-claude-code-laptop".
    """
    q = db.query(APIKey).filter(APIKey.customer_id == auth.customer_id)
    if not include_revoked:
        q = q.filter(APIKey.is_active.is_(True))
    keys = q.order_by(APIKey.created_at.desc()).all()

    # Single round-trip name lookup for any agent-scoped keys we found.
    agent_ids = {k.agent_id for k in keys if k.agent_id}
    name_by_agent_id: dict[str, str] = {}
    if agent_ids:
        rows = db.query(Agent.id, Agent.name).filter(Agent.id.in_(agent_ids)).all()
        name_by_agent_id = {row[0]: row[1] for row in rows}

    return {
        "customer_id": auth.customer_id,
        "keys": [
            _key_summary_with_scope(
                k,
                agent_name=name_by_agent_id.get(k.agent_id) if k.agent_id else None,
            )
            for k in keys
        ],
        "count": len(keys),
    }


class CreateCustomerKeyRequest(BaseModel):
    """Customer-wide key creation body.

    Customer-wide keys live outside any single agent and are the right
    default for MCP / SDK clients that juggle multiple agents under one
    Bearer (this is also the default when minting from /agents/[id]/keys,
    which is why bug-andrea-3 happened). For agent-scoped keys, use the
    nested route `POST /v1/agents/{agent_id}/api-keys` with
    `scope_to_agent=true`.
    """

    name: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=400)


@router.post("/customers/me/api-keys", status_code=201)
def create_customer_key(
    req: CreateCustomerKeyRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Create a customer-wide API key directly (no agent ownership step).

    Returns the raw secret ONCE in the response under `secret`. The list
    endpoint above never returns secrets again — copy now or revoke + recreate.
    """
    raw_key = _generate_key()
    key = APIKey(
        id=new_id("key"),
        customer_id=auth.customer_id,
        agent_id=None,  # customer-wide
        key_hash=_hash_key(raw_key),
        owner_email=auth.customer_email,
        name=req.name,
        description=req.description,
        label=None,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    summary = _key_summary_with_scope(key, agent_name=None)
    summary["secret"] = raw_key  # ONLY in the create response
    summary["warning"] = (
        "Copy this secret now — it will not be shown again. "
        "If you lose it, revoke and create a new one."
    )
    return summary
