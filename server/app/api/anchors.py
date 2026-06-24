"""Per-agent external identity anchors.

Sprint UX-5.9-G (#656). Endpoints to create, verify, list, and remove
anchors that link a Metalins agent to an external identity.

V1 supports two anchor types, each via a challenge-response method:

* `type = "github"` (Sprint UX-5.9-G) — the customer pastes the
  challenge token into any PUBLIC gist; verifier fetches the gist
  through GitHub's REST API and pulls the owner login as the anchor
  `value`.
* `type = "telegram"` (Sprint UX-5.11 R2 / bug-r1-carlos-1, 2026-05-18)
  — first-class flow that does NOT require connecting a watcher. The
  customer pastes the challenge token into the public bio/description
  of any Telegram bot, channel, or user account they control. We then
  fetch the public `t.me/<username>` page and look for the token in the
  rendered HTML (og:description or page body). On success we store
  `value = @<username>`.

Both flows are two-step:

  1. POST /v1/agents/{id}/anchors/<type>/start
       → server creates a pending row, returns a challenge_token + the
         human-readable instructions.
  2. POST /v1/agents/{id}/anchors/<type>/verify {anchor_id, ...}
       → server fetches the external evidence, validates the token is
         present, and on success records value + verified_at = now.

Verified anchors appear in the public verify card via
`/v1/public/agents/{...}` (`external_anchors[]`), and the
priority-derived `primary_anchor` field promotes one to the hero of
the verify page (Round 2 / R2.1).

Removal: DELETE /v1/agents/{id}/anchors/{anchor_id} — the row goes away
and the public card drops the anchor immediately.

Re-checking is out of scope for V1. A weekly background job that
re-fetches each gist/t.me page and clears `verified_at` if the proof
disappeared is on the V1.5 backlog.
"""
from __future__ import annotations

import re
import secrets
import urllib.request
import urllib.error
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, require_auth
from app.core.ids import new_id
from app.db import get_db
from app.db.models import Agent, AgentAnchor, APIKey


router = APIRouter(prefix="/v1/agents", tags=["anchors"])


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _resolve_customer_agent(
    db: Session, agent_id: str, auth: AuthContext
) -> Agent:
    """Return the agent if it belongs to the calling customer, else 404.

    Mirrors the visibility rules in agents.py — we look up the agent
    only via api keys that share the customer_id, so an attacker can't
    point /anchors/* at someone else's agent_id.
    """
    customer_key_ids = [
        row[0]
        for row in db.query(APIKey.id)
        .filter(APIKey.customer_id == auth.customer_id)
        .all()
    ]
    agent = (
        db.query(Agent)
        .filter(Agent.id == agent_id, Agent.api_key_id.in_(customer_key_ids))
        .first()
    )
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return agent


_GIST_URL_RE = re.compile(
    r"^https?://gist\.github\.com/(?:[A-Za-z0-9_-]+/)?(?P<id>[A-Fa-f0-9]+)"
)
"""Accept any gist URL shape:
   https://gist.github.com/<id>
   https://gist.github.com/<user>/<id>
"""


def _extract_gist_id(url: str) -> Optional[str]:
    m = _GIST_URL_RE.match(url.strip())
    return m.group("id") if m else None


# --------------------------------------------------------------------------- #
# Telegram helpers — Sprint UX-5.11 R2 / bug-r1-carlos-1                      #
# --------------------------------------------------------------------------- #


_TELEGRAM_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
"""Telegram username rules per Telegram's UI: 5-32 chars, starts with
letter, only alphanumeric + underscore."""


def _normalize_telegram_username(raw: str) -> Optional[str]:
    """Accept @user, user, https://t.me/user, t.me/user; return clean handle.

    Returns None if the input doesn't look like a valid Telegram username
    after stripping decoration. The returned value has no leading @.
    """
    s = raw.strip()
    if not s:
        return None
    # Strip URL prefix variants.
    for prefix in (
        "https://t.me/",
        "http://t.me/",
        "https://telegram.me/",
        "http://telegram.me/",
        "t.me/",
        "telegram.me/",
    ):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.lstrip("@").split("?", 1)[0].split("/", 1)[0].strip()
    if not _TELEGRAM_USERNAME_RE.match(s):
        return None
    return s


