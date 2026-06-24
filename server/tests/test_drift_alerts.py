"""Tests for the behavioral drift alerts pipeline (#64).

Covers the full path from a κ-engine V2 drift verdict to a delivered
alert:

  • render_drift_detected — customer-facing copy, no internal jargon.
  • maybe_fire_drift — persist a DriftEvent, gate email on prefs, fire
    webhooks, dedup within the window, and stay silent on marginal /
    no-baseline verdicts.
  • ensure_baseline + run_drift_check — the integration path over real
    seeded events (identical window → no alert; model swap → alert).
  • GET /internal/v1/agents/{id}/drift-events + acknowledge — the
    dashboard surface.

All tests use the app's engine/SessionLocal (one temp SQLite for the
module) and unique ids per test, so they never clobber each other and
the TestClient sees the same rows the service wrote.
"""
from __future__ import annotations

import hashlib
import os
import secrets as py_secrets

import pytest

_TMP_DB_PATH = f"/tmp/_metalins_drift_alerts_{os.getpid()}.db"
os.environ.setdefault("METALINS_DB_URL", f"sqlite:///{_TMP_DB_PATH}")
os.environ.setdefault("METALINS_DISABLE_INPROC_SCHEDULER", "1")


# --------------------------------------------------------------------------- #
# Fixtures + helpers                                                          #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    from app.db import Base
    from app.db.session import engine
    import app.db.models  # noqa: F401 — register models

    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def db():
    from app.db.session import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


def _beh(
    chars: int,
    *,
    tokens: int = 40,
    code: bool = False,
    error: str = "none",
    tools=None,
    lsh: str = "0" * 16,
    latency: float = 100.0,
) -> dict:
    return {
        "output_length_chars": chars,
        "output_length_tokens": tokens,
        "input_length_chars": 50,
        "sentence_count_output": 5,
        "mean_sentence_length_output": 12.0,
        "latency_ms": latency,
        "had_code_block": code,
        "had_list": False,
        "had_markdown": code,
        "error_class": error,
        "tool_calls": list(tools) if tools else [],
        "format_markers": {"code": code, "list": False, "markdown": code, "json": False},
        "token_bag_lsh": lsh,
    }


def _identical_samples(n: int, offset: int = 0) -> list[dict]:
    return [_beh(150 + offset + (i % 50)) for i in range(n)]


def _seed_events(db, agent_id: str, samples: list[dict], start: int = 0) -> None:
    from app.db.models import EventLog

    for i, beh in enumerate(samples):
        n = start + i + 1
        db.add(EventLog(
            id=f"evt_{agent_id}_{n}",
            agent_id=agent_id,
            event_count=n,
            input_hash=hashlib.sha256(f"in{agent_id}{n}".encode()).hexdigest(),
            output_hash=hashlib.sha256(f"out{agent_id}{n}".encode()).hexdigest(),
            history_digest=hashlib.sha256(f"d{n}".encode()).hexdigest(),
            signature="sig",
            metadata_json={"behavioral": beh},
        ))
    db.commit()


def _seed_customer_agent(db, slug: str, *, alert_email=None):
    """Seed Customer + APIKey + Agent. Returns (raw_key, agent)."""
    from app.core.ids import new_id
    from app.db.models import Agent, APIKey, Customer

    customer_id = new_id("cust")
    key_id = new_id("key")
    agent_id = f"agt_{slug}"
    raw = "ml_test_" + py_secrets.token_urlsafe(16)

    db.add(Customer(id=customer_id, email=f"{slug}@example.com"))
    db.flush()
    db.add(APIKey(
        id=key_id,
        customer_id=customer_id,
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        owner_email=f"{slug}@example.com",
        is_active=True,
    ))
    agent = Agent(id=agent_id, api_key_id=key_id, name=f"{slug}-bot", is_active=True)
    db.add(agent)
    db.commit()
    return raw, agent


def _high_drift_verdict() -> dict:
    """A synthetic continuous-feature drift verdict (decoupled from the
    engine) for fast unit tests of the alerting layer."""
    return {
        "verified": False,
        "drift_score": 0.85,
        "dominant_feature": "output_length_chars",
        "attribution": {
            "feature_name": "output_length_chars",
            "magnitude": 1400.0,
            "detail": {
                "score": 0.85,
                "test": "ks_2samp",
                "magnitude": 1400.0,
                "baseline_mean": 175.0,
                "current_mean": 1625.0,
            },
        },
        "scores": {"output_length_chars": 0.85},
        "window_size": 50,
        "baseline_n_events": 200,
    }


# --------------------------------------------------------------------------- #
# Renderer                                                                    #
# --------------------------------------------------------------------------- #


