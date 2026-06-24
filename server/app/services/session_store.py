"""In-memory store for verify sessions (challenge → response flow).

For Fase 1 / dev: in-memory dict with TTL.
For Fase 3+ / prod: replace with Redis (Upstash) or DB-backed store.

Sessions are short-lived (~5 min) and one-shot (consumed on verify).
"""
from __future__ import annotations

import threading
import time
from typing import Any


class SessionStore:
    def __init__(self, ttl_seconds: int = 300):
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def create(self, *, session_id: str, agent_id: str, challenges: list[dict[str, Any]], steps: int) -> None:
        with self._lock:
            self._sessions[session_id] = {
                "agent_id": agent_id,
                "challenges": challenges,
                "steps": steps,
                "created_at": time.time(),
            }
            self._gc_expired()

    def consume(self, session_id: str) -> dict[str, Any] | None:
        """One-shot retrieve + delete."""
        with self._lock:
            self._gc_expired()
            return self._sessions.pop(session_id, None)

    def _gc_expired(self) -> None:
        now = time.time()
        expired = [sid for sid, sess in self._sessions.items() if now - sess["created_at"] > self._ttl]
        for sid in expired:
            del self._sessions[sid]


sessions = SessionStore()
