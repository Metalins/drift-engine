"""Pydantic schemas for API I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


# --- Register agent ---

class BehaviorSample(BaseModel):
    challenge_id: str
    response: str


class RegisterAgentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    model: str | None = None
    framework: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    behavior_samples: list[BehaviorSample] = Field(default_factory=list)


class RegisterAgentResponse(BaseModel):
    agent_id: str
    enrolment_score: float
    created_at: datetime
    # UX-5.17 #931 — the agent_secret is what the agent uses to answer
    # verification checks (the round-trip half). The developer API
    # already returns it; the dashboard register path now does too, so
    # a customer who creates an agent in the UI and connects it via the
    # SDK / HTTP API has the secret without needing a re-key. Shown once.
    agent_secret: str


# --- Verify (two-step flow) ---

class RequestChallengesRequest(BaseModel):
    agent_id: str
    steps: int = Field(default=1, ge=1, le=10)


class Challenge(BaseModel):
    id: str
    payload: str
    step: int
    depends_on: str | None = None


class RequestChallengesResponse(BaseModel):
    agent_id: str
    challenges: list[Challenge]
    session_id: str


class VerifyRequest(BaseModel):
    agent_id: str
    session_id: str
    responses: list[BehaviorSample]
    scope: str | None = None


class VerifyResponse(BaseModel):
    verified: bool
    score: float
    proof_id: str
    kappa_proof: str  # JWT
    issued_at: datetime
    expires_at: datetime
    steps: int


# --- Issue token (combines verify + tokens for external services) ---

class IssueTokenRequest(BaseModel):
    agent_id: str
    session_id: str
    responses: list[BehaviorSample]
    scope: str  # required for tokens


class IssueTokenResponse(BaseModel):
    verified: bool
    token: str  # the κ-Proof JWT, usable directly as a Bearer token
    proof_id: str
    expires_in: int
    scope: str


# --- Sprint 6-A2A 6.1: dashboard-issued verifiable identity claim ---
# Distinto del flow verify-challenges: el customer está logueado en
# dashboard y es dueño del agent. Mintea un JWT directo sin pasar por
# challenge/response. Reusa `sign_kappa_proof` con TTL configurable.

class IssueProofRequest(BaseModel):
    # ttl en segundos: 300 (5min), 3600 (1h), 86400 (24h). Validamos
    # contra una lista cerrada en el endpoint para no permitir
    # arbitrary long-lived tokens.
    ttl_seconds: int = 3600
    # scope libre (string corto, e.g. "verify-only" / "data-read" /
    # "marketplace-listing"). El customer lo elige; nuestro server lo
    # incrusta en el JWT pero NO le da semántica — es para el relying
    # party usar.
    scope: str | None = None


class IssueProofResponse(BaseModel):
    proof_id: str
    agent_id: str
    kappa_proof: str  # the JWT, copy-paste-able as a Bearer token
    issued_at: datetime
    expires_at: datetime
    scope: str | None = None
    score: float | None = None  # current identity_confidence at issue time


# --- Public verify endpoint (relying parties) ---

class VerifyProofRequest(BaseModel):
    kappa_proof: str  # JWT to verify


class VerifyProofResponse(BaseModel):
    valid: bool
    agent_id: str | None = None
    # Sprint UX-5.11 R2 / R2.4f (2026-05-18) — include the agent's
    # human-readable slug + name so the verify page rendering a JWT
    # proof can confirm the slug in the URL matches the proof's
    # subject, and render the operator identity consistently.
    public_slug: str | None = None
    agent_name: str | None = None
    proof_id: str | None = None
    issued_at: datetime | None = None
    expires_at: datetime | None = None
    still_active: bool | None = None
    scope: str | None = None
    score: float | None = None
    steps: int | None = None
    reason: str | None = None  # if invalid, why


# --- Revoke ---

class RevokeAgentRequest(BaseModel):
    agent_id: str
    reason: str | None = None


class RevokeAgentResponse(BaseModel):
    agent_id: str
    revoked_at: datetime


# --- Disconnect / reconnect MCP (Sprint 6.4 / #575) ---

class DisconnectMcpRequest(BaseModel):
    """Sprint 6.4 — explicit MCP disconnect with type-the-name confirmation.

    `confirmation_name` must match the agent's display name exactly so the
    user can't disable MCP by accident (it stops accepting events on that
    surface). Watcher disconnect uses the existing DELETE /v1/watchers/{id}.
    """
    confirmation_name: str


class DisconnectMcpResponse(BaseModel):
    agent_id: str
    mcp_disabled_at: datetime


class ReconnectMcpResponse(BaseModel):
    agent_id: str
    mcp_reconnected_at: datetime


# --- Reset behavior baseline (UX-5.15.P / D-PROD.25) ---

class ResetBaselineRequest(BaseModel):
    """UX-5.15.P — explicit confirm-by-name for reset behavior baseline.

    The customer is saying "the new behavior is the new normal". Past
    events stay archived as auditable evidence; the identity engine
    ignores observables prior to this timestamp when computing the
    current shape.

    See docs/product/INTEGRATION-LIFECYCLE.md §4.
    """
    confirmation_name: str


class ResetBaselineResponse(BaseModel):
    agent_id: str
    last_baseline_reset_at: datetime
    baseline_reset_count: int


# --- Reissue agent secret (UX-5.17 #505 / #931) ---

class ReissueSecretRequest(BaseModel):
    """Confirm-by-name for re-keying an agent's secret.

    A full re-key: the agent gets a brand-new `agent_secret` and its
    cryptographic verification restarts from a fresh genesis. This is
    unavoidable — the digest chain is rooted in the secret, so a new
    secret means a new chain. The agent keeps its id / name / slug /
    anchors / keys; only its verification history is cleared and its
    tier resets. Same confirm-by-name guard as revoke / reset-baseline.
    """
    confirmation_name: str


class ReissueSecretResponse(BaseModel):
    agent_id: str
    agent_secret: str  # the new secret — shown once
    reissued_at: datetime
    secret_warning: str


# --- Update / edit ---

class UpdateAgentRequest(BaseModel):
    """Editable fields on an Agent. All optional — only present keys update."""
    name: str | None = None
    model: str | None = None
    framework: str | None = None
    metadata: dict | None = None