def _fetch_telegram_profile_html(username: str) -> str:
    """Fetch the public t.me profile page HTML.

    No auth — Telegram's t.me previews are publicly served. Errors are
    rethrown as HTTPException so callers don't unpack urllib's exception
    tree. We accept a 10s timeout in line with the gist fetcher.
    """
    url = f"https://t.me/{username}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Metalins-Anchor-Verifier/1.0",
            # t.me serves slightly richer SSR when Accept-Language is set.
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HTTPException(
                404,
                f"Telegram profile @{username} not found or not public.",
            ) from e
        raise HTTPException(
            502, f"Telegram returned {e.code} fetching the profile."
        ) from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"Could not reach Telegram: {e}") from e
    try:
        return body.decode("utf-8", errors="replace")
    except Exception as e:  # pragma: no cover — decode never raises with errors="replace"
        raise HTTPException(502, f"Could not decode Telegram response: {e}") from e


_OG_DESC_RE = re.compile(
    r'<meta\s+property=["\']og:description["\']\s+content=["\'](?P<c>[^"\']*)["\']',
    re.IGNORECASE,
)
_TGME_DESC_RE = re.compile(
    r'<div\s+class=["\']tgme_page_description[^"\']*["\'][^>]*>(?P<c>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _extract_telegram_descriptions(html: str) -> list[str]:
    """Return candidate text blobs from a t.me HTML page where a bio
    would appear. We check og:description (always present on t.me pages
    that resolve to a real account) and the rendered description div.
    """
    out: list[str] = []
    m = _OG_DESC_RE.search(html)
    if m:
        out.append(m.group("c"))
    m = _TGME_DESC_RE.search(html)
    if m:
        out.append(m.group("c"))
    return out


_TGME_GENERIC_OG_DESCRIPTIONS = (
    # t.me serves a generic page (with this og:description) when the
    # username has no public preview — e.g. a private account or a
    # never-claimed handle. We don't try to verify those.
    "If you have Telegram, you can contact",
)


def _telegram_profile_looks_real(html: str) -> bool:
    descriptions = _extract_telegram_descriptions(html)
    if not descriptions:
        return False
    # If the ONLY thing we can find is the generic placeholder, treat as
    # not-resolvable. (Some legitimate bots may include phrases similar
    # to the placeholder in their bio, so we only fail when ALL
    # descriptions are the placeholder.)
    for d in descriptions:
        if not any(g in d for g in _TGME_GENERIC_OG_DESCRIPTIONS):
            return True
    return False


def _fetch_gist(gist_id: str) -> dict:
    """Fetch a public gist via GitHub's public REST API.

    No auth header — keeps us safely under the 60 req/hr unauthenticated
    rate limit; verification volume in V1 is well under that. Throws
    HTTPException on errors so callers don't have to unpack urllib's
    exception hierarchy.
    """
    api_url = f"https://api.github.com/gists/{gist_id}"
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "Metalins-Anchor-Verifier/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise HTTPException(404, "Gist not found or not public.") from e
        if e.code == 403:
            raise HTTPException(
                429,
                "GitHub rate-limited the verifier. Try again in a few minutes.",
            ) from e
        raise HTTPException(
            502, f"GitHub returned {e.code} fetching the gist."
        ) from e
    except urllib.error.URLError as e:
        raise HTTPException(502, f"Could not reach GitHub: {e}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"GitHub gist response was not JSON: {e}") from e


# --------------------------------------------------------------------------- #
# Schemas                                                                     #
# --------------------------------------------------------------------------- #


class AnchorOut(BaseModel):
    id: str
    type: str
    method: str
    value: Optional[str] = None
    verified_at: Optional[str] = None
    created_at: Optional[str] = None
    last_check_at: Optional[str] = None


def _to_out(a: AgentAnchor) -> AnchorOut:
    return AnchorOut(
        id=a.id,
        type=a.type,
        method=a.method,
        value=a.value,
        verified_at=a.verified_at.isoformat() + "Z" if a.verified_at else None,
        created_at=a.created_at.isoformat() + "Z" if a.created_at else None,
        last_check_at=(
            a.last_check_at.isoformat() + "Z" if a.last_check_at else None
        ),
    )


class StartGithubAnchorResponse(BaseModel):
    anchor_id: str
    challenge_token: str = Field(
        ...,
        description="Paste this exact token into any public gist.",
    )
    instructions: str


class VerifyGithubAnchorRequest(BaseModel):
    anchor_id: str
    gist_url: str = Field(
        ..., description="Public gist URL containing the challenge_token."
    )


class StartTelegramAnchorResponse(BaseModel):
    anchor_id: str
    challenge_token: str = Field(
        ...,
        description=(
            "Paste this exact token into the public bio/description of "
            "the Telegram bot, channel, or account you want to anchor."
        ),
    )
    instructions: str


class VerifyTelegramAnchorRequest(BaseModel):
    anchor_id: str
    telegram_username: str = Field(
        ...,
        description=(
            "Telegram @username (with or without leading @, or t.me URL). "
            "Bot usernames typically end in 'bot'."
        ),
    )


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/{agent_id}/anchors")
def list_anchors(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """List all anchors (verified + pending) for one agent."""
    _resolve_customer_agent(db, agent_id, auth)
    rows = (
        db.query(AgentAnchor)
        .filter(AgentAnchor.agent_id == agent_id)
        .order_by(AgentAnchor.created_at.desc())
        .all()
    )
    return {"anchors": [_to_out(a).model_dump() for a in rows]}


@router.post(
    "/{agent_id}/anchors/github/start",
    response_model=StartGithubAnchorResponse,
)
def start_github_anchor(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Begin a GitHub gist anchor flow. Returns a challenge token.

    Idempotent: if a pending github anchor already exists (verified_at
    IS NULL), we reuse it instead of minting a new token. Avoids
    polluting the row count when the customer clicks "start" twice.
    """
    _resolve_customer_agent(db, agent_id, auth)

    existing = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.agent_id == agent_id,
            AgentAnchor.type == "github",
            AgentAnchor.verified_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        anchor = existing
    else:
        anchor = AgentAnchor(
            id=new_id("anc"),
            agent_id=agent_id,
            type="github",
            method="gist",
            value=None,
            challenge_token=f"metalins-verify-{secrets.token_urlsafe(16)}",
            metadata_json={},
            verified_at=None,
            last_check_at=None,
        )
        db.add(anchor)
        db.commit()
        db.refresh(anchor)

    instructions = (
        "Create a PUBLIC gist on github.com with any filename and "
        "include this exact token in the contents:\n\n"
        f"    {anchor.challenge_token}\n\n"
        "Then paste the gist URL into the verify step to link the agent "
        "to your GitHub identity."
    )
    return StartGithubAnchorResponse(
        anchor_id=anchor.id,
        challenge_token=anchor.challenge_token,
        instructions=instructions,
    )


@router.post(
    "/{agent_id}/anchors/github/verify",
    response_model=AnchorOut,
)
def verify_github_anchor(
    agent_id: str,
    body: VerifyGithubAnchorRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Verify a pending GitHub anchor by fetching its gist."""
    _resolve_customer_agent(db, agent_id, auth)

    anchor = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.id == body.anchor_id,
            AgentAnchor.agent_id == agent_id,
        )
        .first()
    )
    if anchor is None:
        raise HTTPException(404, "Anchor not found")
    if anchor.verified_at is not None:
        # Already verified — return current state. Re-verification not
        # supported yet (re-running the flow is fine — start_anchor
        # would mint a fresh challenge token if needed).
        return _to_out(anchor)

    gist_id = _extract_gist_id(body.gist_url)
    if not gist_id:
        raise HTTPException(
            400,
            "URL doesn't look like a gist (expected gist.github.com/<id>).",
        )

    gist = _fetch_gist(gist_id)
    owner_login = (gist.get("owner") or {}).get("login")
    if not owner_login:
        raise HTTPException(
            400, "Could not read the gist's owner. Is it a public gist?"
        )

    files = gist.get("files") or {}
    token = anchor.challenge_token
    found = False
    for f in files.values():
        if token in (f.get("content") or ""):
            found = True
            break
    if not found:
        raise HTTPException(
            400,
            "The challenge token wasn't found in any file of that gist. "
            "Paste it exactly as shown and try again.",
        )

    now = datetime.utcnow()
    anchor.value = owner_login
    anchor.method = "gist"
    anchor.verified_at = now
    anchor.last_check_at = now
    anchor.metadata_json = {"gist_id": gist_id, "gist_url": body.gist_url}
    db.commit()
    db.refresh(anchor)
    return _to_out(anchor)


# --------------------------------------------------------------------------- #
# Telegram endpoints — Sprint UX-5.11 R2 / bug-r1-carlos-1                    #
# --------------------------------------------------------------------------- #


@router.post(
    "/{agent_id}/anchors/telegram/start",
    response_model=StartTelegramAnchorResponse,
)
def start_telegram_anchor(
    agent_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Begin a Telegram-bio anchor flow. Returns a short challenge token.

    Telegram bios are limited (~70 chars for `short_description`, 120
    for `description`), so we mint a shorter token than the GitHub flow:
    `metalins:<11-char>` ≈ 20 chars total.

    Idempotent: a pending telegram anchor (verified_at IS NULL) is
    reused on a second click — same token, same anchor_id.
    """
    _resolve_customer_agent(db, agent_id, auth)

    existing = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.agent_id == agent_id,
            AgentAnchor.type == "telegram",
            AgentAnchor.method == "bio",
            AgentAnchor.verified_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        anchor = existing
    else:
        anchor = AgentAnchor(
            id=new_id("anc"),
            agent_id=agent_id,
            type="telegram",
            method="bio",
            value=None,
            challenge_token=f"metalins:{secrets.token_urlsafe(8)}",
            metadata_json={},
            verified_at=None,
            last_check_at=None,
        )
        db.add(anchor)
        db.commit()
        db.refresh(anchor)

    instructions = (
        "Add this exact token anywhere in the public bio/description of "
        "the Telegram bot, channel, or user account you want to anchor:\n\n"
        f"    {anchor.challenge_token}\n\n"
        "For bots, use @BotFather → /setdescription (or /setabouttext) and "
        "paste the token. For channels and users, edit your profile bio. "
        "Then enter your @username here to verify.\n\n"
        "You can remove the token from your bio after verification — we "
        "only need to see it once."
    )
    return StartTelegramAnchorResponse(
        anchor_id=anchor.id,
        challenge_token=anchor.challenge_token,
        instructions=instructions,
    )


@router.post(
    "/{agent_id}/anchors/telegram/verify",
    response_model=AnchorOut,
)
def verify_telegram_anchor(
    agent_id: str,
    body: VerifyTelegramAnchorRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Verify a pending Telegram anchor by fetching the t.me profile.

    Reads the public preview page at `https://t.me/<username>`, extracts
    the og:description meta tag and the rendered description div, and
    requires the challenge token to appear in at least one of them.
    """
    _resolve_customer_agent(db, agent_id, auth)

    anchor = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.id == body.anchor_id,
            AgentAnchor.agent_id == agent_id,
        )
        .first()
    )
    if anchor is None:
        raise HTTPException(404, "Anchor not found")
    if anchor.type != "telegram":
        raise HTTPException(400, "Anchor is not a Telegram anchor.")
    if anchor.verified_at is not None:
        return _to_out(anchor)

    username = _normalize_telegram_username(body.telegram_username)
    if username is None:
        raise HTTPException(
            400,
            "That doesn't look like a Telegram @username. Use 5-32 "
            "characters (letters, numbers, underscore) — for example, "
            "@my_signals_bot or @my_channel.",
        )

    html = _fetch_telegram_profile_html(username)
    if not _telegram_profile_looks_real(html):
        raise HTTPException(
            404,
            f"@{username} doesn't have a public Telegram preview yet — "
            "make sure the username is correct and the account is "
            "visible at t.me/<username>.",
        )

    descriptions = _extract_telegram_descriptions(html)
    token = anchor.challenge_token
    found = any(token in d for d in descriptions)
    if not found:
        raise HTTPException(
            400,
            "The challenge token wasn't found in @"
            f"{username}'s bio. Paste it exactly as shown — Telegram "
            "sometimes caches old previews for a minute, so wait briefly "
            "and try again if you just updated the bio.",
        )

    now = datetime.utcnow()
    anchor.value = f"@{username}"
    anchor.method = "bio"
    anchor.verified_at = now
    anchor.last_check_at = now
    anchor.metadata_json = {
        "username": username,
        "profile_url": f"https://t.me/{username}",
    }
    db.commit()
    db.refresh(anchor)
    return _to_out(anchor)


# --------------------------------------------------------------------------- #
# Slug claim from verified anchor — Sprint UX-5.11 R2 / R2.3b                  #
# --------------------------------------------------------------------------- #


class ClaimSlugRequest(BaseModel):
    anchor_id: str = Field(
        ...,
        description=(
            "ID of a verified anchor on this agent. The slug is derived "
            "from that anchor's value (Telegram @handle, GitHub login, "
            "DNS domain) — the customer can only claim handles they've "
            "proved control of."
        ),
    )


class ClaimSlugResponse(BaseModel):
    slug: str = Field(
        ..., description="The claimed slug. Public verify URL is `/v/<slug>`."
    )
    previous_slug: Optional[str] = Field(
        None,
        description=(
            "The slug the agent had before this claim, if any. Useful "
            "for surfacing 'your old URL still works as /verify/<id>'."
        ),
    )


@router.post("/{agent_id}/claim-slug", response_model=ClaimSlugResponse)
def claim_slug_from_anchor(
    agent_id: str,
    body: ClaimSlugRequest,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Claim a public slug for the agent, derived from a verified anchor.

    The customer must already have verified an external anchor on this
    agent. The slug is derived from that anchor's value (Telegram
    @handle, GitHub login, DNS domain) via `slugify`. If the derived
    slug is taken by another agent the allocator appends `-2`, `-3`,
    ... — but since the customer has cryptographic proof of control
    over the source handle, that suffix only happens in legitimate
    rare overlap cases (e.g. two GitHub users named "carlos" both
    claiming `/v/carlos`).

    This is the only way (besides the watcher auto-attach path) to
    obtain a `/v/<slug>` URL. New agents are slugless until they
    claim — their default URL is `/verify/<agent_id>`.
    """
    agent = _resolve_customer_agent(db, agent_id, auth)

    anchor = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.id == body.anchor_id,
            AgentAnchor.agent_id == agent_id,
        )
        .first()
    )
    if anchor is None:
        raise HTTPException(404, "Anchor not found")
    if anchor.verified_at is None:
        raise HTTPException(
            400,
            "Anchor is not verified yet. Complete the verification step "
            "before claiming a slug.",
        )
    if not anchor.value:
        raise HTTPException(
            400,
            "Anchor has no value to derive a slug from. (This should not "
            "happen for verified anchors — please re-create the anchor.)",
        )

    # Derive the slug candidate from the anchor's value. The leading @
    # on Telegram handles is stripped by slugify naturally.
    from app.core.slug import commit_with_slug_retry, slugify

    candidate = slugify(anchor.value)
    if not candidate:
        raise HTTPException(
            400,
            f"Could not derive a usable slug from anchor value "
            f"{anchor.value!r}.",
        )

    previous_slug = agent.public_slug

    def _set_slug(slug):
        agent.public_slug = slug

    chosen = commit_with_slug_retry(
        db,
        candidate=candidate,
        fallback=agent_id,
        set_slug=_set_slug,
        # No new ORM objects — we're only updating the agent row in place.
        pending_objects=None,
    )
    if chosen is None:
        raise HTTPException(
            409,
            "All slug candidates derived from this anchor are taken. "
            "Try a different anchor or contact support.",
        )
    return ClaimSlugResponse(slug=chosen, previous_slug=previous_slug)


@router.delete("/{agent_id}/anchors/{anchor_id}", status_code=204)
def delete_anchor(
    agent_id: str,
    anchor_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Remove an anchor (verified or pending)."""
    _resolve_customer_agent(db, agent_id, auth)
    anchor = (
        db.query(AgentAnchor)
        .filter(
            AgentAnchor.id == anchor_id,
            AgentAnchor.agent_id == agent_id,
        )
        .first()
    )
    if anchor is None:
        raise HTTPException(404, "Anchor not found")
    db.delete(anchor)
    db.commit()
    return None
