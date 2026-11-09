"""Alert subscribe / confirm / fire with SQLite + mail outbox."""

from __future__ import annotations

import pytest

from egxdesk.alerts import mail, service
from egxdesk.alerts.db import init_db, reset_engine, session_scope
from egxdesk.alerts.rules import evaluate_rule
from egxdesk.config import settings


@pytest.fixture()
def alerts_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'alerts.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "alerts_public_base_url", "http://test.local")
    reset_engine()
    init_db()
    mail.use_outbox(True)
    mail.clear_outbox()
    yield
    mail.use_outbox(False)
    reset_engine()


def test_subscribe_confirm_add_rule(alerts_db: None) -> None:
    with session_scope() as session:
        sub = service.subscribe(session, "User@Example.com", "en", digest_on=True)
        assert sub.email == "user@example.com"
        assert sub.confirmed_at is None
        token = sub.confirm_token
        manage = sub.manage_token
        assert token
        # Rules can be saved before confirm (they will not fire yet).
        rule = service.add_rule(
            session,
            manage,
            target_type="stock",
            target_id="comi",
            rule_kind="above",
            threshold=100.0,
        )
        assert rule.target_id == "COMI"
    assert mail._outbox and "Confirm" in mail._outbox[0]["subject"]

    with session_scope() as session:
        confirmed = service.confirm(session, token)
        assert confirmed is not None
        assert confirmed.confirmed_at is not None
        payload = service.manage_payload(session, manage)
        assert payload is not None
        assert len(payload["rules"]) == 1


def test_evaluate_fires_with_mocked_price(alerts_db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service,
        "resolve_quote",
        lambda tt, tid: {"price": 150.0, "previous": 100.0, "label": "COMI.CA"},
    )
    with session_scope() as session:
        sub = service.subscribe(session, "a@b.co", "en", False)
        service.confirm(session, sub.confirm_token or "")
        manage = sub.manage_token
        service.add_rule(
            session,
            manage,
            target_type="stock",
            target_id="COMI",
            rule_kind="above",
            threshold=120.0,
        )
        mail.clear_outbox()
        fired = service.evaluate_alerts(session)
        assert fired == 1
        assert mail._outbox and "Alert" in mail._outbox[0]["subject"]
        # Cooldown prevents second fire
        fired2 = service.evaluate_alerts(session)
        assert fired2 == 0


def test_unsubscribe_stops_digest(alerts_db: None) -> None:
    with session_scope() as session:
        sub = service.subscribe(session, "x@y.z", "ar", True)
        service.confirm(session, sub.confirm_token or "")
        service.unsubscribe(session, sub.manage_token)
        payload = service.manage_payload(session, sub.manage_token)
        assert payload is None


def test_session_window_weekdays() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cairo = ZoneInfo("Africa/Cairo")
    # Wednesday 12:00 Cairo
    wed = datetime(2026, 11, 11, 12, 0, tzinfo=cairo)
    assert service.in_session_window(wed) is True
    # Friday
    fri = datetime(2026, 11, 13, 12, 0, tzinfo=cairo)
    assert service.in_session_window(fri) is False


def test_rule_helper_still_pure() -> None:
    assert evaluate_rule("above", 10, 11) is True
