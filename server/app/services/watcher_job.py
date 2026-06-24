"""Watcher batch job — Sprint 4.

Periodically (default every 60s) polls every active Watcher, asks its
PlatformAdapter for new events, and logs each event into the agent's
EventLog using the same digest-chain logic as the MCP `metalins_log_event`
tool (sans the API-key plumbing — we resolve agent ownership via the
watcher's `agent_id` directly).

Designed to share the same APScheduler instance as observable_job. See
`start_scheduler()` in observable_job.py for the in-proc startup hook.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import Agent, AgentState, EventLog, Watcher
from app.db.session import SessionLocal
from app.services import watcher_crypto
from app.services.watchers import EventDraft, get_adapter

log = logging.getLogger(__name__)


@dataclass
class WatcherRunReport:
    """Summary of one watcher's poll. Useful for diagnostics + tests."""
    watcher_id: str
    platform: str
    events_drained: int
    error: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_event_internal(
    db: Session,
    agent: Agent,
    state: AgentState,
    draft: EventDraft,
) -> None:
    """Internal log_event — mirrors mcp_endpoints._do_log_event minus the
    auth + agent-resolution dance, since we already have the agent + state.

    Mutates `state` (event_count, history_digest, last_event_at) and inserts
    one EventLog row. Caller commits.
    """
    # Update digest chain.
    h = hashlib.sha256()
    h.update(bytes.fromhex(state.history_digest))
    h.update(draft.input_hash.encode())
    h.update(draft.output_hash.encode())
    new_digest = h.hexdigest()
    state.event_count += 1
    state.history_digest = new_digest
    state.last_event_at = _utcnow()

    # Rotating-secret signature.
    rotating_secret = hmac.new(
        bytes.fromhex(state.agent_secret),
        bytes.fromhex(new_digest),
        hashlib.sha256,
    ).digest()
    msg = f"{draft.input_hash}|{draft.output_hash}|{state.event_count}".encode()
    sig = hmac.new(rotating_secret, msg, hashlib.sha256).hexdigest()

    event = EventLog(
        id=new_id("evt"),
        agent_id=agent.id,
        event_count=state.event_count,
        input_hash=draft.input_hash,
        output_hash=draft.output_hash,
        history_digest=new_digest,
        signature=sig,
        metadata_json={
            "source": "watcher",
            "platform_message_id": draft.platform_message_id,
            "chat_id_hash": draft.chat_id_hash,
            **draft.metadata,
        },
        ts=draft.ts,
    )
    db.add(event)


def _process_watcher(db: Session, watcher: Watcher) -> WatcherRunReport:
    """Poll one watcher, drain new events into the agent's log."""
    adapter = get_adapter(watcher.platform)
    if adapter is None:
        return WatcherRunReport(
            watcher_id=watcher.id,
            platform=watcher.platform,
            events_drained=0,
            error=f"unknown_platform:{watcher.platform}",
        )

    # Decrypt token in-memory only.
    try:
        token = watcher_crypto.decrypt_token(
            watcher.encrypted_token, watcher.encryption_key_ref
        )
    except Exception as e:
        watcher.state = "error"
        watcher.error_message = f"decrypt_failed: {type(e).__name__}"
        db.add(watcher)
        return WatcherRunReport(
            watcher_id=watcher.id,
            platform=watcher.platform,
            events_drained=0,
            error="decrypt_failed",
        )

    # Resolve agent + state once.
    agent = db.query(Agent).filter(Agent.id == watcher.agent_id).first()
    if agent is None or not agent.is_active:
        watcher.state = "error"
        watcher.error_message = "agent_missing_or_revoked"
        db.add(watcher)
        return WatcherRunReport(
            watcher_id=watcher.id,
            platform=watcher.platform,
            events_drained=0,
            error="agent_missing",
        )
    state = db.query(AgentState).filter(AgentState.agent_id == agent.id).first()
    if state is None:
        watcher.state = "error"
        watcher.error_message = "agent_state_missing"
        db.add(watcher)
        return WatcherRunReport(
            watcher_id=watcher.id,
            platform=watcher.platform,
            events_drained=0,
            error="agent_state_missing",
        )

    # Fetch + log.
    drafts: Sequence[EventDraft]
    try:
        drafts = adapter.fetch_new_events(watcher, token, db)
    except Exception as e:
        # 401-equivalent → mark error and stop polling.
        watcher.state = "error"
        watcher.error_message = f"adapter_error:{type(e).__name__}:{e}"[:500]
        db.add(watcher)
        log.exception("Adapter error for watcher %s", watcher.id)
        return WatcherRunReport(
            watcher_id=watcher.id,
            platform=watcher.platform,
            events_drained=0,
            error="adapter_error",
        )

    for draft in drafts:
        _log_event_internal(db, agent, state, draft)
        watcher.last_event_id = draft.platform_message_id

    watcher.events_logged = (watcher.events_logged or 0) + len(drafts)
    watcher.last_polled_at = _utcnow()
    watcher.error_message = None
    if watcher.state == "pending":
        watcher.state = "active"
    db.add(watcher)

    return WatcherRunReport(
        watcher_id=watcher.id,
        platform=watcher.platform,
        events_drained=len(drafts),
    )


def run_batch() -> dict:
    """Poll every active watcher once. Returns aggregate report."""
    started = _utcnow()
    reports: list[WatcherRunReport] = []

    db = SessionLocal()
    try:
        active = (
            db.query(Watcher)
            .filter(Watcher.deleted_at.is_(None))
            .filter(Watcher.state.in_(("pending", "active")))
            .all()
        )
        for w in active:
            try:
                reports.append(_process_watcher(db, w))
            except Exception as e:  # pragma: no cover — defensive
                log.exception("Watcher %s crashed", w.id)
                reports.append(
                    WatcherRunReport(
                        watcher_id=w.id,
                        platform=w.platform,
                        events_drained=0,
                        error=f"crash:{type(e).__name__}",
                    )
                )
                db.rollback()
        db.commit()
    finally:
        db.close()

    finished = _utcnow()
    return {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": (finished - started).total_seconds(),
        "watchers_seen": len(reports),
        "events_drained_total": sum(r.events_drained for r in reports),
        "errors": [r.__dict__ for r in reports if r.error],
    }


# --------------------------------------------------------------------------- #
# APScheduler registration                                                    #
# --------------------------------------------------------------------------- #


def start_watcher_scheduler(interval_seconds: int = 60) -> None:
    """Register the watcher batch on the shared scheduler. Idempotent.

    Default cadence is 60s — small enough for fresh-feeling identity
    updates, big enough not to thrash platform APIs. Per-watcher polling
    interval is also enforced inside fetch_new_events for fairness.
    """
    from app.services.scheduler import get_or_create_scheduler

    sched = get_or_create_scheduler()
    if sched is None:
        return
    # ops-2 — best-effort warm backup only; the external Cloud Scheduler
    # job (POST /v1/admin/watchers/run-batch, provisioned by
    # deploy-cloudrun.sh) is the source of truth for cadence. Force an
    # immediate first run so a fresh revision drains watchers right away.
    sched.add_job(
        run_batch,
        trigger="interval",
        seconds=interval_seconds,
        id="watcher_batch",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    log.info(
        "watcher batch registered on shared scheduler "
        "(interval=%ds, first run immediate)",
        interval_seconds,
    )
