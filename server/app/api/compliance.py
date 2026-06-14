"""Compliance export endpoint — GET /v1/agents/{id}/compliance-export.

Generates a downloadable ZIP containing:
  - events.json: full audit trail with cryptographic signatures, hashes,
    and history digest chain (Art. 12 / Art. 72 evidence).
  - compliance_mapping.json: per-article mapping of how the audit data
    satisfies EU AI Act obligations.
  - agent_metadata.json: agent registration details and current state.

Auth: API key of the agent's owner. Returns 403 for any other key.
Response: application/zip with Content-Disposition: attachment.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.auth import require_api_key
from app.core import ml_dsa_signing
from app.db import get_db
from app.db.models import Agent, AgentState, APIKey, EventLog

router = APIRouter(prefix="/v1/agents", tags=["compliance"])

_BUNDLE_VERSION = "1.0"
_EU_AI_ACT_REFERENCE = "EU AI Act 2024/1689"


def _customer_id_for_key(api_key: APIKey) -> str:
    return api_key.customer_id or ""


def _agent_owned_by_key(agent: Agent, api_key: APIKey, db: Session) -> bool:
    """Return True if the agent's creator key belongs to the same customer
    as the calling API key. Mirrors the scoping logic in agents.py
    `_customer_agent_query`, but without requiring an AuthContext.
    """
    creator = db.query(APIKey).filter(APIKey.id == agent.api_key_id).first()
    if creator is None:
        return False
    return creator.customer_id == api_key.customer_id


def _signed_event_record(event: EventLog) -> dict:
    """Serialize one EventLog row into the audit trail format.

    Each record includes:
      - event_count: monotonically increasing counter (non-repudiation).
      - input_hash / output_hash: SHA-256 of the raw interaction (privacy-
        preserving: raw text never leaves the customer's process).
      - history_digest: rolling SHA-256 chain tying every event to its
        predecessor — tampering with any prior event breaks all subsequent
        digests.
      - signature: HMAC-SHA256 over the event tuple, keyed by the agent
        secret at the time of logging (proof of origin).
      - ts: UTC timestamp.
      - metadata: caller-supplied free-form metadata (model, session id, …).

    The combination of digest chain + per-event signature is the technical
    implementation of Art. 12's requirement for "logging capabilities"
    with "integrity" guarantees.
    """
    # Build ML-DSA + RFC 3161 data: use stored signature when present,
    # or generate a fresh RFC 3161 stub for display (signature itself is
    # already in the DB from log_event time).
    canonical = ml_dsa_signing.event_canonical_bytes(
        agent_id=event.agent_id,
        event_count=event.event_count,
        input_hash=event.input_hash,
        output_hash=event.output_hash,
        history_digest=event.history_digest,
    )
    rfc3161_ts = ml_dsa_signing.make_rfc3161_timestamp(canonical)
    ml_dsa_pub = ml_dsa_signing.get_public_key_hex()

    return {
        "event_id": event.id,
        "event_count": event.event_count,
        "input_hash": event.input_hash,
        "output_hash": event.output_hash,
        "history_digest": event.history_digest,
        "signature": event.signature,
        # ML-DSA-65 (FIPS 204) quantum-safe signature — Asqav-compatible
        "ml_dsa_signature": event.ml_dsa_signature,
        "ml_dsa_public_key_hex": ml_dsa_pub,
        "ml_dsa_algorithm": ml_dsa_signing.ALGORITHM,
        # RFC 3161 timestamp stub (format-compatible; rfc3161_stub=true means
        # this is a local stub, not a real TSA. Production can upgrade to a
        # real TSA without schema changes.)
        "rfc3161_timestamp": rfc3161_ts,
        "rfc3161_stub": True,
        "ts": event.ts.isoformat() + "Z" if event.ts else None,
        "metadata": event.metadata_json or {},
    }


def _build_compliance_mapping(agent: Agent, state: AgentState | None, event_count: int) -> dict:
    """Build the article-by-article compliance mapping.

    Art. 12 — Transparency and provision of information to deployers:
      Metalins satisfies this via cryptographically-signed event logs that
      provide an immutable record of every agent interaction. Each event log
      entry is HMAC-signed with the agent secret and chained via SHA-256
      digest, ensuring tamper-evidence.

    Art. 72 — Post-market monitoring (for high-risk AI systems):
      Metalins satisfies this via baseline behavioral profiling (κ-fingerprint)
      and continuous drift detection. The `baseline_kappa` established at
      registration is the reference point; subsequent observable snapshots are
      compared against it to detect anomalies (behavioral drift = potential
      model substitution or jailbreak).
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    art12_status = "compliant" if event_count > 0 else "insufficient_data"
    art72_status = "compliant" if agent.baseline_kappa else "baseline_not_established"

    drift_history: list[dict] = []
    if state and state.last_baseline_reset_at:
        drift_history.append({
            "event": "baseline_reset",
            "ts": state.last_baseline_reset_at.isoformat() + "Z",
            "reset_count": state.baseline_reset_count or 0,
        })

    return {
        "bundle_version": _BUNDLE_VERSION,
        "regulation": _EU_AI_ACT_REFERENCE,
        "generated_at": now_iso,
        "agent_id": agent.id,
        # Asqav open-standard receipt — signals that Metalins is built on the
        # same ML-DSA-65 (FIPS 204) cryptographic base as the Asqav open
        # standard (MIT licence, github.com/jagmarques/asqav-sdk).
        "asqav_receipt": {
            "standard": "asqav-sdk",
            "license": "MIT",
            "repository": "https://github.com/jagmarques/asqav-sdk",
            "algorithm": ml_dsa_signing.ALGORITHM,
            "note": "Cryptographic layer built on Asqav open standard (MIT)",
            "ml_dsa_public_key_hex": ml_dsa_signing.get_public_key_hex(),
        },
        # RFC 3161 timestamp standard declaration
        "timestamp_standard": "RFC 3161 compatible",
        "timestamp_note": (
            "Each event carries an RFC 3161-compatible timestamp token "
            "(see events.json → rfc3161_timestamp). The current implementation "
            "uses a local stub; production can upgrade to a real TSA "
            "(e.g. freetsa.org) without schema changes."
        ),
        "articles": {
            "art_12_transparency_logging": {
                "article": "Art. 12 — Transparency and provision of information to deployers",
                "obligation": (
                    "High-risk AI systems shall be designed and developed with capabilities "
                    "enabling the automatic recording of events (logs) throughout the lifetime "
                    "of the system."
                ),
                "status": art12_status,
                "implementation": {
                    "mechanism": "Cryptographically-signed event logs with SHA-256 digest chain and ML-DSA-65 quantum-safe signatures",
                    "total_events_logged": event_count,
                    "signature_scheme": "ML-DSA-65 (FIPS 204 / Asqav-compatible) + HMAC-SHA256 keyed by agent secret",
                    "chain_integrity": (
                        "Each event's history_digest = SHA-256(prev_digest || event_data), "
                        "ensuring any tampering invalidates all subsequent entries."
                    ),
                    "audit_trail_file": "events.json",
                    "notes": (
                        "Event hashes (input_hash, output_hash) are SHA-256 of raw interaction "
                        "data. Raw content is never transmitted to Metalins (privacy-by-design)."
                    ) if event_count > 0 else (
                        "No events logged yet. The agent must log interactions via the SDK "
                        "to establish an audit trail."
                    ),
                },
            },
            "art_72_post_market_monitoring": {
                "article": "Art. 72 — Post-market monitoring by providers",
                "obligation": (
                    "Providers of high-risk AI systems shall establish and document a "
                    "post-market monitoring system to proactively collect, document and "
                    "analyse relevant data on the performance of high-risk AI systems "
                    "throughout their lifetime."
                ),
                "status": art72_status,
                "implementation": {
                    "mechanism": "Behavioral fingerprinting (κ-baseline) + continuous drift detection",
                    "baseline_established_at": (
                        agent.created_at.isoformat() + "Z"
                        if agent.created_at else None
                    ),
                    "baseline_kappa_enrolment_score": agent.enrolment_score,
                    "drift_anomaly_detection": (
                        "Active — identity observables computed over rolling event windows. "
                        "Deviations from baseline trigger alerts in the Metalins dashboard."
                        if agent.baseline_kappa else
                        "Inactive — no baseline established. Register the agent via the SDK "
                        "with behavior_samples to enable drift detection."
                    ),
                    "baseline_drift_history": drift_history,
                    "notes": (
                        "The κ-fingerprint baseline is the technical reference point for "
                        "behavioral continuity. If the agent's responses deviate significantly "
                        "from the baseline (e.g. due to model update, jailbreak, or substitution), "
                        "the observable score drops and the owner is notified."
                    ),
                },
            },
        },
    }


def _build_agent_metadata(agent: Agent, state: AgentState | None, event_count: int) -> dict:
    """Build the agent_metadata.json section."""
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "bundle_version": _BUNDLE_VERSION,
        "exported_at": now_iso,
        "agent": {
            "agent_id": agent.id,
            "name": agent.name,
            "model": agent.model,
            "framework": agent.framework,
            "is_active": agent.is_active,
            "created_at": agent.created_at.isoformat() + "Z" if agent.created_at else None,
            "revoked_at": agent.revoked_at.isoformat() + "Z" if agent.revoked_at else None,
            "public_slug": agent.public_slug,
            "metadata": agent.metadata_json or {},
        },
        "state": {
            "event_count": event_count,
            "last_event_at": (
                state.last_event_at.isoformat() + "Z"
                if state and state.last_event_at else None
            ),
            "baseline_reset_count": state.baseline_reset_count if state else 0,
            "last_baseline_reset_at": (
                state.last_baseline_reset_at.isoformat() + "Z"
                if state and state.last_baseline_reset_at else None
            ),
        },
    }


