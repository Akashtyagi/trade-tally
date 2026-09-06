"""Telegram Bot API helper."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PLACEHOLDER_TOKEN = "your_telegram_bot_token_here"


def _chat_and_enabled() -> tuple[str, bool]:
    # UI AppSettings overlay .env; fall back if the DB is not ready (tests, migrate).
    try:
        from trades.runtime_config import telegram_alerts_enabled, telegram_chat_id

        return telegram_chat_id(), telegram_alerts_enabled()
    except Exception:
        return (settings.TELEGRAM_CHAT_ID or "", True)


def is_configured() -> bool:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or token == PLACEHOLDER_TOKEN:
        return False
    chat_id, enabled = _chat_and_enabled()
    return bool(enabled and chat_id)


def send_message(text: str) -> bool:
    """POST Telegram Bot API sendMessage. No-op when token/chat is unset."""
    if not is_configured():
        logger.info("Telegram not configured; skipping message: %s", text)
        return False
    chat_id, _enabled = _chat_and_enabled()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=15,
    )
    response.raise_for_status()
    return True