def test_render_drift_detected_shape_and_no_jargon():
    from app.services.email_delivery import render_drift_detected

    subject, html, text = render_drift_detected(
        agent_name="support-bot",
        agent_id="agt_ABC",
        public_slug=None,
        dominant_feature="output_length_chars",
        drift_score=0.85,
        baseline_value="175.00",
        current_value="1625.00",
    )
    assert "support-bot" in subject
    assert "[Metalins]" in subject
    # Humanized feature label, not the raw feature name.
    assert "response length" in html
    assert "response length" in text
    # Before/after surface for the customer.
    assert "175.00" in text and "1625.00" in text
    # Change strength rendered as a percentage.
    assert "85%" in text
    # No internal crypto-layer jargon (D-PROD.18).
    for term in ["ICR", "MVS", "RKS", "TWC", "TTM", "ZKH", "ADV", "PRS", "MCS",
                 "ks_2samp", "wasserstein", "Wasserstein", "KS statistic"]:
        assert term not in subject
        assert term not in html
        assert term not in text


def test_feature_label_fallback():
    from app.services.email_delivery import feature_label

    assert feature_label("latency_ms") == "response latency"
    assert feature_label("some_new_feature") == "some new feature"
    assert feature_label(None) == "behavior"


# --------------------------------------------------------------------------- #
# maybe_fire_drift — persistence + gating + dedup                             #
# --------------------------------------------------------------------------- #


def test_maybe_fire_persists_drift_event(db, monkeypatch):
    from app.services import drift_alerts
    from app.db.models import DriftEvent

    # Email/webhook are exercised separately; neutralize here.
    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(
        drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0
    )

    raw, agent = _seed_customer_agent(db, "persist")
    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())

    assert event is not None
    assert event.dominant_feature == "output_length_chars"
    assert event.drift_score == 0.85
    assert event.baseline_value == "175.00"
    assert event.current_value == "1625.00"
    assert event.magnitude == 1400.0
    assert event.customer_id is not None  # resolved via API key
    row = db.query(DriftEvent).filter(DriftEvent.id == event.id).first()
    assert row is not None


def test_below_threshold_does_not_fire(db, monkeypatch):
    from app.services import drift_alerts

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "marginal")
    verdict = _high_drift_verdict()
    verdict["drift_score"] = 0.4  # below DRIFT_ALERT_THRESHOLD (0.6)
    assert drift_alerts.maybe_fire_drift(db, agent=agent, verdict=verdict) is None


def test_no_baseline_reason_does_not_fire(db, monkeypatch):
    from app.services import drift_alerts

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "nobaseline")
    verdict = {"verified": False, "drift_score": 0.0, "dominant_feature": None,
               "attribution": {}, "scores": {}, "reason": "no_baseline"}
    assert drift_alerts.maybe_fire_drift(db, agent=agent, verdict=verdict) is None


def test_dedup_within_window(db, monkeypatch):
    from app.services import drift_alerts
    from app.db.models import DriftEvent

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "dedup")
    first = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    second = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())

    assert first is not None
    assert second is None  # same feature within the dedup window
    n = db.query(DriftEvent).filter(DriftEvent.agent_id == agent.id).count()
    assert n == 1


# --------------------------------------------------------------------------- #
# Email gating                                                                #
# --------------------------------------------------------------------------- #


def test_email_sent_with_default_prefs(db, monkeypatch):
    from app.services import drift_alerts, email_delivery

    captured = {}

    def _fake_send(*, to, subject, html, text, **kw):
        captured["to"] = to
        captured["subject"] = subject
        return email_delivery.EmailDeliveryResult(ok=True, provider_id="x")

    monkeypatch.setattr(email_delivery, "send_email", _fake_send)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "emaildefault")
    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())

    assert event is not None
    assert event.notified_email is True
    assert captured["to"] == "emaildefault@example.com"
    assert "support" not in captured["subject"].lower()  # uses agent name


def test_email_suppressed_when_drift_toggle_off(db, monkeypatch):
    from app.services import drift_alerts, email_delivery
    from app.db.models import EmailPreferences

    sent = {"called": False}

    def _fake_send(**kw):
        sent["called"] = True
        return email_delivery.EmailDeliveryResult(ok=True)

    monkeypatch.setattr(email_delivery, "send_email", _fake_send)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "drifftoff")
    customer = drift_alerts.resolve_customer(db, agent)
    db.add(EmailPreferences(
        customer_id=customer.id,
        alerts_enabled=True,
        drift_detected_enabled=False,  # the gate under test
    ))
    db.commit()

    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    assert event is not None
    assert event.notified_email is False
    assert sent["called"] is False


def test_email_suppressed_when_master_alerts_off(db, monkeypatch):
    from app.services import drift_alerts, email_delivery
    from app.db.models import EmailPreferences

    sent = {"called": False}
    monkeypatch.setattr(
        email_delivery, "send_email",
        lambda **kw: (sent.__setitem__("called", True) or
                      email_delivery.EmailDeliveryResult(ok=True)),
    )
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "masteroff")
    customer = drift_alerts.resolve_customer(db, agent)
    db.add(EmailPreferences(
        customer_id=customer.id,
        alerts_enabled=False,
        drift_detected_enabled=True,
    ))
    db.commit()

    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    assert event.notified_email is False
    assert sent["called"] is False


