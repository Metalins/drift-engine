"""Tests for app/services/email_delivery.py — Sprint UX-5.13.E.1.

Strategy: monkeypatch `urllib.request.urlopen` so we never hit the
real Resend API in CI. Two layers of testing:

  • Pure renderers (`render_state_changed`) — verify subject/html/text
    shape for each severity level. No I/O.
  • `send_email` — verify the request envelope (URL, headers, body)
    matches what Resend expects; verify the EmailDeliveryResult is
    populated correctly on success, HTTP error, network error, and
    when the API key is unset.
"""
from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from app.services import email_delivery
from app.services.email_delivery import (
    EmailDeliveryResult,
    render_state_changed,
    send_email,
)


# --------------------------------------------------------------------------- #
# Renderers                                                                    #
# --------------------------------------------------------------------------- #


def test_render_state_changed_action_required_subject_and_tone():
    subject, html, text = render_state_changed(
        agent_name="customer-support-bot",
        agent_id="agt_ABC123",
        public_slug=None,
        previous_state="verified",
        new_state="action_required",
        confidence=0.42,
    )
    # Subject should hint urgency without being alarmist.
    assert "customer-support-bot" in subject
    assert "[Metalins]" in subject
    assert "needs your attention" in subject
    # The body explains the situation in plain language — no jargon.
    assert "unusual activity" in html
    assert "unusual activity" in text
    # The state values appear so the reader can scan them quickly.
    assert "verified" in text
    assert "action_required" in text
    # The recommended action exists and isn't empty boilerplate.
    assert "Revoke" in text or "revoke" in text
    # No internal mechanism names (D-PROD.18 — strict).
    forbidden = ["ICR", "MVS", "RKS", "TWC", "TTM", "ZKH", "ADV", "PRS", "MCS"]
    for term in forbidden:
        assert term not in subject
        assert term not in html
        assert term not in text


def test_render_state_changed_caution_softer_tone():
    subject, html, text = render_state_changed(
        agent_name="my-bot",
        agent_id="agt_XYZ789",
        public_slug=None,
        previous_state="verified",
        new_state="caution",
        confidence=0.78,
    )
    assert "is worth a look" in subject
    # Caution copy is the "dipped" / "temporary blip" framing.
    assert "dipped" in html
    assert "dipped" in text
    # No "compromised" language for caution — that's reserved for action.
    assert "compromised" not in html.lower()
    assert "compromised" not in text.lower()


def test_render_state_changed_uses_slug_when_present():
    _, html, text = render_state_changed(
        agent_name="agent",
        agent_id="agt_999",
        public_slug="customer-support",
        previous_state="verified",
        new_state="caution",
        confidence=None,
    )
    # /v/<slug> is the slug-bearing public verify URL.
    assert "/v/customer-support" in html
    assert "/v/customer-support" in text


def test_render_state_changed_falls_back_to_agent_id_without_slug():
    _, html, text = render_state_changed(
        agent_name="agent",
        agent_id="agt_NOSLUG",
        public_slug=None,
        previous_state="verified",
        new_state="caution",
        confidence=None,
    )
    assert "/verify/agt_NOSLUG" in html
    assert "/verify/agt_NOSLUG" in text


def test_render_state_changed_handles_none_confidence_gracefully():
    _, html, text = render_state_changed(
        agent_name="a",
        agent_id="agt_X",
        public_slug=None,
        previous_state="unverified",
        new_state="caution",
        confidence=None,
    )
    # We render "—" rather than "None" or a blank.
    assert "None" not in html
    assert "None" not in text
    assert "—" in text


# --------------------------------------------------------------------------- #
# send_email — guard rails                                                     #
# --------------------------------------------------------------------------- #


def test_send_email_without_api_key_returns_unconfigured(monkeypatch):
    """When RESEND_API_KEY is unset, the function must NOT raise and
    must NOT attempt any HTTP request. It returns a falsy result with
    error='provider_unconfigured' so callers can log and move on."""
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", None)

    called = False

    def _explode(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("urlopen should not be called when key is missing")

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _explode)

    result = send_email(
        to="user@example.com",
        subject="x",
        html="<p>x</p>",
        text="x",
    )
    assert not called
    assert result.ok is False
    assert result.error == "provider_unconfigured"


