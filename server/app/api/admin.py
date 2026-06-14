"""Admin endpoints — protected by master token.

Solo para operaciones de bootstrap / management. NO exponer al público.

Auth: header `X-Master-Token` con el valor de `METALINS_MASTER_TOKEN`.
Si la env var no está seteada, todos los endpoints admin devuelven 503.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.db.models import Agent, APIKey, MemoryProbe
from app.services.observable_job import run_batch, DEFAULT_WINDOW


router = APIRouter(prefix="/v1/admin", tags=["admin"])


def require_master_token(x_master_token: str | None = Header(default=None)) -> None:
    """Valida el master token. Falla con 503 si no está configurado, 401 si no coincide."""
    if not settings.master_token:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints disabled (METALINS_MASTER_TOKEN not set).",
        )
    if not x_master_token:
        raise HTTPException(status_code=401, detail="Missing X-Master-Token header")
    # Constant-time comparison para evitar timing attacks
    if not hmac.compare_digest(x_master_token, settings.master_token):
        raise HTTPException(status_code=401, detail="Invalid master token")


class BootstrapApiKeyRequest(BaseModel):
    owner_email: EmailStr
    label: str = Field(default="bootstrap", max_length=64)


class BootstrapApiKeyResponse(BaseModel):
    api_key: str
    key_id: str
    owner_email: str
    label: str


@router.post(
    "/bootstrap-api-key",
    response_model=BootstrapApiKeyResponse,
    dependencies=[Depends(require_master_token)],
)
def bootstrap_api_key(req: BootstrapApiKeyRequest, db: Session = Depends(get_db)):
    """Crear un API key. Usado para bootstrap inicial en prod (la DB arranca vacía).

    Devuelve el raw key una sola vez — guardalo, no se puede recuperar después.

    ⚠️ Idempotencia: este endpoint NO chequea duplicados. Cada call crea un key
    nuevo. Si el master token está activo, podés crear varios keys legítimamente
    (uno por dev, uno por CI, etc.).
    """
    raw_key = "ml_live_" + secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_id = "key_" + secrets.token_urlsafe(12)

    api_key = APIKey(
        id=key_id,
        key_hash=key_hash,
        owner_email=req.owner_email,
        label=req.label,
        is_active=True,
    )
    db.add(api_key)
    db.commit()

    return BootstrapApiKeyResponse(
        api_key=raw_key,
        key_id=key_id,
        owner_email=req.owner_email,
        label=req.label,
    )


@router.post(
    "/observables/run-batch",
    dependencies=[Depends(require_master_token)],
)
def run_observables_batch(window: int = DEFAULT_WINDOW):
    """Trigger one batch run of Trinity observables across all active agents.

    Intended for Cloud Scheduler to call hourly (Cloud Run scale-to-zero
    means the in-process APScheduler isn't reliable). Idempotent: each call
    writes a fresh snapshot row per agent.
    """
    report = run_batch(window=window)
    return report.to_dict()


@router.post(
    "/watchers/run-batch",
    dependencies=[Depends(require_master_token)],
)
def run_watchers_batch():
    """Trigger one watcher poll across all active watchers.

    Cloud Run scale-to-zero workaround: the in-process APScheduler only
    runs while a container is warm. Cloud Scheduler can hit this every
    minute for guaranteed cadence. Also useful for manual smoke testing —
    the dashboard "pending" state flips after the first successful call.
    """
    from app.services.watcher_job import run_batch as run_watchers
    return run_watchers()


@router.post(
    "/agents/{agent_id}/disable-probes",
    dependencies=[Depends(require_master_token)],
)
def disable_agent_probes(agent_id: str, db: Session = Depends(get_db)):
    """Turn memory probes OFF for one agent and clear its pending checks.

    gh-88 — operational cleanup for agents that were incorrectly opted into
    hash-based probes (e.g. dogfood-v2: a stochastic LLM stamped
    ``probe_client=true`` under the old auto-stamp behavior). This:

      1. Sets ``probe_client = false`` so the engine stops issuing probes and
         suppresses the ``probes_failing`` factor (gh-80 gate).
      2. Expires every still-pending probe WITHOUT counting it as a fresh
         failure surfaced to the customer — once ``probe_client`` is false the
         round-trip factors are gated out of the score entirely.

    Idempotent: re-running is a no-op once the flag is off and nothing is
    pending. Returns what it changed so the caller (QA) can verify.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    pending = (
        db.query(MemoryProbe)
        .filter(
            MemoryProbe.agent_id == agent_id,
            MemoryProbe.status == "pending",
        )
        .all()
    )
    expired = 0
    for p in pending:
        p.status = "expired"
        p.valid = False
        expired += 1

    meta = dict(agent.metadata_json or {})
    was_enabled = bool(meta.get("probe_client"))
    meta["probe_client"] = False
    agent.metadata_json = meta

    db.commit()

    return {
        "agent_id": agent_id,
        "probe_client_was": was_enabled,
        "probe_client_now": False,
        "pending_probes_expired": expired,
    }
