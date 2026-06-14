"""Backfill `public_slug` for legacy agents that pre-date Sprint UX-5.7a.

Sprint UX-5.9-B (#651) — the UX walkthrough on 2026-05-16 caught that the
public slug column was added in UX-5.7a but only populated on NEW agents.
Pre-existing rows (anything registered before May 14, 2026) still have
`public_slug = NULL`, so their owners can't share a `/v/<slug>` link.

Behaviour
---------
Idempotent. For every agent with `public_slug IS NULL`:

  1. If the agent has an active Telegram watcher with a `display_name`,
     prefer that as the slug source (matches the UX-5.7a watcher path —
     e.g. "@SenalesCryptoCarlos" → "senales-crypto-carlos").
  2. Otherwise, fall back to the agent's own `name`.
  3. Otherwise (both are empty/un-normalizable), skip and warn — that
     row stays NULL until the customer renames the agent.

Each candidate goes through `allocate_public_slug()` which appends
`-2`, `-3`, ... to break collisions. So running this twice is safe.

Usage
-----
    cd server
    DATABASE_URL=... python scripts/backfill_public_slugs.py
    DATABASE_URL=... python scripts/backfill_public_slugs.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.slug import allocate_public_slug  # noqa: E402
from app.db.models import Agent, Watcher  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def _candidate_for(agent: Agent, db) -> tuple[str | None, str | None]:
    """Return (candidate, source) for an agent.

    source is one of "watcher" | "name" | None — useful for logging.
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
    if watcher and watcher.display_name:
        return watcher.display_name, "watcher"
    if agent.name:
        return agent.name, "name"
    return None, None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would change without committing.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        rows = (
            db.query(Agent).filter(Agent.public_slug.is_(None)).all()
        )
        if not rows:
            print("✓ No agents need backfilling. All rows have public_slug.")
            return

        print(f"Found {len(rows)} agent(s) without public_slug.")
        print()

        allocated = 0
        skipped = 0
        for agent in rows:
            candidate, source = _candidate_for(agent, db)
            if candidate is None:
                print(
                    f"  ⊘ {agent.id} ({agent.name!r}) — "
                    "no usable name, skipping."
                )
                skipped += 1
                continue

            slug = allocate_public_slug(
                db,
                candidate=candidate,
                fallback=agent.id,
                exclude_agent_id=agent.id,
            )
            if slug is None:
                print(
                    f"  ⊘ {agent.id} ({agent.name!r}) — "
                    f"could not allocate (source={source})"
                )
                skipped += 1
                continue

            print(
                f"  ✓ {agent.id} ({agent.name!r}) → "
                f"{slug!r} (from {source})"
            )
            if not args.dry_run:
                agent.public_slug = slug
            allocated += 1

        if args.dry_run:
            print()
            print(f"--dry-run: would allocate {allocated}, skip {skipped}.")
            db.rollback()
            return

        db.commit()
        print()
        print(f"✓ Allocated {allocated} slug(s). Skipped {skipped}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
