"""Watchers REST API — Sprint 4.

Customer-facing endpoints for managing public-bot watchers:

  GET    /v1/agents/{agent_id}/watchers          — list watchers for one agent
  POST   /v1/agents/{agent_id}/watchers          — connect a new bot
  POST   /v1/watchers/{watcher_id}/pause         — pause polling
  POST   /v1/watchers/{watcher_id}/resume        — resume polling
  DELETE /v1/watchers/{watcher_id}               — soft-delete

Tokens are accepted in the POST body and encrypted before the row is
persisted; the plaintext token is never returned in any response.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, require_auth
from app.core.ids import new_id
from app.db import get_db
from app.db.models import APIKey, Agent, Watcher
from app.services import watcher_crypto
from app.services.watchers import list_supported_platforms

router = APIRouter(prefix="/v1", tags=["watchers"])


# --------------------------------------------------------------------------- #
# Shapes                                                                      #
# --------------------------------------------------------------------------- #


PlatformLiteral = Literal["telegram", "discord", "slack", "x"]


class WatcherSummary(BaseModel):
    """Public-safe shape of a watcher row. No token, ever."""
    id: str
    agent_id: str
    platform: PlatformLiteral
    display_name: Optional[str] = None
    state: str
    error_message: Optional[str] = None
    polling_interval_sec: int
    last_polled_at: Optional[datetime] = None
    events_logged: int
    created_at: datetime
    paused_at: Optional[datetime] = None


class CreateWatcherRequest(BaseModel):
    platform: PlatformLiteral
    token: str = Field(..., min_length=10, max_length=4096)
    display_name: Optional[str] = Field(None, max_length=200)


class CreateWatcherResponse(BaseModel):
    watcher: WatcherSummary


class WatcherListResponse(BaseModel):
    watchers: list[WatcherSummary]
    supported_platforms: list[str]


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _resolve_agent_for_customer(
    agent_id: str, ctx: AuthContext, db: Session
) -> Agent:
    """Verify the calling customer owns this agent.

    Mirrors the logic in mcp_endpoints._resolve_agent but at the customer
    level (not per-scoped-key) since watcher management is dashboard-only.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    creator_key = db.query(APIKey).filter(APIKey.id == agent.api_key_id).first()
    if not creator_key or creator_key.customer_id != ctx.customer_id:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    return agent


def _to_summary(w: Watcher) -> WatcherSummary:
    return WatcherSummary(
        id=w.id,
        agent_id=w.agent_id,
        platform=w.platform,  # type: ignore[arg-type]
        display_name=w.display_name,
        state=w.state,
        error_message=w.error_message,
        polling_interval_sec=w.polling_interval_sec,
        last_polled_at=w.last_polled_at,
        events_logged=w.events_logged or 0,
        created_at=w.created_at,
        paused_at=w.paused_at,
    )


