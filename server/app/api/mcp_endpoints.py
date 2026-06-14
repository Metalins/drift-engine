"""MCP-compatible HTTP endpoints.

These implement the MCP protocol over HTTP so that AI clients (Claude Code,
Cursor, etc.) can integrate Metalins with minimal config — no local install.

Two transports supported:
  1. POST /v1/mcp/tools/{tool_name} — direct tool call (REST-style)
  2. POST /v1/mcp/jsonrpc — JSON-RPC 2.0 (MCP standard)

The exposed tools to LLM clients via JSON-RPC (Sprint UX-5.15.R — D-PROD.26):
  - metalins_log_event
  - metalins_get_proof
  - metalins_get_status
  - metalins_respond_probe / predict / corroboration / zkh_*

`metalins_register_agent` was REMOVED from the JSON-RPC surface in
UX-5.15.R because letting the LLM create agents was the root cause
of the "ghost agent" bug Jose hit during UX-5.15.Q: the LLM would
address an existing agent by name, get a 404, and then helpfully
create a *new* agent with that name as its `agent_id`, producing
silent duplicates. Customer-facing wizard is now the only path the
LLM ever sees — it hands the LLM a canonical `agt_…` id and the LLM
only ever logs against an already-existing agent.

The REST shortcut `POST /v1/mcp/tools/metalins_register_agent`
remains live because:
  • Real MCP clients (Claude Desktop, Cursor, etc.) speak JSON-RPC,
    not this REST shortcut, so the LLM cannot reach it.
  • The Python SDK and the planned `metalins-wrap` wrapper post to
    this REST path directly to bootstrap agents from deterministic
    application code (Diana persona) — that path must keep working.
Two transports, asymmetric exposure: JSON-RPC = LLM = read-only on
agent identity; REST shortcut = SDK = full lifecycle.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.auth import require_api_key
from app.core import ml_dsa_signing
from app.core.ids import new_id
from app.core.slug import slugify
from app.db import get_db
from app.db.models import APIKey, Agent, EventLog, AgentState, MemoryProbe
from app.kappa.behavioral_schema import BehavioralSchemaError, validate_behavioral
from app.services import behavior_detection, memory_verifier


router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


def _find_agent_by_handle(
    handle: str, customer_id: str | None, db: Session
) -> Agent | None:
    """UX-5.15.Q — find an agent the customer "owns" by id OR slug OR slugified
    name. Used by `_resolve_agent` and `_do_register_agent` so the LLM can
    say "agent prueba-claudio" and we resolve to the real opaque id.

    Match precedence:
      1. `Agent.id` exact match (canonical path).
      2. `Agent.public_slug == handle` (already-claimed slug).
      3. `slugify(Agent.name) == slugify(handle)` (humanized name match).

    Returns the unique match or None. If multiple agents in the same
    customer scope match (2) or (3), returns None — caller must surface
    an ambiguous-id error rather than guess.

    Customer scope: only agents whose creator_key.customer_id == the
    given customer_id are eligible. Caller is responsible for passing
    api_key.customer_id.
    """
    if not handle or customer_id is None:
        return None

    # (1) Exact id match — fast path, includes the legacy agt_XXX format.
    by_id = db.query(Agent).filter(Agent.id == handle).first()
    if by_id is not None:
        creator_key = (
            db.query(APIKey).filter(APIKey.id == by_id.api_key_id).first()
        )
        if creator_key and creator_key.customer_id == customer_id:
            return by_id
        return None  # exists but other customer — caller decides response

    # (2)+(3) Scan agents in this customer's scope.
    candidates = (
        db.query(Agent)
        .join(APIKey, Agent.api_key_id == APIKey.id)
        .filter(APIKey.customer_id == customer_id)
        .filter(Agent.is_active.is_(True))
        .all()
    )
    handle_slug = slugify(handle)

    matches = []
    for c in candidates:
        if c.public_slug and c.public_slug == handle:
            matches.append(c)
            continue
        if handle_slug and c.name and slugify(c.name) == handle_slug:
            matches.append(c)

    if len(matches) == 1:
        return matches[0]
    return None  # zero or ambiguous


def _resolve_agent(agent_id: str, api_key: APIKey, db: Session) -> Agent:
    """Find an agent the caller's API key is allowed to operate on.

    Sprint 3a-auth.9: the legacy filter `Agent.api_key_id == api_key.id` breaks
    when a customer creates a new key scoped to an existing agent — the new
    key's id doesn't match the original creator's. Correct ownership is by
    customer:

      - If `api_key.agent_id` is set (scoped key), it must match this agent.
      - Otherwise, any key belonging to the same customer as the agent's
        creator_key may operate on it (customer-wide visibility).

    This matches the dashboard scoping rules we already use for GET /v1/agents.
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        # UX-5.15.Q — before giving up, try to match by public_slug or
        # slugified name within this customer's scope. The LLM frequently
        # sends the human-readable name (e.g. "prueba-claudio") instead
        # of the opaque internal id (agt_XXX...). Resolving by slug
        # closes the γ↔α gap from INTEGRATION-LIFECYCLE.md §2 without
        # making the customer think about it.
        agent = _find_agent_by_handle(agent_id, api_key.customer_id, db)
    if not agent:
        # Sprint UX-5.15.O — actionable 404 for MCP clients.
        # Claude Code & friends surface the tool-call error message to
        # the LLM, which often relays it to the user. A bare "not found"
        # leads the user nowhere; this guidance tells them their MCP
        # server entry is pointing to a deleted agent and how to clean
        # it up.
        raise HTTPException(
            404,
            (
                f"Agent '{agent_id}' was not found. This usually means the "
                f"agent was deleted from the Metalins dashboard. Your MCP "
                f"client should stop trying to log to it: run "
                f"`claude mcp list` to find the server entry for this "
                f"agent, then `claude mcp remove <name> --scope user`. "
                f"For Cursor or Claude Desktop, remove the matching entry "
                f"in their config or Connectors settings."
            ),
        )

    # Scoped key: must point at exactly this agent.
    if api_key.agent_id is not None:
        if api_key.agent_id != agent.id:
            # Sprint UX-5.15.O — actionable 404 for MCP clients.
            # Claude Code & friends surface the tool-call error message to
            # the LLM, which often relays it to the user. A bare "not found"
            # leads the user nowhere; this guidance tells them their MCP
            # server entry is pointing to a deleted agent and how to clean
            # it up.
            raise HTTPException(
                404,
                (
                    f"Agent '{agent_id}' was not found. This usually means the "
                    f"agent was deleted from the Metalins dashboard. Your MCP "
                    f"client should stop trying to log to it: run "
                    f"`claude mcp list` to find the server entry for this "
                    f"agent, then `claude mcp remove <name> --scope user`. "
                    f"For Cursor or Claude Desktop, remove the matching entry "
                    f"in their config or Connectors settings."
                ),
            )
        return agent

    # Customer-wide key: agent's creator_key must share customer with us.
    creator_key = (
        db.query(APIKey).filter(APIKey.id == agent.api_key_id).first()
    )
    if not creator_key or creator_key.customer_id != api_key.customer_id:
        # Sprint UX-5.15.O — actionable 404 for MCP clients.
        # Claude Code & friends surface the tool-call error message to
        # the LLM, which often relays it to the user. A bare "not found"
        # leads the user nowhere; this guidance tells them their MCP
        # server entry is pointing to a deleted agent and how to clean
        # it up.
        raise HTTPException(
            404,
            (
                f"Agent '{agent_id}' was not found. This usually means the "
                f"agent was deleted from the Metalins dashboard. Your MCP "
                f"client should stop trying to log to it: run "
                f"`claude mcp list` to find the server entry for this "
                f"agent, then `claude mcp remove <name> --scope user`. "
                f"For Cursor or Claude Desktop, remove the matching entry "
                f"in their config or Connectors settings."
            ),
        )
    return agent


