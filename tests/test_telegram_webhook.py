"""Telegram webhook HTTP tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from egxdesk.alerts import bot, mail
from egxdesk.alerts import telegram as tg
from egxdesk.alerts.db import init_db, reset_engine
from egxdesk.config import settings
from egxdesk.main import app


@pytest.fixture()
def alerts_db_telegram(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'webhook.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alerts_public_base_url", "http://test.local")
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "good")
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


def test_webhook_rejects_bad_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_webhook_secret", "good")
    monkeypatch.setattr(settings, "alerts_enabled", True)
    client = TestClient(app)
    res = client.post(
        "/v1/telegram/webhook",
        json={},
        headers={"X-Telegram-Bot-Api-Secret-Token": "bad"},
    )
    assert res.status_code == 403


def test_webhook_start_ok(alerts_db_telegram: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegram_webhook_secret", "good")
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    tg.clear_outbox()
    client = TestClient(app)
    res = client.post(
        "/v1/telegram/webhook",
        json={"message": {"chat": {"id": 42}, "text": "/start"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "good"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert tg._outbox
