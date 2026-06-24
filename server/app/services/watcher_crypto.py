"""Envelope encryption for bot tokens — Sprint 4.

Watcher bot tokens are AES-256-GCM encrypted with a Key Encryption Key (KEK)
stored in GCP Secret Manager. The KEK is fetched once at process start (or
on first use) and held in memory. The DB only ever stores the ciphertext.

Storage format (hex-encoded in `watchers.encrypted_token`):

    nonce_12_bytes || ciphertext || tag_16_bytes

Rotation: every `watcher` row stores `encryption_key_ref` (e.g. "v1"). When
we mint a new KEK version, the worker decrypts with the version the row
references, then re-encrypts with the current version. Out of scope for MVP.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# Current KEK version label. Bump when rotating.
CURRENT_KEY_REF = "v1"

# Env var name that holds the KEK plaintext (32 bytes hex = 64 chars).
# Injected from GCP Secret Manager via Cloud Run --set-secrets.
_KEK_ENV = "METALINS_WATCHER_KEK"


@dataclass
class EncryptedBlob:
    """Result of `encrypt_token` — store both fields in the DB."""
    encrypted_token: str        # hex(nonce || ciphertext || tag)
    encryption_key_ref: str     # KEK version used


_kek_cache: Optional[bytes] = None


def _load_kek() -> bytes:
    """Lazy-load the KEK from the env var. Cached after first call.

    Returns:
        32 raw bytes of the current KEK.

    Raises:
        RuntimeError if METALINS_WATCHER_KEK is not set or malformed.
    """
    global _kek_cache
    if _kek_cache is not None:
        return _kek_cache

    raw = os.environ.get(_KEK_ENV)
    if not raw:
        raise RuntimeError(
            f"{_KEK_ENV} not set. Watcher token encryption disabled. "
            "Inject via Cloud Run secret binding."
        )
    try:
        kek = bytes.fromhex(raw.strip())
    except ValueError as e:
        raise RuntimeError(f"{_KEK_ENV} must be hex-encoded") from e
    if len(kek) != 32:
        raise RuntimeError(
            f"{_KEK_ENV} must decode to 32 bytes; got {len(kek)}"
        )
    _kek_cache = kek
    return kek


def encrypt_token(plaintext: str) -> EncryptedBlob:
    """Encrypt a bot token for storage in `watchers.encrypted_token`.

    Args:
        plaintext: the bot token as received from the customer.

    Returns:
        An EncryptedBlob with `encrypted_token` (hex) and `encryption_key_ref`.
    """
    kek = _load_kek()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(kek)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    blob = nonce + ct_with_tag  # ct_with_tag already includes the 16-byte tag
    return EncryptedBlob(
        encrypted_token=blob.hex(),
        encryption_key_ref=CURRENT_KEY_REF,
    )


def decrypt_token(encrypted_token: str, encryption_key_ref: str) -> str:
    """Decrypt a stored token. Use this only in-memory inside the worker.

    Args:
        encrypted_token: hex string as stored in DB (nonce || ct || tag).
        encryption_key_ref: KEK version label used at encrypt time.

    Returns:
        The plaintext bot token. Do not log this value.

    Raises:
        RuntimeError if the ref is unknown.
        cryptography.exceptions.InvalidTag if the ciphertext was tampered.
    """
    # For MVP we only have one KEK version. When rotating, look up the
    # historical key by ref here.
    if encryption_key_ref != CURRENT_KEY_REF:
        raise RuntimeError(
            f"Unknown encryption_key_ref '{encryption_key_ref}'. "
            "Did you forget to migrate an older watcher row?"
        )
    kek = _load_kek()
    blob = bytes.fromhex(encrypted_token)
    nonce, ct_with_tag = blob[:12], blob[12:]
    aesgcm = AESGCM(kek)
    plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
    return plaintext.decode("utf-8")


def hash_chat_id(chat_id: str | int, customer_salt: str) -> str:
    """Privacy-preserving hash of a platform chat ID, salted per-customer.

    Used in EventDraft.chat_id_hash so we can deduplicate within a watcher
    without ever surfacing the raw chat ID across customers.
    """
    import hashlib
    h = hashlib.sha256()
    h.update(str(chat_id).encode("utf-8"))
    h.update(b"|")
    h.update(customer_salt.encode("utf-8"))
    return h.hexdigest()