def test_email_uses_alert_email_override(db, monkeypatch):
    from app.services import drift_alerts, email_delivery
    from app.db.models import EmailPreferences

    captured = {}
    monkeypatch.setattr(
        email_delivery, "send_email",
        lambda **kw: (captured.update(kw) or
                      email_delivery.EmailDeliveryResult(ok=True)),
    )
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "override")
    customer = drift_alerts.resolve_customer(db, agent)
    db.add(EmailPreferences(
        customer_id=customer.id,
        alert_email="ops@team.example.com",
    ))
    db.commit()

    drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    assert captured["to"] == "ops@team.example.com"


# --------------------------------------------------------------------------- #
# Webhook firing                                                              #
# --------------------------------------------------------------------------- #


def test_webhook_fired_for_active_endpoint(db, monkeypatch):
    from app.services import drift_alerts, webhook_delivery
    from app.core.ids import new_id
    from app.db.models import WebhookEndpoint

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)

    captured = {}

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def _capture(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["sig"] = req.headers.get("X-metalins-signature")
        return _Resp()

    monkeypatch.setattr(webhook_delivery.urllib.request, "urlopen", _capture)

    raw, agent = _seed_customer_agent(db, "webhook")
    customer = drift_alerts.resolve_customer(db, agent)
    db.add(WebhookEndpoint(
        id=new_id("wh"),
        agent_id=agent.id,
        customer_id=customer.id,
        url="https://example.com/hook",
        secret_hash="deadbeef",
        is_active=True,
    ))
    db.commit()

    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    assert event.notified_webhook is True
    assert captured["url"] == "https://example.com/hook"
    assert b"behavioral_drift.detected" in captured["body"]
    assert captured["sig"] is not None


# --------------------------------------------------------------------------- #
# ensure_baseline + run_drift_check — integration over real events           #
# --------------------------------------------------------------------------- #


def test_ensure_baseline_waits_for_enough_events(db):
    from app.services import drift_alerts

    raw, agent = _seed_customer_agent(db, "tooFew")
    _seed_events(db, agent.id, _identical_samples(20))
    assert drift_alerts.ensure_baseline(db, agent.id) is False

    _seed_events(db, agent.id, _identical_samples(120), start=20)
    assert drift_alerts.ensure_baseline(db, agent.id) is True


def test_run_drift_check_identical_no_alert(db, monkeypatch):
    from app.services import drift_alerts

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "identical")
    _seed_events(db, agent.id, _identical_samples(200))
    assert drift_alerts.ensure_baseline(db, agent.id) is True

    event = drift_alerts.run_drift_check(db, agent=agent)
    assert event is None  # window is the same identical stream


def test_run_drift_check_model_swap_fires(db, monkeypatch):
    from app.services import drift_alerts

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "swap")
    # Clean baseline first (so it isn't polluted by the drift window).
    _seed_events(db, agent.id, _identical_samples(200))
    assert drift_alerts.ensure_baseline(db, agent.id) is True
    # Then 50 newer events with 10x output length.
    _seed_events(db, agent.id, [_beh(1600 + (i % 50)) for i in range(50)], start=200)

    event = drift_alerts.run_drift_check(db, agent=agent)
    assert event is not None
    assert event.dominant_feature == "output_length_chars"
    assert event.drift_score > 0.6


# --------------------------------------------------------------------------- #
# API surface                                                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture
def http_client():
    import importlib
    from fastapi.testclient import TestClient
    import app.main as main_mod

    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_drift_events_endpoint_lists_and_acknowledges(db, http_client, monkeypatch):
    from app.services import drift_alerts

    monkeypatch.setattr(drift_alerts, "_send_drift_email", lambda *a, **k: False)
    monkeypatch.setattr(drift_alerts.webhook_delivery, "fire_drift", lambda *a, **k: 0)

    raw, agent = _seed_customer_agent(db, "apisurface")
    event = drift_alerts.maybe_fire_drift(db, agent=agent, verdict=_high_drift_verdict())
    assert event is not None

    headers = {"Authorization": f"Bearer {raw}"}
    r = http_client.get(f"/internal/v1/agents/{agent.id}/drift-events", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["dominant_feature"] == "output_length_chars"
    assert item["acknowledged_at"] is None

    # Acknowledge it.
    r2 = http_client.post(
        f"/internal/v1/agents/{agent.id}/drift-events/{event.id}/acknowledge",
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["acknowledged_at"] is not None

    # Idempotent re-ack returns the same.
    r3 = http_client.post(
        f"/internal/v1/agents/{agent.id}/drift-events/{event.id}/acknowledge",
        headers=headers,
    )
    assert r3.status_code == 200


def test_drift_events_endpoint_requires_ownership(db, http_client):
    raw_a, agent_a = _seed_customer_agent(db, "ownerA")
    raw_b, agent_b = _seed_customer_agent(db, "ownerB")

    # Customer B's key must not see customer A's agent drift events.
    r = http_client.get(
        f"/internal/v1/agents/{agent_a.id}/drift-events",
        headers={"Authorization": f"Bearer {raw_b}"},
    )
    assert r.status_code == 404
