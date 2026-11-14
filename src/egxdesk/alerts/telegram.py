"""Telegram Bot API send helper with optional outbox for tests."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from egxdesk.config import settings

log = structlog.get_logger()
_outbox: list[dict[str, Any]] | None = None


def use_outbox(enabled: bool = True) -> list[dict[str, Any]]:
    global _outbox
    _outbox = [] if enabled else None
    return _outbox if _outbox is not None else []


def clear_outbox() -> None:
    if _outbox is not None:
        _outbox.clear()


def send_message(
    *,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    if _outbox is not None:
        item: dict[str, Any] = {"chat_id": str(chat_id), "text": text}
        if reply_markup is not None:
            item["reply_markup"] = reply_markup
        _outbox.append(item)
        return True
    token = settings.telegram_bot_token.strip()
    if not token:
        log.warning("telegram_send_skipped_no_token")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, object] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, json=payload)
        if res.status_code == 429:
            log.warning("telegram_rate_limited", chat_id=str(chat_id))
            return False
        data = res.json()
        if not data.get("ok"):
            desc = str(data.get("description") or "")
            if "blocked" in desc.lower() or "deactivated" in desc.lower():
                log.info("telegram_chat_blocked", chat_id=str(chat_id))
            log.warning("telegram_send_failed", status=res.status_code, body=desc[:200])
            return False
        return True
    except Exception as exc:
        log.warning("telegram_send_error", error=str(exc))
        return False


def answer_callback_query(*, callback_query_id: str, text: str | None = None) -> bool:
    if _outbox is not None:
        _outbox.append({"callback_query_id": callback_query_id, "text": text or ""})
        return True
    token = settings.telegram_bot_token.strip()
    if not token or not callback_query_id:
        return False
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload: dict[str, object] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, json=payload)
        return bool(res.json().get("ok"))
    except Exception as exc:
        log.warning("telegram_answer_callback_failed", error=str(exc))
        return False
