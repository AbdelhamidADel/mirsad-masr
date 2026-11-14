"""HTTP webhook for Telegram Bot API updates."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from egxdesk.alerts import bot
from egxdesk.alerts import telegram as tg
from egxdesk.alerts.bot import BotReply
from egxdesk.alerts.db import init_db, session_scope
from egxdesk.config import settings

router = APIRouter(prefix="/telegram", tags=["Telegram"])


def _extract_chat_id(update: dict[str, Any]) -> str | None:
    cq = update.get("callback_query")
    if isinstance(cq, dict):
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        return str(cid) if cid is not None else None
    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    return str(cid) if cid is not None else None


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    secret: str | None = Query(default=None),
) -> dict[str, Any]:
    expected = settings.telegram_webhook_secret.strip()
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or (header != expected and secret != expected):
        raise HTTPException(status_code=403, detail="forbidden")

    try:
        update = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid json") from exc
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="invalid update")

    if not settings.alerts_enabled or not settings.database_url.strip():
        return {"ok": True, "disabled": True}

    init_db()
    with session_scope() as session:
        reply = bot.handle_update(session, update)

    if isinstance(reply, BotReply):
        if reply.callback_query_id:
            tg.answer_callback_query(callback_query_id=reply.callback_query_id)
        if (
            reply.clear_keyboard_chat_id is not None
            and reply.clear_keyboard_message_id is not None
        ):
            tg.clear_inline_keyboard(
                chat_id=reply.clear_keyboard_chat_id,
                message_id=reply.clear_keyboard_message_id,
            )
        chat = _extract_chat_id(update)
        if chat is not None and reply.text:
            tg.send_message(
                chat_id=chat,
                text=reply.text,
                reply_markup=reply.reply_markup,
            )
    return {"ok": True}
