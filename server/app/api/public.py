"""Public endpoints — no auth required.

Estos endpoints son la interface para RELYING PARTIES (servicios externos
que aceptan κ-Proofs). Son GRATIS, sin auth, rate-limited razonable.

Crítico para el efecto red. Ver: product/RELYING-PARTY-MODEL.md
"""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.api.schemas import VerifyProofRequest, VerifyProofResponse
from app.config import settings
from app.core.ids import new_id
from app.core.signing import get_jwks
from app.db import get_db
from app.db.models import (
    Agent,
    AgentAnchor,
    AgentObservable,
    AgentState,
    MemoryProbe,
    Revocation,
    Verification,
    VerificationAttempt,
    Watcher,
)
from cryptography.hazmat.primitives import serialization


router = APIRouter(tags=["public"])


# --------------------------------------------------------------------------- #
# Proof shortener — Sprint UX-5.11 R2 / R2.7 (2026-05-18)                     #
# --------------------------------------------------------------------------- #
#
# Embedding the full JWT in a verify URL (`?proof=<700-char JWT>`) made
# the link too long to share in Telegram/X bios. The operator-issued
# proof is already persisted server-side (in `verifications.proof_jwt`
# keyed by `proof_id ~15 chars`), so we can hand out a tiny URL like
# `/v/<slug>?p=<proof_id>` and have the verify page resolve the JWT on
# the server in one request. Security is identical: anyone with the
# proof_id can fetch the same JWT they would have had directly. TTL +
# revocation still apply via the regular /v1/verify-proof flow.


@router.get("/v1/public/proofs/{proof_id}")
def get_public_proof(proof_id: str, db: Session = Depends(get_db)):
    """Resolve a short proof_id into the full κ-Proof JWT.

    No auth — the JWT itself is the credential. The endpoint exists
    purely to shorten verification URLs that humans share in chat.
    A2A integrators who want offline verification can keep passing the
    JWT directly to /v1/verify-proof; they don't need this round trip.

    Returns 404 if the proof_id is unknown. Does NOT pre-check TTL or
    revocation — caller is expected to chain into /v1/verify-proof
    which is the single source of truth for proof validity.
    """
    row = (
        db.query(Verification)
        .filter(Verification.id == proof_id)
        .first()
    )
    if row is None or not row.proof_jwt:
        raise HTTPException(404, "Proof not found")
    return {
        "proof_id": row.id,
        "agent_id": row.agent_id,
        "kappa_proof": row.proof_jwt,
        "issued_at": (
            row.issued_at.isoformat() + "Z" if row.issued_at else None
        ),
        "expires_at": (
            row.expires_at.isoformat() + "Z" if row.expires_at else None
        ),
        "scope": row.scope,
    }


@router.get("/.well-known/jwks.json")
def jwks():
    """JWKS endpoint — public keys for relying parties to verify κ-Proofs."""
    return get_jwks()


def _log_attempt(
    db: Session,
    *,
    proof_id: str | None,
    agent_id: str | None,
    valid: bool,
    reason: str | None,
    scope: str | None,
) -> None:
    """Append a verification_attempts row. Sprint 6-A2A 6.2.

    Best-effort: if the insert fails (DB hiccup, schema mismatch on
    older deploys), we swallow the error rather than 500 the relying
    party. The public verify endpoint is more important than the
    audit trail.
    """
    try:
        db.add(VerificationAttempt(
            id=new_id("vat"),
            proof_id=proof_id,
            agent_id=agent_id,
            valid=valid,
            reason=reason,
            scope=scope,
        ))
        db.commit()
    except Exception:
        db.rollback()


