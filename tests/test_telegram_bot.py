"""Telegram bot conversation tests."""

from __future__ import annotations

import pytest

from egxdesk.alerts import bot, mail, service
from egxdesk.alerts import telegram as tg
from egxdesk.alerts.db import init_db, reset_engine, session_scope
from egxdesk.config import settings


@pytest.fixture()
def alerts_db_telegram(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'bot.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alerts_public_base_url", "http://test.local")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "alerts_max_rules", 3)
    reset_engine()
    init_db()
    mail.use_outbox(True)
    mail.clear_outbox()
    tg.use_outbox(True)
    tg.clear_outbox()
    bot.clear_sessions()
    yield
    mail.use_outbox(False)
    tg.use_outbox(False)
    bot.clear_sessions()
    reset_engine()


def _msg(chat_id: str, text: str) -> dict:
    return {
        "message": {
            "chat": {"id": int(chat_id) if chat_id.isdigit() else chat_id},
            "text": text,
        }
    }


def _cb(chat_id: str, data: str) -> dict:
    return {
        "callback_query": {
            "id": "cb1",
            "data": data,
            "message": {
                "chat": {"id": int(chat_id) if chat_id.isdigit() else chat_id},
                "text": "pick",
            },
        }
    }


def test_start_and_add_rule_flow_with_buttons(alerts_db_telegram: None) -> None:
    with session_scope() as session:
        r1 = bot.handle_update(session, _msg("1", "/start"))
        assert r1 is not None
        assert r1.reply_markup is not None
        r2 = bot.handle_update(session, _cb("1", "lang:en"))
        assert r2 is not None
        assert "Commands" in r2.text
        r3 = bot.handle_update(session, _msg("1", "/add"))
        assert r3 is not None
        assert r3.reply_markup is not None
        bot.handle_update(session, _cb("1", "type:stock"))
        bot.handle_update(session, _cb("1", "id:COMI"))
        bot.handle_update(session, _cb("1", "kind:above"))
        r_done = bot.handle_update(session, _msg("1", "100"))
        assert r_done is not None
        assert "Rule saved" in r_done.text
        rules = service.list_rules_for_chat(session, "1")
        assert len(rules) == 1
        assert rules[0].target_id == "COMI"


def test_arabic_language_button(alerts_db_telegram: None) -> None:
    with session_scope() as session:
        bot.handle_update(session, _msg("9", "/start"))
        reply = bot.handle_update(session, _cb("9", "lang:ar"))
        assert reply is not None
        assert "الأوامر" in reply.text
        sub = service.get_by_telegram_chat(session, "9")
        assert sub is not None
        assert sub.lang == "ar"


def test_stop_unsubscribes(alerts_db_telegram: None) -> None:
    with session_scope() as session:
        bot.handle_update(session, _msg("2", "/start"))
        bot.handle_update(session, _cb("2", "lang:en"))
        bot.handle_update(session, _msg("2", "/stop"))
        sub = service.get_by_telegram_chat(session, "2")
        assert sub is not None
        assert sub.unsubscribed_at is not None


def test_digest_on_sends_confirm(alerts_db_telegram: None) -> None:
    mail.clear_outbox()
    with session_scope() as session:
        bot.handle_update(session, _msg("3", "/start"))
        bot.handle_update(session, _cb("3", "lang:en"))
        bot.handle_update(session, _msg("3", "/digest on"))
        reply = bot.handle_update(session, _msg("3", "user@example.com"))
        assert reply is not None
        assert "confirm" in reply.text.lower() or "Confirmation" in reply.text
    assert mail._outbox
    assert "Confirm" in mail._outbox[0]["subject"]
