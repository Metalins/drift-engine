"""Local username/password + JWT auth (gh-117, self-hosted pivot 2026-06-19).

Drift Engine is self-hosted. Instead of delegating login to Supabase, the
server owns the whole flow:

  * Passwords are hashed with bcrypt (`hash_password` / `verify_password`).
  * A successful `POST /auth/login` mints a short-lived HS256 JWT
    (`mint_access_token`) carrying the customer id + email.
  * `app.core.auth.require_auth` validates that JWT locally
    (`decode_access_token`) — no JWKS fetch, no external identity provider.

The signing secret comes from `settings.auth_jwt_secret` when set. When it
is NOT set (the turnkey docker-compose default), we derive it
deterministically from the RS256 signing private key, which is itself
persisted in the `keys` volume. That keeps `docker-compose up` zero-config
while still surviving restarts (the same key → the same derived secret →
already-issued sessions stay valid).

Local tokens always carry `iss="metalins-local"`, which lets the auth layer
tell them apart from any legacy Supabase token during the migration window.
"""
from __future__ import annotations

import hashlib
import time

import bcrypt
from jose import jwt

from app.config import settings


# Issuer claim stamped on every locally-minted token. The auth layer keys
# off this to route a Bearer JWT to local validation vs. the legacy
# Supabase path (which is kept only while a deploy still has Supabase env
# vars configured).
LOCAL_ISSUER = "metalins-local"
_ALGORITHM = "HS256"

# bcrypt only considers the first 72 bytes of a password. We reject longer
# inputs explicitly rather than silently truncating, so two distinct long
# passwords can't collide.
MAX_PASSWORD_BYTES = 72


# --------------------------------------------------------------------------- #
# Password hashing                                                            #
# --------------------------------------------------------------------------- #


def hash_password(password: str) -> str:
    """Return a bcrypt hash (utf-8 string) for `password`.

    Raises ValueError when the password exceeds bcrypt's 72-byte limit so
    the caller can surface a clear validation error.
    """
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Password too long (max {MAX_PASSWORD_BYTES} bytes)."
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time check of `password` against a stored bcrypt hash.

    Returns False for a missing/blank hash (an account with no password set
    can never authenticate via the password path) and for any malformed
    hash, instead of raising.
    """
    if not password_hash:
        return False
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raw = raw[:MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT mint / verify                                                          #
# --------------------------------------------------------------------------- #


def _jwt_secret() -> str:
    """Resolve the HS256 signing secret for session tokens.

    Prefers the explicit `METALINS_AUTH_JWT_SECRET`. Falls back to a value
    derived from the RS256 signing private key (PEM contents or the file on
    disk), domain-separated so it can't be confused with the raw key
    material. As a last resort (no key configured yet — e.g. a bare unit
    test) we fall back to the issuer string; tokens still round-trip within
    the process.
    """
    if settings.auth_jwt_secret:
        return settings.auth_jwt_secret

    key_material: str | None = settings.private_key_pem
    if not key_material:
        try:
            with open(settings.private_key_path, "r") as fh:
                key_material = fh.read()
        except OSError:
            key_material = None

    if key_material:
        return hashlib.sha256(
            (LOCAL_ISSUER + ":" + key_material).encode("utf-8")
        ).hexdigest()

    # No secret and no signing key — degrade to a fixed (insecure) value so
    # local/unit flows still work. Real deploys always have one of the above.
    return hashlib.sha256(LOCAL_ISSUER.encode("utf-8")).hexdigest()


def mint_access_token(
    customer_id: str,
    email: str,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a signed session JWT for a customer.

    Claims: `sub` (customer id), `email`, `iss` (LOCAL_ISSUER), `iat`,
    `exp`. TTL defaults to `settings.auth_jwt_ttl_seconds`.
    """
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else settings.auth_jwt_ttl_seconds
    payload = {
        "sub": customer_id,
        "email": email,
        "iss": LOCAL_ISSUER,
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode + verify a local session JWT. Raises jose.JWTError on failure.

    Audience is not used for local tokens; we verify signature + expiry and
    pin the issuer so a token minted elsewhere can't be replayed here.
    """
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=[_ALGORITHM],
        issuer=LOCAL_ISSUER,
        options={"verify_aud": False, "verify_exp": True},
    )
