"""Telegram subscriber schema and delivery tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from egxdesk.alerts import mail, service
from egxdesk.alerts import telegram as tg
from egxdesk.alerts.db import init_db, reset_engine, session_scope
from egxdesk.alerts.models import Subscriber
from egxdesk.config import settings


@pytest.fixture()
def alerts_db_telegram(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'telegram_alerts.db'}"
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
    yield
    mail.use_outbox(False)
    tg.use_outbox(False)
    reset_engine()


def test_subscriber_telegram_without_email(alerts_db_telegram: None) -> None:
    with session_scope() as session:
        row = Subscriber(
            email=None,
            telegram_chat_id="12345",
            telegram_linked_at=datetime.now(timezone.utc),
            lang="en",
            digest_on=False,
            manage_token="m" * 32,
        )
        session.add(row)
        session.flush()
        assert row.id
        assert row.email is None
        assert row.telegram_chat_id == "12345"


def test_telegram_outbox_records_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    tg.use_outbox(True)
    tg.clear_outbox()
    assert tg.send_message(chat_id="99", text="hello") is True
    assert tg._outbox is not None
    assert tg._outbox[0]["chat_id"] == "99"
    assert tg._outbox[0]["text"] == "hello"
    tg.use_outbox(False)


def test_upsert_and_max_three_rules(alerts_db_telegram: None) -> None:
    with session_scope() as session:
        sub = service.upsert_telegram_subscriber(session, "777", lang="en")
        assert sub.telegram_chat_id == "777"
        for i in range(3):
            service.add_rule_for_chat(
                session,
                "777",
                target_type="stock",
                target_id="COMI",
                rule_kind="above",
                threshold=100 + i,
            )
        with pytest.raises(ValueError, match="max"):
            service.add_rule_for_chat(
                session,
                "777",
                target_type="stock",
                target_id="HRHO",
                rule_kind="above",
                threshold=1.0,
            )


def test_evaluate_sends_telegram_not_email(
    alerts_db_telegram: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        service,
        "resolve_quote",
        lambda tt, tid: {"price": 150.0, "previous": 100.0, "label": "COMI"},
    )
    tg.clear_outbox()
    mail.clear_outbox()
    with session_scope() as session:
        service.upsert_telegram_subscriber(session, "777", lang="en")
        service.add_rule_for_chat(
            session,
            "777",
            target_type="stock",
            target_id="COMI",
            rule_kind="above",
            threshold=120.0,
        )
        fired = service.evaluate_alerts(session)
        assert fired == 1
    assert tg._outbox is not None and tg._outbox
    assert "COMI" in tg._outbox[0]["text"]
    assert mail._outbox == []
