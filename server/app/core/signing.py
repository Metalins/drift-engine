"""κ-Proof signing service.

Signs κ-Proofs using RSA private key. Public key se sirve via JWKS
para que cualquier relying party pueda verificar firmas sin pagar nada.

⚠️ La private key NUNCA sale del server. En producción vivirá en HSM.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from jose import jwt
from jose.utils import base64url_encode

from app.config import settings


_private_key: RSAPrivateKey | None = None
_public_key: RSAPublicKey | None = None


def _load_keys() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Lazy load keypair from disk OR from env-provided PEM strings.

    PROD (Fly.io / Render): set METALINS_PRIVATE_KEY_PEM and METALINS_PUBLIC_KEY_PEM
    env vars with the PEM contents inline. Inline values take precedence over file paths.

    DEV: set the *_path settings or place keys at default ./keys/.
    """
    global _private_key, _public_key
    if _private_key is None:
        # Inline PEM (preferred for prod / Fly.io)
        if settings.private_key_pem and settings.public_key_pem:
            _private_key = serialization.load_pem_private_key(
                settings.private_key_pem.encode("utf-8"), password=None
            )
            _public_key = serialization.load_pem_public_key(
                settings.public_key_pem.encode("utf-8")
            )
        else:
            # File-based (dev default)
            priv_path = Path(settings.private_key_path)
            pub_path = Path(settings.public_key_path)
            if not priv_path.exists() or not pub_path.exists():
                raise RuntimeError(
                    f"Keypair not found. Either:\n"
                    f"  • Run scripts/generate_keypair.py to create {priv_path} / {pub_path}, OR\n"
                    f"  • Set METALINS_PRIVATE_KEY_PEM / METALINS_PUBLIC_KEY_PEM env vars\n"
                    f"    with the PEM contents inline (recommended for prod)."
                )

            with priv_path.open("rb") as f:
                _private_key = serialization.load_pem_private_key(f.read(), password=None)
            with pub_path.open("rb") as f:
                _public_key = serialization.load_pem_public_key(f.read())

    return _private_key, _public_key


def sign_kappa_proof(
    *,
    proof_id: str,
    agent_id: str,
    score: float,
    verified: bool,
    steps: int,
    scope: str | None = None,
    extra_claims: dict[str, Any] | None = None,
    ttl_seconds: int | None = None,
) -> tuple[str, datetime]:
    """Sign a κ-Proof as JWT (RS256).

    Args:
      ttl_seconds: optional override of `settings.proof_ttl_seconds`. Used
        by Sprint 6-A2A 6.1 (dashboard-issued claims) to let the customer
        pick 5min / 1h / 24h. None = use settings default.

    Returns:
        (jwt_string, expires_at)
    """
    priv, _ = _load_keys()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    now = datetime.now(timezone.utc)
    effective_ttl = ttl_seconds if ttl_seconds is not None else settings.proof_ttl_seconds
    expires_at = now + timedelta(seconds=effective_ttl)

    claims: dict[str, Any] = {
        "iss": settings.public_base_url,
        "sub": agent_id,
        "aud": "metalins-relying-party",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": proof_id,
        "kappa_score": score,
        "kappa_verified": verified,
        "kappa_steps": steps,
    }
    if scope:
        claims["scope"] = scope
    if extra_claims:
        claims.update(extra_claims)

    headers = {"kid": settings.key_id, "typ": "JWT", "alg": "RS256"}
    token = jwt.encode(claims, priv_pem, algorithm="RS256", headers=headers)

    return token, expires_at


def get_jwks() -> dict[str, Any]:
    """Build JWKS document with our public keys.

    Served at /.well-known/jwks.json — relying parties cache this.
    """
    _, pub = _load_keys()
    pub_numbers = pub.public_numbers()

    def _int_to_b64url(n: int) -> str:
        byte_len = (n.bit_length() + 7) // 8
        return base64url_encode(n.to_bytes(byte_len, "big")).decode("ascii").rstrip("=")

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": settings.key_id,
        "n": _int_to_b64url(pub_numbers.n),
        "e": _int_to_b64url(pub_numbers.e),
    }
    return {"keys": [jwk]}
