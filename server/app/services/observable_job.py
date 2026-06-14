"""Batch job: compute Trinity observables for all active agents.

Designed to run periodically (hourly by default) via APScheduler in-process,
and also exposable as an HTTP endpoint that Cloud Scheduler can poke when
running on scale-to-zero infrastructure.

The job is idempotent: it always reads the current event_logs window and
writes a new agent_observables row per agent. Old rows are not modified.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from app.core.ids import new_id
from app.db.models import Agent, AgentObservable, AgentState, EventLog, MemoryProbe, Watcher
from app.db.session import SessionLocal
from app.services import email_delivery, memory_verifier, webhook_delivery
from app.services.identity_engine import (
    compute_trinity,
    explain_score,
    identity_confidence_v1,
)
from app.services.verification_state import derive_trust
from app.services.rks_verifier import compute_rks, RKS_WARNING_THRESHOLD
from app.services.tls import compute_tls, TLS_WARNING_THRESHOLD
from app.services.adv import compute_adv, ADV_WARNING_THRESHOLD
from app.services.prs import (
    compute_prs, resolve_pending_predictions, PRS_WARNING_THRESHOLD,
)
from app.services.mcs import compute_mcs, MCS_WARNING_THRESHOLD
from app.services.zkh import compute_zkh, ZKH_WARNING_THRESHOLD

log = logging.getLogger(__name__)


# Default window: last N events per agent. Caller can override per-call.
DEFAULT_WINDOW = 2000

# Minimum events before we persist an observables row. Set to match the
# probe-issuance threshold (memory_verifier.MIN_EVENTS_FOR_PROBE = 10) so
# any agent that's eligible for MVS probes also gets an observables row
# even if Trinity components return None for sub-threshold individual
# checks (ICR needs ≥4, TTM ≥100, TWC ≥ ~250). The aggregator handles
# None values gracefully.
MIN_EVENTS_FOR_COMPUTE = 10


@dataclass
class JobReport:
    """Summary of a single batch run."""
    started_at: datetime
    finished_at: datetime
    agents_seen: int
    agents_computed: int
    agents_skipped: int
    failures: list[str]

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "agents_seen": self.agents_seen,
            "agents_computed": self.agents_computed,
            "agents_skipped": self.agents_skipped,
            "failures": self.failures,
            "duration_seconds": (self.finished_at - self.started_at).total_seconds(),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fetch_recent_events(
    db: Session,
    agent_id: str,
    window: int,
    baseline_cutoff: "datetime | None" = None,
) -> list[dict]:
    """Pull the latest `window` events for an agent, oldest-first.

    UX-5.15.P / D-PROD.25 — if `baseline_cutoff` is supplied, events
    older than this timestamp are excluded from the window. This is
    used after a customer "Reset behavior baseline": the underlying
    EventLog rows remain (they're auditable evidence), but the shape
    is recomputed only from events accumulated after the reset.
    """
    stmt = (
        select(EventLog.input_hash, EventLog.output_hash, EventLog.event_count, EventLog.ts)
        .where(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.desc())
        .limit(window)
    )
    if baseline_cutoff is not None:
        stmt = stmt.where(EventLog.ts >= baseline_cutoff)
    rows = db.execute(stmt).all()
    # Reverse to oldest-first
    rows = list(reversed(rows))
    return [
        {
            "input_hash": r.input_hash,
            "output_hash": r.output_hash,
            "event_count": r.event_count,
            "ts": r.ts,
        }
        for r in rows
    ]


def _detect_integration(db: Session, agent_id: str) -> dict:
    """Inspect an agent's integration profile (D-PROD.18).

    Returns a dict with:
      has_watcher: bool        — agent has an active/pending/error watcher
                                 (NOT paused or deleted)
      watcher_platform: str | None — telegram / discord / slack / x
      has_mcp_activity: bool   — total event count exceeds what the
                                 watcher has logged (i.e. some events
                                 came in through the MCP API surface)

    V1 model: one agent = one identity = one integration surface, so in
    practice exactly one of these is True for a healthy agent. Both can
    be True only as a legacy mixed state we want to migrate away from
    (see backlog #575: hard-enforce exclusivity).
    """
    watcher = (
        db.query(Watcher)
        .filter(Watcher.agent_id == agent_id, Watcher.deleted_at.is_(None))
        .first()
    )
    has_watcher = watcher is not None and watcher.state != "paused"
    watcher_platform = watcher.platform if watcher else None
    watcher_events = watcher.events_logged if watcher else 0

    total_events = (
        db.query(EventLog).filter(EventLog.agent_id == agent_id).count()
    )
    has_mcp_activity = total_events > watcher_events
    return {
        "has_watcher": has_watcher,
        "watcher_platform": watcher_platform,
        "has_mcp_activity": has_mcp_activity,
    }


def _maybe_issue_fresh_probe(
    db: Session,
    agent_id: str,
    *,
    has_mcp_activity: bool,
) -> None:
    """If the agent has no pending probe issued in the last hour, issue one.

    Probes are how MVS is measured. Without periodic issuance the score
    can't update. We avoid double-issuing by checking for any pending probe
    from the last hour.

    Sprint 6.4 / #574 — gate by integration profile. Memory probes are
    answered by the agent via MCP. For watcher-only agents there's no
    channel to respond, so probes would just pile up, expire, and tank
    a future MVS computation if the agent ever switched to MCP. Skip
    issuance entirely when there's no MCP surface.
    """
    if not has_mcp_activity:
        return

    one_hour_ago = _utcnow() - timedelta(hours=1)
    recent_pending = (
        db.query(MemoryProbe)
        .filter(
            MemoryProbe.agent_id == agent_id,
            MemoryProbe.status == "pending",
            MemoryProbe.issued_at >= one_hour_ago,
        )
        .first()
    )
    if recent_pending is not None:
        return
    try:
        memory_verifier.issue_probe(db, agent_id)
    except Exception:  # pragma: no cover — defensive
        db.rollback()
        log.exception("failed to issue probe for agent %s", agent_id)


def compute_for_agent(
    db: Session,
    agent_id: str,
    window: int = DEFAULT_WINDOW,
) -> AgentObservable | None:
    """Compute Trinity observables + MVS for one agent and persist a row.

    Side effects:
      1. Expires any stale pending probes for the agent.
      2. Issues a fresh probe if no pending one in the last hour.
      3. Computes ICR/TWC/TTM over the latest `window` events.
      4. Computes MVS from recently decided probes.
      5. Aggregates Identity Confidence v1 (Trinity + MVS, ICR-gated).

    Returns the new AgentObservable row, or None if skipped (too few events).
    """
    # 0. Integration profile — decides whether to issue probes (skipped
    # for watcher-only agents) and feeds explain_score() below.
    integration = _detect_integration(db, agent_id)

    # 0b. Snapshot the verification_state BEFORE the recompute so we can
    # detect transitions and fire webhooks (Sprint UX-5.10-6). We need
    # this BEFORE we modify any observable rows, otherwise we'd compare
    # the new state against itself.
    agent_row = db.query(Agent).filter(Agent.id == agent_id).first()
    state_row = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    prev_obs = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    # Sprint UX-5.12 — only the cryptographic layer drives webhook
    # alerts (design doc §3.1). A behavioral state change from
    # `building` to `stable` is not an incident; a cryptographic
    # transition from `verified` to `caution` IS.
    prev_state = (
        derive_trust(agent_row, state_row, prev_obs)["cryptographic"]["state"]
        if agent_row is not None
        else "unverified"
    )

    # UX-5.15.AL — probe-capability gate. Round-trip mechanisms (MVS /
    # ADV / TLS / PRS / MCS / ZKH) need a client that actively answers
    # challenges. A V1 MCP-prompt agent has none, so we neither issue
    # probes nor compute those signals — issuing probes it can never
    # answer produced false `probes_unanswered` / `protocol_unaware`
    # alarms. The score rests on the event-stream layer. See D-PROD.27.
    from app.services.protections_catalog import agent_probes_enabled

    # gh-88 — probe-capable AND not stochastic. Stochastic agents (LLMs) can
    # never satisfy a hash-based probe, so we neither issue probes to them nor
    # let the round-trip factors (incl. probes_failing) surface, even if the
    # probe_client flag is set. `probe_capable` flows to explain_score() below
    # as has_probe_client, so the same gate also suppresses the factor.
    probe_capable = agent_probes_enabled(agent_row)
    # gh-77 — the declared-vs-observed `profile_mismatch` factor is retired.
    # The customer no longer declares a profile; behavior is detected from
    # the event stream (Agent.detected_behavior_mode), so the engine band
    # and the detected mode are both behavior-derived and a "mismatch"
    # against a customer declaration is meaningless. Pass None so
    # explain_score skips the mismatch emission.
    agent_profile = None

    # 1. Expire stale probes (counts toward MVS as failures).
    memory_verifier.expire_stale_probes(db, agent_id=agent_id)

    # 2. Issue fresh probe so MVS keeps refreshing — only for agents with
    # a probe-capable client (UX-5.15.AL).
    if probe_capable:
        _maybe_issue_fresh_probe(
            db, agent_id, has_mcp_activity=integration["has_mcp_activity"]
        )

    # 3. Trinity over recent events.
    # UX-5.15.P / D-PROD.25 — if the customer reset the baseline,
    # ignore events older than the reset (they remain in EventLog as
    # auditable evidence, but don't contribute to the current shape).
    baseline_cutoff = getattr(state_row, "last_baseline_reset_at", None) if state_row else None
    events = _fetch_recent_events(db, agent_id, window, baseline_cutoff=baseline_cutoff)
    if len(events) < MIN_EVENTS_FOR_COMPUTE:
        return None
    trinity = compute_trinity(events)

    # 4. RKS — chain replay verification (Sprint 7). Event-stream
    # mechanism: verified from the EventLog itself, no agent round-trip,
    # so it is always computed. Returns None if the agent has no events.
    rks = compute_rks(db, agent_id)

    # 4b. Round-trip mechanisms (MVS / TLS / ADV / PRS / MCS / ZKH) —
    # UX-5.15.AL. These need the agent to actively answer challenges; a
    # non-probe-capable agent has no client to do so. Skip them entirely
    # — the score rests on the event-stream layer (signed chain / RKS /
    # ICR). MVS uses the UX-5.15.AJ outcome breakdown when computed.
    if probe_capable:
        mvs_breakdown = memory_verifier.compute_mvs_breakdown(db, agent_id)
        mvs = (
            mvs_breakdown.passed / mvs_breakdown.total
            if mvs_breakdown.total > 0
            else None
        )
        tls = compute_tls(db, agent_id)
        adv = compute_adv(db, agent_id)
        resolve_pending_predictions(db, agent_id)
        prs = compute_prs(db, agent_id)
        mcs = compute_mcs(db, agent_id)
        zkh = compute_zkh(db, agent_id)
    else:
        mvs_breakdown = memory_verifier.MVSBreakdown(
            total=0, passed=0, responded_invalid=0, expired=0
        )
        mvs = tls = adv = prs = mcs = zkh = None

    # 5. Aggregate v1 confidence (all 11 layers).
    confidence = identity_confidence_v1(
        icr=trinity.icr,
        twc=trinity.twc,
        ttm=trinity.ttm,
        mvs=mvs,
        n_events=trinity.n_events,
        rks=rks,
        tls=tls,
        adv=adv,
        prs=prs,
        mcs=mcs,
        zkh=zkh,
    )

    window_start = events[0]["ts"]
    window_end = events[-1]["ts"]

    # Customer-facing explanation of why the score is what it is. Stored
    # alongside internals in details_json so the API layer can surface it
    # without re-running the engine. See identity_engine.explain_score.
    pending_probes_count = (
        db.query(MemoryProbe)
        .filter(MemoryProbe.agent_id == agent_id, MemoryProbe.status == "pending")
        .count()
        if probe_capable
        else 0
    )

    score_factors = explain_score(
        icr=trinity.icr,
        twc=trinity.twc,
        ttm=trinity.ttm,
        mvs=mvs,
        mvs_expired=mvs_breakdown.expired,
        mvs_responded_invalid=mvs_breakdown.responded_invalid,
        n_events=trinity.n_events,
        pending_probes_count=pending_probes_count,
        identity_confidence=confidence,
        has_watcher=integration["has_watcher"],
        watcher_platform=integration["watcher_platform"],
        has_mcp_activity=integration["has_mcp_activity"],
        agent_profile=agent_profile,
        # gh-80 — gate round-trip factors (MVS/ADV/PRS/ZKH/TLS/MCS) inside
        # explain_score for agents without a probe-capable client, matching
        # the protections catalog. Without this the engine raised a
        # "memory checks failing" alarm for a mechanism the catalog hides.
        has_probe_client=probe_capable,
        rks=rks,
        tls=tls,
        adv=adv,
        prs=prs,
        mcs=mcs,
        zkh=zkh,
    )

    details = {
        **trinity.details,
        "mvs": mvs,
        "rks": rks,
        "tls": tls,
        "adv": adv,
        "prs": prs,
        "mcs": mcs,
        "zkh": zkh,
        "score_factors": score_factors,
    }

    row = AgentObservable(
        id=new_id("obs"),
        agent_id=agent_id,
        ts=_utcnow(),
        window_start=window_start,
        window_end=window_end,
        icr=trinity.icr,
        twc=trinity.twc,
        ttm=trinity.ttm,
        beta_crooks=trinity.beta_crooks,
        n_events=trinity.n_events,
        identity_confidence=confidence,
        details_json=details,
    )
    db.add(row)
    db.commit()

    # Sprint UX-5.10-6 — fire webhooks if state transitioned to a
    # level that warrants attention. No-op when state is unchanged or
    # going back to healthy.
    if agent_row is not None:
        new_state = derive_trust(agent_row, state_row, row)["cryptographic"]["state"]
        try:
            webhook_delivery.maybe_fire(
                db,
                agent=agent_row,
                previous_state=prev_state,
                new_state=new_state,
                confidence=confidence,
                score_factors=score_factors,
            )
        except Exception:
            # Webhook failure must not break the recompute path.
            log.exception("webhook fire failed for agent %s", agent_id)

        # Sprint UX-5.13 (2026-05-18) — email fire mirrors webhook
        # fire. Independent channel: customer can have both, either,
        # or neither configured. Each maybe_fire is internally
        # best-effort; the try/except here is belt + suspenders so
        # that a bug in email_delivery cannot block recompute.
        try:
            email_delivery.maybe_fire(
                db,
                agent=agent_row,
                previous_state=prev_state,
                new_state=new_state,
                confidence=confidence,
            )
        except Exception:
            log.exception("email fire failed for agent %s", agent_id)

        # #64 — behavioral drift alerts (κ-engine V2). Independent of the
        # cryptographic state machine above: this passively learns the
        # agent's behavioral baseline and fires a DRIFT_DETECTED alert
        # (DriftEvent row → email → webhook) when a fresh traffic window
        # drifts away from it. Best-effort, never breaks recompute.
        try:
            from app.services import drift_alerts

            drift_alerts.run_drift_check(db, agent=agent_row)
        except Exception:
            log.exception("drift check failed for agent %s", agent_id)

    return row


def _active_agent_ids(db: Session) -> Iterable[str]:
    stmt = select(Agent.id).where(Agent.is_active.is_(True))
    return [r[0] for r in db.execute(stmt).all()]


def run_batch(window: int = DEFAULT_WINDOW) -> JobReport:
    """Run the batch over all active agents. Returns a summary.

    Opens its own DB session — safe to call from a scheduler thread or from
    an HTTP request handler.
    """
    started = _utcnow()
    seen = 0
    computed = 0
    skipped = 0
    failures: list[str] = []

    db = SessionLocal()
    try:
        agent_ids = list(_active_agent_ids(db))
        seen = len(agent_ids)
        for agent_id in agent_ids:
            try:
                row = compute_for_agent(db, agent_id, window=window)
                if row is None:
                    skipped += 1
                else:
                    computed += 1
            except Exception as e:  # pragma: no cover — defensive
                db.rollback()
                failures.append(f"{agent_id}: {type(e).__name__}: {e}")
                log.exception("observable batch failed for agent %s", agent_id)
    finally:
        db.close()

    finished = _utcnow()
    report = JobReport(
        started_at=started,
        finished_at=finished,
        agents_seen=seen,
        agents_computed=computed,
        agents_skipped=skipped,
        failures=failures,
    )
    log.info("observable batch done: %s", report.to_dict())
    return report


# --------------------------------------------------------------------------- #
# APScheduler integration                                                     #
# --------------------------------------------------------------------------- #


def start_scheduler(interval_minutes: int = 60) -> None:
    """Register the observable batch on the shared scheduler. Idempotent.

    ops-2 — the in-proc scheduler is now a BEST-EFFORT WARM BACKUP only.
    The source of truth for cadence is the external Cloud Scheduler job
    that pokes `POST /v1/admin/observables/run-batch` hourly (provisioned
    by deploy-cloudrun.sh). Reasons the in-proc path can't be trusted on
    Cloud Run:
      - CPU is throttled to ~0 between requests (no `--no-cpu-throttling`),
        so the BackgroundScheduler thread doesn't reliably tick.
      - An `interval` trigger first fires at now+interval; every deploy
        restarts the process and resets that timer, so a burst of deploys
        (e.g. gh-80/81/82/83) can keep it from ever reaching a first run.

    We still register it AND force an immediate first run (`next_run_time`
    = now) so a fresh revision produces an observables row right away
    instead of waiting a full interval — this is what makes a deploy
    verifiable within minutes, and covers the gap before Cloud Scheduler's
    next tick.
    """
    from app.services.scheduler import get_or_create_scheduler

    sched = get_or_create_scheduler()
    if sched is None:
        return
    # Idempotent: replace if already registered. next_run_time=now forces
    # the first run immediately rather than at now+interval (ops-2).
    sched.add_job(
        run_batch,
        trigger="interval",
        minutes=interval_minutes,
        id="observable_batch",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    log.info(
        "observable batch registered on shared scheduler "
        "(interval=%d min, first run immediate)",
        interval_minutes,
    )


def stop_scheduler() -> None:
    """Stop the shared scheduler if running."""
    from app.services.scheduler import shutdown_scheduler

    shutdown_scheduler()