@router.post("/v1/verify-proof", response_model=VerifyProofResponse)
def verify_proof(req: VerifyProofRequest, db: Session = Depends(get_db)):
    """Verify a κ-Proof's signature and check revocation. GRATIS.

    Cualquiera puede llamar este endpoint sin auth. Es el punto de entrada
    para que servicios externos (relying parties) acepten agents Metalins-verified.

    Sprint 6-A2A 6.2 — every call appends a row to verification_attempts
    so the issuer's dashboard can show "Recent verifications served" in
    near-real-time. We do NOT store the caller's IP (privacy decision).
    """
    # 1. Load public key (inline PEM env var has priority over disk file)
    if settings.public_key_pem:
        pub_key = serialization.load_pem_public_key(
            settings.public_key_pem.encode("utf-8")
        )
    else:
        with open(settings.public_key_path, "rb") as f:
            pub_key = serialization.load_pem_public_key(f.read())
    pub_pem = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # 2. Decode + verify signature
    try:
        claims = jwt.decode(
            req.kappa_proof,
            pub_pem,
            algorithms=["RS256"],
            audience="metalins-relying-party",
            issuer=settings.public_base_url,
        )
    except JWTError as e:
        _log_attempt(
            db, proof_id=None, agent_id=None, valid=False,
            reason="signature_invalid", scope=None,
        )
        return VerifyProofResponse(valid=False, reason=f"signature_invalid: {e}")

    proof_id = claims.get("jti")
    agent_id = claims.get("sub")
    scope_claim = claims.get("scope")

    # 3. Check revocation list
    revoked = db.query(Revocation).filter(Revocation.proof_id == proof_id).first()
    if revoked:
        _log_attempt(
            db, proof_id=proof_id, agent_id=agent_id, valid=False,
            reason="revoked", scope=scope_claim,
        )
        return VerifyProofResponse(
            valid=False,
            reason="revoked",
            proof_id=proof_id,
            agent_id=agent_id,
        )

    # 4. Check agent still active.
    # Sprint 6 (2026-05-16): the previous logic only flipped still_active to
    # false when the agent row existed AND had is_active=False (soft-delete
    # model). Sprint 5 changed revoke to HARD delete — the row is gone. So
    # an absent row must also mean "not active anymore". Treat both cases
    # the same: only return still_active=True if the agent exists AND is
    # currently is_active=True.
    #
    # Sprint UX-5.11 R2 / R2.4f (2026-05-18): also surface the agent's
    # public_slug and name so the verify page can confirm the URL slug
    # matches the proof's subject and render operator identity.
    still_active = True
    agent_slug = None
    agent_name = None
    if agent_id:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent is None or not agent.is_active:
            still_active = False
        if agent is not None:
            agent_slug = agent.public_slug
            agent_name = agent.name

    # 5. Log the attempt as a successful verification (valid signature +
    # not revoked). Note: still_active=False does NOT make valid=False —
    # the proof is cryptographically authentic, the agent just doesn't
    # exist anymore. Relying parties decide how to treat that.
    _log_attempt(
        db, proof_id=proof_id, agent_id=agent_id, valid=True,
        reason=None if still_active else "agent_inactive",
        scope=scope_claim,
    )

    return VerifyProofResponse(
        valid=True,
        agent_id=agent_id,
        public_slug=agent_slug,
        agent_name=agent_name,
        proof_id=proof_id,
        issued_at=datetime.fromtimestamp(claims.get("iat", 0), tz=timezone.utc),
        expires_at=datetime.fromtimestamp(claims.get("exp", 0), tz=timezone.utc),
        still_active=still_active,
        scope=scope_claim,
        score=claims.get("kappa_score"),
        steps=claims.get("kappa_steps"),
    )


# --------------------------------------------------------------------------- #
# Public verification state machine                                           #
# --------------------------------------------------------------------------- #
#
# Sprint UX-5.9-A introduced the state machine; Sprint UX-5.10-6
# extracted the derivation function to `services.verification_state`
# so the webhook delivery path can call it without an import cycle.
# Re-export the symbols for callers that imported them from here.

from app.services.verification_state import derive_trust  # noqa: E402


def _telegram_anchor_for_agent(agent: Agent, db: Session) -> dict | None:
    """Return the Telegram auto-anchor for an agent, if any. Sprint UX-5.9-F.

    A watcher binding proves the customer owns the bot's token at the
    moment they pasted it. We surface the bot's display_name (typically
    `@username`) as a public anchor on the verify card so a stranger can
    cross-check the Telegram side independently:

      "This agent is operated by @<botusername> on Telegram (auto-verified
       via watcher)."

    Returns None for agents without an active Telegram watcher.
    """
    watcher = (
        db.query(Watcher)
        .filter(
            Watcher.agent_id == agent.id,
            Watcher.deleted_at.is_(None),
            Watcher.platform == "telegram",
        )
        .first()
    )
    if watcher is None or not watcher.display_name:
        return None
    return {
        "type": "telegram",
        "value": watcher.display_name,
        "verified_at": (
            watcher.created_at.isoformat() + "Z"
            if watcher.created_at
            else None
        ),
        "method": "watcher",
    }


