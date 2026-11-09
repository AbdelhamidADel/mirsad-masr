"""Alert subscribe / confirm / fire with SQLite + mail outbox."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from egxdesk.alerts import mail, service
from egxdesk.alerts.db import init_db, reset_engine, session_scope
from egxdesk.alerts.models import Subscriber
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
        sub, sent = service.subscribe(session, "User@Example.com", "en", digest_on=True)
        assert sent is True
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
        sub, _sent = service.subscribe(session, "a@b.co", "en", False)
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
        sub, _sent = service.subscribe(session, "x@y.z", "ar", True)
        service.confirm(session, sub.confirm_token or "")
        service.unsubscribe(session, sub.manage_token)
        payload = service.manage_payload(session, sub.manage_token)
        assert payload is None
        # Soft delete: row remains in DB with unsubscribed_at set.
        row = session.scalar(select(Subscriber).where(Subscriber.email == "x@y.z"))
        assert row is not None
        assert row.unsubscribed_at is not None


def test_already_registered_rejects_active_email(alerts_db: None) -> None:
    with session_scope() as session:
        service.subscribe(session, "dup@ex.com", "en", False)
    with session_scope() as session, pytest.raises(service.AlreadyRegisteredError):
        service.subscribe(session, "dup@ex.com", "en", False)


def test_soft_deleted_can_resubscribe(alerts_db: None) -> None:
    with session_scope() as session:
        sub, _sent = service.subscribe(session, "back@ex.com", "en", True)
        service.confirm(session, sub.confirm_token or "")
        manage = sub.manage_token
        service.unsubscribe(session, manage)
    with session_scope() as session:
        again, sent = service.subscribe(session, "back@ex.com", "ar", False)
        assert sent is True
        assert again.unsubscribed_at is None
        assert again.confirmed_at is None
        assert again.confirm_token
    with session_scope() as session:
        gone = service.unsubscribe_by_email(session, "missing@ex.com")
        assert gone is None


def test_resend_confirm(alerts_db: None) -> None:
    with session_scope() as session:
        sub, _sent = service.subscribe(session, "again@ex.com", "en", False)
        manage = sub.manage_token
        mail.clear_outbox()
        row, sent = service.resend_confirm(session, manage)
        assert row is not None and sent is True
        assert mail._outbox and "Confirm" in mail._outbox[0]["subject"]


def test_send_email_uses_resend_when_configured(
    alerts_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    mail.use_outbox(False)
    monkeypatch.setattr(settings, "resend_api_key", "re_test")
    monkeypatch.setattr(settings, "smtp_from", "alerts@example.com")

    class _Resp:
        status_code = 200
        text = "{}"

    called: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> _Resp:
        called["url"] = url
        called["json"] = kwargs.get("json")
        return _Resp()

    monkeypatch.setattr(mail.httpx, "post", fake_post)
    assert mail.send_email(to="a@b.co", subject="Hi", text="body") is True
    assert called["url"] == "https://api.resend.com/emails"
    assert called["json"]["to"] == ["a@b.co"]
    mail.use_outbox(True)


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
