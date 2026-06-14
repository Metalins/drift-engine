"""Telegram Bot API adapter — Sprint 4.3.

Polls https://api.telegram.org/bot<TOKEN>/getUpdates with `offset` set to
`watcher.last_event_id + 1` to fetch only new updates since the previous
poll. For each `message` update, we hash:

  - input_hash  = sha256(message.text or '')
  - output_hash = sha256(message.reply_to_message.text or '')

This is a minimal MVP shape — it works for bots that operate in 1:1 DMs and
group chats where users address the bot. For richer flows (commands,
callback_query, edited_message) we extend later. Privacy unchanged.

Auth failure (401) → adapter raises so watcher_job marks state='error'.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Sequence

import httpx
from sqlalchemy.orm import Session

from app.db.models import Watcher
from app.services import watcher_crypto
from app.services.watchers import EventDraft, register_adapter

log = logging.getLogger(__name__)

# Telegram getUpdates allows long-polling, but for a 60s scheduler we just
# fetch what's queued. 5 seconds is enough margin.
_HTTP_TIMEOUT = 10.0
_MAX_UPDATES_PER_POLL = 100


class _Adapter:
    """The Telegram adapter — registered in module-level register_adapter()."""

    platform_name = "telegram"

    def fetch_new_events(
        self,
        watcher: Watcher,
        token: str,
        db: Session,
    ) -> Sequence[EventDraft]:
        # Cursor: Telegram's update_id, stored as string in watcher.last_event_id.
        offset = 0
        if watcher.last_event_id:
            try:
                offset = int(watcher.last_event_id) + 1
            except ValueError:
                log.warning(
                    "Watcher %s has non-int last_event_id; resetting to 0",
                    watcher.id,
                )
                offset = 0

        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {
            "offset": offset,
            "limit": _MAX_UPDATES_PER_POLL,
            "allowed_updates": "message",
            "timeout": 0,  # no long poll — we're scheduled
        }

        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                resp = client.get(url, params=params)
        except httpx.HTTPError as e:
            raise RuntimeError(f"telegram_http_error: {e}") from e

        if resp.status_code == 401:
            raise RuntimeError("telegram_unauthorized (token revoked?)")
        if resp.status_code != 200:
            raise RuntimeError(
                f"telegram_unexpected_status:{resp.status_code} body={resp.text[:200]}"
            )

        data = resp.json()
        if not data.get("ok", False):
            raise RuntimeError(
                f"telegram_not_ok: {data.get('description','?')}"
            )

        drafts: list[EventDraft] = []
        # Per-customer chat-id salt for hashing. Use customer_id since it's
        # already unique and not derivable from public data.
        customer_salt = watcher.customer_id

        for update in data.get("result", []):
            message = update.get("message")
            if not message:
                # Not a message-type update (we asked for messages only, but
                # extra types might slip in). Still advance the cursor.
                continue

            text = message.get("text") or message.get("caption") or ""
            reply_text = ""
            if message.get("reply_to_message"):
                rm = message["reply_to_message"]
                reply_text = rm.get("text") or rm.get("caption") or ""

            input_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            output_hash = hashlib.sha256(reply_text.encode("utf-8")).hexdigest()

            ts_unix = message.get("date")
            ts = (
                datetime.fromtimestamp(ts_unix, tz=timezone.utc).replace(tzinfo=None)
                if isinstance(ts_unix, (int, float))
                else datetime.utcnow()
            )

            chat = message.get("chat", {})
            chat_id_hash = watcher_crypto.hash_chat_id(
                chat.get("id", ""), customer_salt
            )

            drafts.append(
                EventDraft(
                    input_hash=input_hash,
                    output_hash=output_hash,
                    ts=ts,
                    platform_message_id=str(update["update_id"]),
                    chat_id_hash=chat_id_hash,
                    metadata={
                        "platform": "telegram",
                        "chat_type": chat.get("type"),  # 'private'|'group'|'supergroup'|'channel'
                        "has_reply": bool(message.get("reply_to_message")),
                    },
                )
            )

        return drafts


register_adapter(_Adapter())


def get_bot_username(token: str) -> str | None:
    """Call Telegram's getMe and return the bot's `@username`.

    Sprint UX-5.10-7 (#665). Used at watcher creation time so we can
    overwrite whatever descriptive label the customer typed with the
    real public handle — which is what the verify-page anchor needs
    to be meaningful to a third party.

    Returns None on any failure (network error, revoked token, missing
    `result.username`). Callers fall back to user-typed display_name
    in that case.
    """
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            resp = client.get(url)
    except httpx.HTTPError as e:
        log.warning("telegram getMe failed: %s", e)
        return None
    if resp.status_code != 200:
        log.warning(
            "telegram getMe non-200: %d body=%s",
            resp.status_code, resp.text[:200],
        )
        return None
    data = resp.json()
    if not data.get("ok"):
        return None
    username = (data.get("result") or {}).get("username")
    if not username:
        return None
    return f"@{username}"