def _surface_for_public(agent: Agent, db: Session) -> str:
    """Sprint UX-5.11 R2 / R2.6 (2026-05-18) — derive integration_surface
    for the public payload. Same logic as agents._surface_for (D-PROD.18)
    but loads its own watcher + event count for a single agent (no
    batch pre-load). Output: "watcher" | "mcp" | "none".

    The verify page uses this to tailor the "ask for a verification
    proof" CTA — MCP/HTTP agents get the specific "the agent itself
    can emit a proof" copy; watcher-only agents get the generic
    "ask the operator" copy.
    """
    from app.db.models import Watcher, EventLog
    from sqlalchemy import func as _func

    w = (
        db.query(Watcher)
        .filter(Watcher.agent_id == agent.id, Watcher.deleted_at.is_(None))
        .first()
    )
    if w is not None and w.state != "paused":
        return "watcher"
    total = (
        db.query(_func.count(EventLog.id))
        .filter(EventLog.agent_id == agent.id)
        .scalar()
    ) or 0
    watcher_events = w.events_logged if w else 0
    has_mcp = (
        total > watcher_events
        and getattr(agent, "mcp_disabled_at", None) is None
    )
    return "mcp" if has_mcp else "none"


def _public_agent_payload(agent: Agent, db: Session) -> dict:
    """Shape used by both the by-id and by-slug public lookups.

    Sprint UX-5.5f (#629) + Sprint UX-5.7a (#634) + Sprint UX-5.9-A (#650).

    Backward-compat: `is_active`, `verified_since`, `last_active`,
    `revoked_at` keep their original semantics so older clients still
    work. New fields (`verification_state`, `event_count`, etc.) are
    additive — clients that don't read them get the same view they
    used to.
    """
    state = (
        db.query(AgentState).filter(AgentState.agent_id == agent.id).first()
    )
    latest_obs = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent.id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    # gh-83 — use the actual latest probe issued_at for last_probe_at
    # rather than latest_obs.ts (the observable computation time, which
    # can be stale). See agents.py for the same fix applied there.
    _latest_probe = (
        db.query(MemoryProbe)
        .filter(MemoryProbe.agent_id == agent.id)
        .order_by(MemoryProbe.issued_at.desc())
        .first()
    )
    _latest_probe_at = _latest_probe.issued_at if _latest_probe is not None else None
    last_active = state.last_event_at if state else None
    event_count = state.event_count if state else 0
    # Sprint UX-5.12 — two-layer trust replaces the old single
    # verification_state field. Frontend reads `trust.cryptographic.state`
    # and `trust.behavioral.state` independently.
    trust = derive_trust(agent, state, latest_obs, latest_probe_at=_latest_probe_at)

    anchors: list[dict] = []
    telegram_anchor = _telegram_anchor_for_agent(agent, db)
    if telegram_anchor is not None:
        anchors.append(telegram_anchor)

    # Sprint UX-5.9-G — verified rows from `agent_anchors`. Only rows
    # with `verified_at IS NOT NULL` surface publicly; pending rows
    # remain invisible to third parties.
    verified_rows = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.agent_id == agent.id,
            AgentAnchor.verified_at.isnot(None),
        )
        .all()
    )
    for row in verified_rows:
        anchors.append(
            {
                "type": row.type,
                "value": row.value or "",
                "verified_at": (
                    row.verified_at.isoformat() + "Z"
                    if row.verified_at
                    else None
                ),
                "method": row.method,
            }
        )

    # Sprint UX-5.11 R2 / bug-visitor-1: derive a single "primary
    # anchor" that the verify page can surface as the seller / operator
    # identity. Without this, third-party visitors only see the agent
    # slug and have no way to connect a marketplace listing claim
    # ("operated by Sofía Research Co.") to the verify page. With it,
    # the page can render "Operated by @sofia-research on Telegram"
    # and the visitor cross-checks on Telegram instead of trusting
    # Metalins. Priority order: telegram > github > dns. We pick the
    # first verified anchor of the highest-priority type.
    primary_anchor = None
    for preferred_type in ("telegram", "github", "dns"):
        for a in anchors:
            if a.get("type") == preferred_type and a.get("value"):
                primary_anchor = a
                break
        if primary_anchor:
            break

    return {
        "agent_id": agent.id,
        "public_slug": agent.public_slug,
        "name": agent.name,
        "is_active": bool(agent.is_active),
        # `verified_since` historically encoded the registration date.
        # We keep the name for compat but the verify page should now
        # prefer `verification_state` + `event_count` to decide what to
        # render. The date still carries meaning ("registered with
        # Metalins since <date>") and is shown only on the verified card.
        "verified_since": (
            agent.created_at.isoformat() + "Z" if agent.created_at else None
        ),
        "last_active": (
            last_active.isoformat() + "Z" if last_active else None
        ),
        "revoked_at": (
            agent.revoked_at.isoformat() + "Z" if agent.revoked_at else None
        ),
        # Sprint UX-5.12 — two-layer trust block (replaces verification_state
        # + baselining_threshold). See TWO-LAYER-TRUST-DESIGN.md §4 for the
        # exact shape and intended interpretation per layer.
        "trust": trust,
        "event_count": event_count,
        # Sprint UX-5.9-F/G — external identity anchors. Empty list when
        # the agent has no anchor. Each entry: {type, value, verified_at,
        # method}. The frontend renders one line per anchor.
        "external_anchors": anchors,
        # Sprint UX-5.11 R2 — primary anchor for seller-identity headline.
        # Null when no verified anchor exists; in that case the verify
        # page falls back to the agent name only.
        "primary_anchor": primary_anchor,
        # Sprint UX-5.11 R2 / R2.6 — integration surface tells the
        # verify page whether this agent is reachable via MCP/HTTP (in
        # which case the agent itself can emit proofs on demand) or is
        # a watcher-only entity (manual proof generation from the
        # dashboard). The CTA copy changes accordingly.
        "integration_surface": _surface_for_public(agent, db),
    }


