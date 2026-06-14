"""API auth dependencies — dual auth (API key | Supabase JWT) per D-PROD.17.

Two callers reach the API:
  - SDK + scripts → present a Bearer `ml_live_*` API key.
  - Dashboard      → presents a Bearer Supabase JWT (HS256, signed with
                     SUPABASE_JWT_SECRET).

Both paths produce an `AuthContext` carrying the customer_id (the unit of
ownership for agents, observables, probes) and, when API-key auth was used,
the api_key row (so legacy queries that filter by api_key_id still work).

Legacy `require_api_key` is preserved for existing endpoints — new endpoints
should call `require_auth` instead.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import Header, HTTPException, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.db.models import APIKey, Customer


# Sprint UX-5.11 — Synthetic User Validation framework. Canonical sandbox
# tenant used by the bypass-auth path. Created by
# scripts/migrate-sprint-ux-5-11-synthetic-user.sql (applied via Supabase
# MCP on 2026-05-17). The UUID is intentionally all-zeros-with-trailing-1
# so it cannot collide with a Supabase-issued auth.users.id (v4).
TEST_USER_BYPASS_ID = "00000000-0000-0000-0000-000000000001"
TEST_USER_BYPASS_EMAIL = "testing@metalins.local"


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _expected_bypass_signature(secret: str) -> str:
    """Compute the HMAC-SHA256 hex digest the bypass header must carry.

    Domain-separated by the test user's email so that the same secret cannot
    be repurposed as a generic auth shared-secret. Callers (persona runner,
    smoke scripts) reproduce this exact computation locally.
    """
    return hmac.new(
        secret.encode("utf-8"),
        TEST_USER_BYPASS_EMAIL.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# --------------------------------------------------------------------------- #
# Legacy API-key-only dependency (still used by SDK-facing endpoints)         #
# --------------------------------------------------------------------------- #


def require_api_key(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> APIKey:
    """Validate Bearer API key and return APIKey row.

    Preserved as a thin wrapper for SDK endpoints that explicitly do NOT
    accept JWT (e.g. agent registration, event logging — these are programmatic
    and a session cookie there would be a smell).
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    raw_key = authorization[len("Bearer "):].strip()
    if not raw_key:
        raise HTTPException(status_code=401, detail="Empty Bearer token")

    api_key = (
        db.query(APIKey).filter(APIKey.key_hash == _hash_key(raw_key)).first()
    )
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    api_key.last_used_at = datetime.utcnow()
    db.commit()
    return api_key


# --------------------------------------------------------------------------- #
# Dual auth (API key OR Supabase JWT)                                         #
# --------------------------------------------------------------------------- #


@dataclass
class AuthContext:
    """Caller identity, normalized across both auth types.

    customer_id is the unit of ownership. For an API-key call, it comes from
    api_key.customer_id; for a JWT call, from jwt.sub. Both are validated to
    correspond to a real customers row.

    When auth_type == "api_key", api_key holds the row (for backward-compat
    with endpoints that filter by api_key_id, like agent registration).
    When auth_type == "jwt", api_key is None.
    """

    auth_type: Literal["api_key", "jwt"]
    customer_id: str
    customer_email: str
    api_key: APIKey | None = None


# Module-level JWKS cache (Supabase rotates rarely; 1h TTL is fine).
_JWKS_CACHE: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


def _fetch_jwks() -> dict:
    """Fetch (and cache) Supabase's JWKS for session-token verification.

    Supabase 2025+ defaults to asymmetric session tokens (ES256 / RS256 /
    EdDSA) signed with keys exposed at
    `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. The legacy HS256 path
    using `supabase_jwt_secret` is kept as a fallback for older projects.
    """
    import time

    now = time.time()
    if (
        _JWKS_CACHE["keys"] is not None
        and now - _JWKS_CACHE["fetched_at"] < _JWKS_TTL_SECONDS
    ):
        return _JWKS_CACHE["keys"]

    if not settings.supabase_url:
        raise HTTPException(
            status_code=500,
            detail="SUPABASE_URL not configured — cannot validate asymmetric JWTs",
        )

    import httpx

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        resp = httpx.get(url, timeout=5.0)
        resp.raise_for_status()
        jwks = resp.json()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not fetch Supabase JWKS: {e}",
        )

    _JWKS_CACHE["keys"] = jwks
    _JWKS_CACHE["fetched_at"] = now
    return jwks


