"""Email delivery service via Resend.

Sprint UX-5.13 (2026-05-18). Mirror of `webhook_delivery.py`'s shape:
synchronous best-effort delivery, no queue, no retry, logs outcome on
the caller's row (when there is one). Provider-agnostic at the call
site — the rest of the codebase calls `send_alert_email(...)` and
doesn't care that the implementation is Resend.

Why we picked Resend
--------------------
- Free tier covers 3,000 messages/month + 100/day, no credit card.
  Andrea's "I want alerts about my own AI" use case is well below
  that ceiling even at 100% conversion of our early users.
- HTTP API is one POST with JSON. No SDK needed, no SMTP/STARTTLS
  ritual, no library that brings 20 transitive deps. We use the same
  `urllib` shape as `webhook_delivery.py`.
- Plays nicely as Supabase Auth's SMTP backend later (Sprint UX-5.13
  step E.6), so the magic-link email can use the same verified
  sending domain (`auth@contact.metalins.ai`).

What we do NOT do
-----------------
- Retries / DLQ / dedup — same V1 design as webhooks: log + move on.
  If Resend is down for a stretch, the customer sees missed alerts.
  At our V1 volume the failure rate is rounding error; we'll add a
  proper outbox table when our second customer ships their first
  prod incident.
- Templating engine — V1 emails are hand-written HTML+text strings
  per event type, kept inline below. When we have 5+ event types
  we'll move to a `templates/` dir with Jinja or similar; today
  hand-written is cheaper.
- Tracking pixels / open tracking — privacy-preserving by default.
  Customer-facing principle (D-PROD.18 family): we don't tell you
  more than you asked us to do.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Agent, Customer, EmailPreferences


log = logging.getLogger(__name__)


_RESEND_ENDPOINT = "https://api.resend.com/emails"
_REQUEST_TIMEOUT_SECONDS = 5


_FIRING_STATES = {"caution", "action_required"}
"""Cryptographic-layer states that warrant an email. Mirrors the
webhook-delivery firing logic — same gates, parallel channels. The
two delivery services are intentionally independent: a customer can
get email + webhook + neither (legacy) without either side knowing
about the other."""


class EmailDeliveryResult:
    """Outcome of a single send attempt — small dataclass-shaped record
    rather than a tuple so callers can read field names in logs."""

    __slots__ = ("ok", "provider_id", "status_code", "error", "sent_at")

    def __init__(
        self,
        *,
        ok: bool,
        provider_id: str | None = None,
        status_code: int | None = None,
        error: str | None = None,
    ) -> None:
        self.ok = ok
        self.provider_id = provider_id
        self.status_code = status_code
        self.error = error
        self.sent_at = datetime.utcnow()

    def __repr__(self) -> str:
        if self.ok:
            return f"<EmailDeliveryResult ok provider_id={self.provider_id!r}>"
        return (
            f"<EmailDeliveryResult fail status={self.status_code} "
            f"error={self.error!r}>"
        )


# --------------------------------------------------------------------------- #
# Public entry points                                                          #
# --------------------------------------------------------------------------- #


def send_email(
    *,
    to: str | Iterable[str],
    subject: str,
    html: str,
    text: str,
    from_address: str | None = None,
    reply_to: str | None = None,
) -> EmailDeliveryResult:
    """Send a single email. Returns the delivery result.

    `from_address` defaults to `settings.email_from_noreply`; the
    `auth` variant exists for cases where we send on behalf of the
    auth flow rather than the alerting flow.

    The function NEVER raises on transport errors. Callers that need
    to react to failure should inspect `result.ok`. This matches the
    webhook-delivery contract — the alert pipeline must not break
    when the provider is having a bad day.
    """
    api_key = settings.resend_api_key
    if not api_key:
        log.warning(
            "email_delivery: METALINS_RESEND_API_KEY not set — "
            "skipping send (to=%r, subject=%r)",
            to,
            subject,
        )
        return EmailDeliveryResult(
            ok=False, error="provider_unconfigured"
        )

    if isinstance(to, str):
        recipients = [to]
    else:
        recipients = list(to)
    if not recipients:
        return EmailDeliveryResult(ok=False, error="no_recipients")

    payload: dict = {
        "from": from_address or settings.email_from_noreply,
        "to": recipients,
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _RESEND_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Metalins-Email/1.0",
        },
    )
    try:
        with urllib.request.urlopen(
            req, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as resp:
            raw = resp.read()
            data = json.loads(raw.decode("utf-8")) if raw else {}
            provider_id = data.get("id")
            return EmailDeliveryResult(
                ok=True, provider_id=provider_id, status_code=resp.status
            )
    except urllib.error.HTTPError as e:
        # Resend returns useful 4xx bodies — surface the message to
        # logs so we can debug bad-from / unverified-domain / quota
        # mistakes quickly.
        detail = "?"
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        log.warning(
            "email_delivery: HTTP %d sending to %r — %s",
            e.code,
            recipients,
            detail,
        )
        return EmailDeliveryResult(
            ok=False, status_code=e.code, error=f"http_{e.code}:{detail[:200]}"
        )
    except urllib.error.URLError as e:
        log.warning(
            "email_delivery: network error sending to %r — %s",
            recipients,
            e.reason,
        )
        return EmailDeliveryResult(
            ok=False, error=f"network:{e.reason}"
        )
    except Exception as e:  # noqa: BLE001 — last-resort safety net
        log.exception(
            "email_delivery: unexpected error sending to %r", recipients
        )
        return EmailDeliveryResult(
            ok=False, error=f"{type(e).__name__}:{e}"
        )


# --------------------------------------------------------------------------- #
# Pre-rendered alert templates                                                 #
# --------------------------------------------------------------------------- #
#
# V1 templates are inline. Each function takes the data it needs and
# returns `(subject, html, text)`. The caller passes those to
# `send_email`. Splitting render from send keeps the send function
# pure and the templates trivially testable.

def _verify_url_for(
    *, public_slug: str | None, agent_id: str
) -> str:
    """Public-facing verify URL — slug if we have one, agent_id
    fallback. Matches the dashboard's behavior so the email link
    survives the agent migrating from "no slug" to "slug" mid-life."""
    base = settings.public_base_url.rstrip("/")
    if public_slug:
        return f"{base}/v/{public_slug}"
    return f"{base}/verify/{agent_id}"


def render_state_changed(
    *,
    agent_name: str,
    agent_id: str,
    public_slug: str | None,
    previous_state: str,
    new_state: str,
    confidence: float | None,
) -> tuple[str, str, str]:
    """Email for verification_state.changed events.

    Mirrors the webhook payload semantically but reads like prose. We
    do NOT name internal mechanisms (D-PROD.18) — the user sees only
    "identity confidence" / "verification state" language.
    """
    if new_state == "action_required":
        verb = "needs your attention"
        body_intro = (
            "We detected unusual activity on this agent. The identity "
            "signals look very different from before, which usually "
            "means the agent's credentials were leaked, the model "
            "behind it was swapped, or another agent is logging events "
            "under its name."
        )
        recommended_action = (
            "Review the agent in your dashboard. If you didn't expect "
            "any change, revoke this agent and register a fresh one."
        )
    elif new_state == "caution":
        verb = "is worth a look"
        body_intro = (
            "Identity confidence dipped on this agent. Most likely a "
            "temporary blip — but worth confirming nothing unusual "
            "happened."
        )
        recommended_action = (
            "Open the agent in your dashboard to see which signals "
            "shifted and decide if action is needed."
        )
    else:
        verb = "changed state"
        body_intro = f"State transitioned from {previous_state} to {new_state}."
        recommended_action = "Review the agent in your dashboard."

    verify_url = _verify_url_for(public_slug=public_slug, agent_id=agent_id)
    dashboard_url = f"{settings.public_base_url.rstrip('/')}/agents/{agent_id}"

    subject = f"[Metalins] {agent_name} {verb}"

    text = f"""Hi,

