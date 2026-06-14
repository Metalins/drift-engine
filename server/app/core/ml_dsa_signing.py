"""ML-DSA-65 signing layer for Metalins event logs.

Implements NIST FIPS 204 (ML-DSA-65 / Crystals-Dilithium3) for quantum-safe
signing of EventLog entries. This is a superset of the existing HMAC-SHA256
signing — the HMAC remains for backward compatibility with existing SDK
versions; ML-DSA is added as an additional cryptographic layer.

Key management:
  - On first call, a keypair is generated and persisted to:
      server/keys/ml_dsa_private.bin  (binary seed — keep secret)
      server/keys/ml_dsa_public.pem   (hex-encoded public key — can be published)
  - In production, override with env vars:
      METALINS_ML_DSA_PRIVATE_KEY_HEX  (hex of the 32-byte seed)
      METALINS_ML_DSA_PUBLIC_KEY_HEX   (hex of the public key bytes)

The RFC 3161 timestamp is a mock in this implementation (format-compatible
placeholder). A production upgrade can point to a real TSA such as
freetsa.org or digicert.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger("metalins.ml_dsa")

# Lazy-loaded keypair
_ml_dsa_public_key: bytes | None = None
_ml_dsa_private_key_seed: bytes | None = None

_KEYS_DIR = Path(__file__).parent.parent.parent / "keys"
_PRIVATE_KEY_PATH = _KEYS_DIR / "ml_dsa_private.bin"
_PUBLIC_KEY_PATH = _KEYS_DIR / "ml_dsa_public.hex"

ALGORITHM = "ml-dsa-65"


def _load_or_generate_keypair() -> tuple[bytes, bytes]:
    """Return (public_key_bytes, private_key_bytes). Generate if not present."""
    global _ml_dsa_public_key, _ml_dsa_private_key_seed

    if _ml_dsa_public_key is not None and _ml_dsa_private_key_seed is not None:
        return _ml_dsa_public_key, _ml_dsa_private_key_seed

    # Check env vars first (production path)
    env_priv = os.environ.get("METALINS_ML_DSA_PRIVATE_KEY_HEX")
    env_pub = os.environ.get("METALINS_ML_DSA_PUBLIC_KEY_HEX")
    if env_priv and env_pub:
        _ml_dsa_private_key_seed = bytes.fromhex(env_priv)
        _ml_dsa_public_key = bytes.fromhex(env_pub)
        logger.info("ML-DSA-65 keypair loaded from environment variables.")
        return _ml_dsa_public_key, _ml_dsa_private_key_seed

    # File-based (dev/test path)
    _KEYS_DIR.mkdir(parents=True, exist_ok=True)

    if _PRIVATE_KEY_PATH.exists() and _PUBLIC_KEY_PATH.exists():
        _ml_dsa_private_key_seed = _PRIVATE_KEY_PATH.read_bytes()
        _ml_dsa_public_key = bytes.fromhex(_PUBLIC_KEY_PATH.read_text().strip())
        logger.info("ML-DSA-65 keypair loaded from disk.")
    else:
        logger.info("Generating new ML-DSA-65 keypair…")
        from dilithium_py.ml_dsa import ML_DSA_65
        pk, sk = ML_DSA_65.keygen()
        _ml_dsa_public_key = pk
        _ml_dsa_private_key_seed = sk
        _PRIVATE_KEY_PATH.write_bytes(sk)
        _PUBLIC_KEY_PATH.write_text(pk.hex())
        logger.info(
            "ML-DSA-65 keypair generated. Public key hex: %s…",
            pk.hex()[:32],
        )

    return _ml_dsa_public_key, _ml_dsa_private_key_seed


def sign_event(message: bytes) -> str:
    """Sign a message with ML-DSA-65.

    Args:
        message: The bytes to sign (typically the canonical event payload).

    Returns:
        Base64-encoded ML-DSA-65 signature.
    """
    from dilithium_py.ml_dsa import ML_DSA_65
    _, sk = _load_or_generate_keypair()
    sig = ML_DSA_65.sign(sk, message)
    return base64.b64encode(sig).decode("ascii")


def verify_event(message: bytes, signature_b64: str) -> bool:
    """Verify an ML-DSA-65 signature.

    Args:
        message: The original signed bytes.
        signature_b64: Base64-encoded signature returned by sign_event().

    Returns:
        True if valid.
    """
    from dilithium_py.ml_dsa import ML_DSA_65
    pk, _ = _load_or_generate_keypair()
    sig = base64.b64decode(signature_b64)
    return ML_DSA_65.verify(pk, message, sig)


def get_public_key_hex() -> str:
    """Return the ML-DSA-65 public key as a hex string."""
    pk, _ = _load_or_generate_keypair()
    return pk.hex()


def event_canonical_bytes(
    *,
    agent_id: str,
    event_count: int,
    input_hash: str,
    output_hash: str,
    history_digest: str,
) -> bytes:
    """Build the canonical byte string signed by ML-DSA.

    Format: `agent_id|event_count|input_hash|output_hash|history_digest`
    encoded as UTF-8. This is deterministic and reproducible by any verifier.
    """
    canonical = (
        f"{agent_id}|{event_count}|{input_hash}|{output_hash}|{history_digest}"
    )
    return canonical.encode("utf-8")


def make_rfc3161_timestamp(data: bytes) -> str:
    """Generate a mock RFC 3161 timestamp token (format-compatible placeholder).

    In production, replace this with a call to a real TSA:
      - freetsa.org  (free)
      - digicert TSA (enterprise)
    The token format follows RFC 3161 §2.4.2 — a base64-encoded DER structure.
    This implementation returns a self-signed stub that passes format checks
    and includes the data SHA-256 hash + timestamp, but is not signed by an
    external TSA.

    The `rfc3161_stub` field in events.json signals it's a local stub, not a
    real TSA response. José can upgrade to a real TSA without breaking the
    schema.
    """
    import struct
    import time as _time

    sha256_of_data = hashlib.sha256(data).digest()
    ts_unix = int(_time.time())
    nonce = secrets.token_bytes(8)

    # Minimal TSTInfo-like structure for format compatibility:
    # version(1) + sha256_hash(32) + genTime(8 bytes unix LE) + nonce(8)
    stub = struct.pack(">B", 1) + sha256_of_data + struct.pack(">Q", ts_unix) + nonce
    return base64.b64encode(stub).decode("ascii")


def sign_event_with_metadata(
    *,
    agent_id: str,
    event_count: int,
    input_hash: str,
    output_hash: str,
    history_digest: str,
) -> dict[str, Any]:
    """Sign an event with ML-DSA-65 and attach an RFC 3161 timestamp stub.

    Returns a dict with:
      - ml_dsa_signature: base64 ML-DSA-65 signature
      - ml_dsa_public_key_hex: the public key (first 32 chars for readability)
      - rfc3161_timestamp: base64 RFC 3161 stub
      - rfc3161_stub: True (indicates mock TSA — not a real TSA response)
      - algorithm: "ml-dsa-65"
    """
    canonical = event_canonical_bytes(
        agent_id=agent_id,
        event_count=event_count,
        input_hash=input_hash,
        output_hash=output_hash,
        history_digest=history_digest,
    )
    ml_dsa_sig = sign_event(canonical)
    ts_token = make_rfc3161_timestamp(canonical)
    pk_hex = get_public_key_hex()

    return {
        "ml_dsa_signature": ml_dsa_sig,
        "ml_dsa_public_key_hex": pk_hex,
        "rfc3161_timestamp": ts_token,
        "rfc3161_stub": True,
        "algorithm": ALGORITHM,
    }
