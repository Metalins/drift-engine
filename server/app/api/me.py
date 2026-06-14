"""Customer-self endpoints — `/v1/me`.

Returns the authenticated customer's basic info. Designed for the dashboard
header ("Authenticated as <email>") and for the SDK to confirm a key is
valid + introspect plan.

Sprint UX-5.13 (2026-05-18): added /v1/me/email-preferences for
Andrea's alert delivery — see app/services/email_delivery.py.
"""
from __future__ import annotations

import logging
import re
import urllib.request

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.auth import AuthContext, require_auth
from app.core.ids import new_id
from app.db.models import EmailPreferences
from app.db.session import get_db


log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["customer"])


@router.get("/me")
def get_me(auth: AuthContext = Depends(require_auth)) -> dict:
    """Return the calling customer's profile.

    Works for both JWT (dashboard login) and API key (SDK) callers.
    The auth_type field lets the client tell the dashboard whether the
    current session came from magic-link or from a static key.
    """
    return {
        "customer_id": auth.customer_id,
        "email": auth.customer_email,
        "auth_type": auth.auth_type,
        "api_key_id": auth.api_key.id if auth.api_key else None,
        "api_key_name": auth.api_key.name if auth.api_key else None,
        # gh-118 — lets the dashboard show the "change your default password"
        # banner without a second round-trip. Always False for API keys.
        "must_change_password": auth.must_change_password,
    }


# --------------------------------------------------------------------------- #
# Email preferences                                                            #
# --------------------------------------------------------------------------- #
#
# Sprint UX-5.13.E.3 — read/write the customer's email_preferences
# row. Absent row = defaults; the GET endpoint synthesizes the defaults
# in-memory rather than auto-creating a row, so a customer who never
# touches /settings doesn't accumulate empty rows in the table.

# Pragmatic email-address regex. Not RFC 5321 perfect — that's a
# rabbit hole — but rejects the kinds of typos and shell-injection
# attempts that matter ("user@x" / "user@@x.com" / "<script>"). The
# real validation is that Resend will reject malformed addresses at
# send time; we just catch the obvious garbage early.
_EMAIL_RE = re.compile(r"^[^\s@<>'\"]+@[^\s@<>'\"]+\.[^\s@<>'\"]+$")


class EmailPreferencesIn(BaseModel):
    """PATCH body. All fields optional — only sent fields are updated."""

    alert_email: str | None = Field(default=None)
    alerts_enabled: bool | None = None
    threshold_crossed_enabled: bool | None = None
    drift_detected_enabled: bool | None = None
    weekly_digest_enabled: bool | None = None


def _serialize(prefs: EmailPreferences | None, fallback_email: str) -> dict:
    """Render an EmailPreferences row (or synthetic defaults) as JSON."""
    if prefs is None:
        return {
            "alert_email": None,
            "effective_email": fallback_email,
            "alerts_enabled": True,
            "threshold_crossed_enabled": True,
            "drift_detected_enabled": True,
            "weekly_digest_enabled": False,
            "is_default": True,
        }
    return {
        "alert_email": prefs.alert_email,
        "effective_email": prefs.alert_email or fallback_email,
        "alerts_enabled": prefs.alerts_enabled,
        "threshold_crossed_enabled": prefs.threshold_crossed_enabled,
        "drift_detected_enabled": prefs.drift_detected_enabled,
        "weekly_digest_enabled": prefs.weekly_digest_enabled,
        "is_default": False,
    }