{body_intro}

Agent: {agent_name}
Previous state: {previous_state}
New state: {new_state}
Identity confidence: {confidence if confidence is not None else "—"}

Recommended next step:
{recommended_action}

Dashboard: {dashboard_url}
Public verify page: {verify_url}

— Metalins
You're receiving this because alerts are turned on for your account.
Manage email preferences in your dashboard settings.
"""

    # Minimal inline-styled HTML — email clients are a hostile rendering
    # environment, so we lean into the conservative subset that works
    # everywhere (no CSS files, no background-images, no <style> blocks).
    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111;background:#fafafa;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:32px;">
    <h1 style="margin:0 0 16px;font-size:20px;font-weight:600;">
      {agent_name} {verb}
    </h1>
    <p style="margin:0 0 16px;line-height:1.55;color:#444;">{body_intro}</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">
      <tr>
        <td style="padding:8px 0;color:#666;width:40%;">Previous state</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{previous_state}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666;">New state</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{new_state}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666;">Identity confidence</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{confidence if confidence is not None else "—"}</td>
      </tr>
    </table>
    <p style="margin:24px 0 8px;font-weight:600;">Recommended next step</p>
    <p style="margin:0 0 24px;line-height:1.55;color:#444;">{recommended_action}</p>
    <p style="margin:0;">
      <a href="{dashboard_url}" style="display:inline-block;padding:10px 16px;background:#111;color:#fff;text-decoration:none;border-radius:8px;font-weight:500;">Open dashboard →</a>
    </p>
    <p style="margin:16px 0 0;font-size:13px;color:#666;">
      Public verify link:
      <a href="{verify_url}" style="color:#666;">{verify_url}</a>
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:32px 0 16px;">
    <p style="margin:0;font-size:12px;color:#888;line-height:1.5;">
      You're receiving this because alerts are turned on for your account.
      <a href="{settings.public_base_url.rstrip('/')}/settings" style="color:#666;">Manage email preferences →</a>
    </p>
  </div>
</body></html>"""

    return subject, html, text


