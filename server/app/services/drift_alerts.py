"""Behavioral drift alerts pipeline (#64).

When the κ-engine V2 (#62) detects that an agent's recent traffic window
has drifted away from its learned behavioral baseline (#62/#63), this
module turns that verdict into a durable, customer-facing alert:

  1. Persist a ``DriftEvent`` row — the carrier of the ``DRIFT_DETECTED``
     event (agent_id, dominant_feature, baseline_value, current_value,
     magnitude). This is what the dashboard surfaces (#65 renders it).
  2. Email the customer's ``EmailPreferences`` recipient, gated on the
     ``drift_detected_enabled`` toggle (mirrors the cryptographic
     alerting in ``email_delivery.maybe_fire``).
  3. Fire any active webhook with a ``behavioral_drift.detected`` payload.

Design choices
--------------
- **Separate alert threshold.** The engine calls drift "unverified" at
  ``drift_score >= 0.5`` (DRIFT_THRESHOLD). We only *alert* at a higher
  bar (``DRIFT_ALERT_THRESHOLD``) so the customer's inbox isn't woken by
  marginal, ambiguous shifts. The dashboard can still show sub-threshold
  movement; an email/webhook is reserved for a clear change.
- **Dedup window.** The observable batch runs hourly; without dedup a
  sustained drift would email the customer every hour. We suppress a
  repeat alert for the *same dominant feature* within
  ``DEDUP_WINDOW_HOURS`` of the last one. A different feature drifting,
  or the same feature after the cooldown, is a fresh alert.
- **Baseline bootstrap.** V2 is passive: it needs a baseline before it
  can compare. ``ensure_baseline`` lazily computes one the first time an
  agent crosses ``MIN_BASELINE_EVENTS`` behavioral events, then leaves it
  fixed (re-baselining is the customer's "mark as expected" action, #65 /
  the reset primitive — out of scope here). Comparing the rolling window
  against that fixed baseline is exactly the shadow-mode behavior the #62
  spec calls for.
- **Never raises.** Like the email/webhook services, the whole pipeline
  is best-effort. A failure here must not break the recompute path that
  calls it.

CLOSED-SOURCE boundary: this consumes the κ-engine verdict but lives in
``services`` (the alerting layer), not in ``kappa`` (the engine). The
engine stays content-blind; this layer only ever sees structural
summaries, never raw input/output.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.ids import new_id
from app.db.models import (
    Agent,
    AgentBaseline,
    APIKey,
    Customer,
    DriftEvent,
    EmailPreferences,
)
from app.kappa import (
    compare_behavioral_to_baseline,
    fingerprint_behavioral_baseline,
)
from app.services import email_delivery, webhook_delivery

log = logging.getLogger(__name__)


# Alert only on a clear drift. Higher than the engine's DRIFT_THRESHOLD
# (0.5, the "unverified" line) so marginal shifts surface in the
# dashboard without firing an email/webhook.
DRIFT_ALERT_THRESHOLD = 0.6

# Don't compute a baseline until the agent has at least this many
# behavioral events — too few and the baseline is noise that produces
# false drift. Matches the engine's window economics (compares 50 against
# a baseline of up to 200).
MIN_BASELINE_EVENTS = 100

# Events used to build the baseline + the comparison window size.
BASELINE_N_EVENTS = 200
COMPARE_WINDOW_SIZE = 50

# Suppress a repeat alert for the same dominant feature within this many
# hours of the previous one (the batch runs hourly).
DEDUP_WINDOW_HOURS = 6


def resolve_customer(db: Session, agent: Agent) -> Customer | None:
    """Resolve the owning customer for an agent via its API key.

    The ``agents`` table has no ``customer_id`` column — ownership is
    ``agent.api_key_id`` → ``api_keys.customer_id`` → ``customers.id``.
    Returns None for orphan / legacy agents whose key has no customer.
    """
    api_key = (
        db.query(APIKey).filter(APIKey.id == agent.api_key_id).one_or_none()
    )
    if api_key is None or not api_key.customer_id:
        return None
    return (
        db.query(Customer)
        .filter(Customer.id == api_key.customer_id)
        .one_or_none()
    )


def _count_behavioral_events(db: Session, agent_id: str) -> int:
    """Count events that carry ``metadata_json['behavioral']`` (#63).

    SQLite (dev/test) and Postgres (prod) disagree on JSON path operators,
    so we count in Python over a bounded scan rather than push a JSON
    predicate into SQL. The scan is capped at ``MIN_BASELINE_EVENTS`` worth
    of recent events — we only need to know whether the floor is crossed.
    """
    from app.db.models import EventLog

    rows = (
        db.query(EventLog.metadata_json)
        .filter(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.desc())
        .limit(BASELINE_N_EVENTS)
        .all()
    )
    n = 0
    for (md,) in rows:
        if isinstance(md, dict) and isinstance(md.get("behavioral"), dict):
            n += 1
    return n


def ensure_baseline(db: Session, agent_id: str) -> bool:
    """Lazily compute the behavioral baseline if the agent is ready.

    Returns True if a baseline exists (already there, or just built),
    False if the agent still has too few behavioral events to learn one.
    """
    existing = (
        db.query(AgentBaseline)
        .filter(AgentBaseline.agent_id == agent_id)
        .first()
    )
    if existing is not None and existing.n_events >= MIN_BASELINE_EVENTS:
        return True

    if _count_behavioral_events(db, agent_id) < MIN_BASELINE_EVENTS:
        return False

    fingerprint_behavioral_baseline(db, agent_id, n_events=BASELINE_N_EVENTS)
    return True


def _attribution_summary(
    attribution: dict,
) -> tuple[str | None, str | None, float | None]:
    """Turn the engine's attribution detail into (baseline, current, mag).

    The dominant-feature ``detail`` shape depends on the test that scored
    it: continuous features carry ``baseline_mean`` / ``current_mean``,
    categorical features carry ``baseline_dist`` / ``current_dist``, and
    the LSH feature carries ``mean_min_hamming``. We render a compact,
    display-ready before/after for each.
    """
    detail = attribution.get("detail") or {}
    magnitude = attribution.get("magnitude")
    if isinstance(magnitude, (int, float)):
        magnitude = float(magnitude)
    else:
        magnitude = None

    if "baseline_mean" in detail and "current_mean" in detail:
        return (
            f"{detail['baseline_mean']:.2f}",
            f"{detail['current_mean']:.2f}",
            magnitude,
        )
    if "baseline_dist" in detail and "current_dist" in detail:
        return (
            json.dumps(detail["baseline_dist"], separators=(",", ":"))[:240],
            json.dumps(detail["current_dist"], separators=(",", ":"))[:240],
            magnitude,
        )
    if "mean_min_hamming" in detail:
        return ("0", f"{detail['mean_min_hamming']:.1f}", magnitude)
    return (None, None, magnitude)


def _recent_duplicate(
    db: Session, agent_id: str, dominant_feature: str, now: datetime
) -> bool:
    """True if we already alerted on this feature within the dedup window."""
    cutoff = now - timedelta(hours=DEDUP_WINDOW_HOURS)
    prior = (
        db.query(DriftEvent)
        .filter(
            DriftEvent.agent_id == agent_id,
            DriftEvent.dominant_feature == dominant_feature,
            DriftEvent.detected_at >= cutoff,
        )
        .first()
    )
    return prior is not None


def maybe_fire_drift(
    db: Session, *, agent: Agent, verdict: dict
) -> DriftEvent | None:
    """Persist + deliver a drift alert if the verdict warrants one.

    Decision tree:
      1. Verdict has a ``reason`` (no baseline / no window / no comparable
         features) → no-op.
      2. ``drift_score`` below ``DRIFT_ALERT_THRESHOLD`` → no-op (the
         dashboard can still show it; we don't email marginal drift).
      3. No ``dominant_feature`` → no-op (nothing to attribute).
      4. A same-feature alert already fired within the dedup window →
         no-op.
      5. Otherwise: write the DriftEvent, then best-effort email + webhook.

    Returns the DriftEvent on a fired alert, else None. Never raises.
    """
    if verdict.get("reason"):
        return None
    drift_score = float(verdict.get("drift_score", 0.0) or 0.0)
    if drift_score < DRIFT_ALERT_THRESHOLD:
        return None
    dominant_feature = verdict.get("dominant_feature")
    if not dominant_feature:
        return None

    now = datetime.utcnow()
    if _recent_duplicate(db, agent.id, dominant_feature, now):
        return None

    baseline_value, current_value, magnitude = _attribution_summary(
        verdict.get("attribution") or {}
    )
    customer = resolve_customer(db, agent)

    event = DriftEvent(
        id=new_id("drift"),
        agent_id=agent.id,
        customer_id=customer.id if customer is not None else None,
        dominant_feature=dominant_feature,
        drift_score=drift_score,
        magnitude=magnitude,
        baseline_value=baseline_value,
        current_value=current_value,
        attribution_json=verdict.get("attribution") or {},
        window_size=verdict.get("window_size"),
        baseline_n_events=verdict.get("baseline_n_events"),
        detected_at=now,
    )
    db.add(event)
    db.commit()

    # Email — gated on the customer's drift toggle.
    try:
        if _send_drift_email(db, agent=agent, customer=customer, event=event):
            event.notified_email = True
    except Exception:
        log.exception("drift email fire failed for agent %s", agent.id)

    # Webhook — independent channel, same event.
    try:
        if webhook_delivery.fire_drift(db, agent=agent, drift_event=event) > 0:
            event.notified_webhook = True
    except Exception:
        log.exception("drift webhook fire failed for agent %s", agent.id)

    try:
        db.commit()
    except Exception:
        db.rollback()
    return event


def _send_drift_email(
    db: Session,
    *,
    agent: Agent,
    customer: Customer | None,
    event: DriftEvent,
) -> bool:
    """Render + send the drift email if prefs allow. Returns True if sent.

    Mirrors ``email_delivery.maybe_fire``'s gating: master ``alerts_enabled``
    AND the per-event ``drift_detected_enabled``. Absent prefs row = sane
    defaults (both on, recipient = the customer's auth email).
    """
    if customer is None:
        return False

    prefs = (
        db.query(EmailPreferences)
        .filter(EmailPreferences.customer_id == customer.id)
        .one_or_none()
    )
    if prefs is None:
        alerts_enabled = True
        drift_enabled = True
        alert_email = None
    else:
        alerts_enabled = prefs.alerts_enabled
        drift_enabled = prefs.drift_detected_enabled
        alert_email = prefs.alert_email

    if not alerts_enabled or not drift_enabled:
        return False

    recipient = alert_email or customer.email
    if not recipient:
        return False

    subject, html, text = email_delivery.render_drift_detected(
        agent_name=agent.name,
        agent_id=agent.id,
        public_slug=getattr(agent, "public_slug", None),
        dominant_feature=event.dominant_feature,
        drift_score=event.drift_score,
        baseline_value=event.baseline_value,
        current_value=event.current_value,
    )
    result = email_delivery.send_email(
        to=recipient, subject=subject, html=html, text=text
    )
    if not result.ok:
        log.warning(
            "drift_alerts: email send failed for customer %s — %s",
            customer.id,
            result.error,
        )
    return bool(result.ok)


def run_drift_check(db: Session, *, agent: Agent) -> DriftEvent | None:
    """Full per-agent drift pass: ensure baseline → compare → maybe alert.

    The single entry point the observable batch calls. Best-effort: a
    failure logs and returns None rather than breaking the recompute.
    """
    try:
        if not ensure_baseline(db, agent.id):
            return None
        verdict = compare_behavioral_to_baseline(
            db, agent.id, window_size=COMPARE_WINDOW_SIZE
        )
        return maybe_fire_drift(db, agent=agent, verdict=verdict)
    except Exception:
        db.rollback()
        log.exception("drift check failed for agent %s", agent.id)
        return None
