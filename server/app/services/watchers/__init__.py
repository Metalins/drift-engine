"""Platform adapter registry — Sprint 4.

Each adapter implements `PlatformAdapter`. The watcher_job iterates over
active watchers, looks up the adapter for `watcher.platform`, and asks it
for new EventDrafts since `last_event_id`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, Sequence

from sqlalchemy.orm import Session

from app.db.models import Watcher


@dataclass
class EventDraft:
    """Platform-agnostic shape of one watcher-observed event.

    Produced by an adapter, consumed by watcher_job._log_event_drafts.
    All hashes are sha256 hex of UTF-8 encoded plaintext. The plaintext
    NEVER leaves the adapter — only these hashes do.
    """

    input_hash: str
    output_hash: str
    ts: datetime
    platform_message_id: str
    chat_id_hash: str
    metadata: dict = field(default_factory=dict)


class PlatformAdapter(Protocol):
    """Interface every platform adapter implements."""

    platform_name: str  # 'telegram' | 'discord' | 'slack' | 'x'

    def fetch_new_events(
        self,
        watcher: Watcher,
        token: str,
        db: Session,
    ) -> Sequence[EventDraft]:
        """Fetch events newer than `watcher.last_event_id`.

        Args:
            watcher: the watcher row (state may be mutated by caller after).
            token: the DECRYPTED bot token. Never log this.
            db: read-only DB session for any per-call queries (rare).

        Returns:
            EventDrafts in chronological order. May be empty.

        Implementations must:
          - Be idempotent: re-running with the same watcher must not re-emit
            events already cursor'd past.
          - Update watcher.last_event_id on the caller side via the return
            value of the last EventDraft.platform_message_id.
          - Raise on auth errors (401-equivalent) so the job can flip
            state to 'error' and stop polling.
        """
        ...


# Registry populated by each adapter module's import side-effect.
_ADAPTERS: dict[str, PlatformAdapter] = {}


def register_adapter(adapter: PlatformAdapter) -> None:
    """Adapters call this at module load to register themselves."""
    _ADAPTERS[adapter.platform_name] = adapter


def get_adapter(platform: str) -> PlatformAdapter | None:
    return _ADAPTERS.get(platform)


def list_supported_platforms() -> list[str]:
    return sorted(_ADAPTERS.keys())


# Eager import so adapters self-register.
from app.services.watchers import telegram as _telegram  # noqa: E402, F401