# Human-readable labels for the κ-engine V2 behavioral features. The
# raw feature names are product-level (not internal crypto mechanisms,
# so they're not under the D-PROD.18 jargon ban), but customers read
# "response length" more easily than "output_length_chars".
_FEATURE_LABELS = {
    "output_length_chars": "response length",
    "output_length_tokens": "response length",
    "input_length_chars": "prompt length",
    "sentence_count_output": "response structure",
    "mean_sentence_length_output": "sentence length",
    "latency_ms": "response latency",
    "had_code_block": "code formatting",
    "had_list": "list formatting",
    "had_markdown": "markdown formatting",
    "error_class": "error pattern",
    "tool_calls": "tool usage",
    "tool_bigrams": "tool sequencing",
    "token_bag_lsh": "vocabulary",
}


def feature_label(feature: str | None) -> str:
    """Customer-facing label for a behavioral feature name."""
    if not feature:
        return "behavior"
    return _FEATURE_LABELS.get(feature, feature.replace("_", " "))


def render_drift_detected(
    *,
    agent_name: str,
    agent_id: str,
    public_slug: str | None,
    dominant_feature: str | None,
    drift_score: float,
    baseline_value: str | None,
    current_value: str | None,
) -> tuple[str, str, str]:
    """Email for ``behavioral_drift.detected`` events (#64).

    The κ-engine V2 learned this agent's behavioral baseline and a fresh
    window of its traffic drifted away from it. We describe WHAT changed
    (the dominant feature) and the before/after, in plain language —
    never the statistical machinery (KS / Wasserstein / TVD). A drift can
    mean a model swap, a prompt-injection takeover, or organic concept
    drift; we surface the signal and let the customer judge.
    """
    label = feature_label(dominant_feature)
    pct = max(0, min(100, int(round(drift_score * 100))))

    body_intro = (
        f"Metalins learned this agent's normal behavior and just noticed "
        f"its {label} drift away from that baseline. A change like this "
        f"usually means the model behind the agent was swapped, its "
        f"instructions were altered or injected, or its task genuinely "
        f"shifted — worth a look either way."
    )
    recommended_action = (
        "Open the agent in your dashboard to see the full behavioral "
        "timeline. If you expected this change, mark it as expected to "
        "update the baseline. If you didn't, treat the agent as suspect "
        "until you've confirmed what changed."
    )

    verify_url = _verify_url_for(public_slug=public_slug, agent_id=agent_id)
    dashboard_url = f"{settings.public_base_url.rstrip('/')}/agents/{agent_id}"

    subject = f"[Metalins] {agent_name} — behavioral change detected"

    before = baseline_value if baseline_value is not None else "—"
    after = current_value if current_value is not None else "—"

    text = f"""Hi,

{body_intro}

Agent: {agent_name}
What changed: {label}
Baseline: {before}
Now: {after}
Change strength: {pct}%

Recommended next step:
{recommended_action}

Dashboard: {dashboard_url}
Public verify page: {verify_url}

— Metalins
You're receiving this because behavioral drift alerts are turned on for
your account. Manage email preferences in your dashboard settings.
"""

    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#111;background:#fafafa;">
  <div style="max-width:560px;margin:0 auto;background:#fff;border:1px solid #e5e5e5;border-radius:12px;padding:32px;">
    <h1 style="margin:0 0 16px;font-size:20px;font-weight:600;">
      {agent_name} — behavioral change detected
    </h1>
    <p style="margin:0 0 16px;line-height:1.55;color:#444;">{body_intro}</p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">
      <tr>
        <td style="padding:8px 0;color:#666;width:40%;">What changed</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{label}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666;">Baseline</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{before}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666;">Now</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{after}</td>
      </tr>
      <tr>
        <td style="padding:8px 0;color:#666;">Change strength</td>
        <td style="padding:8px 0;font-family:ui-monospace,Menlo,monospace;">{pct}%</td>
      </tr>
    </table>
    <p style="margin:24px 0 8px;font-weight:600;">Recommended next step</p>
    <p style="margin:0 0 24px;line-height:1.55;color:#444;">{recommended_action}</p>
    <p style="margin:0;">
      <a href="{dashboard_url}" style="display:inline-block;padding:10px 16px;background:#111;color:#fff;text-decoration:none;border-radius:8px;font-weight:500;">Open dashboard →</a>
    </p>
    <p style="margin:16px 0 0;font-size:13px;color:#666;">
      Public verify link:
      <a href="{verify_url}" style="color:#666;">{verify_url}</a>
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:32px 0 16px;">
    <p style="margin:0;font-size:12px;color:#888;line-height:1.5;">
      You're receiving this because behavioral drift alerts are turned on
      for your account.
      <a href="{settings.public_base_url.rstrip('/')}/settings" style="color:#666;">Manage email preferences →</a>
    </p>
  </div>
