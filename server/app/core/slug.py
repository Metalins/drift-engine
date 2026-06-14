"""Public slug generation for verify URLs.

Sprint UX-5.7a (#634). Maps a human-typed handle (Telegram bot username,
agent name, etc.) into a URL-safe slug that can be used as the path of
the public verify page (`/v/<slug>`).

Rules:
    • Lowercase ASCII letters, digits, and hyphens.
    • 3-64 chars after normalization (Telegram usernames are min 5; we
      go lower so agent-name fallbacks like "bot" still fit).
    • No leading or trailing hyphen.
    • No consecutive hyphens.

The auto-allocator (`allocate_public_slug`) takes a candidate, normalizes
it, and if the result collides with an existing row, appends `-2`,
`-3`, ... until it finds free real estate. We keep this conservative
(no random suffix) so the URL stays predictable from the watcher
username most of the time.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional, TypeVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Agent


T = TypeVar("T")


_MIN_LEN = 3
_MAX_LEN = 64
_INVALID_CHARS = re.compile(r"[^a-z0-9]+")
_TRIM_HYPHENS = re.compile(r"^-+|-+$")


def slugify(text: str) -> str:
    """Normalize free-form text to slug form.

    Examples:
        "@SenalesCryptoCarlos"   → "senales-crypto-carlos"
        "Customer Support Bot 3" → "customer-support-bot-3"
        "agente de prueba para telegram"
                                 → "agente-de-prueba-para-telegram"
        "🤖 my bot ✨"            → "my-bot"
    """
    if not text:
        return ""
    # 1. Strip Unicode accents and emojis to plain ASCII.
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    # 2. Lowercase.
    lowered = ascii_only.lower()
    # 3. Collapse runs of non-[a-z0-9] into single hyphens.
    hyphenated = _INVALID_CHARS.sub("-", lowered)
    # 4. Trim leading/trailing hyphens.
    trimmed = _TRIM_HYPHENS.sub("", hyphenated)
    # 5. Cap to max length, but don't end on a hyphen if we cut mid-word.
    if len(trimmed) > _MAX_LEN:
        trimmed = trimmed[:_MAX_LEN]
        trimmed = _TRIM_HYPHENS.sub("", trimmed)
    return trimmed


def is_valid_slug(slug: str) -> bool:
    """True iff slug matches the normalized shape we accept publicly."""
    if not slug:
        return False
    if len(slug) < _MIN_LEN or len(slug) > _MAX_LEN:
        return False
    return slugify(slug) == slug


def allocate_public_slug(
    db: Session,
    candidate: str,
    *,
    fallback: Optional[str] = None,
    exclude_agent_id: Optional[str] = None,
) -> Optional[str]:
    """Find a free slug starting from `candidate`, optionally falling
    back to `fallback` if the candidate normalizes to nothing.

    Returns the chosen slug, or None if we couldn't normalize anything
    usable. The caller writes it to the agent row.

    `exclude_agent_id` lets you re-run the allocator on an agent that
    already has a slug (e.g. to regenerate after a rename) without
    bumping itself out of its current slot.
    """
    base = slugify(candidate)
    if len(base) < _MIN_LEN and fallback:
        base = slugify(fallback)
    if len(base) < _MIN_LEN:
        return None

    # Try the bare slug first, then -2, -3, ...
    attempt = base
    suffix = 1
    while True:
        q = db.query(Agent).filter(Agent.public_slug == attempt)
        if exclude_agent_id:
            q = q.filter(Agent.id != exclude_agent_id)
        if q.first() is None:
            return attempt
        suffix += 1
        # Keep the suffixed slug within the length limit.
        suffix_str = f"-{suffix}"
        max_base = _MAX_LEN - len(suffix_str)
        attempt = base[:max_base] + suffix_str
        # Sanity: if we somehow hit 1000 collisions, bail out.
        if suffix > 1000:
            return None


def commit_with_slug_retry(
    db: Session,
    candidate: str,
    *,
    fallback: Optional[str] = None,
    set_slug: Callable[[Optional[str]], None],
    pending_objects: Optional[list] = None,
    max_attempts: int = 5,
) -> Optional[str]:
    """Commit current session, retrying if the slug UNIQUE index trips.

    Sprint UX-5.11 R2 / R2.2b (2026-05-18). `allocate_public_slug` does
    a SELECT-then-pick, which races with concurrent registers: two
    sessions can both SELECT a free slug, then both INSERT. The DB has
    a partial UNIQUE index (`agents_public_slug_unique`) that catches
    the second commit with `IntegrityError` — without retry, the second
    customer's request would 500.

    This helper takes:
        - `candidate` — the human-typed handle for slug generation
        - `fallback` — optional secondary candidate
        - `set_slug(slug)` — callback the caller uses to write the chosen
          slug onto whatever ORM row is pending in `db` (agent, watcher
          rename, etc.). Called once per attempt with the freshly-
          allocated slug, and once at the end with None if every attempt
          collided.
        - `pending_objects` — list of ORM instances that were `db.add`-ed
          before calling this helper. On rollback those objects get
          detached, so we re-add them on each retry. If your write is a
          plain UPDATE on an existing row (no new inserts), leave this
          as None.

    Returns the slug that ultimately committed, or None on giving up.
    The caller is responsible for raising a user-visible HTTPException
    if None comes back.
    """
    slug = allocate_public_slug(db, candidate, fallback=fallback)
    set_slug(slug)
    for attempt in range(max_attempts):
        try:
            db.commit()
            return slug
        except IntegrityError as e:
            # Only swallow if it's specifically the slug index that tripped;
            # other integrity errors (FK, agent_id PK, etc.) must propagate.
            msg = str(getattr(e, "orig", e)).lower()
            if "public_slug" not in msg and "agents_public_slug_unique" not in msg:
                raise
            db.rollback()
            # Rollback detaches any added instances — re-attach them so
            # the next commit attempt actually writes them.
            if pending_objects:
                for obj in pending_objects:
                    db.add(obj)
            # Re-pick. After rollback the conflicting row is committed
            # by the other transaction, so the next allocate sees it and
            # walks past it.
            slug = allocate_public_slug(db, candidate, fallback=fallback)
            set_slug(slug)
    # All attempts collided — fall back to clearing the slug so the
    # row commits without one, and the customer can rename later.
    db.rollback()
    if pending_objects:
        for obj in pending_objects:
            db.add(obj)
    set_slug(None)
    db.commit()
    return None
