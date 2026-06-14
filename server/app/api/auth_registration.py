"""Public-registration gate (gh-95, research-lab pivot 2026-06-14).

After the pivot, `api.metalins.ai` is José's **private** instance — there
are no external users. Drift Engine is open source; anyone who wants their
own instance self-hosts it (see the docker-compose stack). So the public
registration surface is closed.

The actual account-provisioning vector is Supabase magic-link
(`signInWithOtp` with auto-signup). The dashboard now passes
`shouldCreateUser: false`, so a brand-new email never auto-creates an
account. This module adds the matching server-side gate + policy probe:

  POST /v1/auth/signup   (alias: POST /auth/signup)
        The explicit "create me an account" endpoint. Returns 403 while
        `METALINS_REGISTRATION_ENABLED` is false (the default / prod state),
        regardless of caller. There is no admin self-signup path — the admin
        account already exists; this endpoint only ever *creates new* users.

  GET  /v1/auth/registration
        Public policy probe — `{"enabled": <bool>}`. The dashboard reads it
        to decide whether to show the self-hosting notice instead of an
        onboarding flow.

Nothing here touches existing-account login (magic-link/password for the
admin) or the API-key surface — only NEW-account creation is gated.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings

router = APIRouter(tags=["auth"])

# Self-host pointer surfaced in the 403 so a curious caller learns the
# project is open source rather than hitting an opaque wall.
_SELF_HOST_HINT = (
    "Public registration is disabled — api.metalins.ai is a private instance. "
    "Drift Engine is open source: self-host your own instance. "
    "See https://github.com/Metalins"
)


class SignupBody(BaseModel):
    # Accepted for shape compatibility with a normal signup call; the body is
    # never used while registration is disabled (we 403 before reading it).
    email: str | None = None


def _signup() -> dict:
    """Shared handler for both the /v1/auth/signup and /auth/signup paths.

    Reads `settings.registration_enabled` at call time so a test (or a
    deploy that flips the env var) takes effect without re-importing.
    """
    if not settings.registration_enabled:
        raise HTTPException(status_code=403, detail=_SELF_HOST_HINT)
    # Registration is intentionally Supabase-mediated (magic-link). If a deploy
    # ever re-opens signups, that flow — not this endpoint — provisions the
    # account; here we just acknowledge the policy is open.
    return {"ok": True, "registration": "open", "flow": "magic-link"}


@router.post("/v1/auth/signup")
@router.post("/auth/signup")
def signup(_body: SignupBody | None = None) -> dict:
    return _signup()


@router.get("/v1/auth/registration")
def registration_status() -> dict:
    """Whether public registration is currently open. Public, no auth."""
    return {"enabled": settings.registration_enabled}
