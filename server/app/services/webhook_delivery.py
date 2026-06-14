"""Webhook delivery service.

Sprint UX-5.10-6 (#664). Fires HTTPS POSTs to customer-configured
webhook endpoints when an agent's `verification_state` transitions to
a level that warrants attention (caution / action).

Design choices
--------------
- HMAC-SHA256 over the body using the webhook's plaintext secret
  (which the customer keeps locally; we keep only its hash). Header:
  `X-Metalins-Signature: sha256=<hex>`. Customer validates by
  recomputing.
- Synchronous best-effort delivery from inside the recompute path.
  V1 — no retry queue. We log the last status + error on the
  WebhookEndpoint row; the customer's dashboard shows it. If a
  customer's endpoint is flaky, they see it and fix it.
- We trigger ONLY on transitions INTO caution or action. Going back
  to verified is reassuring but doesn't need a wake-up; we'll add a
  "resolved" payload in V1.1 once we know customers actually want it.
- Timeout = 5 s. Cloud Run requests routinely complete in 100 ms;
  longer than that and the customer's endpoint is too slow to be
  alerting infrastructure.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Agent, WebhookEndpoint


log = logging.getLogger(__name__)


_FIRING_STATES = {"caution", "action_required"}
"""Cryptographic-layer states that warrant a wake-up. Sprint UX-5.12
renamed `action` → `action_required` for the two-layer trust model.
Other transitions are silent:
  - verified → verified is a no-op.
  - unverified → verified is good news (no alert).
  - revoked is initiated by the customer themselves (no alert).
  - Behavioral-layer transitions (building → stable, etc.) NEVER fire
    webhooks. Only cryptographic transitions do, per design doc §3.1."""


_REQUEST_TIMEOUT_SECONDS = 5


def maybe_fire(
    db: Session,
    *,
    agent: Agent,
    previous_state: str,
    new_state: str,
    confidence: float | None,
    score_factors: list,
) -> None:
    """Fire webhooks if the transition warrants it.

    Pure no-op on the common path (state unchanged or going back to
    healthy). When firing, runs through every active webhook for the
    agent — same payload, separate request each.
    """
    if new_state == previous_state:
        return
    if new_state not in _FIRING_STATES:
        return

    webhooks = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.agent_id == agent.id,
            WebhookEndpoint.is_active.is_(True),
            WebhookEndpoint.deleted_at.is_(None),
        )
        .all()
    )
    if not webhooks:
        return

    payload = {
        "event": "verification_state.changed",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "public_slug": getattr(agent, "public_slug", None),
        "previous_state": previous_state,
        "new_state": new_state,
        "confidence": confidence,
        "score_factors": score_factors,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    for wh in webhooks:
        # We don't have the plaintext secret (only the hash). The
        # customer KEEPS the plaintext from creation time and signs
        # locally to verify. So we sign with the HASH of the secret
        # — which is also what the customer has reproducibly (they
        # know the plaintext, can hash it, and use the hash for HMAC).
        # Simpler than keeping plaintext secrets server-side.
        sig = hmac.new(
            wh.secret_hash.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        _deliver(db, wh, body, sig)


def fire_drift(db: Session, *, agent: Agent, drift_event) -> int:
    """Fire ``behavioral_drift.detected`` webhooks for a drift event (#64).

    Parallel to ``maybe_fire`` but driven by the κ-engine V2 behavioral
    pipeline instead of the cryptographic state machine. Same HMAC
    signing + best-effort delivery. Returns the number of endpoints we
    attempted to deliver to (0 when the agent has no active webhooks).

    The caller (``services.drift_alerts``) decides WHETHER a drift is
    alert-worthy; this function just delivers an already-decided event.
    """
    webhooks = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.agent_id == agent.id,
            WebhookEndpoint.is_active.is_(True),
            WebhookEndpoint.deleted_at.is_(None),
        )
        .all()
    )
    if not webhooks:
        return 0

    payload = {
        "event": "behavioral_drift.detected",
        "agent_id": agent.id,
        "agent_name": agent.name,
        "public_slug": getattr(agent, "public_slug", None),
        "dominant_feature": drift_event.dominant_feature,
        "drift_score": drift_event.drift_score,
        "baseline_value": drift_event.baseline_value,
        "current_value": drift_event.current_value,
        "magnitude": drift_event.magnitude,
        "detected_at": (
            drift_event.detected_at.isoformat() + "Z"
            if drift_event.detected_at is not None
            else None
        ),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    for wh in webhooks:
        sig = hmac.new(
            wh.secret_hash.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        _deliver(db, wh, body, sig)
    return len(webhooks)


def _deliver(
    db: Session, wh: WebhookEndpoint, body: bytes, sig: str
) -> None:
    """Single HTTP POST. Best-effort. Logs outcome on the row."""
    req = urllib.request.Request(
        wh.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Metalins-Signature": f"sha256={sig}",
            "User-Agent": "Metalins-Webhook/1.0",
        },
    )
    try:
        with urllib.request.urlopen(
            req, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as resp:
            wh.last_delivery_status = resp.status
            wh.last_delivery_error = None
    except urllib.error.HTTPError as e:
        wh.last_delivery_status = e.code
        wh.last_delivery_error = f"HTTP {e.code}"
        log.warning("webhook %s delivery failed: HTTP %d", wh.id, e.code)
    except urllib.error.URLError as e:
        wh.last_delivery_status = None
        wh.last_delivery_error = f"network: {e.reason}"
        log.warning("webhook %s delivery failed: %s", wh.id, e.reason)
    except Exception as e:  # noqa: BLE001 — last-resort safety net
        wh.last_delivery_status = None
        wh.last_delivery_error = f"{type(e).__name__}: {e}"
        log.exception("webhook %s unexpected delivery error", wh.id)
    wh.last_delivery_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
