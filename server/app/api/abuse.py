"""Anti-abuse — unsolicited-email reporting + the login flag check.

Phase-2 of the anti-abuse flow (Jose, 2026-05-21).

The magic-link email carries a "this wasn't me" link. A recipient who
never asked for the email can click it to flag their own address as an
unsolicited sign-in request. While the flag stands, the dashboard login
page refuses to send another magic link to that address and shows a
"contact support" message instead.

Two endpoints, both public (no auth — this all happens pre-login):

  POST /v1/auth-email/report-unsolicited
        Record a flag. Gated by a Cloudflare Turnstile human-check so
        the flag cannot be scripted in bulk.

  GET  /v1/auth-email/status?email=...
        Is this address currently flagged? The login page calls it
        before sending a magic link.

Design rule: a flag NEVER hard-bans. The report link travels inside an
email anyone could have triggered, so the worst a flag does is add a
one-time "contact support" detour. Support clears it (`cleared_at`).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.db.models import FlaggedEmail

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth-email", tags=["anti-abuse"])

_TURNSTILE_VERIFY_URL = (
    "https://challenges.cloudflare.com/turnstile/v0/siteverify"
)
_TURNSTILE_TIMEOUT_SECONDS = 5


class ReportUnsolicitedBody(BaseModel):
    email: str
    turnstile_token: str


def _normalize(email: str) -> str:
    return email.strip().lower()


def _verify_turnstile(token: str) -> bool:
    """Verify a Cloudflare Turnstile token server-side.

    Fails CLOSED: if the secret isn't configured, or the call errors,
    or the token is rejected, returns False. We never record a flag
    without a confirmed human — so the feature is simply inert until
    `METALINS_TURNSTILE_SECRET` is set, rather than wide open.
    """
    secret = settings.turnstile_secret
    if not secret:
        log.warning(
            "auth-email: METALINS_TURNSTILE_SECRET unset — report rejected"
        )
        return False
    data = urllib.parse.urlencode(
        {"secret": secret, "response": token}
    ).encode("utf-8")
    req = urllib.request.Request(
        _TURNSTILE_VERIFY_URL, data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(
            req, timeout=_TURNSTILE_TIMEOUT_SECONDS
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return bool(body.get("success"))
    except Exception:  # noqa: BLE001 — any failure → fail closed
        log.exception("auth-email: turnstile verification call failed")
        return False


@router.post("/report-unsolicited", status_code=200)
def report_unsolicited(
    body: ReportUnsolicitedBody, db: Session = Depends(get_db)
):
    """Record an email address as an unsolicited sign-in request.

    Idempotent: a second report for an already-flagged address just
    bumps `report_count`; a report for a previously-cleared address
    re-opens the flag.
    """
    email = _normalize(body.email)
    if not email or "@" not in email:
        raise HTTPException(
            status_code=400, detail="A valid email is required."
        )
    if not _verify_turnstile(body.turnstile_token):
        raise HTTPException(
            status_code=400,
            detail="Human verification failed. Please try again.",
        )

    row = (
        db.query(FlaggedEmail)
        .filter(FlaggedEmail.email == email)
        .one_or_none()
    )
    if row is None:
        db.add(FlaggedEmail(email=email))
    else:
        row.report_count = (row.report_count or 0) + 1
        if row.cleared_at is not None:
            # A fresh report on a cleared address re-opens it.
            row.cleared_at = None
            row.flagged_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.get("/status")
def auth_email_status(email: str, db: Session = Depends(get_db)):
    """Whether an address is currently flagged.

    Public — the login page calls it before sending a magic link. The
    response is only a boolean, so it leaks nothing about whether a
    Metalins account exists for the address.
    """
    row = (
        db.query(FlaggedEmail)
        .filter(
            FlaggedEmail.email == _normalize(email),
            FlaggedEmail.cleared_at.is_(None),
        )
        .one_or_none()
    )
    return {"flagged": row is not None}