# ---------- MCP tool implementations ----------

def _do_register_agent(args: dict, api_key: APIKey, db: Session) -> dict:
    agent_id = args.get("agent_id")
    description = args.get("description", "")
    if not agent_id:
        raise HTTPException(400, "agent_id required")

    # Scoped keys cannot register new agents — they may only operate on
    # their bound agent. Use a customer-wide key (or the dashboard) instead.
    if api_key.agent_id is not None:
        raise HTTPException(
            403,
            "This API key is scoped to a specific agent and cannot register new ones.",
        )

    # Check if exists in this customer's namespace.
    # UX-5.15.Q — match by id OR slug OR slugified name so that an LLM
    # calling register_agent with the human-readable name doesn't
    # create a ghost agent next to the real one created via the
    # dashboard. If we find the existing agent, return its real id (not
    # the handle the LLM sent) so subsequent tool calls use the canon.
    existing = _find_agent_by_handle(agent_id, api_key.customer_id, db)
    if existing:
        return {
            "status": "already_registered",
            "agent_id": existing.id,
            "message": (
                f"Agent '{existing.name}' is already registered (id "
                f"{existing.id}). Use that id for subsequent tool calls."
            ),
        }
    # Cross-customer collision check on the raw id — same as before.
    collision = db.query(Agent).filter(Agent.id == agent_id).first()
    if collision is not None:
        raise HTTPException(409, f"agent_id '{agent_id}' already taken")

    # Create
    agent_secret = os.urandom(32).hex()
    # gh-77 — ignore any declared behavior profile in the registration
    # metadata. Behavior is detected server-side from the agent's first
    # events (Agent.detected_behavior_mode), not declared at creation.
    _raw_meta = args.get("metadata", {}) or {}
    _ignored_profile_keys = ("agent_profile", "profile", "agent_type", "behavior_mode")
    clean_meta = {k: v for k, v in _raw_meta.items() if k not in _ignored_profile_keys}
    agent = Agent(
        id=agent_id,
        api_key_id=api_key.id,
        name=description or agent_id,
        model=args.get("model"),
        framework=args.get("framework"),
        metadata_json=clean_meta,
        detected_behavior_mode="unknown",
        is_active=True,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(agent)
    # Initial state
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
    # SECURITY: agent_secret is returned ONCE, at register. The SDK / agent
    # must persist it locally — it is required to compute MVS probe proofs.
    # If lost, the agent must re-register (new agent_id). The server keeps
    # the same secret in AgentState; this response is the only window the
    # client has to capture it.
    return {
        "status": "registered",
        "agent_id": agent_id,
        "agent_secret": agent_secret,
        "initial_digest": initial_digest,
        "secret_warning": (
            "Save 'agent_secret' and 'initial_digest' immediately. They are "
            "shown only once and are required to respond to memory verification "
            "(MVS) probes. If lost, the agent must be re-registered."
        ),
        "message": f"Agent '{agent_id}' registered successfully.",
    }


def _do_log_event(args: dict, api_key: APIKey, db: Session) -> dict:
    agent_id = args.get("agent_id")
    input_hash = args.get("input_hash")
    output_hash = args.get("output_hash")
    metadata = args.get("metadata", {})

    if not all([agent_id, input_hash, output_hash]):
        raise HTTPException(400, "agent_id, input_hash, output_hash required")

    # #63 — behavioral features carrier. The SDK ships a bag of
    # irreversible structural features under metadata['behavioral'] so the
    # κ-engine V2 has signal to baseline against (the server only stores
    # hashes of the content). Validate the schema when present; events
    # without it (everything logged before #63) stay valid. Persist the
    # normalized copy so downstream stats read a consistent shape.
    if isinstance(metadata, dict) and "behavioral" in metadata:
        try:
            metadata = {**metadata, "behavioral": validate_behavioral(metadata["behavioral"])}
        except BehavioralSchemaError as exc:
            raise HTTPException(400, f"invalid behavioral metadata: {exc}")

    # Verify agent belongs to customer (Sprint 3a-auth.9 scoping).
    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id

    # Sprint 6.4 / #575 — MCP disconnect gate. If the user explicitly
    # disconnected MCP for this agent, refuse new events on this surface.
    # The user can reconnect via POST /v1/agents/{id}/reconnect-mcp.
    if getattr(agent, "mcp_disabled_at", None) is not None:
        # Sprint UX-5.15.O — same accionable framing as the 404 case.
        # The LLM relaying this error to the user gets a real next step
        # ("reconnect, or remove the MCP server entry") instead of a
        # dead-end refusal.
        raise HTTPException(
            403,
            (
                f"MCP integration is disconnected for agent '{agent_id}'. "
                f"Either reconnect it from the Metalins dashboard, or "
                f"stop your client from trying: run `claude mcp list` to "
                f"find the server entry and `claude mcp remove <name> "
                f"--scope user` to clean it up. (Cursor / Claude Desktop: "
                f"remove the matching entry in their config or Connectors "
                f"settings.)"
            ),
        )

    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if not state:
        raise HTTPException(500, "Agent state missing — re-register")

    # Update history digest chain
    h = hashlib.sha256()
    h.update(bytes.fromhex(state.history_digest))
    h.update(input_hash.encode())
    h.update(output_hash.encode())
    new_digest = h.hexdigest()
    state.event_count += 1
    state.history_digest = new_digest
    state.last_event_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # Sign event with rotating secret (R10-A RKS)
    rotating_secret = hmac.new(
        bytes.fromhex(state.agent_secret), bytes.fromhex(new_digest),
        hashlib.sha256,
    ).digest()
    msg = f"{input_hash}|{output_hash}|{state.event_count}".encode()
    sig = hmac.new(rotating_secret, msg, hashlib.sha256).hexdigest()

    # ML-DSA-65 (FIPS 204) quantum-safe signature — Asqav-compatible
    try:
        ml_dsa_sig_info = ml_dsa_signing.sign_event_with_metadata(
            agent_id=agent_id,
            event_count=state.event_count,
            input_hash=input_hash,
            output_hash=output_hash,
            history_digest=new_digest,
        )
        ml_dsa_sig = ml_dsa_sig_info["ml_dsa_signature"]
    except Exception as _ml_dsa_err:
        # Non-fatal: ML-DSA is additive. HMAC remains the primary sig.
        import logging as _log
        _log.getLogger("metalins.ml_dsa").warning(
            "ML-DSA signing failed (non-fatal): %s", _ml_dsa_err
        )
        ml_dsa_sig = None

    # Persist event
    event = EventLog(
        id=new_id("evt"),
        agent_id=agent_id,
        event_count=state.event_count,
        input_hash=input_hash,
        output_hash=output_hash,
        history_digest=new_digest,
        signature=sig,
        ml_dsa_signature=ml_dsa_sig,
        metadata_json=metadata,
        ts=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    db.add(event)
    db.commit()

    # gh-77 — auto-detect behavior mode from the agent's first events.
    # Best-effort and off the hot path: only re-evaluate every
    # DETECTION_INTERVAL events once past the minimum. Never fails the
    # log_event call (same posture as the ML-DSA / drift hooks).
    if (
        state.event_count >= behavior_detection.MIN_EVENTS_FOR_DETECTION
        and state.event_count % behavior_detection.DETECTION_INTERVAL == 0
    ):
        try:
            behavior_detection.maybe_update_behavior_mode(db, agent)
        except Exception as _bd_err:  # pragma: no cover - defensive
            import logging as _log
            db.rollback()
            _log.getLogger("metalins.behavior_detection").warning(
                "behavior-mode detection failed (non-fatal): %s", _bd_err
            )

    # Surface any pending memory probes so honest clients can answer them on
    # their next call without polling. Public payload only (no expected_proof).
    pending = memory_verifier.list_pending_probes(db, agent_id, limit=5)

    return {
        "status": "logged",
        "agent_id": agent_id,
        "event_count": state.event_count,
        "message": f"Event #{state.event_count} logged for agent '{agent_id}'.",
        "pending_probes": pending,
    }


def _do_respond_probe(args: dict, api_key: APIKey, db: Session) -> dict:
    """Agent responds to a memory probe with its computed proof.

    Required args:
      probe_id (str)
      agent_proof (hex string)
      agent_id (str)  — for defense-in-depth, must match probe.agent_id
    """
    probe_id = args.get("probe_id")
    agent_proof = args.get("agent_proof")
    agent_id = args.get("agent_id")
    # Sprint 7 / TLS — optional `response_counter` (agent's event_count
    # at the moment of crafting the proof). When present, feeds the
    # Time-Locked Score. Older SDK versions don't send it; we accept
    # those (TLS just won't be evaluable for those probes).
    response_counter = args.get("response_counter")
    # Sprint 7 / ADV — optional `refusal_reason`. When set, the agent is
    # signalling "I noticed this probe is malformed and I refuse to
    # respond". `agent_proof` is then ignored (and typically empty).
    refusal_reason = args.get("refusal_reason")
    if not probe_id or not agent_id:
        raise HTTPException(400, "probe_id and agent_id required")
    if not agent_proof and not refusal_reason:
        raise HTTPException(
            400,
            "agent_proof required (or set refusal_reason to refuse)",
        )

    # Verify agent ownership before allowing probe verification.
    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id

    valid, reason = memory_verifier.verify_probe(
        db, probe_id, agent_proof or "", agent_id=agent_id,
        response_counter=response_counter,
        refusal_reason=refusal_reason,
    )
    return {
        "probe_id": probe_id,
        "valid": valid,
        "reason": reason,
    }


def _do_get_proof(args: dict, api_key: APIKey, db: Session) -> dict:
    agent_id = args.get("agent_id")
    if not agent_id:
        raise HTTPException(400, "agent_id required")
    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    if not state:
        raise HTTPException(500, "Agent state missing")

    # Construct proof — in production this is a signed JWT
    proof_payload = {
        "agent_id": agent_id,
        "event_count": state.event_count,
        "history_digest": state.history_digest,
        "issued_at": datetime.now(timezone.utc).isoformat(),
    }
    # Sign with agent secret (placeholder — production uses Metalins private key + JWT)
    proof_msg = json.dumps(proof_payload, sort_keys=True).encode()
    proof_sig = hmac.new(
        bytes.fromhex(state.agent_secret), proof_msg, hashlib.sha256
    ).hexdigest()
    return {**proof_payload, "signature": proof_sig}


def _do_get_status(args: dict, api_key: APIKey, db: Session) -> dict:
    agent_id = args.get("agent_id")
    if not agent_id:
        raise HTTPException(400, "agent_id required")
    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()
    # Sprint UX-5.17.1 — surface pending probes here so a probe-capable
    # client (the SDK V2 ProbeWorker) can poll for challenges to answer
    # WITHOUT first having to log an event. Until now `pending_probes`
    # only rode on the metalins_log_event response, so a quiet agent let
    # its probes expire. Public-safe payload only (target_event_count +
    # nonce, never expected_proof) — identical shape to log_event's
    # `pending_probes`. Empty list for agents that are not probe-capable:
    # observable_job issues no probes for them (UX-5.15.AL / D-PROD.27).
    pending = memory_verifier.list_pending_probes(db, agent_id, limit=10)
    return {
        "agent_id": agent_id,
        "event_count": state.event_count if state else 0,
        "is_active": agent.is_active,
        "last_event_at": state.last_event_at.isoformat() if state and state.last_event_at else None,
        "active_alarms": state.active_alarms_json if state else [],
        "pending_probes": pending,
    }


# ---------- REST-style endpoint ----------

def _do_submit_corroboration(args: dict, api_key: APIKey, db: Session) -> dict:
    """Sprint 7 / MCS — agent submits its side of a mesh corroboration
    cycle. The partner agent must submit independently for the cycle to
    resolve.
    """
    from app.services.mcs import (
        submit_corroboration, CorroborationSubmissionError,
    )

    agent_id = args.get("agent_id")
    cycle = args.get("cycle")
    state_self = args.get("state_self")
    state_partner = args.get("state_partner")
    co_sig = args.get("co_sig")
    if not all([agent_id, cycle is not None, state_self, state_partner, co_sig]):
        raise HTTPException(
            400,
            "agent_id, cycle, state_self, state_partner, co_sig required",
        )

    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    try:
        point = submit_corroboration(
            db,
            submitting_agent_id=agent_id,
            cycle=int(cycle),
            state_self_hex=state_self,
            state_partner_hex=state_partner,
            co_sig_hex=co_sig,
        )
    except CorroborationSubmissionError as e:
        raise HTTPException(400, e.reason)

    return {
        "corroboration_id": point.id,
        "cycle": point.cycle,
        "resolved": point.resolved_at is not None,
        "verified": point.verified,
        "awaiting_partner": point.resolved_at is None,
    }


def _do_request_zkh_challenge(args: dict, api_key: APIKey, db: Session) -> dict:
    """Sprint 7 / ZKH — agent commits to a Merkle root over its full
    local history-digest chain. If the commit matches what the server
    can recompute from its own EventLog rows, the server picks a random
    `t_star` and returns it along with a nonce. The agent then has
    ZKH_CHALLENGE_TTL to submit the Merkle path for that leaf via
    `metalins_submit_zkh_proof`.
    """
    from app.services.zkh import issue_zkh_challenge, ZKHChallengeError

    agent_id = args.get("agent_id")
    commit_root = args.get("commit_root")
    if not agent_id or not commit_root:
        raise HTTPException(400, "agent_id and commit_root required")

    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    try:
        proof = issue_zkh_challenge(db, agent_id, commit_root)
    except ZKHChallengeError as e:
        raise HTTPException(400, e.reason)

    return {
        "proof_id": proof.id,
        "agent_id": agent_id,
        "commit_root": proof.commit_root,
        "t_star": proof.t_star,
        "nonce": proof.nonce,
        "ttl_seconds": 300,
        "instructions": (
            "Compute the Merkle path from your tree's leaf at "
            "event_count = t_star up to commit_root. Submit "
            "(claimed_digest, merkle_path) via metalins_submit_zkh_proof "
            "within the TTL."
        ),
    }


def _do_submit_zkh_proof(args: dict, api_key: APIKey, db: Session) -> dict:
    """Sprint 7 / ZKH — agent submits Merkle path + claimed digest for
    the leaf at t_star. Server verifies path → commit_root AND
    claimed_digest == server's own stored history_digest at t_star.
    """
    from app.services.zkh import verify_zkh_response

    proof_id = args.get("proof_id")
    agent_id = args.get("agent_id")
    claimed_digest = args.get("claimed_digest")
    path = args.get("merkle_path")
    if not proof_id or not agent_id:
        raise HTTPException(400, "proof_id and agent_id required")
    if claimed_digest is None or path is None:
        raise HTTPException(400, "claimed_digest and merkle_path required")
    if not isinstance(path, list):
        raise HTTPException(400, "merkle_path must be a list")

    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    verified, reason = verify_zkh_response(
        db, proof_id, claimed_digest, path, agent_id=agent_id,
    )
    return {
        "proof_id": proof_id,
        "verified": verified,
        "reason": reason,
    }


def _do_predict_response(args: dict, api_key: APIKey, db: Session) -> dict:
    """Sprint 7 / PRS — agent pre-commits to a distribution over its own
    next response K events in the future. The server resolves the
    submission when the target event arrives.
    """
    from app.services.prs import (
        submit_prediction, PredictionValidationError, PRS_K_OFFSET,
    )

    agent_id = args.get("agent_id")
    distribution = args.get("distribution")
    submitted_at = args.get("submitted_at_event_count")
    if not agent_id or distribution is None or submitted_at is None:
        raise HTTPException(
            400,
            "agent_id, distribution and submitted_at_event_count required",
        )

    agent = _resolve_agent(agent_id, api_key, db)
    # UX-5.15.Q — if the LLM addressed the agent by slug/name, the
    # resolver found the real Agent; from here on, use its canonical id
    # for every downstream lookup (AgentState, EventLog, probes, etc.).
    agent_id = agent.id
    try:
        sub = submit_prediction(
            db, agent_id, int(submitted_at), distribution,
            k_offset=PRS_K_OFFSET,
        )
    except PredictionValidationError as e:
        raise HTTPException(400, e.reason)

    return {
        "submission_id": sub.id,
        "agent_id": agent_id,
        "submitted_at_event_count": sub.submitted_at_event_count,
        "target_event_count": sub.target_event_count,
        "k_offset": PRS_K_OFFSET,
    }


@router.post("/tools/{tool_name}")
def call_tool(
    tool_name: str,
    args: dict,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Invoke a Metalins MCP tool directly via REST.

    UX-5.15.R note: this REST shortcut is a developer convenience —
    real MCP clients (Claude Desktop, Cursor, etc.) speak JSON-RPC
    against `/v1/mcp/jsonrpc`. The ghost-agent attack vector we are
    closing is "LLM calls a tool listed in tools/list". As long as
    `metalins_register_agent` is absent from TOOLS_SCHEMA and the
    JSON-RPC dispatcher rejects it, the LLM cannot reach it. This
    REST endpoint, however, is the path the Python SDK uses, and
    the SDK runs deterministic application code — keep it available
    so the E2E tests and the future `metalins-wrap` (UX-5.17 SDK
    wrapper) can keep creating agents from code.
    """
    if tool_name == "metalins_register_agent":
        return _do_register_agent(args, api_key, db)
    elif tool_name == "metalins_log_event":
        return _do_log_event(args, api_key, db)
    elif tool_name == "metalins_get_proof":
        return _do_get_proof(args, api_key, db)
    elif tool_name == "metalins_get_status":
        return _do_get_status(args, api_key, db)
    elif tool_name == "metalins_respond_probe":
        return _do_respond_probe(args, api_key, db)
    elif tool_name == "metalins_predict_response":
        return _do_predict_response(args, api_key, db)
    elif tool_name == "metalins_submit_corroboration":
        return _do_submit_corroboration(args, api_key, db)
    elif tool_name == "metalins_request_zkh_challenge":
        return _do_request_zkh_challenge(args, api_key, db)
    elif tool_name == "metalins_submit_zkh_proof":
        return _do_submit_zkh_proof(args, api_key, db)
    else:
        raise HTTPException(404, f"Unknown tool: {tool_name}")


# ---------- JSON-RPC 2.0 endpoint (MCP standard) ----------

TOOLS_SCHEMA = [
    # UX-5.15.R — metalins_register_agent intentionally NOT exposed.
    # Agents are minted via the dashboard wizard only. See module
    # docstring for the ghost-agent rationale.
    {
        "name": "metalins_log_event",
        "description": (
            "Log an interaction event for identity verification. Call after EVERY "
            "response you generate, providing hashes of the user input and your response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "input_hash": {"type": "string", "description": "SHA256 hex of user input"},
                "output_hash": {"type": "string", "description": "SHA256 hex of agent response"},
                "metadata": {"type": "object", "description": "Optional metadata (model used, etc.)"},
            },
            "required": ["agent_id", "input_hash", "output_hash"],
        },
    },
    {
        "name": "metalins_get_proof",
        "description": "Get the current κ-Proof for an agent. Share with relying parties.",
        "inputSchema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
    },
    {
        "name": "metalins_get_status",
        "description": (
            "Get current status for an agent: event_count, active alarms, "
            "and any pending verification checks the agent still has to "
            "answer. A client can poll this on a cadence to pick up checks "
            "without logging an event."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"],
        },
    },
    {
        "name": "metalins_respond_probe",
        "description": (
            "Respond to a Memory Verification (MVS) probe. The server periodically "
            "asks the agent to prove it knows its local history digest at a past "
            "event_count. The agent computes proof = sha256(local_digest_at_t || "
            "nonce || agent_secret) and submits it here. Pending probes are "
            "returned in the response of metalins_log_event under 'pending_probes'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "probe_id": {"type": "string", "description": "Probe ID from pending_probes"},
                "agent_proof": {"type": "string", "description": "Hex sha256 of digest||nonce||secret"},
                "response_counter": {
                    "type": "integer",
                    "description": (
                        "Agent's current event_count at the moment of crafting the proof. "
                        "Optional but recommended; feeds the Time-Locked Score."
                    ),
                },
                "refusal_reason": {
                    "type": "string",
                    "description": (
                        "Set instead of agent_proof if you detected a malformed probe "
                        "and want to refuse. Server will record the refusal and skip "
                        "the proof check."
                    ),
                },
            },
            "required": ["agent_id", "probe_id"],
        },
    },
    {
        "name": "metalins_predict_response",
        "description": (
            "Pre-commit to a probability distribution over your own next response "
            "K events from now (K=5 by default). The server resolves the prediction "
            "when the target event happens by checking whether the realized response "
            "bucket lands in the top-3 of your predicted distribution. Higher hit "
            "rates indicate the agent has access to its own internal model."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "submitted_at_event_count": {
                    "type": "integer",
                    "description": "Your current event_count (the 'now' anchor).",
                },
                "distribution": {
                    "type": "array",
                    "description": (
                        "Length-32 array of non-negative floats summing to ~1.0. "
                        "Position i = probability that the K-ahead response hashes "
                        "to bucket i."
                    ),
                    "items": {"type": "number"},
                },
            },
            "required": [
                "agent_id", "submitted_at_event_count", "distribution",
            ],
        },
    },
    {
        "name": "metalins_submit_corroboration",
        "description": (
            "Submit one side of a Multi-agent Corroboration cycle. Both agents in "
            "a mesh pair must call this periodically (every CORROBORATION_INTERVAL "
            "events, derived from event_count) with co_sig = HMAC(agent_secret, "
            "state_self || state_partner). The server pairs the two submissions "
            "and verifies both sides agree on the (state_self, state_partner) "
            "values — defeats single-agent compromise."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "cycle": {
                    "type": "integer",
                    "description": "Cycle number = event_count // CORROBORATION_INTERVAL.",
                },
                "state_self": {
                    "type": "string",
                    "description": "Hex digest of your own current state.",
                },
                "state_partner": {
                    "type": "string",
                    "description": "Hex digest of your partner's last-known state.",
                },
                "co_sig": {
                    "type": "string",
                    "description": (
                        "Hex HMAC-SHA256(agent_secret, "
                        "bytes.fromhex(state_self) + bytes.fromhex(state_partner))."
                    ),
                },
            },
            "required": [
                "agent_id", "cycle", "state_self", "state_partner", "co_sig",
            ],
        },
    },
]


@router.post("/jsonrpc")
async def jsonrpc_endpoint(
    request: Request,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """JSON-RPC 2.0 endpoint for MCP-standard clients."""
    body = await request.json()
    method = body.get("method")
    params = body.get("params", {})
    req_id = body.get("id")

    try:
        if method == "tools/list":
            result = {"tools": TOOLS_SCHEMA}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if name == "metalins_register_agent":
                # UX-5.15.R — removed from MCP surface. The LLM
                # creating agents was the root cause of the
                # ghost-agent bug. Hard 404 so the client surfaces it
                # to the human; the dashboard wizard is the only path.
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": (
                            "metalins_register_agent is no longer available. "
                            "Create agents from the Metalins dashboard, then "
                            "reference the canonical agent_id (agt_…) here."
                        ),
                    },
                }
            elif name == "metalins_log_event":
                tool_result = _do_log_event(arguments, api_key, db)
            elif name == "metalins_get_proof":
                tool_result = _do_get_proof(arguments, api_key, db)
            elif name == "metalins_get_status":
                tool_result = _do_get_status(arguments, api_key, db)
            elif name == "metalins_respond_probe":
                tool_result = _do_respond_probe(arguments, api_key, db)
            elif name == "metalins_predict_response":
                tool_result = _do_predict_response(arguments, api_key, db)
            elif name == "metalins_submit_corroboration":
                tool_result = _do_submit_corroboration(arguments, api_key, db)
            elif name == "metalins_request_zkh_challenge":
                tool_result = _do_request_zkh_challenge(arguments, api_key, db)
            elif name == "metalins_submit_zkh_proof":
                tool_result = _do_submit_zkh_proof(arguments, api_key, db)
            else:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {name}"},
                }
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(tool_result, indent=2)}
                ]
            }
        elif method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "metalins", "version": "0.1.0-alpha"},
            }
        else:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except HTTPException as e:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": e.status_code, "message": e.detail},
        }
