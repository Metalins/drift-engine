"""Verify + issue-token endpoints (the core of the product)."""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import (
    RequestChallengesRequest, RequestChallengesResponse, Challenge,
    VerifyRequest, VerifyResponse,
    IssueTokenRequest, IssueTokenResponse,
)
from app.core.auth import require_api_key
from app.core.ids import new_id
from app.core.signing import sign_kappa_proof
from app.db import get_db
from app.db.models import Agent, Verification, APIKey
from app.kappa import compare_to_baseline, generate_challenges
from app.services.session_store import sessions


router = APIRouter(prefix="/v1", tags=["verify"])


@router.post("/challenges/request", response_model=RequestChallengesResponse)
def request_challenges(
    req: RequestChallengesRequest,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Step 1 of verify flow: client requests fresh challenges."""
    agent = db.query(Agent).filter(
        Agent.id == req.agent_id,
        Agent.api_key_id == api_key.id,
        Agent.is_active.is_(True),
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found or revoked")

    challenges = generate_challenges(baseline=agent.baseline_kappa, n=req.steps)
    session_id = new_id("ses")
    sessions.create(session_id=session_id, agent_id=agent.id, challenges=challenges, steps=req.steps)

    return RequestChallengesResponse(
        agent_id=agent.id,
        challenges=[Challenge(**c) for c in challenges],
        session_id=session_id,
    )


@router.post("/verify", response_model=VerifyResponse)
def verify(
    req: VerifyRequest,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Step 2: client sends agent's responses to the challenges. Server verifies."""
    agent = db.query(Agent).filter(
        Agent.id == req.agent_id,
        Agent.api_key_id == api_key.id,
        Agent.is_active.is_(True),
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found or revoked")

    sess = sessions.consume(req.session_id)
    if not sess or sess["agent_id"] != agent.id:
        raise HTTPException(400, "Invalid or expired session_id")

    result = compare_to_baseline(
        baseline=agent.baseline_kappa,
        metadata=agent.metadata_json or {},
        responses=[r.model_dump() for r in req.responses],
        steps=sess["steps"],
    )

    proof_id = new_id("prf")
    token, expires_at = sign_kappa_proof(
        proof_id=proof_id,
        agent_id=agent.id,
        score=result["score"],
        verified=result["verified"],
        steps=result["steps"],
        scope=req.scope,
    )
    issued_at_aware = datetime.now(timezone.utc)

    db.add(Verification(
        id=proof_id,
        agent_id=agent.id,
        proof_jwt=token,
        score=result["score"],
        verified=result["verified"],
        steps=result["steps"],
        scope=req.scope,
        issued_at=issued_at_aware.replace(tzinfo=None),
        expires_at=expires_at.replace(tzinfo=None),
    ))
    db.commit()

    return VerifyResponse(
        verified=result["verified"],
        score=result["score"],
        proof_id=proof_id,
        kappa_proof=token,
        issued_at=issued_at_aware,   # aware, consistent con expires_at
        expires_at=expires_at,
        steps=result["steps"],
    )


@router.post("/issue-token", response_model=IssueTokenResponse)
def issue_token(
    req: IssueTokenRequest,
    api_key: APIKey = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """Verify + emit Bearer token in one call. Token IS the κ-Proof."""
    verify_req = VerifyRequest(
        agent_id=req.agent_id,
        session_id=req.session_id,
        responses=req.responses,
        scope=req.scope,
    )
    result = verify(verify_req, api_key=api_key, db=db)

    if not result.verified:
        raise HTTPException(401, f"Verification failed (score={result.score:.3f})")

    seconds_to_expiry = int((result.expires_at - result.issued_at).total_seconds())
    return IssueTokenResponse(
        verified=True,
        token=result.kappa_proof,
        proof_id=result.proof_id,
        expires_in=seconds_to_expiry,
        scope=req.scope,
    )
