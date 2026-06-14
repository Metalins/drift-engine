"""Public SVG verification badges.

Sprint UX-5.10-5 (#663). Sofía's promise on the agent-vendors landing:
"One embeddable badge for your listing, docs, or API response." This
module makes that real.

Endpoint
--------
GET /v1/public/badge/{slug}.svg
    Returns a shields.io-style two-tone SVG that renders the agent's
    current verdict. No auth, no rate limit beyond Cloud Run defaults.

The badge text on the right side reflects the same
`verification_state` derived in `app.api.public._derive_verification_state`
(Sprint UX-5.9-A), so the badge and the verify page never disagree.

Cache
-----
We set `Cache-Control: public, max-age=300, stale-while-revalidate=600`.
Five minutes is short enough that a state change reflects quickly on
the badge embedded in a README, and long enough that a popular listing
won't hammer our DB.

Design choice (shields.io shape)
--------------------------------
Buyers will embed this in GitHub READMEs and HuggingFace listings
alongside other shields.io badges. Visually matching that convention
(width ~150px, height 20px, 2 tones, system font) makes it look at
home rather than out-of-place. Brand presence is the left "metalins"
label.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.slug import slugify
from app.db import get_db
from app.db.models import Agent, AgentObservable, AgentState
from app.services.verification_state import derive_trust


router = APIRouter(tags=["public"])


# Map the cryptographic-layer state to (right-side text, fill color).
# Sprint UX-5.12 — the badge advertises the cryptographic guarantee
# (binary, immediate) rather than a mixed score. The behavioral layer
# isn't shown in the badge: it's a gradual signal the badge doesn't
# need to expose to third parties (see TWO-LAYER-TRUST-DESIGN.md §7.4).
_CRYPTO_STATE_VISUALS: dict[str, tuple[str, str]] = {
    "verified":         ("verified",        "#4c1"),       # green
    "unverified":       ("setting up",      "#007ec6"),    # blue
    "caution":          ("verify w/ care",  "#dfb317"),    # amber
    "action_required":  ("not trusted",     "#e05d44"),    # red
    "revoked":          ("revoked",         "#9f9f9f"),    # grey
    "unknown":          ("not found",       "#9f9f9f"),    # grey
}

_LEFT_TEXT = "metalins"
_LEFT_BG = "#555"        # dark grey, shields convention
_TEXT_FILL = "#fff"

# Tuning: char widths are approximate for shields' built-in font
# (Verdana 11px). We round up so wide letters like W/M don't clip.
_CHAR_W = 6.5
_PADDING = 9             # px on each side of each label


def _label_width(text: str) -> int:
    """Approximate pixel width for a text label at shields' font."""
    return int(len(text) * _CHAR_W + _PADDING * 2)


def _render_svg(left: str, right: str, right_bg: str) -> str:
    """Render a 20px-tall two-tone badge. Returns the SVG string.

    Uses `<text>` with `text-anchor=middle` over rect halves so the
    text stays centered even if widths shift. No external font — relies
    on the system stack (Verdana on Windows/Mac, DejaVu Sans on Linux),
    which is what shields.io uses too.
    """
    lw = _label_width(left)
    rw = _label_width(right)
    total = lw + rw
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{left}: {right}">
  <title>{left}: {right}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".7"/>
    <stop offset=".1" stop-color="#aaa" stop-opacity=".1"/>
    <stop offset=".9" stop-color="#000" stop-opacity=".3"/>
    <stop offset="1" stop-color="#000" stop-opacity=".5"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total}" height="20" rx="3"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{lw}" height="20" fill="{_LEFT_BG}"/>
    <rect x="{lw}" width="{rw}" height="20" fill="{right_bg}"/>
    <rect width="{total}" height="20" fill="url(#s)"/>
  </g>
  <g fill="{_TEXT_FILL}" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="110">
    <text x="{lw * 5}" y="150" transform="scale(.1)" fill="#000" fill-opacity=".25" textLength="{(lw - _PADDING * 2) * 10}">{left}</text>
    <text x="{lw * 5}" y="140" transform="scale(.1)" textLength="{(lw - _PADDING * 2) * 10}">{left}</text>
    <text x="{(lw + rw / 2) * 10}" y="150" transform="scale(.1)" fill="#000" fill-opacity=".25" textLength="{(rw - _PADDING * 2) * 10}">{right}</text>
    <text x="{(lw + rw / 2) * 10}" y="140" transform="scale(.1)" textLength="{(rw - _PADDING * 2) * 10}">{right}</text>
  </g>
</svg>'''


def _svg_response(svg: str, *, found: bool = True) -> Response:
    """Wrap an SVG string in a Response with the right cache + CORS headers.

    `found=False` shortens the cache so a typo isn't memorized for long.
    """
    max_age = 300 if found else 30
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": f"public, max-age={max_age}, stale-while-revalidate=600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/v1/public/badge/{slug}.svg")
def public_badge(slug: str, db: Session = Depends(get_db)):
    """Render a verification badge for a slug.

    Resolves the slug → agent → verification_state, then renders the
    matching two-tone SVG. Unknown slugs render an "not found" grey
    badge rather than a 404 so a stale embed degrades gracefully.
    """
    normalized = slugify(slug)
    if not normalized:
        text, color = _CRYPTO_STATE_VISUALS["unknown"]
        return _svg_response(_render_svg(_LEFT_TEXT, text, color), found=False)

    agent = (
        db.query(Agent).filter(Agent.public_slug == normalized).first()
    )
    if agent is None:
        text, color = _CRYPTO_STATE_VISUALS["unknown"]
        return _svg_response(_render_svg(_LEFT_TEXT, text, color), found=False)

    state = db.query(AgentState).filter(AgentState.agent_id == agent.id).first()
    latest_obs = (
        db.query(AgentObservable)
        .filter(AgentObservable.agent_id == agent.id)
        .order_by(AgentObservable.ts.desc())
        .first()
    )
    trust = derive_trust(agent, state, latest_obs)
    crypto_state = trust["cryptographic"]["state"]
    text, color = _CRYPTO_STATE_VISUALS.get(
        crypto_state, _CRYPTO_STATE_VISUALS["unknown"]
    )
    return _svg_response(_render_svg(_LEFT_TEXT, text, color))