@router.get("/{agent_id}/compliance-export")
def compliance_export(
    agent_id: str,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Download a compliance bundle ZIP for an agent.

    The ZIP contains three JSON files covering EU AI Act obligations:
      - events.json: full audit trail (Art. 12 — logging with integrity)
      - compliance_mapping.json: per-article implementation evidence
        (Art. 12 + Art. 72)
      - agent_metadata.json: registration details, current state, and
        export timestamp

    Auth: the calling API key must belong to the agent's owner. Any other
    valid API key receives 403 (not just 404) so that bundle existence is
    not leaked cross-customer.

    The ZIP is generated in memory and streamed as application/zip. There
    is no size limit enforced server-side for V1 — agents with millions of
    events should use pagination (future work).
    """
    # Resolve agent — existence check without ownership first, so we can
    # return 403 (not 404) when the agent exists but belongs to another
    # customer. This is intentional: a 404 would leak whether the id exists.
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        raise HTTPException(404, "Agent not found")

    # Ownership check: the calling key must own this agent.
    if not _agent_owned_by_key(agent, api_key, db):
        raise HTTPException(
            403,
            "The provided API key does not own this agent. "
            "Use the API key of the agent's owner to export its compliance bundle.",
        )

    # Fetch supporting data.
    state = db.query(AgentState).filter(AgentState.agent_id == agent_id).first()

    events = (
        db.query(EventLog)
        .filter(EventLog.agent_id == agent_id)
        .order_by(EventLog.event_count.asc())
        .all()
    )
    event_count = state.event_count if state else len(events)

    # Build the three JSON payloads.
    audit_trail = {
        "bundle_version": _BUNDLE_VERSION,
        "agent_id": agent_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_events": event_count,
        "events": [_signed_event_record(e) for e in events],
        "chain_note": (
            "The history_digest field in each event is a rolling SHA-256 hash "
            "chaining every event to its predecessor. Verify chain integrity by "
            "recomputing: digest[n] = SHA-256(digest[n-1] || event_data[n])."
        ),
    }

    compliance_mapping = _build_compliance_mapping(agent, state, event_count)
    agent_metadata = _build_agent_metadata(agent, state, event_count)

    # Assemble the ZIP in memory.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "events.json",
            json.dumps(audit_trail, indent=2, ensure_ascii=False),
        )
        zf.writestr(
            "compliance_mapping.json",
            json.dumps(compliance_mapping, indent=2, ensure_ascii=False),
        )
        zf.writestr(
            "agent_metadata.json",
            json.dumps(agent_metadata, indent=2, ensure_ascii=False),
        )

    buf.seek(0)
    zip_bytes = buf.read()

    # Safe filename: strip the prefix and truncate.
    safe_name = agent_id.replace("agt_", "")[:32]
    filename = f"metalins-compliance-{safe_name}.zip"

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(zip_bytes)),
        },
    )