def test_send_email_with_empty_recipients_returns_no_recipients(monkeypatch):
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")
    result = send_email(
        to=[], subject="x", html="<p>x</p>", text="x"
    )
    assert result.ok is False
    assert result.error == "no_recipients"


# --------------------------------------------------------------------------- #
# send_email — happy path                                                      #
# --------------------------------------------------------------------------- #


def test_send_email_posts_correct_envelope(monkeypatch):
    """When configured, the request must hit Resend's URL with the
    right headers and a JSON body containing `from`, `to`, `subject`,
    `html`, `text`."""
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(
        email_delivery.settings, "email_from_noreply", "noreply@contact.metalins.ai"
    )

    captured = {}

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"id": "resend-msg-id-abc"}'

    def _capture(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _capture)

    result = send_email(
        to="user@example.com",
        subject="hello",
        html="<b>hello</b>",
        text="hello",
    )

    assert result.ok is True
    assert result.provider_id == "resend-msg-id-abc"
    assert result.status_code == 200
    assert captured["url"] == "https://api.resend.com/emails"
    # urllib.request normalizes header names to title case.
    auth_value = captured["headers"].get("Authorization")
    assert auth_value == "Bearer re_test_key"
    assert captured["headers"].get("Content-type") == "application/json"
    assert captured["body"]["from"] == "noreply@contact.metalins.ai"
    assert captured["body"]["to"] == ["user@example.com"]
    assert captured["body"]["subject"] == "hello"
    assert captured["body"]["html"] == "<b>hello</b>"
    assert captured["body"]["text"] == "hello"
    # Sane timeout — long enough for slow networks, short enough not
    # to stall the alert pipeline.
    assert 1 <= captured["timeout"] <= 30


def test_send_email_accepts_multiple_recipients(monkeypatch):
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")
    captured = {}

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b"{}"

    def _capture(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _capture)

    send_email(
        to=["a@x.com", "b@x.com"],
        subject="x",
        html="<p>x</p>",
        text="x",
    )
    assert captured["body"]["to"] == ["a@x.com", "b@x.com"]


def test_send_email_includes_reply_to_when_given(monkeypatch):
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")
    captured = {}

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            return b"{}"

    def _capture(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _capture)

    send_email(
        to="u@x.com",
        subject="x",
        html="<p>x</p>",
        text="x",
        reply_to="support@contact.metalins.ai",
    )
    assert captured["body"]["reply_to"] == "support@contact.metalins.ai"


# --------------------------------------------------------------------------- #
# send_email — failure modes                                                   #
# --------------------------------------------------------------------------- #


def test_send_email_handles_http_error_without_raising(monkeypatch):
    """A 4xx from Resend (bad domain, quota, invalid from) must NOT
    raise — the alert pipeline depends on best-effort semantics."""
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")

    def _raise_http(req, timeout=None):
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=422,
            msg="Unprocessable Entity",
            hdrs={},
            fp=io.BytesIO(
                b'{"name":"validation_error","message":"domain not verified"}'
            ),
        )

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _raise_http)

    result = send_email(
        to="u@x.com", subject="x", html="<p>x</p>", text="x"
    )
    assert result.ok is False
    assert result.status_code == 422
    assert "http_422" in result.error
    assert "domain not verified" in result.error


def test_send_email_handles_network_error_without_raising(monkeypatch):
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")

    def _raise_url(req, timeout=None):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _raise_url)

    result = send_email(
        to="u@x.com", subject="x", html="<p>x</p>", text="x"
    )
    assert result.ok is False
    assert "network" in result.error


def test_send_email_handles_unexpected_exception_without_raising(monkeypatch):
    """Generic safety net — if urllib gives us something we don't
    expect (corrupted SSL, JSON decode error, etc.) the function must
    still return a falsy result rather than propagate."""
    monkeypatch.setattr(email_delivery.settings, "resend_api_key", "re_test")

    def _explode(req, timeout=None):
        raise RuntimeError("unexpected boom")

    monkeypatch.setattr(email_delivery.urllib.request, "urlopen", _explode)

    result = send_email(
        to="u@x.com", subject="x", html="<p>x</p>", text="x"
    )
    assert result.ok is False
    assert "RuntimeError" in result.error
