"""Tests for envelope encryption + adapter registry — Sprint 4.6.

Pure unit tests, no DB, no network. The point is to lock in:
  - encrypt/decrypt is a true round-trip.
  - encrypt is non-deterministic (different ciphertext on re-encrypt).
  - decrypt with the wrong key_ref raises.
  - chat_id hashing is deterministic per (chat_id, customer_salt) but
    different customers can never collide on the same chat_id.
  - The telegram adapter registers itself at import time.
"""
from __future__ import annotations

import os
import secrets

import pytest


@pytest.fixture(autouse=True)
def _set_kek(monkeypatch):
    """Each test gets a fresh KEK + a clean module cache for watcher_crypto."""
    kek_hex = secrets.token_hex(32)
    monkeypatch.setenv("METALINS_WATCHER_KEK", kek_hex)
    # Force re-load so the in-memory KEK cache is reset.
    import importlib
    import app.services.watcher_crypto as wc
    importlib.reload(wc)
    return wc


def test_encrypt_decrypt_round_trip(_set_kek):
    wc = _set_kek
    plaintext = "1234567890:AAFsomeTelegramBotTokenLooking"
    blob = wc.encrypt_token(plaintext)

    assert blob.encryption_key_ref == "v1"
    assert len(blob.encrypted_token) > len(plaintext)  # ciphertext + nonce + tag

    recovered = wc.decrypt_token(blob.encrypted_token, blob.encryption_key_ref)
    assert recovered == plaintext


def test_encrypt_is_non_deterministic(_set_kek):
    """Same plaintext, two calls → different ciphertexts (random nonce)."""
    wc = _set_kek
    a = wc.encrypt_token("hello")
    b = wc.encrypt_token("hello")
    assert a.encrypted_token != b.encrypted_token
    # But both decrypt to the same plaintext.
    assert wc.decrypt_token(a.encrypted_token, a.encryption_key_ref) == "hello"
    assert wc.decrypt_token(b.encrypted_token, b.encryption_key_ref) == "hello"


def test_decrypt_with_unknown_key_ref_raises(_set_kek):
    wc = _set_kek
    blob = wc.encrypt_token("token")
    with pytest.raises(RuntimeError, match="Unknown encryption_key_ref"):
        wc.decrypt_token(blob.encrypted_token, "v999-fake")


def test_decrypt_tampered_ciphertext_raises(_set_kek):
    """AES-GCM auth tag should reject any flipped byte."""
    from cryptography.exceptions import InvalidTag

    wc = _set_kek
    blob = wc.encrypt_token("token")
    # Flip a byte deep in the ciphertext.
    raw = bytearray(bytes.fromhex(blob.encrypted_token))
    raw[20] ^= 0x55
    with pytest.raises(InvalidTag):
        wc.decrypt_token(raw.hex(), blob.encryption_key_ref)


def test_missing_kek_env_raises(monkeypatch):
    """If METALINS_WATCHER_KEK is unset, encrypt_token should fail loudly."""
    import importlib
    monkeypatch.delenv("METALINS_WATCHER_KEK", raising=False)
    import app.services.watcher_crypto as wc
    importlib.reload(wc)
    with pytest.raises(RuntimeError, match="not set"):
        wc.encrypt_token("anything")


def test_hash_chat_id_deterministic_per_customer(_set_kek):
    wc = _set_kek
    h1 = wc.hash_chat_id("123456", "cust-a")
    h2 = wc.hash_chat_id("123456", "cust-a")
    assert h1 == h2  # determinism for same (chat, customer)


def test_hash_chat_id_isolates_customers(_set_kek):
    """Same chat_id across different customers must NOT collide."""
    wc = _set_kek
    a = wc.hash_chat_id("123456", "customer-A")
    b = wc.hash_chat_id("123456", "customer-B")
    assert a != b


def test_telegram_adapter_registered_at_import():
    """Importing the watchers package must self-register the telegram adapter."""
    from app.services.watchers import get_adapter, list_supported_platforms

    assert "telegram" in list_supported_platforms()
    telegram = get_adapter("telegram")
    assert telegram is not None
    assert telegram.platform_name == "telegram"
    assert hasattr(telegram, "fetch_new_events")


def test_event_draft_shape():
    """EventDraft should accept the fields watcher_job feeds it."""
    from datetime import datetime
    from app.services.watchers import EventDraft

    ed = EventDraft(
        input_hash="a" * 64,
        output_hash="b" * 64,
        ts=datetime.utcnow(),
        platform_message_id="42",
        chat_id_hash="c" * 64,
        metadata={"platform": "telegram"},
    )
    assert ed.platform_message_id == "42"
    assert ed.metadata["platform"] == "telegram"