def _load_watcher(
    watcher_id: str, ctx: AuthContext, db: Session
) -> Watcher:
    w = (
        db.query(Watcher)
        .filter(Watcher.id == watcher_id)
        .filter(Watcher.customer_id == ctx.customer_id)
        .filter(Watcher.deleted_at.is_(None))
        .first()
    )
    if not w:
        raise HTTPException(404, f"Watcher '{watcher_id}' not found")
    return w


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get(
    "/agents/{agent_id}/watchers",
    response_model=WatcherListResponse,
)
def list_watchers(
    agent_id: str,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List all watchers (active + paused + error) for one agent."""
    _resolve_agent_for_customer(agent_id, ctx, db)
    rows = (
        db.query(Watcher)
        .filter(Watcher.agent_id == agent_id)
        .filter(Watcher.deleted_at.is_(None))
        .order_by(Watcher.created_at.desc())
        .all()
    )
    return WatcherListResponse(
        watchers=[_to_summary(w) for w in rows],
        supported_platforms=list_supported_platforms(),
    )


@router.post(
    "/agents/{agent_id}/watchers",
    response_model=CreateWatcherResponse,
    status_code=201,
)
def create_watcher(
    agent_id: str,
    body: CreateWatcherRequest,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Connect a bot to this agent.

    The plaintext token is encrypted with the watcher KEK before the row
    is persisted. It is never echoed back to the caller.
    """
    agent = _resolve_agent_for_customer(agent_id, ctx, db)

    if body.platform not in list_supported_platforms():
        raise HTTPException(
            400,
            f"Platform '{body.platform}' not supported yet. "
            f"Available: {list_supported_platforms()}",
        )

    # Sprint 4.14 — enforce 1 active watcher per agent.
    # Multi-bot was originally allowed for multi-platform persona use cases,
    # but for V1 the simpler mental model is "one agent = one bot identity".
    # Soft-deleted (deleted_at NOT NULL) and paused don't count as active.
    existing = (
        db.query(Watcher)
        .filter(Watcher.agent_id == agent.id)
        .filter(Watcher.deleted_at.is_(None))
        .filter(Watcher.state.in_(("pending", "active", "error", "paused")))
        .first()
    )
    if existing is not None:
        raise HTTPException(
            409,
            "This agent already has a connected bot. "
            "Disconnect it first or create a new agent for a different bot.",
        )

    token_plain = body.token.strip()
    try:
        blob = watcher_crypto.encrypt_token(token_plain)
    except RuntimeError as e:
        raise HTTPException(
            500,
            f"Token encryption unavailable: {e}",
        )

    # Sprint UX-5.10-7 (#665) — resolve the real public handle from
    # the platform itself, instead of trusting whatever descriptive
    # label the customer typed in. For Telegram that's `@username`
    # from getMe; falls back to the user-typed display_name if the
    # API call fails so the watcher can still be created.
    resolved_display_name: str | None = body.display_name
    if body.platform == "telegram":
        from app.services.watchers.telegram import get_bot_username

        real_username = get_bot_username(token_plain)
        if real_username:
            resolved_display_name = real_username

    watcher = Watcher(
        id=new_id("wch"),
        agent_id=agent.id,
        customer_id=ctx.customer_id,
        platform=body.platform,
        encrypted_token=blob.encrypted_token,
        encryption_key_ref=blob.encryption_key_ref,
        display_name=resolved_display_name,
        state="pending",  # batch promotes to 'active' on first successful poll
        polling_interval_sec=60,
        events_logged=0,
    )
    db.add(watcher)

    # Sprint UX-5.7a (#634) — the bot username (e.g.
    # "@SenalesCryptoCarlos") makes a much better public slug than the
    # name the user typed at agent-registration time. The bot token is
    # itself a proof of control over that handle, so we treat watcher
    # connect as an implicit anchor and auto-claim a matching slug.
    #
    # Sprint UX-5.11 R2 / R2.3c (2026-05-18) — only auto-claim if the
    # agent doesn't already have a slug. Under "Full C" policy the
    # customer may have manually claimed a slug via an anchor
    # (`/v1/agents/{id}/claim-slug`) — we must not silently overwrite
    # that with the bot @username.
    #
    # R2.2b: wrap in try/IntegrityError so a concurrent claim that
    # races us through the partial UNIQUE index doesn't 500. We'd
    # rather keep the old slug than fail the watcher attach.
    from sqlalchemy.exc import IntegrityError as _IE

    old_slug = agent.public_slug
    if resolved_display_name and old_slug is None:
        from app.core.slug import allocate_public_slug

        new_slug = allocate_public_slug(
            db,
            candidate=resolved_display_name,
            fallback=agent.id,
            exclude_agent_id=agent.id,
        )
        if new_slug:
            agent.public_slug = new_slug

    try:
        db.commit()
    except _IE as e:
        if "public_slug" in str(getattr(e, "orig", e)).lower():
            db.rollback()
            # Re-add the watcher we lost in the rollback, keep old slug.
            agent.public_slug = old_slug
            db.add(watcher)
            db.commit()
        else:
            raise
    db.refresh(watcher)

    return CreateWatcherResponse(watcher=_to_summary(watcher))


@router.post(
    "/watchers/{watcher_id}/pause",
    response_model=WatcherSummary,
)
def pause_watcher(
    watcher_id: str,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    w = _load_watcher(watcher_id, ctx, db)
    w.state = "paused"
    w.paused_at = datetime.utcnow()
    db.add(w)
    db.commit()
    db.refresh(w)
    return _to_summary(w)


@router.post(
    "/watchers/{watcher_id}/resume",
    response_model=WatcherSummary,
)
def resume_watcher(
    watcher_id: str,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    w = _load_watcher(watcher_id, ctx, db)
    w.state = "pending"  # batch will promote to 'active' on next poll
    w.paused_at = None
    w.error_message = None
    db.add(w)
    db.commit()
    db.refresh(w)
    return _to_summary(w)


@router.post(
    "/watchers/{watcher_id}/retry",
    response_model=WatcherSummary,
)
def retry_watcher(
    watcher_id: str,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Force an immediate poll attempt for a watcher in error state.

    Sprint UX-5.10-8 (#666). When the customer sees "Connection issue"
    in the dashboard they don't want to wait 60s for the scheduler to
    try again. This endpoint runs the same poll routine the batch job
    runs, synchronously, and returns the resulting state.

    Resets error_message + state to pending first so the poll has a
    clean slate.
    """
    from app.services.watcher_job import _process_watcher

    w = _load_watcher(watcher_id, ctx, db)
    w.error_message = None
    if w.state == "error":
        w.state = "pending"
    db.add(w)
    db.commit()
    db.refresh(w)
    # _process_watcher updates the row's state + error_message based on
    # the outcome and commits internally.
    try:
        _process_watcher(db, w)
    except Exception as e:
        # Never let an unexpected failure leak as 500 — _process_watcher
        # itself already catches adapter errors, but be defensive.
        w.state = "error"
        w.error_message = f"unexpected: {type(e).__name__}: {e}"
        db.add(w)
        db.commit()
    db.refresh(w)
    return _to_summary(w)


@router.delete(
    "/watchers/{watcher_id}",
    status_code=204,
)
def delete_watcher(
    watcher_id: str,
    ctx: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Soft-delete: deleted_at is set, polling stops, row preserved for audit."""
    w = _load_watcher(watcher_id, ctx, db)
    w.deleted_at = datetime.utcnow()
    w.state = "paused"
    db.add(w)
    db.commit()
    return None
