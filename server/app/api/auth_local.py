"""Local auth endpoints (gh-117) — login + change password.

Self-hosted Drift Engine owns its login. The dashboard posts admin
credentials here, gets a short-lived session JWT back, and sends it as
`Authorization: Bearer <jwt>` on subsequent API calls (validated by
`app.core.auth.require_auth`). No Supabase, no magic-link.

Routes (public plane — mounted without the /internal prefix):

  POST /auth/login
        {email, password} → {access_token, token_type, must_change_password}.
        401 on bad credentials (same message for unknown email vs wrong
        password, so the endpoint isn't an account-enumeration oracle).

  POST /auth/change-password   (requires a valid session)
        {current_password, new_password} → {ok: true}. Clears the
        must_change_password flag. The forced-change flow after a
        default-password first login goes through here.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core import local_auth
from app.core.auth import AuthContext, require_auth
from app.db.models import Customer
from app.db.session import get_db

log = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# Minimum length for a NEW password. Kept modest — this is a single-operator
# self-hosted tool, not a consumer SaaS — but enough to stop "1".
MIN_PASSWORD_LEN = 8


class LoginBody(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    email: str


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginBody, db: Session = Depends(get_db)) -> LoginResponse:
    email = (body.email or "").strip().lower()
    customer = (
        db.query(Customer).filter(Customer.email == email).first()
        if email
        else None
    )

    # Same failure for "no such account" and "wrong password" — don't leak
    # which emails exist. verify_password also returns False for accounts
    # with no password_hash (legacy Supabase customers), so they can't log
    # in via this path until a password is set.
    if customer is None or not local_auth.verify_password(
        body.password, customer.password_hash
    ):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = local_auth.mint_access_token(customer.id, customer.email)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        must_change_password=bool(customer.must_change_password),
        email=customer.email,
    )


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
def change_password(
    body: ChangePasswordBody,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    if auth.auth_type != "jwt":
        # API-key callers don't have a password to change.
        raise HTTPException(
            status_code=403,
            detail="Password change requires a session login, not an API key.",
        )

    customer = db.query(Customer).filter(Customer.id == auth.customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Account not found.")

    if not local_auth.verify_password(
        body.current_password, customer.password_hash
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    new_password = body.new_password or ""
    if len(new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"New password must be at least {MIN_PASSWORD_LEN} characters.",
        )
    if new_password == body.current_password:
        raise HTTPException(
            status_code=400,
            detail="New password must differ from the current one.",
        )

    try:
        customer.password_hash = local_auth.hash_password(new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    customer.must_change_password = False
    db.commit()
    log.info("Password changed for account %s", customer.id)
    return {"ok": True}