def _validate_jwt(token: str, db: Session) -> AuthContext:
    """Decode a Supabase JWT and ensure the customer exists.

    Supports both:
      - Asymmetric session tokens (ES256/RS256/EdDSA) verified via JWKS.
      - Legacy HS256 tokens verified with the JWT secret (fallback).

    The customer row is created automatically by the on_auth_user_created
    Postgres trigger when Supabase Auth provisions the user. If it's missing
    here, something went wrong on the Supabase side and we fail closed.
    """
    from jose import jwt, JWTError

    # Peek at the header to pick the right verification path.
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Malformed JWT header: {e}")

    alg = unverified_header.get("alg", "")
    common_opts = {"verify_aud": True, "verify_exp": True}

    try:
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise HTTPException(
                    status_code=401,
                    detail="HS256 JWT received but SUPABASE_JWT_SECRET not configured",
                )
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options=common_opts,
            )
        elif alg in ("ES256", "RS256", "EdDSA"):
            jwks = _fetch_jwks()
            kid = unverified_header.get("kid")
            if not kid:
                raise HTTPException(status_code=401, detail="JWT missing kid")
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
            if key is None:
                # Force a JWKS refresh in case Supabase rotated; one retry.
                _JWKS_CACHE["fetched_at"] = 0
                jwks = _fetch_jwks()
                key = next(
                    (k for k in jwks.get("keys", []) if k.get("kid") == kid), None
                )
                if key is None:
                    raise HTTPException(
                        status_code=401,
                        detail=f"No JWKS key matches kid={kid}",
                    )
            payload = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience="authenticated",
                options=common_opts,
            )
        else:
            raise HTTPException(
                status_code=401,
                detail=f"Unsupported JWT algorithm: {alg}",
            )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid JWT: {e}")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="JWT missing sub claim")

    customer = db.query(Customer).filter(Customer.id == sub).first()
    if not customer:
        # The trigger should have created this. If we're here, the user just
        # logged in for the first time and the trigger hasn't fired yet (or is
        # broken). Don't auto-create — that hides config errors.
        raise HTTPException(
            status_code=403,
            detail=(
                "Authenticated but no Metalins customer row found. The "
                "Supabase trigger may not have fired — contact support."
            ),
        )

    return AuthContext(
        auth_type="jwt",
        customer_id=customer.id,
        customer_email=customer.email,
        api_key=None,
    )


def _validate_api_key(token: str, db: Session) -> AuthContext:
    api_key = (
        db.query(APIKey).filter(APIKey.key_hash == _hash_key(token)).first()
    )
    if not api_key or not api_key.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    api_key.last_used_at = datetime.utcnow()

    # Legacy keys may not have customer_id set yet (pre-3a-auth keys). For
    # those we can't determine ownership and the dashboard would show nothing,
    # so fail with a clear error pointing at the backfill step in
    # migrate-3a-auth.sql.
    if not api_key.customer_id:
        db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                "This API key is not linked to a customer yet. Run the "
                "backfill step in scripts/migrate-3a-auth.sql after your "
                "first dashboard login."
            ),
        )

    customer = (
        db.query(Customer).filter(Customer.id == api_key.customer_id).first()
    )
    if not customer:
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="API key references a missing customer — data integrity issue",
        )

    db.commit()
    return AuthContext(
        auth_type="api_key",
        customer_id=customer.id,
        customer_email=customer.email,
        api_key=api_key,
    )


def _validate_bypass(signature: str, db: Session) -> AuthContext:
    """Validate the synthetic-user bypass header and return the test AuthContext.

    Only reachable when `settings.test_user_bypass_secret` is set. The signature
    is compared in constant time against HMAC-SHA256(secret, test-email). On
    success we return an AuthContext pinned to the sandbox tenant — any
    writes hit only that customer's data.
    """
    secret = settings.test_user_bypass_secret
    if not secret:
        # Defensive: never reached because the caller in require_auth guards
        # on this, but keeps the function safe to call independently.
        raise HTTPException(status_code=401, detail="Bypass auth not configured")

    expected = _expected_bypass_signature(secret)
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise HTTPException(status_code=401, detail="Invalid bypass signature")

    customer = (
        db.query(Customer).filter(Customer.id == TEST_USER_BYPASS_ID).first()
    )
    if not customer:
        # The migration in scripts/migrate-sprint-ux-5-11-synthetic-user.sql
        # must have been applied — fail loudly if it wasn't.
        raise HTTPException(
            status_code=500,
            detail=(
                "Bypass auth misconfigured: testing@metalins.local customer "
                "row is missing. Apply the Sprint UX-5.11 migration."
            ),
        )

    return AuthContext(
        auth_type="jwt",  # treat as JWT-equivalent for downstream filters
        customer_id=customer.id,
        customer_email=customer.email,
        api_key=None,
    )


def require_auth(
    authorization: str | None = Header(default=None),
    x_metalins_test_bypass: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    """Dual auth: accept Bearer API key OR Supabase JWT.

    Sprint UX-5.11 adds a third path: when the deploy has
    `METALINS_TEST_USER_BYPASS_SECRET` set, an HTTP header
    `X-Metalins-Test-Bypass: <hmac>` maps the caller to the synthetic-user
    sandbox tenant. The bypass is silently ignored when the env var is unset,
    so production deploys without the secret behave as if the path didn't
    exist.

    Order of resolution:
      1. Bypass header (only if env var set + header present + valid signature)
      2. Bearer token starting with `ml_` → API key
      3. Bearer token otherwise → Supabase JWT
    """
    # Bypass path takes precedence when configured + header present so a
    # persona runner can authenticate without minting real JWTs.
    if x_metalins_test_bypass and settings.test_user_bypass_secret:
        return _validate_bypass(x_metalins_test_bypass, db)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty Bearer token")

    if token.startswith("ml_"):
        return _validate_api_key(token, db)
    return _validate_jwt(token, db)
