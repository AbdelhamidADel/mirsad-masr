"""Telegram conversation handler for alert signup and rule management."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from egxdesk.alerts import service
from egxdesk.config import settings

_SESSION_TTL_SEC = 15 * 60
_sessions: dict[str, dict[str, Any]] = {}

_TARGET_TYPES = ("stock", "gold", "index", "fx")
_RULE_KINDS = ("above", "below", "pct_move", "points_move")

# Curated picks — tap instead of typing.
_STOCK_PICKS = (
    ("COMI", "COMI"),
    ("TMGH", "TMGH"),
    ("SWDY", "SWDY"),
    ("ETEL", "ETEL"),
    ("ORAS", "ORAS"),
    ("FWRY", "FWRY"),
    ("HRHO", "HRHO"),
    ("EAST", "EAST"),
)
_GOLD_PICKS = (("Gold 21K", "gold_21k"),)
_INDEX_PICKS = (("EGX30", "CASE30"), ("EGX70", "CASE70"))
_FX_PICKS = (("USD/EGP", "usd_egp"), ("EUR/EGP", "eur_egp"))


@dataclass
class BotReply:
    text: str
    reply_markup: dict[str, Any] | None = None
    callback_query_id: str | None = None


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


def _keyboard(rows: list[list[tuple[str, str]]]) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row] for row in rows
        ]
    }


def _lang_keyboard() -> dict[str, Any]:
    return _keyboard([[("English", "lang:en"), ("العربية", "lang:ar")]])


def _type_keyboard(lang: str) -> dict[str, Any]:
    if lang == "ar":
        return _keyboard(
            [
                [("سهم", "type:stock"), ("ذهب", "type:gold")],
                [("مؤشر", "type:index"), ("عملة", "type:fx")],
            ]
        )
    return _keyboard(
        [
            [("Stock", "type:stock"), ("Gold", "type:gold")],
            [("Index", "type:index"), ("FX", "type:fx")],
        ]
    )


def _id_keyboard(target_type: str, lang: str) -> dict[str, Any]:
    picks = {
        "stock": _STOCK_PICKS,
        "gold": _GOLD_PICKS,
        "index": _INDEX_PICKS,
        "fx": _FX_PICKS,
    }[target_type]
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for label, tid in picks:
        row.append((label, f"id:{tid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    other = ("رمز آخر (اكتب)", "id:__other__") if lang == "ar" else ("Other (type)", "id:__other__")
    rows.append([other])
    return _keyboard(rows)


def _kind_keyboard(lang: str) -> dict[str, Any]:
    if lang == "ar":
        return _keyboard(
            [
                [("أعلى من", "kind:above"), ("أقل من", "kind:below")],
                [("تغير %", "kind:pct_move"), ("تغير نقاط", "kind:points_move")],
            ]
        )
    return _keyboard(
        [
            [("Above", "kind:above"), ("Below", "kind:below")],
            [("% move", "kind:pct_move"), ("Points move", "kind:points_move")],
        ]
    )


def _home_keyboard(lang: str) -> dict[str, Any]:
    if lang == "ar":
        return _keyboard(
            [
                [("إضافة تنبيه", "menu:add")],
                [("قواعدي", "menu:rules"), ("مساعدة", "menu:help")],
                [("تغيير اللغة", "menu:lang"), ("إيقاف التنبيهات", "menu:stop")],
            ]
        )
    return _keyboard(
        [
            [("Add alert", "menu:add")],
            [("My rules", "menu:rules"), ("Help", "menu:help")],
            [("Change language", "menu:lang"), ("Stop alerts", "menu:stop")],
        ]
    )


def _home(lang: str) -> BotReply:
    if lang == "ar":
        return BotReply(
            "مرصاد مصر — التنبيهات\nاختر من الأزرار:",
            reply_markup=_home_keyboard("ar"),
        )
    return BotReply(
        "MIRSAD MASR — Alerts\nChoose an option:",
        reply_markup=_home_keyboard("en"),
    )


def _help(lang: str) -> str:
    if lang == "ar":
        return (
            "اضغط الأزرار للتنقل.\n"
            "• إضافة تنبيه — اختر سهم/ذهب/مؤشر/عملة بالضغط\n"
            "• قواعدي — عرض تنبيهاتك\n"
            "• يمكنك أيضاً: /add /rules /stop"
        )
    return (
        "Use the buttons to navigate.\n"
        "• Add alert — tap stock/gold/index/FX\n"
        "• My rules — see your alerts\n"
        "• You can also type: /add /rules /stop"
    )


def _parse_update(update: dict[str, Any]) -> tuple[str | None, str, str | None]:
    """Return (chat_id, text_or_callback_data, callback_query_id)."""
    cq = update.get("callback_query")
    if isinstance(cq, dict):
        msg = cq.get("message") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        data = str(cq.get("data") or "").strip()
        cqid = str(cq.get("id") or "") or None
        return (str(cid) if cid is not None else None, data, cqid)

    msg = update.get("message") or update.get("edited_message") or {}
    chat = msg.get("chat") or {}
    cid = chat.get("id")
    text = str(msg.get("text") or "").strip()
    return (str(cid) if cid is not None else None, text, None)


def handle_update(session: Session, update: dict[str, Any]) -> BotReply | None:
    """Process one Telegram Update; return reply or None."""
    if not settings.alerts_enabled:
        return BotReply("Alerts are offline right now. Try again later.")

    chat_id, text, callback_query_id = _parse_update(update)
    if not chat_id or not text:
        return None

    sub = service.get_by_telegram_chat(session, chat_id)
    lang = sub.lang if sub is not None else "en"
    lower = text.lower()

    # Normalize callback payloads into wizard / menu tokens.
    if text.startswith("lang:"):
        lower = text.split(":", 1)[1].lower()
        text = lower
    elif text.startswith("menu:"):
        lower = text  # keep menu:add etc.
    elif text.startswith("type:"):
        lower = text.split(":", 1)[1].lower()
        text = lower
    elif text.startswith("id:"):
        text = text.split(":", 1)[1]
        lower = text.lower()
    elif text.startswith("kind:"):
        lower = text.split(":", 1)[1].lower()
        text = lower

    state = _get_session(chat_id)
    if state and state.get("step"):
        reply = _continue_wizard(session, chat_id, text, state, lang=lang)
        if reply is not None:
            reply.callback_query_id = callback_query_id
        return reply

    if lower.startswith("/start") or lower == "menu:lang":
        service.upsert_telegram_subscriber(session, chat_id, lang=lang)
        # Returning users: show home in their language. New / explicit lang change: ask once.
        if lower == "menu:lang" or sub is None or sub.unsubscribed_at is not None:
            _set_session(chat_id, step="await_lang")
            return BotReply(
                "اختر اللغة / Choose language:",
                reply_markup=_lang_keyboard(),
                callback_query_id=callback_query_id,
            )
        home = _home(lang)
        home.callback_query_id = callback_query_id
        return home

    if lower in ("en", "ar"):
        service.upsert_telegram_subscriber(session, chat_id, lang=lower)
        _clear_session(chat_id)
        home = _home(lower)
        home.callback_query_id = callback_query_id
        return home

    if lower.startswith("/stop") or lower == "menu:stop":
        service.stop_telegram(session, chat_id)
        _clear_session(chat_id)
        return BotReply(
            "تم إيقاف التنبيهات. أرسل /start للعودة."
            if lang == "ar"
            else "Alerts stopped. Send /start to return.",
            callback_query_id=callback_query_id,
        )

    if lower.startswith("/help") or lower == "menu:help":
        return BotReply(
            _help(lang),
            reply_markup=_home_keyboard(lang),
            callback_query_id=callback_query_id,
        )

    if sub is None or sub.unsubscribed_at is not None:
        return BotReply(
            "أرسل /start أولاً." if lang == "ar" else "Send /start to subscribe first.",
            callback_query_id=callback_query_id,
        )

    if lower.startswith("/rules") or lower == "menu:rules":
        rules = service.list_rules_for_chat(session, chat_id)
        if not rules:
            return BotReply(
                "لا توجد تنبيهات بعد." if lang == "ar" else "No alerts yet.",
                reply_markup=_home_keyboard(lang),
                callback_query_id=callback_query_id,
            )
        lines = [
            f"{r.id[:8]}… {r.target_type}:{r.target_id} {r.rule_kind} {r.threshold}"
            for r in rules
        ]
        header = "تنبيهاتك:" if lang == "ar" else "Your alerts:"
        return BotReply(
            header + "\n" + "\n".join(lines),
            reply_markup=_home_keyboard(lang),
            callback_query_id=callback_query_id,
        )

    if lower.startswith("/delete"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return BotReply(
                "الاستخدام: /delete <rule_id>" if lang == "ar" else "Usage: /delete <rule_id>",
                reply_markup=_home_keyboard(lang),
                callback_query_id=callback_query_id,
            )
        needle = parts[1].strip()
        rules = service.list_rules_for_chat(session, chat_id)
        match = next((r for r in rules if r.id.startswith(needle) or r.id == needle), None)
        if match is None:
            return BotReply(
                "القاعدة غير موجودة." if lang == "ar" else "Rule not found.",
                reply_markup=_home_keyboard(lang),
                callback_query_id=callback_query_id,
            )
        service.delete_rule_for_chat(session, chat_id, match.id)
        return BotReply(
            "تم حذف القاعدة." if lang == "ar" else "Rule deleted.",
            reply_markup=_home_keyboard(lang),
            callback_query_id=callback_query_id,
        )

    if lower.startswith("/digest"):
        parts = lower.split()
        if len(parts) >= 2 and parts[1] == "off":
            if sub.manage_token:
                service.set_digest(session, sub.manage_token, False)
            return BotReply(
                "تم إيقاف الملخص اليومي."
                if lang == "ar"
                else "Daily email digest off.",
                reply_markup=_home_keyboard(lang),
                callback_query_id=callback_query_id,
            )
        if len(parts) >= 2 and parts[1] == "on":
            _set_session(chat_id, step="await_email")
            return BotReply(
                "أرسل بريدك الإلكتروني للملخص اليومي."
                if lang == "ar"
                else "Send the email address for your daily digest.",
                callback_query_id=callback_query_id,
            )
        return BotReply(
            "الاستخدام: /digest on | /digest off"
            if lang == "ar"
            else "Usage: /digest on | /digest off",
            reply_markup=_home_keyboard(lang),
            callback_query_id=callback_query_id,
        )

    if lower.startswith("/add") or lower == "menu:add":
        if len(service.list_rules_for_chat(session, chat_id)) >= settings.alerts_max_rules:
            return BotReply(
                f"الحد الأقصى {settings.alerts_max_rules} تنبيهات."
                if lang == "ar"
                else f"Max {settings.alerts_max_rules} alerts reached.",
                reply_markup=_home_keyboard(lang),
                callback_query_id=callback_query_id,
            )
        _set_session(chat_id, step="await_type")
        return BotReply(
            "اختر نوع التنبيه:" if lang == "ar" else "Choose what to watch:",
            reply_markup=_type_keyboard(lang),
            callback_query_id=callback_query_id,
        )

    home = _home(lang)
    home.callback_query_id = callback_query_id
    return home


def _continue_wizard(
    session: Session,
    chat_id: str,
    text: str,
    state: dict[str, Any],
    *,
    lang: str,
) -> BotReply:
    step = str(state.get("step") or "")
    lower = text.lower().strip()
    sub = service.get_by_telegram_chat(session, chat_id)
    if sub is not None:
        lang = sub.lang

    if step == "await_lang":
        if lower not in ("en", "ar"):
            return BotReply(
                "اختر اللغة من الأزرار / Tap a language button",
                reply_markup=_lang_keyboard(),
            )
        service.upsert_telegram_subscriber(session, chat_id, lang=lower)
        _clear_session(chat_id)
        return _home(lower)

    if step == "await_email":
        try:
            _sub, sent = service.request_digest_email(session, chat_id, text.strip())
        except service.AlreadyRegisteredError:
            return BotReply(
                "هذا البريد مسجل مسبقاً."
                if lang == "ar"
                else "That email is already registered. Use another address."
            )
        except ValueError as exc:
            return BotReply(str(exc))
        _clear_session(chat_id)
        if sent:
            return BotReply(
                "تم إرسال رسالة التأكيد."
                if lang == "ar"
                else "Confirmation email sent. Open the link to enable the daily digest."
            )
        return BotReply(
            "تعذر إرسال التأكيد. حاول لاحقاً."
            if lang == "ar"
            else "Saved email, but confirmation email failed to send. Try /digest on again later."
        )

    if step == "await_type":
        if lower not in _TARGET_TYPES:
            return BotReply(
                "اختر نوعاً من الأزرار:" if lang == "ar" else "Tap a type button:",
                reply_markup=_type_keyboard(lang),
            )
        _set_session(chat_id, step="await_id", target_type=lower)
        prompt = {
            "stock": "اختر السهم:" if lang == "ar" else "Choose a stock:",
            "gold": "اختر الذهب:" if lang == "ar" else "Choose gold:",
            "index": "اختر المؤشر:" if lang == "ar" else "Choose an index:",
            "fx": "اختر العملة:" if lang == "ar" else "Choose FX:",
        }[lower]
        return BotReply(prompt, reply_markup=_id_keyboard(lower, lang))

    if step == "await_id":
        if lower in ("__other__", "other"):
            _set_session(chat_id, step="await_id_typed")
            return BotReply(
                "اكتب الرمز (مثال COMI):" if lang == "ar" else "Type the symbol (e.g. COMI):"
            )
        tid = text.strip()
        if not tid or tid.startswith("/"):
            tt = str(state.get("target_type") or "stock")
            return BotReply(
                "اختر من الأزرار أو Other:" if lang == "ar" else "Tap a button or Other:",
                reply_markup=_id_keyboard(tt, lang),
            )
        _set_session(chat_id, step="await_kind", target_id=tid)
        return BotReply(
            "اختر شرط التنبيه:" if lang == "ar" else "Choose the condition:",
            reply_markup=_kind_keyboard(lang),
        )

    if step == "await_id_typed":
        tid = text.strip()
        if not tid or tid.startswith("/"):
            return BotReply(
                "اكتب الرمز (مثال COMI):" if lang == "ar" else "Type the symbol (e.g. COMI):"
            )
        _set_session(chat_id, step="await_kind", target_id=tid)
        return BotReply(
            "اختر شرط التنبيه:" if lang == "ar" else "Choose the condition:",
            reply_markup=_kind_keyboard(lang),
        )

    if step == "await_kind":
        if lower not in _RULE_KINDS:
            return BotReply(
                "اختر شرطاً من الأزرار:" if lang == "ar" else "Tap a condition button:",
                reply_markup=_kind_keyboard(lang),
            )
        _set_session(chat_id, step="await_threshold", rule_kind=lower)
        return BotReply(
            "اكتب الرقم الحدّي (مثال 100 أو 2.5):"
            if lang == "ar"
            else "Type the threshold number (e.g. 100 or 2.5):"
        )

    if step == "await_threshold":
        try:
            threshold = float(text.strip().replace(",", ""))
        except ValueError:
            return BotReply(
                "أرسل رقماً للحد." if lang == "ar" else "Send a number for the threshold."
            )
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
            return BotReply(str(exc))
        _clear_session(chat_id)
        if lang == "ar":
            return BotReply(
                f"تم حفظ التنبيه ({rule.id[:8]}…):\n"
                f"{rule.target_type}:{rule.target_id} {rule.rule_kind} {rule.threshold}",
                reply_markup=_home_keyboard("ar"),
            )
        return BotReply(
            f"Alert saved ({rule.id[:8]}…):\n"
            f"{rule.target_type}:{rule.target_id} {rule.rule_kind} {rule.threshold}",
            reply_markup=_home_keyboard("en"),
        )

    _clear_session(chat_id)
    return _home(lang)
