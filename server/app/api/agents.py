"""Agent registration + management endpoints."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    RegisterAgentRequest, RegisterAgentResponse,
    RevokeAgentRequest, RevokeAgentResponse,
    UpdateAgentRequest,
    DisconnectMcpRequest, DisconnectMcpResponse, ReconnectMcpResponse,
    ResetBaselineRequest, ResetBaselineResponse,
    ReissueSecretRequest, ReissueSecretResponse,
    IssueProofRequest, IssueProofResponse,
)
from app.core.auth import AuthContext, require_api_key, require_auth
from app.core.ids import new_id
from app.db import get_db
from app.db.models import (
    Agent,
    AgentState,
    APIKey,
    AgentObservable,
    EventLog,
    MemoryProbe,
    VerificationAttempt,
    Watcher,
)
from app.kappa import fingerprint_baseline
from app.services.observable_job import compute_for_agent, DEFAULT_WINDOW
from app.services import memory_verifier
from app.services.verification_state import derive_tier, derive_trust


router = APIRouter(prefix="/v1/agents", tags=["agents"])


# gh-77 — keys a customer might use to *declare* a behavior profile. These
# are no longer honored: the engine detects behavior from the agent's first
# events (Agent.detected_behavior_mode). We strip them at registration so a
# stale declaration can never be mistaken for a real signal downstream.
_IGNORED_PROFILE_KEYS = ("agent_profile", "profile", "agent_type", "behavior_mode")


def _strip_declared_profile(metadata: dict | None) -> dict:
    """Return a copy of metadata with any declared-profile keys removed."""
    if not metadata:
        return {}
    return {k: v for k, v in metadata.items() if k not in _IGNORED_PROFILE_KEYS}


def _customer_agent_query(db: Session, auth: AuthContext):
    """Base query for agents owned by the caller's customer.

    Sprint 3a-auth: agents are scoped by customer_id (not api_key_id). The
    list of api_keys owned by this customer is the union of (a) legacy keys
    with customer_id set via backfill and (b) new keys created from the
    dashboard.

    Sprint 6 fix (2026-05-16): we used to also narrow by
    `auth.api_key.agent_id` when the calling key was agent-scoped. That
    broke management operations: a key scoped to agent A could not list,
    edit or revoke agent B even though both belonged to the same customer.
    The scope of a key is meaningful for **runtime data operations**
    (event logging, proof issuance — enforced in `mcp_endpoints._resolve_agent`),
    NOT for management. So we now grant any active customer key full
    visibility/control over all of that customer's agents. JWT callers
    (dashboard) were already unaffected because their `api_key` is None.
    """
    customer_key_ids = [
        row[0]
        for row in db.query(APIKey.id)
        .filter(APIKey.customer_id == auth.customer_id)
        .all()
    ]
    return db.query(Agent).filter(Agent.api_key_id.in_(customer_key_ids))


def _resolve_creator_key(auth: AuthContext, db: Session) -> APIKey:
    """Pick which API key to attribute as Agent.api_key_id.

    Sprint 3a-auth.8 fix: the dashboard creates agents via JWT (no api_key in
    the AuthContext), but Agent.api_key_id is NOT NULL by schema. Resolution:

      - API-key call → use that key (legacy behavior).
      - JWT call    → pick any active key of the customer. The attribution is
                       cosmetic (real ownership is customer_id via the key's
                       FK); subsequent scoped keys live on the agent's own
                       /api-keys subresource.

    If the customer has NO active keys yet (rare for legacy users; impossible
    for new sign-ups since we'll bootstrap one), we return a 412 so the
    dashboard can guide the user to create a key first.
    """
    if auth.api_key:
        return auth.api_key
    key = (
        db.query(APIKey)
        .filter(APIKey.customer_id == auth.customer_id, APIKey.is_active.is_(True))
        .order_by(APIKey.created_at.asc())
        .first()
    )
    if not key:
        raise HTTPException(
            status_code=412,
            detail=(
                "Customer has no active API keys. Create one first under any "
                "existing agent, or contact support to bootstrap a customer-"
                "wide key."
            ),
        )
    return key


@router.post("/register", response_model=RegisterAgentResponse, status_code=201)
def register_agent(
    req: RegisterAgentRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Register a new agent and compute its κ-fingerprint baseline.

    Sprint 3a-auth.8: dual auth — SDK uses API key, dashboard uses JWT.
    Agent ownership is by customer_id via api_keys.customer_id; api_key_id
    on the row is a cosmetic attribution of which key originally registered.
    """
    import hashlib
    import os

    samples = [s.model_dump() for s in req.behavior_samples]
    # gh-77 — ignore any declared behavior profile. Behavior is detected
    # server-side from the agent's first events, not declared at creation.
    clean_metadata = _strip_declared_profile(req.metadata)
    metadata = {**clean_metadata, "model": req.model, "framework": req.framework}

    baseline = fingerprint_baseline(metadata=metadata, behavior_samples=samples)
    creator_key = _resolve_creator_key(auth, db)

    agent_id = new_id("agt")
    # Sprint UX-5.11 R2 / R2.3a (2026-05-18) — STOP auto-allocating
    # public_slug from the typed name. Previously (#634) we slugified
    # `req.name` and grabbed the global slug namespace first-come-
    # first-served. That was vulnerable to two issues:
    #   • Squatting: customer A could reserve "claude-code-laptop"
    #     pre-emptively, forcing every later customer to share a
    #     suffixed URL like `/v/claude-code-laptop-2`.
    #   • Same-customer duplicates: a customer who registered the
    #     same name twice got `-2`, with no warning that the URL was
    #     ambiguous.
    # New policy ("Full C"): agents are born slugless. Their default
    # verify URL is `/verify/<agent_id>`. To claim a clean `/v/<slug>`
    # URL the customer must verify an external anchor (Telegram bot
    # bio, GitHub gist, DNS) via /v1/agents/{id}/anchors/* and then
    # call POST /v1/agents/{id}/claim-slug. The anchor proves identity
    # over the claimed handle — no squatting.
    #
    # Watchers still auto-claim on first connect (Sprint UX-5.9-F)
    # because the bot token is itself a proof of control, but only
    # if the agent doesn't already have a slug (see R2.3c).
    agent = Agent(
        id=agent_id,
        api_key_id=creator_key.id,
        name=req.name,
        model=req.model,
        framework=req.framework,
        metadata_json=clean_metadata,
        # gh-77 — born with no declared profile; the engine detects it.
        detected_behavior_mode="unknown",
        baseline_kappa=baseline,
        enrolment_score=baseline["enrolment_score"],
        is_active=True,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        public_slug=None,
    )
    db.add(agent)

    # Sprint 3a-auth.10 fix: bootstrap AgentState so the first metalins_log_event
    # call doesn't fail with "Agent state missing". The MCP register path
    # (metalins_register_agent) did this; the REST path didn't, leaving agents
    # created from the dashboard in a half-initialized state.
    agent_secret = os.urandom(32).hex()
    initial_digest = hashlib.sha256(
        bytes.fromhex(agent_secret) + b"init"
    ).hexdigest()
    state = AgentState(
        agent_id=agent_id,
        history_digest=initial_digest,
        event_count=0,
        agent_secret=agent_secret,
    )
    db.add(state)
    db.commit()
    db.refresh(agent)

    return RegisterAgentResponse(
        agent_id=agent.id,
        enrolment_score=agent.enrolment_score,
        created_at=agent.created_at,
        # UX-5.17 #931 — hand back the secret so a dashboard-created
        # agent can be connected via the SDK / HTTP API without a
        # re-key. Shown once; the caller must store it.
        agent_secret=agent_secret,
    )


@router.post("/revoke", response_model=RevokeAgentResponse)
def revoke_agent(
    req: RevokeAgentRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """HARD DELETE an agent and every row that depends on it.

    Sprint 5 (2026-05-14): the endpoint name + URL stay `/revoke` for API
    backward compat (SDK, scripts, GH actions can keep calling it), but the
    semantics flipped from soft-delete (mark inactive) to hard-delete (wipe
    the row + every FK-pointing child). The dashboard's danger zone is now
    explicit: "Deleting an agent permanently removes it and all its data."

    Sprint UX-5.14 F1 fix (2026-05-18): the E2E framework's first run
    surfaced a latent bug — six tables grew FKs to agents after Sprint 5
    shipped but the wipe list never caught up, so any agent with one of
    those rows (webhooks most commonly) 500'd on revoke. Backfilled.

    Wipe order (must precede the agent row delete because of FK constraints):
      1. agent_observables, memory_probes, event_logs, verifications
      2. watchers
      3. webhook_endpoints                     (Sprint UX-5.10-6, was missing)
      4. agent_anchors                          (Sprint UX-5.9-G, was missing)
      5. prediction_submissions                 (Sprint 7 PRS, was missing)
      6. zkh_proofs                             (Sprint 7 ZKH, was missing)
      7. corroboration_points (via mesh_pair_id) + agent_mesh_pairs
         (Sprint 7 MCS, were missing)
      8. api_keys WHERE agent_id == this agent  (scoped keys; customer-wide
         with agent_id IS NULL are left alone)
      9. agent_state
     10. agents
    revocations rows (CRL by proof_id, no FK to agents) are left alone —
    they're a tombstone list, and verifies for a deleted agent fail with
    404 anyway because the agents row no longer exists.
    """
    from app.db.models import (
        AgentAnchor,
        AgentMeshPair,
        AgentObservable,
        AgentState,
        CorroborationPoint,
        EventLog,
        MemoryProbe,
        PredictionSubmission,
        Verification,
        Watcher,
        WebhookEndpoint,
        ZKHProof,
    )

    agent = _customer_agent_query(db, auth).filter(Agent.id == req.agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    agent_id = agent.id

    # FK-safe delete order. Each DELETE is scoped to this agent_id so we
    # never touch another customer's data.
    db.query(AgentObservable).filter(AgentObservable.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(MemoryProbe).filter(MemoryProbe.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(EventLog).filter(EventLog.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(Watcher).filter(Watcher.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(Verification).filter(Verification.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(WebhookEndpoint).filter(WebhookEndpoint.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(AgentAnchor).filter(AgentAnchor.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(PredictionSubmission).filter(
        PredictionSubmission.agent_id == agent_id
    ).delete(synchronize_session=False)
    db.query(ZKHProof).filter(ZKHProof.agent_id == agent_id).delete(
        synchronize_session=False
    )
    # CorroborationPoint references mesh_pair_id (NOT agent_id). Find every
    # mesh pair this agent participates in, then nuke any corroboration_points
    # that hang off those pairs before deleting the pairs themselves.
    mesh_pair_ids = [
        row[0]
        for row in db.query(AgentMeshPair.id)
        .filter(
            (AgentMeshPair.agent_a_id == agent_id)
            | (AgentMeshPair.agent_b_id == agent_id)
        )
        .all()
    ]
    if mesh_pair_ids:
        db.query(CorroborationPoint).filter(
            CorroborationPoint.mesh_pair_id.in_(mesh_pair_ids)
        ).delete(synchronize_session=False)
        db.query(AgentMeshPair).filter(
            AgentMeshPair.id.in_(mesh_pair_ids)
        ).delete(synchronize_session=False)
    db.query(APIKey).filter(APIKey.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.query(AgentState).filter(AgentState.agent_id == agent_id).delete(
        synchronize_session=False
    )
    db.delete(agent)
    db.commit()

    # Response keeps the original shape (`agent_id`, `revoked_at`) so the
    # SDK / dashboard don't need a model change.
    return RevokeAgentResponse(agent_id=agent_id, revoked_at=deleted_at)


@router.patch("/{agent_id}")
def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Edit an agent's metadata. Sprint 4.11.

    Only the owning customer can edit. Identity-affecting fields (digest
    chain, key, secret) are NOT editable here — only display fields.
    Inactive/revoked agents cannot be edited.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if not agent.is_active:
        raise HTTPException(409, "Agent is revoked — cannot edit")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "name cannot be empty")
        if len(name) > 200:
            raise HTTPException(400, "name too long (max 200)")
        agent.name = name
    if body.model is not None:
        agent.model = body.model.strip() or None
    if body.framework is not None:
        agent.framework = body.framework.strip() or None
    if body.metadata is not None:
        # Replace metadata wholesale. Frontend should send the full object.
        agent.metadata_json = body.metadata

    db.commit()
    db.refresh(agent)
    return {
        "agent_id": agent.id,
        "name": agent.name,
        "model": agent.model,
        "framework": agent.framework,
        "metadata": agent.metadata_json or {},
        "is_active": agent.is_active,
    }


def _agent_summary(
    agent: Agent,
    state: AgentState | None,
    latest_obs: AgentObservable | None,
    integration_surface: str = "none",
    watcher_state: str | None = None,
    is_mesh_paired: bool = False,
    latest_probe_at: datetime | None = None,
) -> dict:
    """Build the compact agent summary used by both list and detail endpoints.

    `integration_surface` is one of "watcher" | "mcp" | "none" — the
    dashboard list uses it to gate the per-row quick-action buttons so
    we don't show "Connect a bot" + "Connect MCP" on an agent that's
    already connected via one of them (D-PROD.18).

    `watcher_state` — Sprint UX-5.9-D. One of "pending" | "active" |
    "error" | "paused" or None when there is no watcher. Lets the
    dashboard list show "Connection issue" inline when a Telegram (or
    future) adapter has been failing without forcing an N+1 fetch per
    row.

    Sprint UX-5.12 — emits the two-layer `trust` block (same shape used
    publicly on `/v1/public/agents/...`). Replaces the legacy
    `latest_confidence` field, which was a single number derived from a
    bias-prone aggregator. See TWO-LAYER-TRUST-DESIGN.md §4.
    """
    from app.services.protections_catalog import agent_has_probe_client

    return {
        "agent_id": agent.id,
        # Sprint UX-5.7a (#634) — slug for the public verify URL.
        # Optional in older clients; treat as fallback to agent_id.
        "public_slug": getattr(agent, "public_slug", None),
        "name": agent.name,
        "model": agent.model,
        "framework": agent.framework,
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "revoked_at": agent.revoked_at.isoformat() if agent.revoked_at else None,
        "last_event_at": (
            state.last_event_at.isoformat() if state and state.last_event_at else None
        ),
        "event_count": state.event_count if state else 0,
        # Sprint UX-5.12 — two-layer trust block. `cryptographic.state` is
        # the binary identity verdict; `behavioral.state` is the sample-
        # size-aware drift signal. The dashboard list renders a compact
        # strip from this; the detail page renders the full breakdown.
        "trust": derive_trust(agent, state, latest_obs, latest_probe_at=latest_probe_at),
        "integration_surface": integration_surface,
        "watcher_state": watcher_state,
        # gh-77 — server-detected behavior mode ("unknown" | "deterministic"
        # | "stochastic"). The customer no longer declares this; the engine
        # observes the first events and decides. Drives which protections
        # apply via resolve_agent_profile().
        "detected_behavior_mode": getattr(
            agent, "detected_behavior_mode", "unknown"
        ),
        # Sprint UX-5.15.C2 — protections summary inline so the dashboard
        # list view can render a per-row health badge without an extra
        # round-trip per agent. Cheap to compute (pure Python iteration
        # over the catalog, no DB queries).
        "protections_summary": _compute_protections_summary(
            agent, state, integration_surface, is_mesh_paired
        ),
        # Sprint UX-5.15.A — customer-facing tier (T0..T4). Pure event-count
        # derivation; consumed by the dashboard TierBadge. See
        # verification_state.derive_tier and IDENTITY-TIERS-AND-COMMUNICATION.md.
        "tier": derive_tier(state.event_count if state else 0, is_mesh_paired),
        # UX-5.15.AL — whether this agent has a probe-capable client.
        # False for every V1 MCP-prompt agent; the dashboard uses it to
        # hide the memory-probe panels that don't apply.
        "probe_capable": agent_has_probe_client(agent),
    }


def _compute_protections_summary(
    agent: Agent,
    state: AgentState | None,
    integration_surface: str,
    is_mesh_paired: bool,
) -> dict:
    """Tiny rollup of the protections catalog: just the counts.

    Customer-safe: returns only {active_count, applicable_count,
    total_count, agent_profile}. The full per-item list lives in the
    detail endpoint's `protections.items` field.
    """
    from app.services.protections_catalog import (
        agent_has_probe_client,
        derive_protections,
        protection_summary,
        resolve_agent_profile,
    )

    profile = resolve_agent_profile(agent)
    items = derive_protections(
        event_count=state.event_count if state else 0,
        agent_profile=profile,
        integration_surface=integration_surface,
        is_mesh_paired=is_mesh_paired,
    )
    summary = protection_summary(items)
    return {**summary, "agent_profile": profile}


@router.get("")
def list_agents(
    limit: int = 50,
    offset: int = 0,
    include_revoked: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List agents owned by the calling customer.

    Sprint 3a-auth: dual auth (API key OR Supabase JWT). Filtering is by
    customer_id, so a customer that has rotated keys or created scoped keys
    still sees all their agents from any of their authorized callers.

    Query params:
      limit:           max rows (1-200, default 50).
      offset:          pagination offset (default 0).
      include_revoked: include revoked agents (default false).

    Ordering: by last_event_at DESC (most recently active first), then
    created_at DESC. Each row carries a lightweight summary including
    the latest identity_confidence so the dashboard can show a list view
    without an extra round-trip per agent.
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    q = _customer_agent_query(db, auth)
    if not include_revoked:
        q = q.filter(Agent.is_active.is_(True))
    agents = q.order_by(Agent.created_at.desc()).limit(limit).offset(offset).all()

    if not agents:
        return {"agents": [], "count": 0, "limit": limit, "offset": offset}

    # Bulk-fetch states and latest observables to avoid N+1 queries.
    agent_ids = [a.id for a in agents]

    states_by_id = {
        s.agent_id: s
        for s in db.query(AgentState).filter(AgentState.agent_id.in_(agent_ids)).all()
    }

    # Latest observable per agent_id via a window-style approach: fetch
    # the most recent row per agent. For small N this is acceptable.
    latest_by_id: dict[str, AgentObservable] = {}
    for aid in agent_ids:
        row = (
            db.query(AgentObservable)
            .filter(AgentObservable.agent_id == aid)
            .order_by(AgentObservable.ts.desc())
            .first()
        )
        if row is not None:
            latest_by_id[aid] = row

    # Sprint 6.5 — integration surface per agent for the dashboard list.
    # We need (a) whether each agent has a live watcher row and (b) how
    # many events its watcher has logged so we can compare against total
    # event count to detect MCP activity. One query each, no N+1.
    from sqlalchemy import func

    watcher_by_agent: dict[str, Watcher] = {
        w.agent_id: w
        for w in db.query(Watcher)
        .filter(
            Watcher.agent_id.in_(agent_ids),
            Watcher.deleted_at.is_(None),
        )
        .all()
    }
    event_totals: dict[str, int] = dict(
        db.query(EventLog.agent_id, func.count(EventLog.id))
        .filter(EventLog.agent_id.in_(agent_ids))
        .group_by(EventLog.agent_id)
        .all()
    )

    def _surface_for(agent: Agent) -> str:
        """V1 model: watcher wins if present and not paused;
        SDK if agent was registered via the developer API (probe_client=True);
        MCP if events flowed from MCP and MCP isn't explicitly disconnected;
        otherwise none."""
        w = watcher_by_agent.get(agent.id)
        if w is not None and w.state != "paused":
            return "watcher"
        metadata = agent.metadata_json or {}
        if metadata.get("probe_client"):
            return "sdk"
        total = event_totals.get(agent.id, 0)
        watcher_events = w.events_logged if w else 0
        has_mcp = (
            total > watcher_events
            and getattr(agent, "mcp_disabled_at", None) is None
        )
        return "mcp" if has_mcp else "none"

    # Sprint UX-5.15.C2 — mesh pair membership per agent for the
    # protections summary. One query, no N+1.
    from app.db.models import AgentMeshPair as _AMP

    mesh_member_ids: set[str] = set()
    for pair in (
        db.query(_AMP.agent_a_id, _AMP.agent_b_id)
        .filter(
            (_AMP.agent_a_id.in_(agent_ids)) | (_AMP.agent_b_id.in_(agent_ids))
        )
        .all()
    ):
        mesh_member_ids.add(pair[0])
        mesh_member_ids.add(pair[1])

    summaries = [
        _agent_summary(
            a,
            states_by_id.get(a.id),
            latest_by_id.get(a.id),
            integration_surface=_surface_for(a),
            watcher_state=(
                watcher_by_agent[a.id].state
                if a.id in watcher_by_agent
                else None
            ),
            is_mesh_paired=a.id in mesh_member_ids,
        )
        for a in agents
    ]

    # Re-sort by last_event_at desc (None last), then created_at desc.
    def _sort_key(s: dict) -> tuple:
        lea = s.get("last_event_at") or ""
        ca = s.get("created_at") or ""
        # Tuple of (has_event, lea, ca) with descending order via negation tricks.
        return (lea == "", lea, ca)  # empty strings sort last when reversed below

    summaries.sort(key=lambda s: (s["last_event_at"] or "", s["created_at"] or ""), reverse=True)

    return {
        "agents": summaries,
        "count": len(summaries),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{agent_id}")
def get_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Single-agent detail with embedded latest observables + pending probes count.

    Designed for the dashboard's `/agents/[id]` detail page — one round-trip
    returns enough to render the entire view, with observables history and
    probe history fetched via the dedicated endpoints when needed.

    Sprint 3a-auth: scoped by customer_id, supports JWT or API key.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    latest_obs = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )

    pending_probes_count = (
        db.query(MemoryProbe)
        .filter(MemoryProbe.agent_id == agent_id, MemoryProbe.status == "pending")
        .count()
    )

    # gh-83 — use the actual latest probe timestamp (issued_at) for
    # last_probe_at instead of latest_obs.ts. The observable ts reflects
    # when the observable job ran, which can be stale or (for agents with
    # observables from a previous registration) completely wrong.
    _latest_probe = (
        db.query(MemoryProbe)
        .filter(MemoryProbe.agent_id == agent_id)
        .order_by(MemoryProbe.issued_at.desc())
        .first()
    )
    _latest_probe_at = _latest_probe.issued_at if _latest_probe is not None else None

    # Compute integration surface up here so _agent_summary can embed
    # the lightweight `integration_surface` string (consumed by the
    # dashboard list view); the full `integration` block is added below.
    from app.services.observable_job import _detect_integration as _detect_int_early

    _int_early = _detect_int_early(db, agent_id)
    _mcp_disabled = getattr(agent, "mcp_disabled_at", None) is not None
    if _int_early["has_watcher"]:
        _surface = "watcher"
    elif _int_early["has_mcp_activity"] and not _mcp_disabled:
        _surface = "mcp"
    else:
        _surface = "none"

    # Sprint UX-5.15.C2 — mesh pair flag computed once and reused for both
    # the inline summary's `protections_summary` and the embedded full items.
    from app.db.models import AgentMeshPair as _AMP_detail

    _is_mesh = (
        db.query(_AMP_detail)
        .filter(
            (_AMP_detail.agent_a_id == agent_id)
            | (_AMP_detail.agent_b_id == agent_id)
        )
        .count()
        > 0
    )
    summary = _agent_summary(
        agent, state, latest_obs,
        integration_surface=_surface,
        is_mesh_paired=_is_mesh,
        latest_probe_at=_latest_probe_at,
    )
    summary["metadata"] = agent.metadata_json or {}
    summary["revocation_reason"] = agent.revocation_reason
    summary["pending_probes_count"] = pending_probes_count
    # Sprint 5 (2026-05-14) pivot to closed algorithm: customer-facing API
    # responses never expose internal observables (ICR / TWC / TTM /
    # β-Crooks) — those are the IP and stay server-side. They're still
    # computed + persisted for the engine's own use.
    # Sprint UX-5.12 — dropped `identity_confidence` from the snapshot
    # too. The single-number aggregator was vulnerable to finite-sample
    # MI bias (Exp-CvD). The customer-facing trust signal now lives in
    # `summary["trust"]` (two layers, never combined).
    summary["latest_observables"] = (
        {
            "ts": latest_obs.ts.isoformat() if latest_obs.ts else None,
            "window_start": (
                latest_obs.window_start.isoformat() if latest_obs.window_start else None
            ),
            "window_end": (
                latest_obs.window_end.isoformat() if latest_obs.window_end else None
            ),
            "n_events": latest_obs.n_events,
            # Customer-facing factors explaining the snapshot in plain
            # English. Persisted in details_json by
            # observable_job.compute_for_agent; we surface them here
            # without filtering. See D-PROD.18 — these never name
            # ICR/TWC/TTM/MVS.
            "score_factors": (
                (latest_obs.details_json or {}).get("score_factors", [])
            ),
        }
        if latest_obs is not None
        else None
    )

    # Sprint 6.3 — integration block (surface label was computed above so
    # the lightweight string is also in `_agent_summary`). Watcher takes
    # precedence over MCP; mcp_disabled_at gates the MCP label so it
    # drops back to watcher/none when the user explicitly disconnected.
    watcher_row = (
        db.query(Watcher)
        .filter(Watcher.agent_id == agent_id, Watcher.deleted_at.is_(None))
        .first()
    )
    watcher_info: dict | None = (
        {
            "id": watcher_row.id,
            "platform": watcher_row.platform,
            "state": watcher_row.state,
            "display_name": watcher_row.display_name,
        }
        if watcher_row is not None and _surface == "watcher"
        else None
    )
    summary["integration"] = {
        "surface": _surface,
        "watcher": watcher_info,
        "mcp_disabled_at": (
            agent.mcp_disabled_at.isoformat()
            if getattr(agent, "mcp_disabled_at", None) is not None
            else None
        ),
    }

    # Sprint UX-5.15.A — protections catalog. Embed the customer-facing
    # checklist in the agent detail response so the dashboard renders it
    # without an extra round-trip. The catalog itself lives server-side
    # (see protections_catalog.py § IP boundary); only the customer-safe
    # subset is exposed here.
    from app.db.models import AgentMeshPair
    from app.services.protections_catalog import (
        agent_has_probe_client,
        derive_protections,
        protection_summary,
        resolve_agent_profile,
    )

    profile = resolve_agent_profile(agent)
    is_mesh_paired = (
        db.query(AgentMeshPair)
        .filter(
            (AgentMeshPair.agent_a_id == agent_id)
            | (AgentMeshPair.agent_b_id == agent_id)
        )
        .count()
        > 0
    )
    protections_items = derive_protections(
        event_count=state.event_count if state else 0,
        agent_profile=profile,
        integration_surface=_surface,
        is_mesh_paired=is_mesh_paired,
        detected_mode=getattr(agent, "detected_behavior_mode", None),
    )
    summary["protections"] = {
        "agent_profile": profile,
        "items": protections_items,
        "summary": protection_summary(protections_items),
    }
    return summary


@router.get("/{agent_id}/protections")
def get_agent_protections(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Customer-facing protections checklist for one agent.

    Sprint UX-5.15.A. Same data as `GET /v1/agents/{id}` embeds under
    `protections`, but available as a lightweight endpoint for the
    dashboard's auto-refresh poll (UX-5.15.UX1 / task #834).
    """
    from app.db.models import AgentMeshPair
    from app.services.protections_catalog import (
        agent_has_probe_client,
        derive_protections,
        protection_summary,
        resolve_agent_profile,
    )

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()

    # Re-derive integration surface (same logic as get_agent above)
    from app.services.observable_job import _detect_integration as _detect_int_p

    _int_p = _detect_int_p(db, agent_id)
    _mcp_disabled_p = getattr(agent, "mcp_disabled_at", None) is not None
    if _int_p["has_watcher"]:
        _surface_p = "watcher"
    elif _int_p["has_mcp_activity"] and not _mcp_disabled_p:
        _surface_p = "mcp"
    else:
        _surface_p = "none"

    profile = resolve_agent_profile(agent)
    is_mesh_paired = (
        db.query(AgentMeshPair)
        .filter(
            (AgentMeshPair.agent_a_id == agent_id)
            | (AgentMeshPair.agent_b_id == agent_id)
        )
        .count()
        > 0
    )
    items = derive_protections(
        event_count=state.event_count if state else 0,
        agent_profile=profile,
        integration_surface=_surface_p,
        is_mesh_paired=is_mesh_paired,
        detected_mode=getattr(agent, "detected_behavior_mode", None),
    )
    return {
        "agent_id": agent_id,
        "event_count": state.event_count if state else 0,
        "agent_profile": profile,
        "integration_surface": _surface_p,
        "items": items,
        "summary": protection_summary(items),
    }


RECOMPUTE_COOLDOWN_SECONDS = 60
"""Minimum gap between manual `/recompute` calls per agent.

Computing is cheap (no external IO; just reads event_logs + applies the
algorithm + writes one row), but we don't want UI button spam writing 100
rows/minute. 60 seconds is the sweet spot: user clicks once, sees the new
score, can re-click in a minute if they generated more activity meanwhile.
"""


@router.post("/{agent_id}/recompute")
def recompute_agent(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Compute a fresh Identity Confidence snapshot for one agent on demand.

    Sprint 6 (2026-05-16): the in-process APScheduler batch runs hourly, which
    means a brand-new agent shows "no data" for up to 60 minutes after first
    activity. Bad onboarding UX. This endpoint lets the dashboard expose a
    "Refresh score" button so the user gets instant feedback.

    Rate-limited to `RECOMPUTE_COOLDOWN_SECONDS` per agent (server-enforced):
    if the latest existing snapshot is younger than the cooldown, returns 429
    with `retry_after_seconds`. The dashboard should grey out the button
    based on this.

    Returns the customer-facing summary of the new snapshot (no internal
    observables — see D-PROD.18). If there were no events in the window,
    `compute_for_agent` returns None and we surface that with 412 so the UI
    can show "no events yet, send some traffic first".
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    latest = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    if latest is not None and latest.ts is not None:
        elapsed = (now - latest.ts).total_seconds()
        if elapsed < RECOMPUTE_COOLDOWN_SECONDS:
            retry_after = int(RECOMPUTE_COOLDOWN_SECONDS - elapsed) + 1
            raise HTTPException(
                status_code=429,
                detail=f"Recompute cooldown active; retry in {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )

    try:
        snap = compute_for_agent(db, agent_id, window=DEFAULT_WINDOW)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Recompute failed: {e}") from e

    if snap is None:
        raise HTTPException(
            412,
            "No events in the current window to compute over yet. "
            "Send some activity to the agent first.",
        )

    # Sprint UX-5.12 — recompute returns the same two-layer trust block
    # the detail endpoint emits. The frontend uses this to refresh the
    # card without a second round-trip. Single-number identity_confidence
    # is no longer exposed (Exp-CvD finding — single aggregator was
    # bias-prone). See TWO-LAYER-TRUST-DESIGN.md §4.
    fresh_state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    fresh_obs = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    return {
        "agent_id": agent_id,
        "ts": snap.ts.isoformat() if snap.ts else None,
        "n_events": snap.n_events,
        "trust": derive_trust(agent, fresh_state, fresh_obs),
        "score_factors": (snap.details_json or {}).get("score_factors", []),
        "next_recompute_at": (
            now + timedelta(seconds=RECOMPUTE_COOLDOWN_SECONDS)
        ).isoformat(),
    }


# ----------------------------------------------------------------------- #
# Sprint 6.4 / #575 — MCP disconnect / reconnect                          #
# ----------------------------------------------------------------------- #

@router.post(
    "/{agent_id}/disconnect-mcp",
    response_model=DisconnectMcpResponse,
)
def disconnect_mcp(
    agent_id: str,
    req: DisconnectMcpRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Disable the MCP integration surface for one agent.

    V1 model (D-PROD.18): one agent = one identity = one integration. If
    a user wants to switch this agent from MCP to a watcher (or just
    park it), they call this endpoint. After the call:
      - POST /v1/log_event returns 403 for this agent.
      - integration.surface drops MCP from the active surface so the
        dashboard can re-offer "Connect a bot" or show the watcher.
      - Historical EventLog rows are preserved — the disconnect is a
        gate on new ingestion, not a wipe.

    Reversible via POST /v1/agents/{id}/reconnect-mcp. To switch agents
    cleanly, customers can create a new agent instead — that gives a
    fresh observable history.

    Confirmation: `confirmation_name` must match the agent's display
    name (same pattern as revoke). 422 if mismatched, 409 if already
    disabled, 404 if agent doesn't exist for this customer.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if req.confirmation_name != agent.name:
        raise HTTPException(
            422,
            "Confirmation name does not match agent name. "
            "Type the agent's exact display name to confirm.",
        )

    if agent.mcp_disabled_at is not None:
        raise HTTPException(
            409,
            "MCP is already disconnected for this agent. "
            "Use /reconnect-mcp to re-enable.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent.mcp_disabled_at = now
    db.commit()
    return {"agent_id": agent_id, "mcp_disabled_at": now}


@router.post(
    "/{agent_id}/reconnect-mcp",
    response_model=ReconnectMcpResponse,
)
def reconnect_mcp(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Re-enable the MCP integration surface for an agent.

    Clears `mcp_disabled_at`. No confirmation required (re-enabling is
    not destructive — it just resumes accepting events on a surface
    that was already wired up).
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent.mcp_disabled_at is None:
        raise HTTPException(409, "MCP is not disconnected for this agent.")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    agent.mcp_disabled_at = None
    db.commit()
    return {"agent_id": agent_id, "mcp_reconnected_at": now}


# ----------------------------------------------------------------------- #
# UX-5.15.P / D-PROD.25 — Reset behavior baseline                         #
# ----------------------------------------------------------------------- #

@router.post(
    "/{agent_id}/reset-baseline",
    response_model=ResetBaselineResponse,
)
def reset_baseline(
    agent_id: str,
    req: ResetBaselineRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Reset the behavior baseline for an agent.

    UX-5.15.P / D-PROD.25 — the customer is saying "the new behavior is
    the new normal". Pre-reset events are NOT deleted; they remain
    archived as auditable evidence. The identity engine ignores
    AgentObservable rows with ts < last_baseline_reset_at when
    computing the current shape, so the next observable batch will
    start fresh.

    Use case: customer received a drift alert (because they ran
    /compact, switched projects, changed machines, etc.) and confirmed
    that the new behavior is intentional. By accepting the new normal,
    the score post-reset can climb back up cleanly without dragging
    the pre-reset divergence as evidence against them.

    Confirmation: `confirmation_name` must match the agent's display
    name (same pattern as revoke / disconnect-mcp) so this is not done
    by accident. 422 if mismatched, 404 if agent doesn't exist for
    this customer.

    Note on anti-receta: the LLM / MCP client cannot trigger this. Only
    the human owner from the dashboard. That's the moat — an impostor
    holding the API key can divert behavior but cannot "accept the new
    normal" on the owner's behalf, so the score stays low and the
    owner sees the drift in the dashboard.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if req.confirmation_name != agent.name:
        raise HTTPException(
            422,
            "Confirmation name does not match agent name. "
            "Type the agent's exact display name to confirm.",
        )

    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if not state:
        # Defensive: AgentState should always exist for a registered agent.
        # If it doesn't, the agent has never logged anything, so a
        # baseline reset is a no-op.
        raise HTTPException(
            409,
            "This agent has no behavior history yet — nothing to reset.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    state.last_baseline_reset_at = now
    state.baseline_reset_count = (state.baseline_reset_count or 0) + 1
    # Snapshot current physical event_count. derive_trust uses this to
    # compute events_since_baseline = event_count - reset_event_count,
    # which is the value that feeds the behavioral state machine
    # (BEHAVIORAL_NOT_ENOUGH_DATA → building → stable). After reset the
    # agent re-enters baselining naturally.
    state.baseline_reset_event_count = state.event_count or 0
    db.commit()
    return {
        "agent_id": agent_id,
        "last_baseline_reset_at": now,
        "baseline_reset_count": state.baseline_reset_count,
    }


@router.post(
    "/{agent_id}/reissue-secret",
    response_model=ReissueSecretResponse,
)
def reissue_secret(
    agent_id: str,
    req: ReissueSecretRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Re-key an agent: issue a fresh agent_secret and restart its
    cryptographic verification from a new genesis.

    UX-5.17 #505 / #931. The agent_secret is what the agent uses to
    answer verification checks. The developer API returns it once at
    register and the dashboard register path now does too (#931) — but
    an agent created before that, or whose owner lost the secret, has
    no way to get one. This is that recovery path.

    A full re-key is the only honest option: the digest chain is rooted
    in the secret (digest[0] = sha256(secret ‖ "init")), so a new
    secret means a new chain. The agent's prior verification activity
    is cleared and its tier resets — a chain whose root just changed
    cannot be preserved. The agent keeps its identity (id, name, slug,
    external anchors, API keys, watcher, webhooks, mesh pairing); only
    the verification history is wiped.

    Confirm-by-name guard (same as revoke / reset-baseline): only the
    human owner from the dashboard. An impostor holding the API key
    cannot re-key — the moat is unchanged.
    """
    import hashlib
    import os

    from app.db.models import (
        AgentMeshPair,
        AgentObservable,
        AgentState,
        CorroborationPoint,
        EventLog,
        MemoryProbe,
        PredictionSubmission,
        ZKHProof,
    )

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if req.confirmation_name != agent.name:
        raise HTTPException(
            422,
            "Confirmation name does not match agent name. "
            "Type the agent's exact display name to confirm.",
        )

    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if not state:
        raise HTTPException(500, "Agent state was not initialized")

    # New secret + fresh genesis. digest[0] = sha256(secret || "init").
    new_secret = os.urandom(32).hex()
    new_genesis = hashlib.sha256(
        bytes.fromhex(new_secret) + b"init"
    ).hexdigest()

    # Wipe verification activity built on the OLD chain. FK-safe, scoped
    # to this agent. The agent row, AgentState, API keys, watcher,
    # anchors, webhooks and mesh pairing all survive — only the
    # verification history is cleared. Verification rows (issued proofs)
    # are kept: a signed proof stays an honest record of what the agent
    # issued, and it is signed by the server key, not the agent_secret.
    db.query(AgentObservable).filter(
        AgentObservable.agent_id == agent_id
    ).delete(synchronize_session=False)
    db.query(MemoryProbe).filter(
        MemoryProbe.agent_id == agent_id
    ).delete(synchronize_session=False)
    db.query(EventLog).filter(
        EventLog.agent_id == agent_id
    ).delete(synchronize_session=False)
    db.query(PredictionSubmission).filter(
        PredictionSubmission.agent_id == agent_id
    ).delete(synchronize_session=False)
    db.query(ZKHProof).filter(
        ZKHProof.agent_id == agent_id
    ).delete(synchronize_session=False)
    mesh_pair_ids = [
        row[0]
        for row in db.query(AgentMeshPair.id)
        .filter(
            (AgentMeshPair.agent_a_id == agent_id)
            | (AgentMeshPair.agent_b_id == agent_id)
        )
        .all()
    ]
    if mesh_pair_ids:
        db.query(CorroborationPoint).filter(
            CorroborationPoint.mesh_pair_id.in_(mesh_pair_ids)
        ).delete(synchronize_session=False)

    # Re-key the state: new secret, fresh genesis, event count back to 0.
    # The behavioral baseline machine keys off
    # event_count - baseline_reset_event_count; with both at 0 the agent
    # cleanly re-enters baselining.
    state.agent_secret = new_secret
    state.history_digest = new_genesis
    state.event_count = 0
    state.baseline_reset_event_count = 0
    reissued_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    return ReissueSecretResponse(
        agent_id=agent_id,
        agent_secret=new_secret,
        reissued_at=reissued_at,
        secret_warning=(
            "Store this secret now — it is shown only once. It replaces "
            "the agent's previous secret, which no longer works. This "
            "agent's verification has restarted from scratch; its tier "
            "will climb again as new activity accumulates."
        ),
    )


# ----------------------------------------------------------------------- #
# Sprint 7 / MCS — mesh pair management                                   #
# ----------------------------------------------------------------------- #

@router.post("/{agent_id}/mesh/pair")
def create_agent_mesh_pair(
    agent_id: str,
    body: dict,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Pair this agent with another agent owned by the same customer.

    Body: {"partner_agent_id": "agt_..."}. The partner must already
    exist for this customer. Returns the canonical pair row (idempotent
    when called repeatedly with the same pair).
    """
    from app.services.mcs import create_mesh_pair, canonical_pair

    partner_id = (body or {}).get("partner_agent_id")
    if not partner_id:
        raise HTTPException(400, "partner_agent_id required")

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    partner = (
        _customer_agent_query(db, auth).filter(Agent.id == partner_id).first()
    )
    if not partner:
        raise HTTPException(404, "Partner agent not found in this customer")
    if agent.id == partner.id:
        raise HTTPException(400, "Cannot pair an agent with itself")

    pair = create_mesh_pair(db, auth.customer_id, agent.id, partner.id)
    return {
        "mesh_pair_id": pair.id,
        "agent_a_id": pair.agent_a_id,
        "agent_b_id": pair.agent_b_id,
        "created_at": pair.created_at.isoformat() if pair.created_at else None,
    }


@router.get("/{agent_id}/mesh")
def get_agent_mesh_pair(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the agent's active mesh pair, if any."""
    from app.services.mcs import find_pair_for_agent

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    pair = find_pair_for_agent(db, agent_id)
    if pair is None:
        return {"mesh_pair": None}
    partner = pair.agent_b_id if pair.agent_a_id == agent_id else pair.agent_a_id
    return {
        "mesh_pair": {
            "id": pair.id,
            "partner_agent_id": partner,
            "created_at": pair.created_at.isoformat() if pair.created_at else None,
        }
    }


@router.delete("/{agent_id}/mesh/{pair_id}")
def delete_agent_mesh_pair(
    agent_id: str,
    pair_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Hard-delete a mesh pair. Both agents stop participating;
    pending corroboration_points remain for audit. Both members of the
    pair must belong to the calling customer.
    """
    from app.db.models import AgentMeshPair

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    pair = (
        db.query(AgentMeshPair)
        .filter(
            AgentMeshPair.id == pair_id,
            AgentMeshPair.customer_id == auth.customer_id,
        )
        .first()
    )
    if pair is None:
        raise HTTPException(404, "Mesh pair not found for this customer")
    if agent.id not in (pair.agent_a_id, pair.agent_b_id):
        raise HTTPException(403, "Agent is not part of this mesh pair")

    db.delete(pair)
    db.commit()
    return {"mesh_pair_id": pair_id, "deleted": True}


@router.get("/{agent_id}/observables")
def get_observables(
    agent_id: str,
    limit: int = 50,
    recompute: bool = False,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the most recent Trinity observable snapshots for an agent.

    Query params:
      limit (int, default 50): number of historical snapshots to return.
      recompute (bool, default false): if true, compute a fresh snapshot
        on-demand before returning. Useful for dogfooding/dashboards before
        the hourly batch has run for a new agent.

    Auth: dual (API key or Supabase JWT), scoped by customer_id.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if recompute:
        try:
            compute_for_agent(db, agent_id, window=DEFAULT_WINDOW)
        except Exception:
            # Don't fail the read; recompute is best-effort.
            db.rollback()

    rows = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )

    # Sprint 5 (2026-05-14): strip internal observables (ICR/TWC/TTM/β) +
    # details_json from the public history. Customer-facing API only sees
    # the identity_confidence score per window + activity counts.
    snapshots = [
        {
            "ts": r.ts.isoformat() if r.ts else None,
            "window_start": r.window_start.isoformat() if r.window_start else None,
            "window_end": r.window_end.isoformat() if r.window_end else None,
            "n_events": r.n_events,
            "identity_confidence": r.identity_confidence,
        }
        for r in rows
    ]

    latest = snapshots[0] if snapshots else None
    return {
        "agent_id": agent_id,
        "is_active": agent.is_active,
        "latest": latest,
        "history": snapshots,
        "count": len(snapshots),
    }


@router.get("/{agent_id}/probes")
def list_probes(
    agent_id: str,
    status: str = "pending",
    limit: int = 20,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List Memory Verification (MVS) probes for an agent.

    Query params:
      status: "pending" (default) | "responded" | "expired" | "all"
      limit:  max rows to return (1-50, default 20)

    Pending probes are returned WITHOUT the expected_proof (only the agent
    should be able to compute it).

    Sprint 3a-auth: dual auth, scoped by customer_id.
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    if status == "pending":
        rows = memory_verifier.list_pending_probes(db, agent_id, limit=limit)
        return {"agent_id": agent_id, "status": "pending", "probes": rows}

    # Responded / expired / all — safe to expose more details (excluding expected_proof).
    from app.db.models import MemoryProbe
    q = db.query(MemoryProbe).filter(MemoryProbe.agent_id == agent_id)
    if status in ("responded", "expired"):
        q = q.filter(MemoryProbe.status == status)
    rows = q.order_by(MemoryProbe.issued_at.desc()).limit(max(1, min(limit, 50))).all()

    return {
        "agent_id": agent_id,
        "status": status,
        "probes": [
            {
                "probe_id": r.id,
                "target_event_count": r.target_event_count,
                "nonce": r.nonce,
                "status": r.status,
                "valid": r.valid,
                "issued_at": r.issued_at.isoformat() if r.issued_at else None,
                "responded_at": r.responded_at.isoformat() if r.responded_at else None,
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
            }
            for r in rows
        ],
    }


# ----------------------------------------------------------------------- #
# Sprint 6-A2A 6.1 — dashboard-issued verifiable identity claim           #
# ----------------------------------------------------------------------- #

# TTLs permitidos por el endpoint (segundos). Mantenemos lista cerrada
# para no permitir tokens arbitrariamente largos.
_ALLOWED_TTL_SECONDS = {
    300,    # 5 min   — for one-off A2A calls
    3600,   # 1 hour  — default
    86400,  # 24 hours — embedded in agent listings / bios
}


@router.post("/{agent_id}/issue-proof", response_model=IssueProofResponse)
def issue_proof(
    agent_id: str,
    req: IssueProofRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Mint a verifiable identity claim for a customer-owned agent.

    Sprint 6-A2A 6.1 — issuing-side companion to the existing public
    `POST /v1/verify-proof` endpoint.

    Distinct from the `/v1/verify` flow (which requires a challenge ↔
    response round trip): here the customer is authenticated against
    the dashboard via JWT and is the proven owner of the agent. They
    just want a signed claim they can hand off to a relying party.

    The signed JWT embeds:
      - sub = agent_id
      - jti = unique proof_id
      - iat / exp = issued / expires (TTL from request, validated)
      - kappa_score = current identity_confidence (snapshot)
      - scope (optional, free-form)

    Insert a `Verification` row so the issue is auditable on the
    customer side and (Sprint 6-A2A 6.2) the verifications panel in
    the dashboard can show "you issued N claims in the last 7 days".
    """
    from app.core.signing import sign_kappa_proof
    from app.db.models import Verification

    if req.ttl_seconds not in _ALLOWED_TTL_SECONDS:
        raise HTTPException(
            422,
            f"ttl_seconds must be one of {sorted(_ALLOWED_TTL_SECONDS)}",
        )
    if req.scope is not None and len(req.scope) > 128:
        raise HTTPException(422, "scope must be 128 chars or fewer")

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if not agent.is_active:
        raise HTTPException(409, "Agent is revoked; cannot issue claims")

    # Snapshot current identity_confidence from the latest observable
    # row (if any) so the claim carries a meaningful score. None is OK
    # for very new agents — the claim still binds identity, just
    # without confidence info.
    latest = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent_id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    score: float = float(latest.identity_confidence) if latest else 0.0

    proof_id = new_id("prf")
    token, expires_at = sign_kappa_proof(
        proof_id=proof_id,
        agent_id=agent_id,
        score=score,
        verified=True,  # the customer authenticated; the claim is authentic
        steps=0,        # no challenge-response round here
        scope=req.scope,
        ttl_seconds=req.ttl_seconds,
    )
    issued_at = datetime.now(timezone.utc)

    db.add(Verification(
        id=proof_id,
        agent_id=agent_id,
        proof_jwt=token,
        score=score,
        verified=True,
        steps=0,
        scope=req.scope,
        issued_at=issued_at.replace(tzinfo=None),
        expires_at=expires_at.replace(tzinfo=None),
    ))
    db.commit()

    return IssueProofResponse(
        proof_id=proof_id,
        agent_id=agent_id,
        kappa_proof=token,
        issued_at=issued_at,
        expires_at=expires_at,
        scope=req.scope,
        score=score,
    )


# ----------------------------------------------------------------------- #
# Sprint 6-A2A 6.2 — verifications served (recent timeline)               #
# ----------------------------------------------------------------------- #

@router.get("/{agent_id}/verifications")
def list_verifications(
    agent_id: str,
    limit: int = 50,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Return the latest verification attempts received for this agent.

    Each row is one call to the public POST /v1/verify-proof endpoint
    where the JWT carried `sub = agent_id`. Used by the dashboard's
    "Recent verifications served" panel and the "X verifications
    served since…" social-proof number on the verify page.

    Privacy: we never recorded the relying-party IP. The returned
    rows only contain timestamp + outcome + scope.

    Auth: customer must own the agent (same scoping as get_agent).
    """
    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    limit = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(VerificationAttempt)
        .filter(VerificationAttempt.agent_id == agent_id)
        .order_by(VerificationAttempt.verified_at.desc())
        .limit(limit)
        .all()
    )
    total = (
        db.query(VerificationAttempt)
        .filter(VerificationAttempt.agent_id == agent_id)
        .count()
    )
    valid_count = (
        db.query(VerificationAttempt)
        .filter(
            VerificationAttempt.agent_id == agent_id,
            VerificationAttempt.valid.is_(True),
        )
        .count()
    )

    return {
        "agent_id": agent_id,
        "total": total,
        "valid": valid_count,
        "items": [
            {
                "id": r.id,
                "proof_id": r.proof_id,
                "verified_at": r.verified_at.isoformat() if r.verified_at else None,
                "valid": r.valid,
                "reason": r.reason,
                "scope": r.scope,
            }
            for r in rows
        ],
    }


# ----------------------------------------------------------------------- #
# #64 — behavioral drift events (κ-engine V2 alerts surface)              #
# ----------------------------------------------------------------------- #

@router.get("/{agent_id}/drift-events")
def list_drift_events(
    agent_id: str,
    limit: int = 50,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List the agent's behavioral drift events, newest first (#64).

    The dashboard surface for the alerts pipeline: each row is a
    ``DRIFT_DETECTED`` event the κ-engine V2 emitted when the agent's
    recent traffic drifted from its learned baseline. #65 renders these
    as the agent's "Behavioral changes" timeline.
    """
    from app.db.models import DriftEvent

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    limit = max(1, min(int(limit or 50), 200))
    rows = (
        db.query(DriftEvent)
        .filter(DriftEvent.agent_id == agent_id)
        .order_by(DriftEvent.detected_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "agent_id": agent_id,
        "total": len(rows),
        "items": [
            {
                "id": r.id,
                "dominant_feature": r.dominant_feature,
                "drift_score": r.drift_score,
                "magnitude": r.magnitude,
                "baseline_value": r.baseline_value,
                "current_value": r.current_value,
                "window_size": r.window_size,
                "baseline_n_events": r.baseline_n_events,
                "notified_email": r.notified_email,
                "notified_webhook": r.notified_webhook,
                "acknowledged_at": (
                    r.acknowledged_at.isoformat() if r.acknowledged_at else None
                ),
                "detected_at": (
                    r.detected_at.isoformat() if r.detected_at else None
                ),
            }
            for r in rows
        ],
    }


@router.post("/{agent_id}/drift-events/{drift_event_id}/acknowledge")
def acknowledge_drift_event(
    agent_id: str,
    drift_event_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Mark a drift event as expected ("this is the new normal") (#64/#65).

    Records the acknowledgement on the row (auditable — we never delete
    the evidence). Idempotent: acknowledging an already-acknowledged
    event returns the existing timestamp. #65 wires the UI; the column +
    endpoint live here so the backend surface is complete.
    """
    from app.db.models import DriftEvent

    agent = _customer_agent_query(db, auth).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")

    event = (
        db.query(DriftEvent)
        .filter(
            DriftEvent.id == drift_event_id,
            DriftEvent.agent_id == agent_id,
        )
        .first()
    )
    if not event:
        raise HTTPException(404, "Drift event not found")

    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

    return {
        "id": event.id,
        "acknowledged_at": event.acknowledged_at.isoformat(),
    }