@router.get("/v1/public/agents/{agent_id}")
def public_agent_info(agent_id: str, db: Session = Depends(get_db)):
    """Public-by-design lookup for the outward verification page.

    Sprint UX-5.5f (#629). Powers the `/verify/<agent_id>` page that
    Carlos pastes in his bot's bio and Sofía embeds in a marketplace
    listing. Returns ONLY the fields a stranger needs to see to make a
    trust decision:

      • name          — so the visitor can compare with the bot's name
                        in Telegram/Discord/the listing.
      • public_slug   — preferred handle for the URL when present.
      • is_active     — false means the agent was revoked. Visitor sees
                        a "no longer verified" page.
      • verified_since — when the customer first registered this agent
                         on Metalins. Builds trust ("verified since
                         April 2026" is stronger than just "verified").
      • last_active   — last time the agent was observed in our logs.
                        Helps the visitor see freshness.
      • revoked_at    — null when active; ISO timestamp when revoked.

    NO event content, NO customer email, NO score numbers. D-PROD.18:
    the public page is a verdict, not a dashboard. The visitor never
    sees an internal observable name.

    Sprint UX-5.11 / bug-carlos-2 (2026-05-17): the lookup also falls
    back to `public_slug` so `/verify/<slug>` resolves even though the
    "official" slug route is `/v/<slug>`. Carlos's exact friction was
    typing the agent name into `/verify/...` and getting "Not verified"
    when the underlying agent was perfectly fine — he was just on the
    wrong route. Falling back keeps both routes useful and reduces
    creator-side friction with zero ambiguity (slug + agent_id share no
    valid character set: agt_<base64-ish> vs [a-z0-9-]+).
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if agent is None:
        # Slug fallback. We re-use `slugify` so an upper-case URL still
        # resolves the same way the dedicated /by-slug route does.
        from app.core.slug import slugify

        normalized = slugify(agent_id)
        if normalized:
            agent = (
                db.query(Agent).filter(Agent.public_slug == normalized).first()
            )
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return _public_agent_payload(agent, db)


@router.get("/v1/public/agents/by-slug/{slug}")
def public_agent_by_slug(slug: str, db: Session = Depends(get_db)):
    """Same as `/v1/public/agents/{id}` but keyed by `public_slug`.

    Sprint UX-5.7a (#634). The verify URL Carlos shares is
    `/v/<slug>` (e.g. `/v/senales-crypto-carlos`); the frontend hits
    this endpoint, gets back the same minimal payload, and renders
    the verify card. Slug is enforced lowercase + [a-z0-9-]+ at the
    application layer; we still do a normalization pass here so a
    visitor who types upper-case or weird chars in the URL still
    resolves.
    """
    from app.core.slug import slugify

    normalized = slugify(slug)
    if not normalized:
        raise HTTPException(404, "Agent not found")
    agent = (
        db.query(Agent).filter(Agent.public_slug == normalized).first()
    )
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return _public_agent_payload(agent, db)


@router.get("/v1/revocations")
def list_revocations(since: str | None = None, db: Session = Depends(get_db)):
    """Public revocation list (CRL).

    Allows relying parties to cache revoked κ-Proofs locally.
    """
    q = db.query(Revocation)
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.filter(Revocation.revoked_at >= since_dt.replace(tzinfo=None))
        except ValueError:
            raise HTTPException(400, "Invalid 'since' timestamp (use ISO 8601)")

    revocations = q.order_by(Revocation.revoked_at.desc()).limit(1000).all()
    return {
        "revocations": [
            {
                "proof_id": r.proof_id,
                "agent_id": r.agent_id,
                "revoked_at": r.revoked_at.isoformat() + "Z",
                "reason": r.reason,
            }
            for r in revocations
        ]
    }


@router.get("/health")
def health():
    """Health check for monitoring."""
    return {"status": "ok", "service": "metalins-server"}
