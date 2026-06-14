"""Tests for the admin endpoints."""
import os
import pytest
from fastapi.testclient import TestClient


def _reload_app_with_env(env_overrides: dict) -> TestClient:
    """Apply env overrides and rebuild the FastAPI app from scratch.

    The 503-pollution bug (task #496): routers cache `from app.config
    import settings` at module load. When a prior test module ran the
    app first, `app.api.admin.settings` is bound to the OLD Settings
    instance. Reloading `app.config` re-runs the module and creates a
    NEW Settings, but the router's binding doesn't follow.

    Fix: reload every router we care about so they re-bind to the
    fresh `settings`. `importlib.reload(main)` alone is NOT enough
    because `from app.api.admin import ...` short-circuits through
    sys.modules without re-running admin.py.
    """
    import os
    import importlib

    for k, v in env_overrides.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    from app import config as config_mod
    importlib.reload(config_mod)
    from app.db import session as session_mod, models as models_mod
    importlib.reload(session_mod)
    models_mod.Base = session_mod.Base
    importlib.reload(models_mod)
    session_mod.Base.metadata.create_all(bind=session_mod.engine)
    # Reload every router that captures `settings` at module scope.
    # Without this, the 503 path inside require_master_token keeps
    # firing because admin.settings is still the stale instance.
    from app.api import admin as admin_mod
    importlib.reload(admin_mod)
    from app import main
    importlib.reload(main)
    return TestClient(main.app)


@pytest.fixture
def client_with_token(monkeypatch, tmp_path):
    """Client where METALINS_MASTER_TOKEN is set."""
    monkeypatch.setenv("METALINS_MASTER_TOKEN", "test-master-secret")
    monkeypatch.setenv("METALINS_DB_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("METALINS_PRIVATE_KEY_PATH", "/nonexistent")
    monkeypatch.setenv("METALINS_PUBLIC_KEY_PATH", "/nonexistent")
    return _reload_app_with_env({})


@pytest.fixture
def client_no_token(monkeypatch, tmp_path):
    """Client where METALINS_MASTER_TOKEN is NOT set (admin endpoints disabled)."""
    monkeypatch.delenv("METALINS_MASTER_TOKEN", raising=False)
    monkeypatch.setenv("METALINS_DB_URL", f"sqlite:///{tmp_path}/test2.db")
    monkeypatch.setenv("METALINS_PRIVATE_KEY_PATH", "/nonexistent")
    monkeypatch.setenv("METALINS_PUBLIC_KEY_PATH", "/nonexistent")
    return _reload_app_with_env({})


def test_bootstrap_creates_api_key(client_with_token):
    r = client_with_token.post(
        "/v1/admin/bootstrap-api-key",
        headers={"X-Master-Token": "test-master-secret"},
        json={"owner_email": "founder@metalins.com", "label": "bootstrap-test"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["api_key"].startswith("ml_live_")
    assert data["key_id"].startswith("key_")
    assert data["owner_email"] == "founder@metalins.com"
    assert data["label"] == "bootstrap-test"


def test_bootstrap_rejects_wrong_token(client_with_token):
    r = client_with_token.post(
        "/v1/admin/bootstrap-api-key",
        headers={"X-Master-Token": "wrong-token"},
        json={"owner_email": "x@y.com"},
    )
    assert r.status_code == 401


def test_bootstrap_rejects_missing_token(client_with_token):
    r = client_with_token.post(
        "/v1/admin/bootstrap-api-key",
        json={"owner_email": "x@y.com"},
    )
    assert r.status_code == 401


def test_bootstrap_disabled_when_no_token_configured(client_no_token):
    r = client_no_token.post(
        "/v1/admin/bootstrap-api-key",
        headers={"X-Master-Token": "anything"},
        json={"owner_email": "x@y.com"},
    )
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"].lower()