@router.get("/me/email-preferences")
def get_email_preferences(
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Return the current customer's email preferences.

    If no row exists yet, returns the defaults with `is_default=true`
    so the dashboard knows to show placeholders rather than "no
    preferences configured". `effective_email` is the address we'd
    actually send to right now — `alert_email` if set, otherwise the
    auth email.
    """
    prefs = (
        db.query(EmailPreferences)
        .filter(EmailPreferences.customer_id == auth.customer_id)
        .one_or_none()
    )
    return _serialize(prefs, fallback_email=auth.customer_email or "")


@router.patch("/me/email-preferences")
def update_email_preferences(
    body: EmailPreferencesIn,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Upsert the current customer's email preferences.

    Only sent fields are touched — missing fields keep their current
    value (or the default if the row didn't exist yet). Passing
    `alert_email: ""` is treated as "clear it, fall back to auth
    email" — useful from the UI's "remove" button.
    """
    # Validate email format BEFORE touching the DB.
    if body.alert_email is not None:
        email_clean = body.alert_email.strip()
        if email_clean and not _EMAIL_RE.match(email_clean):
            raise HTTPException(
                status_code=400, detail="alert_email is not a valid email address"
            )

    prefs = (
        db.query(EmailPreferences)
        .filter(EmailPreferences.customer_id == auth.customer_id)
        .one_or_none()
    )
    if prefs is None:
        prefs = EmailPreferences(customer_id=auth.customer_id)
        db.add(prefs)

    if body.alert_email is not None:
        clean = body.alert_email.strip()
        prefs.alert_email = clean if clean else None
    if body.alerts_enabled is not None:
        prefs.alerts_enabled = body.alerts_enabled
    if body.threshold_crossed_enabled is not None:
        prefs.threshold_crossed_enabled = body.threshold_crossed_enabled
    if body.drift_detected_enabled is not None:
        prefs.drift_detected_enabled = body.drift_detected_enabled
    if body.weekly_digest_enabled is not None:
        prefs.weekly_digest_enabled = body.weekly_digest_enabled

    db.commit()
    db.refresh(prefs)
    return _serialize(prefs, fallback_email=auth.customer_email or "")


# --------------------------------------------------------------------------- #
# Account deletion                                                             #
# --------------------------------------------------------------------------- #
#
# Free tier, immediate (Jose, 2026-05-22). Deleting an account wipes
# EVERYTHING tied to the customer — every agent and all of its data,
# the customer's account-level rows, the customer record. We keep no
# user data afterwards; the one survivor is an `account_deletions`
# audit row (which email, when, the mandatory reason).


class DeleteAccountRequest(BaseModel):
    """Body for POST /v1/me/delete. `reason` is mandatory."""

    reason: str


def _delete_supabase_user(user_id: str) -> None:
    """Remove the customer's Supabase `auth.users` record via the Admin
    API. Best-effort: if the service-role key isn't configured, or the
    call fails, we log and move on — the application data is already
    gone, which is the part that matters for cost and privacy."""
    key = settings.supabase_service_role_key
    base = settings.supabase_url
    if not key or not base:
        log.warning(
            "account deletion: supabase service-role key/url unset — "
            "auth.users record for %s NOT removed",
            user_id,
        )
        return
    req = urllib.request.Request(
        f"{base.rstrip('/')}/auth/v1/admin/users/{user_id}",
        method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception:  # noqa: BLE001 — best-effort, never block deletion
        log.exception(
            "account deletion: failed to delete supabase auth user %s",
            user_id,
        )


@router.post("/me/delete")
def delete_account(
    body: DeleteAccountRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    """Permanently delete the calling customer's account.

    Free tier: immediate, no grace period. Wipes every agent the
    customer owns and all of its data — events, event logs,
    observables, memory checks, proofs, watchers, webhooks, anchors,
    API keys — plus the customer's account-level rows and the customer
    record. The only thing kept is one `account_deletions` audit row.

    `reason` is required (HTTP 400 if blank). The Supabase auth record
    is also removed when the service-role key is configured.
    """
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required.")

    from app.db.models import (
        AccountDeletion,
        Agent,
        AgentAnchor,
        AgentMeshPair,
        AgentObservable,
        AgentState,
        APIKey,
        CorroborationPoint,
        Customer,
        EventLog,
        MemoryProbe,
        PredictionSubmission,
        Verification,
        Watcher,
        WebhookEndpoint,
        ZKHProof,
    )

    customer_id = auth.customer_id
    email = auth.customer_email or ""

    # Every agent owned by this customer (Agent → APIKey → customer).
    agent_ids = [
        row[0]
        for row in db.query(Agent.id)
        .join(APIKey, Agent.api_key_id == APIKey.id)
        .filter(APIKey.customer_id == customer_id)
        .all()
    ]

    # 1. Per-agent child rows. Mirrors the wipe list in
    #    agents.revoke_agent — keep the two in sync if either grows.
    if agent_ids:
        for model in (
            AgentObservable,
            MemoryProbe,
            EventLog,
            Watcher,
            Verification,
            WebhookEndpoint,
            AgentAnchor,
            PredictionSubmission,
            ZKHProof,
            AgentState,
        ):
            db.query(model).filter(model.agent_id.in_(agent_ids)).delete(
                synchronize_session=False
            )

    # 2. Mesh pairs this customer owns (by customer_id or by any of its
    #    agents) + their corroboration points — before the agents,
    #    which the pairs FK-reference.
    mesh_pair_ids = [
        r[0]
        for r in db.query(AgentMeshPair.id)
        .filter(
            (AgentMeshPair.customer_id == customer_id)
            | (AgentMeshPair.agent_a_id.in_(agent_ids))
            | (AgentMeshPair.agent_b_id.in_(agent_ids))
        )
        .all()
    ]
    if mesh_pair_ids:
        db.query(CorroborationPoint).filter(
            CorroborationPoint.mesh_pair_id.in_(mesh_pair_ids)
        ).delete(synchronize_session=False)
        db.query(AgentMeshPair).filter(
            AgentMeshPair.id.in_(mesh_pair_ids)
        ).delete(synchronize_session=False)

    # 3. The agents themselves — before the API keys they point at.
    if agent_ids:
        db.query(Agent).filter(Agent.id.in_(agent_ids)).delete(
            synchronize_session=False
        )

    # 4. Remaining account-level rows.
    db.query(EmailPreferences).filter(
        EmailPreferences.customer_id == customer_id
    ).delete(synchronize_session=False)
    db.query(APIKey).filter(APIKey.customer_id == customer_id).delete(
        synchronize_session=False
    )

    # 5. The one row we keep — the audit record.
    db.add(
        AccountDeletion(id=new_id("acctdel"), email=email, reason=reason)
    )

    # 6. The customer record itself.
    db.query(Customer).filter(Customer.id == customer_id).delete(
        synchronize_session=False
    )
    db.commit()

    # 7. Remove the Supabase login record (best-effort).
    _delete_supabase_user(customer_id)

    return {"ok": True}