</body></html>"""

    return subject, html, text


# --------------------------------------------------------------------------- #
# High-level entry point used by the alert pipeline                            #
# --------------------------------------------------------------------------- #


def maybe_fire(
    db: Session,
    *,
    agent: Agent,
    previous_state: str,
    new_state: str,
    confidence: float | None,
) -> EmailDeliveryResult | None:
    """Fire an alert email if the state transition + customer prefs
    warrant it. Returns None when we deliberately don't send (silent
    no-op for clean paths).

    Decision tree:
      1. No transition into caution / action_required → no-op.
      2. Customer has no email_preferences row → use defaults (alerts
         on, threshold_crossed on, alert_email = auth email).
      3. `alerts_enabled` master switch is off → no-op.
      4. `threshold_crossed_enabled` is off → no-op.
      5. Effective recipient address is empty → no-op.
      6. Otherwise: render + send.

    The function NEVER raises on infrastructure errors — the alert
    pipeline must keep flowing. Returns an EmailDeliveryResult so
    callers that care can log success/failure.
    """
    if new_state == previous_state:
        return None
    if new_state not in _FIRING_STATES:
        return None

    customer = (
        db.query(Customer).filter(Customer.id == agent.customer_id).one_or_none()
    )
    if customer is None:
        # Orphan agent — shouldn't happen, but defending against it.
        log.warning(
            "email_delivery.maybe_fire: agent %s has no customer", agent.id
        )
        return None

    prefs = (
        db.query(EmailPreferences)
        .filter(EmailPreferences.customer_id == agent.customer_id)
        .one_or_none()
    )

    # Resolve effective flags + recipient. Absent row = permissive
    # defaults that match the dashboard's "is_default" rendering.
    if prefs is None:
        alerts_enabled = True
        threshold_crossed_enabled = True
        alert_email = None
    else:
        alerts_enabled = prefs.alerts_enabled
        threshold_crossed_enabled = prefs.threshold_crossed_enabled
        alert_email = prefs.alert_email

    if not alerts_enabled or not threshold_crossed_enabled:
        return None

    recipient = alert_email or customer.email
    if not recipient:
        log.warning(
            "email_delivery.maybe_fire: no recipient for customer %s",
            agent.customer_id,
        )
        return None

    subject, html, text = render_state_changed(
        agent_name=agent.name,
        agent_id=agent.id,
        public_slug=getattr(agent, "public_slug", None),
        previous_state=previous_state,
        new_state=new_state,
        confidence=confidence,
    )
    result = send_email(
        to=recipient, subject=subject, html=html, text=text
    )
    if not result.ok:
        log.warning(
            "email_delivery.maybe_fire: send failed for customer %s — %s",
            agent.customer_id,
            result.error,
        )
    return result
