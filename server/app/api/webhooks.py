"""Per-agent webhook endpoints (Sprint UX-5.10-6 / #664).

Lets Diana wire a state-change alert to whatever HTTPS endpoint her
team monitors. The page promises "webhook alerts when identity
shifts" — this module makes the promise real.

Endpoints
---------
POST   /v1/agents/{id}/webhooks         — create. Returns the secret ONCE.
GET    /v1/agents/{id}/webhooks         — list (no secret in response).
DELETE /v1/agents/{id}/webhooks/{wid}   — soft-delete.

Delivery
--------
Firing logic lives in `services.webhook_delivery`. The identity engine
calls it whenever an agent's `verification_state` transitions to
caution or action.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, require_auth
from app.core.ids import new_id
from app.db import get_db
from app.db.models import Agent, APIKey, WebhookEndpoint


router = APIRouter(prefix="/v1/agents", tags=["webhooks"])


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _resolve_customer_agent(
    db: Session, agent_id: str, auth: AuthContext
) -> Agent:
    """Same ownership check used elsewhere — agent must belong to caller."""
    customer_key_ids = [
        row[0]
        for row in db.query(APIKey.id)
        .filter(APIKey.customer_id == auth.customer_id)
        .all()
    ]
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.api_key_id.in_(customer_key_ids))
        .first()
    )
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return agent


def _hash_secret(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Schemas                                                                     #
# --------------------------------------------------------------------------- #


class WebhookCreate(BaseModel):
    url: HttpUrl


class WebhookOut(BaseModel):
    """Public-safe shape. NEVER includes secret."""
    id: str
    url: str
    is_active: bool
    last_delivery_at: Optional[str] = None
    last_delivery_status: Optional[int] = None
    last_delivery_error: Optional[str] = None
    created_at: Optional[str] = None


class WebhookCreateResponse(BaseModel):
    """Returned ONLY at creation. `secret` is shown once."""
    webhook: WebhookOut
    secret: str = Field(
        ..., description="Shown ONCE. Use it to validate X-Metalins-Signature."
    )


def _to_out(w: WebhookEndpoint) -> WebhookOut:
    return WebhookOut(
        id=w.id,
        url=w.url,
        is_active=bool(w.is_active),
        last_delivery_at=(
            w.last_delivery_at.isoformat() + "Z"
            if w.last_delivery_at
            else None
        ),
        last_delivery_status=w.last_delivery_status,
        last_delivery_error=w.last_delivery_error,
        created_at=w.created_at.isoformat() + "Z" if w.created_at else None,
    )


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/{agent_id}/webhooks")
def list_webhooks(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    _resolve_customer_agent(db, agent_id, auth)
    rows = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.agent_id == agent_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        .order_by(WebhookEndpoint.created_at.desc())
        .all()
    )
    return {"webhooks": [_to_out(w).model_dump() for w in rows]}


@router.post(
    "/{agent_id}/webhooks",
    response_model=WebhookCreateResponse,
    status_code=201,
)
def create_webhook(
    agent_id: str,
    body: WebhookCreate,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Create a webhook. Returns the plaintext secret exactly once.

    Once stored we only keep the hash, so a customer who loses the
    secret has to delete + recreate the webhook. Standard pattern.
    """
    agent = _resolve_customer_agent(db, agent_id, auth)
    plaintext_secret = secrets.token_urlsafe(32)
    row = WebhookEndpoint(
        id=new_id("whk"),
        agent_id=agent.id,
        customer_id=auth.customer_id,
        url=str(body.url),
        secret_hash=_hash_secret(plaintext_secret),
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return WebhookCreateResponse(
        webhook=_to_out(row),
        secret=plaintext_secret,
    )


@router.delete(
    "/{agent_id}/webhooks/{webhook_id}", status_code=204
)
def delete_webhook(
    agent_id: str,
    webhook_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    _resolve_customer_agent(db, agent_id, auth)
    row = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.id == webhook_id,
            WebhookEndpoint.agent_id == agent_id,
            WebhookEndpoint.deleted_at.is_(None),
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, "Webhook not found")
    row.deleted_at = datetime.utcnow()
    row.is_active = False
    db.commit()
    return None
