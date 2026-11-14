"""Telegram subscriber schema and delivery tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    reset_engine()
    init_db()
    yield
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
