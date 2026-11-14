"""Telegram conversation handler for alert signup and rule management."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from egxdesk.alerts import service
from egxdesk.config import settings

_SESSION_TTL_SEC = 15 * 60
_sessions: dict[str, dict[str, Any]] = {}

_TARGET_TYPES = ("stock", "gold", "index", "fx")
_RULE_KINDS = ("above", "below", "pct_move", "points_move")


def clear_sessions() -> None:
    _sessions.clear()


def _now() -> float:
    return time.time()


def _get_session(chat_id: str) -> dict[str, Any] | None:
    state = _sessions.get(chat_id)
    if state is None:
        return None
    if _now() - float(state.get("ts", 0)) > _SESSION_TTL_SEC:
        _sessions.pop(chat_id, None)
        return None
    return state


def _set_session(chat_id: str, **fields: Any) -> None:
    cur = _sessions.get(chat_id) or {}
    cur.update(fields)
    cur["ts"] = _now()
    _sessions[chat_id] = cur


def _clear_session(chat_id: str) -> None:
    _sessions.pop(chat_id, None)


def _chat_id_from_update(update: dict[str, Any]) -> str | None:
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    return str(cid) if cid is not None else None


def _text_from_update(update: dict[str, Any]) -> str:
    msg = update.get("message") or update.get("edited_message") or {}
    return str(msg.get("text") or "").strip()


def _help(lang: str) -> str:
    if lang == "ar":
        return (
            "الأوامر:\n"
            "/start — البداية\n"
            "/add — إضافة قاعدة\n"
            "/rules — عرض القواعد\n"
            "/delete <id> — حذف قاعدة\n"
            "/digest on|off — الملخص اليومي بالبريد\n"
            "/stop — إلغاء الاشتراك"
        )
    return (
        "Commands:\n"
        "/start — begin\n"
        "/add — add a threshold rule\n"
        "/rules — list rules\n"
        "/delete <id> — delete a rule\n"
        "/digest on|off — daily email digest\n"
        "/stop — unsubscribe"
    )


def handle_update(session: Session, update: dict[str, Any]) -> str | None:
    """Process one Telegram Update; return reply text or None."""
    if not settings.alerts_enabled:
        return "Alerts are offline right now. Try again later."

    chat_id = _chat_id_from_update(update)
    if not chat_id:
        return None
    text = _text_from_update(update)
    if not text:
        return None

    sub = service.get_by_telegram_chat(session, chat_id)
    lang = sub.lang if sub is not None else "en"
    lower = text.lower()

    state = _get_session(chat_id)
    if state and state.get("step"):
        return _continue_wizard(session, chat_id, text, state)

    if lower.startswith("/start"):
        service.upsert_telegram_subscriber(session, chat_id, lang=lang)
        _set_session(chat_id, step="await_lang")
        return (
            "Welcome to MIRSAD MASR alerts.\n"
            "Choose language: reply `en` or `ar`"
        )

    if lower.startswith("/stop"):
        service.stop_telegram(session, chat_id)
        _clear_session(chat_id)
        return "Unsubscribed. Send /start to subscribe again."

    if lower.startswith("/help"):
        return _help(lang)

    if sub is None or sub.unsubscribed_at is not None:
        return "Send /start to subscribe first."

    if lower.startswith("/rules"):
        rules = service.list_rules_for_chat(session, chat_id)
        if not rules:
            return "No active rules. Use /add"
        lines = [
            f"{r.id[:8]}… {r.target_type}:{r.target_id} {r.rule_kind} {r.threshold}"
            for r in rules
        ]
        return "Active rules:\n" + "\n".join(lines)

    if lower.startswith("/delete"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return "Usage: /delete <rule_id>"
        needle = parts[1].strip()
        rules = service.list_rules_for_chat(session, chat_id)
        match = next((r for r in rules if r.id.startswith(needle) or r.id == needle), None)
        if match is None:
            return "Rule not found."
        service.delete_rule_for_chat(session, chat_id, match.id)
        return "Rule deleted."

    if lower.startswith("/digest"):
        parts = lower.split()
        if len(parts) >= 2 and parts[1] == "off":
            if sub.manage_token:
                service.set_digest(session, sub.manage_token, False)
            return "Daily email digest off. Telegram alerts still active."
        if len(parts) >= 2 and parts[1] == "on":
            _set_session(chat_id, step="await_email")
            return "Send the email address for your daily digest."
        return "Usage: /digest on | /digest off"

    if lower.startswith("/add"):
        if len(service.list_rules_for_chat(session, chat_id)) >= settings.alerts_max_rules:
            return f"Max {settings.alerts_max_rules} rules reached. /delete one first."
        _set_session(chat_id, step="await_type")
        return "Target type? stock | gold | index | fx"

    return _help(lang)


def _continue_wizard(session: Session, chat_id: str, text: str, state: dict[str, Any]) -> str:
    step = str(state.get("step") or "")
    lower = text.lower().strip()

    if step == "await_lang":
        if lower not in ("en", "ar"):
            return "Reply `en` or `ar`"
        service.upsert_telegram_subscriber(session, chat_id, lang=lower)
        _clear_session(chat_id)
        return (
            f"Language set to {lower}.\n" + _help(lower)
        )

    if step == "await_email":
        try:
            _sub, sent = service.request_digest_email(session, chat_id, text.strip())
        except service.AlreadyRegisteredError:
            return "That email is already registered. Use another address."
        except ValueError as exc:
            return str(exc)
        _clear_session(chat_id)
        if sent:
            return "Confirmation email sent. Open the link to enable the daily digest."
        return "Saved email, but confirmation email failed to send. Try /digest on again later."

    if step == "await_type":
        if lower not in _TARGET_TYPES:
            return "Target type? stock | gold | index | fx"
        _set_session(chat_id, step="await_id", target_type=lower)
        examples = {
            "stock": "e.g. COMI",
            "gold": "e.g. gold_21k",
            "index": "e.g. CASE30",
            "fx": "e.g. usd_egp",
        }
        return f"Target id? ({examples[lower]})"

    if step == "await_id":
        tid = text.strip()
        if not tid:
            return "Send a target id."
        _set_session(chat_id, step="await_kind", target_id=tid)
        return "Rule kind? above | below | pct_move | points_move"

    if step == "await_kind":
        if lower not in _RULE_KINDS:
            return "Rule kind? above | below | pct_move | points_move"
        _set_session(chat_id, step="await_threshold", rule_kind=lower)
        return "Threshold number? (e.g. 100 or 2.5)"

    if step == "await_threshold":
        try:
            threshold = float(text.strip().replace(",", ""))
        except ValueError:
            return "Send a number for the threshold."
        try:
            rule = service.add_rule_for_chat(
                session,
                chat_id,
                target_type=str(state.get("target_type")),
                target_id=str(state.get("target_id")),
                rule_kind=str(state.get("rule_kind")),
                threshold=threshold,
            )
        except ValueError as exc:
            _clear_session(chat_id)
            return str(exc)
        _clear_session(chat_id)
        return (
            f"Rule saved ({rule.id[:8]}…): "
            f"{rule.target_type}:{rule.target_id} {rule.rule_kind} {rule.threshold}"
        )

    _clear_session(chat_id)
    return _help("en")
