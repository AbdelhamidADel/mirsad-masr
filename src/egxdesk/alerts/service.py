"""Subscribe, confirm, manage rules, and evaluate ticks."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from egxdesk.alerts import mail
from egxdesk.alerts import telegram as tg
from egxdesk.alerts.models import AlertEvent, AlertRule, Subscriber
from egxdesk.alerts.prices import resolve_quote
from egxdesk.alerts.rules import cooldown_clear, evaluate_rule
from egxdesk.config import settings

log = structlog.get_logger()
_CAIRO = ZoneInfo("Africa/Cairo")
_RULE_KINDS = {"above", "below", "pct_move", "points_move"}
_TARGET_TYPES = {"stock", "gold", "index", "fx"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _token() -> str:
    return secrets.token_urlsafe(24)


class AlreadyRegisteredError(ValueError):
    """Raised when an active (non soft-deleted) email tries to subscribe again."""


def subscribe(
    session: Session, email: str, lang: str = "en", digest_on: bool = False
) -> tuple[Subscriber, bool]:
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@", 1)[-1]:
        raise ValueError("invalid email")
    lang = "ar" if lang.lower().startswith("ar") else "en"
    row = session.scalar(select(Subscriber).where(Subscriber.email == normalized))
    confirm = _token()
    expires = _utcnow() + timedelta(hours=24)
    if row is not None and row.unsubscribed_at is None:
        raise AlreadyRegisteredError("already registered")
    if row is None:
        row = Subscriber(
            email=normalized,
            lang=lang,
            digest_on=digest_on,
            confirm_token=confirm,
            confirm_expires_at=expires,
            manage_token=_token(),
            confirmed_at=None,
            unsubscribed_at=None,
        )
        session.add(row)
    else:
        # Soft-deleted row: reactivate with a fresh confirmation cycle.
        row.lang = lang
        row.digest_on = digest_on
        row.confirm_token = confirm
        row.confirm_expires_at = expires
        row.confirmed_at = None
        row.unsubscribed_at = None
        if not row.manage_token:
            row.manage_token = _token()
        for rule in row.rules:
            rule.active = False
    session.flush()
    assert row.email is not None
    sent = mail.confirm_email(row.lang, row.email, confirm)
    return row, sent


def upsert_telegram_subscriber(
    session: Session, chat_id: str, *, lang: str = "en"
) -> Subscriber:
    """Create or reactivate a Telegram-first subscriber."""
    cid = str(chat_id).strip()
    if not cid:
        raise ValueError("invalid chat_id")
    lang = "ar" if lang.lower().startswith("ar") else "en"
    row = session.scalar(select(Subscriber).where(Subscriber.telegram_chat_id == cid))
    if row is None:
        row = Subscriber(
            email=None,
            telegram_chat_id=cid,
            telegram_linked_at=_utcnow(),
            lang=lang,
            digest_on=False,
            manage_token=_token(),
            confirmed_at=None,
            unsubscribed_at=None,
        )
        session.add(row)
    else:
        row.lang = lang
        row.telegram_linked_at = row.telegram_linked_at or _utcnow()
        row.unsubscribed_at = None
        if not row.manage_token:
            row.manage_token = _token()
    session.flush()
    return row


def get_by_telegram_chat(session: Session, chat_id: str) -> Subscriber | None:
    return session.scalar(
        select(Subscriber).where(Subscriber.telegram_chat_id == str(chat_id).strip())
    )


def stop_telegram(session: Session, chat_id: str) -> Subscriber | None:
    row = get_by_telegram_chat(session, chat_id)
    if row is None:
        return None
    if row.unsubscribed_at is not None:
        return row
    _soft_unsubscribe(row)
    session.flush()
    return row


def list_rules_for_chat(session: Session, chat_id: str) -> list[AlertRule]:
    row = get_by_telegram_chat(session, chat_id)
    if row is None or row.unsubscribed_at is not None:
        return []
    return [r for r in row.rules if r.active]


def _active_rule_count(session: Session, row: Subscriber) -> int:
    count = session.scalar(
        select(func.count())
        .select_from(AlertRule)
        .where(AlertRule.subscriber_id == row.id, AlertRule.active.is_(True))
    )
    return int(count or 0)


def _build_rule(
    session: Session,
    row: Subscriber,
    *,
    target_type: str,
    target_id: str,
    rule_kind: str,
    threshold: float,
    cooldown_hours: float | None = None,
) -> AlertRule:
    if _active_rule_count(session, row) >= settings.alerts_max_rules:
        raise ValueError("max rules reached")
    tt = target_type.strip().lower()
    rk = rule_kind.strip().lower()
    if tt not in _TARGET_TYPES:
        raise ValueError("invalid target_type")
    if rk not in _RULE_KINDS:
        raise ValueError("invalid rule_kind")
    return AlertRule(
        subscriber_id=row.id,
        target_type=tt,
        target_id=target_id.strip().upper() if tt == "stock" else target_id.strip(),
        rule_kind=rk,
        threshold=float(threshold),
        cooldown_hours=float(
            cooldown_hours
            if cooldown_hours is not None
            else settings.alerts_cooldown_hours_default
        ),
        active=True,
    )


def add_rule_for_chat(
    session: Session,
    chat_id: str,
    *,
    target_type: str,
    target_id: str,
    rule_kind: str,
    threshold: float,
    cooldown_hours: float | None = None,
) -> AlertRule:
    row = get_by_telegram_chat(session, chat_id)
    if row is None or row.unsubscribed_at is not None:
        raise ValueError("subscriber not found")
    rule = _build_rule(
        session,
        row,
        target_type=target_type,
        target_id=target_id,
        rule_kind=rule_kind,
        threshold=threshold,
        cooldown_hours=cooldown_hours,
    )
    session.add(rule)
    session.flush()
    return rule


def delete_rule_for_chat(session: Session, chat_id: str, rule_id: str) -> bool:
    row = get_by_telegram_chat(session, chat_id)
    if row is None:
        return False
    rule = session.get(AlertRule, rule_id)
    if rule is None or rule.subscriber_id != row.id:
        return False
    session.delete(rule)
    session.flush()
    return True


def request_digest_email(
    session: Session, chat_id: str, email: str
) -> tuple[Subscriber, bool]:
    """Opt Telegram subscriber into daily email digest (requires confirm)."""
    row = get_by_telegram_chat(session, chat_id)
    if row is None or row.unsubscribed_at is not None:
        raise ValueError("subscriber not found")
    normalized = email.strip().lower()
    if "@" not in normalized or "." not in normalized.split("@", 1)[-1]:
        raise ValueError("invalid email")
    other = session.scalar(select(Subscriber).where(Subscriber.email == normalized))
    if other is not None and other.id != row.id and other.unsubscribed_at is None:
        raise AlreadyRegisteredError("email already registered")
    confirm = _token()
    row.email = normalized
    row.digest_on = True
    row.confirm_token = confirm
    row.confirm_expires_at = _utcnow() + timedelta(hours=24)
    row.confirmed_at = None
    session.flush()
    sent = mail.confirm_email(row.lang, normalized, confirm)
    return row, sent


def resend_confirm(session: Session, token: str) -> tuple[Subscriber | None, bool]:
    """Issue a fresh confirm token and email it. Returns (subscriber, email_sent)."""
    row = get_by_manage_token(session, token)
    if row is None or row.unsubscribed_at is not None:
        return None, False
    if row.confirmed_at is not None:
        return row, False
    if not row.email:
        return row, False
    confirm = _token()
    row.confirm_token = confirm
    row.confirm_expires_at = _utcnow() + timedelta(hours=24)
    session.flush()
    sent = mail.confirm_email(row.lang, row.email, confirm)
    return row, sent


def confirm(session: Session, token: str) -> Subscriber | None:
    row = session.scalar(select(Subscriber).where(Subscriber.confirm_token == token))
    if row is None:
        return None
    if row.confirm_expires_at and row.confirm_expires_at.replace(tzinfo=UTC) < _utcnow():
        return None
    row.confirmed_at = _utcnow()
    row.confirm_token = None
    row.confirm_expires_at = None
    row.unsubscribed_at = None
    session.flush()
    return row


def get_by_manage_token(session: Session, token: str) -> Subscriber | None:
    return session.scalar(select(Subscriber).where(Subscriber.manage_token == token))


def _soft_unsubscribe(row: Subscriber) -> Subscriber:
    """Mark subscriber inactive without deleting the Neon/Postgres row."""
    row.unsubscribed_at = _utcnow()
    row.digest_on = False
    row.confirm_token = None
    row.confirm_expires_at = None
    for rule in row.rules:
        rule.active = False
    return row


def unsubscribe(session: Session, token: str) -> Subscriber | None:
    row = get_by_manage_token(session, token)
    if row is None:
        return None
    if row.unsubscribed_at is not None:
        return row
    _soft_unsubscribe(row)
    session.flush()
    return row


def unsubscribe_by_email(session: Session, email: str) -> Subscriber | None:
    """Soft-delete by email (alerts tab). Missing / already inactive → None."""
    normalized = email.strip().lower()
    row = session.scalar(select(Subscriber).where(Subscriber.email == normalized))
    if row is None or row.unsubscribed_at is not None:
        return None
    _soft_unsubscribe(row)
    session.flush()
    return row


def manage_payload(session: Session, token: str) -> dict[str, Any] | None:
    row = get_by_manage_token(session, token)
    if row is None or row.unsubscribed_at is not None:
        return None
    return {
        "email": row.email,
        "lang": row.lang,
        "digest_on": row.digest_on,
        "confirmed": row.confirmed_at is not None,
        "manage_token": row.manage_token,
        "rules": [
            {
                "id": rule.id,
                "target_type": rule.target_type,
                "target_id": rule.target_id,
                "rule_kind": rule.rule_kind,
                "threshold": rule.threshold,
                "cooldown_hours": rule.cooldown_hours,
                "active": rule.active,
                "last_fired_at": rule.last_fired_at.isoformat() if rule.last_fired_at else None,
            }
            for rule in row.rules
        ],
    }


def set_digest(session: Session, token: str, digest_on: bool) -> Subscriber | None:
    row = get_by_manage_token(session, token)
    if row is None or row.unsubscribed_at is not None:
        return None
    row.digest_on = bool(digest_on)
    session.flush()
    return row


def add_rule(
    session: Session,
    token: str,
    *,
    target_type: str,
    target_id: str,
    rule_kind: str,
    threshold: float,
    cooldown_hours: float | None = None,
) -> AlertRule:
    row = get_by_manage_token(session, token)
    if row is None or row.unsubscribed_at is not None:
        raise ValueError("subscriber not found")
    # Rules may be added before confirm; evaluate_alerts still skips unconfirmed.
    rule = _build_rule(
        session,
        row,
        target_type=target_type,
        target_id=target_id,
        rule_kind=rule_kind,
        threshold=threshold,
        cooldown_hours=cooldown_hours,
    )
    session.add(rule)
    session.flush()
    return rule


def delete_rule(session: Session, token: str, rule_id: str) -> bool:
    row = get_by_manage_token(session, token)
    if row is None:
        return False
    rule = session.get(AlertRule, rule_id)
    if rule is None or rule.subscriber_id != row.id:
        return False
    session.delete(rule)
    session.flush()
    return True


def _telegram_active(session: Session) -> list[Subscriber]:
    rows = session.scalars(select(Subscriber)).all()
    return [r for r in rows if r.telegram_chat_id and r.unsubscribed_at is None]


def _email_alert_active(session: Session) -> list[Subscriber]:
    """Legacy email-only instant alerts (no telegram_chat_id)."""
    rows = session.scalars(select(Subscriber)).all()
    return [
        r
        for r in rows
        if not r.telegram_chat_id
        and r.email
        and r.confirmed_at is not None
        and r.unsubscribed_at is None
    ]


def _digest_active(session: Session) -> list[Subscriber]:
    rows = session.scalars(select(Subscriber)).all()
    return [
        r
        for r in rows
        if r.digest_on
        and r.email
        and r.confirmed_at is not None
        and r.unsubscribed_at is None
    ]


def _rule_detail(lang: str, label: str, price: Any, previous: Any, rule: AlertRule) -> str:
    if lang == "ar":
        return (
            f"{label}: السعر {price} "
            f"(السابق {previous}) — القاعدة {rule.rule_kind} @ {rule.threshold}"
        )
    return (
        f"{label}: price {price} (prev {previous}) — "
        f"rule {rule.rule_kind} @ {rule.threshold}"
    )


def _collect_hits(
    sub: Subscriber,
) -> list[tuple[AlertRule, float | None, float | None, str]]:
    hits: list[tuple[AlertRule, float | None, float | None, str]] = []
    for rule in list(sub.rules):
        if not rule.active:
            continue
        if not cooldown_clear(rule.last_fired_at, rule.cooldown_hours):
            continue
        quote = resolve_quote(rule.target_type, rule.target_id)
        price = quote.get("price")
        previous = quote.get("previous")
        if not evaluate_rule(rule.rule_kind, rule.threshold, price, previous):
            continue
        label = str(quote.get("label") or rule.target_id)
        detail = _rule_detail(sub.lang, label, price, previous, rule)
        hits.append(
            (
                rule,
                float(price) if price is not None else None,
                float(previous) if previous is not None else None,
                detail,
            )
        )
    return hits


def evaluate_alerts(session: Session) -> int:
    """Evaluate active rules; Telegram for chat users, email for legacy-only."""
    fired = 0
    for sub in _telegram_active(session):
        hits = _collect_hits(sub)
        if not hits:
            continue
        assert sub.telegram_chat_id is not None
        header = "تنبيه مرصاد مصر" if sub.lang == "ar" else "MIRSAD MASR alert"
        body = header + "\n" + "\n".join(detail for _r, _p, _prev, detail in hits)
        ok = tg.send_message(chat_id=sub.telegram_chat_id, text=body)
        if not ok:
            continue
        now = _utcnow()
        for rule, price, previous, detail in hits:
            rule.last_fired_at = now
            session.add(
                AlertEvent(
                    rule_id=rule.id,
                    price=price,
                    previous=previous,
                    payload=detail,
                )
            )
            fired += 1

    for sub in _email_alert_active(session):
        hits = _collect_hits(sub)
        assert sub.email is not None
        for rule, price, previous, detail in hits:
            label = detail.split(":", 1)[0].strip()
            ok = mail.alert_fired_email(
                sub.lang, sub.email, sub.manage_token, title=label, detail=detail
            )
            if not ok:
                continue
            rule.last_fired_at = _utcnow()
            session.add(
                AlertEvent(
                    rule_id=rule.id,
                    price=price,
                    previous=previous,
                    payload=detail,
                )
            )
            fired += 1
    session.flush()
    return fired


def send_digests(session: Session) -> int:
    """Send daily digests to confirmed digest subscribers. Returns send count."""
    sent = 0
    for sub in _digest_active(session):
        assert sub.email is not None
        lines: list[str] = []
        targets = [(r.target_type, r.target_id) for r in sub.rules if r.active]
        if not targets:
            targets = [
                ("index", "CASE30"),
                ("gold", "gold_21k"),
                ("fx", "usd_egp"),
            ]
        seen: set[tuple[str, str]] = set()
        for tt, tid in targets:
            key = (tt, tid)
            if key in seen:
                continue
            seen.add(key)
            quote = resolve_quote(tt, tid)
            label = quote.get("label") or tid
            price = quote.get("price")
            lines.append(f"{label}: {price if price is not None else 'n/a'}")
        if sub.lang == "ar":
            body = "ملخص اليوم\n" + "\n".join(lines)
        else:
            body = "Today's summary\n" + "\n".join(lines)
        if mail.digest_email(sub.lang, sub.email, sub.manage_token, body):
            sent += 1
    return sent


def in_session_window(now: datetime | None = None) -> bool:
    """Sun–Thu Cairo ~09:45–15:15 (buffer around EGX hours).

    Egypt weekend is Friday–Saturday (weekday 4 and 5).
    """
    current = now.astimezone(_CAIRO) if now else datetime.now(_CAIRO)
    if current.weekday() in (4, 5):
        return False
    minutes = current.hour * 60 + current.minute
    return (9 * 60 + 45) <= minutes <= (15 * 60 + 15)


def digest_due(now: datetime | None = None, *, last_digest_date: str | None = None) -> bool:
    """True at/after 16:30 Cairo if we have not already sent today."""
    current = now.astimezone(_CAIRO) if now else datetime.now(_CAIRO)
    stamp = current.strftime("%Y-%m-%d")
    if last_digest_date == stamp:
        return False
    return (current.hour, current.minute) >= (16, 30)


def run_tick(
    session: Session,
    *,
    force_digest: bool = False,
    force_alerts: bool = False,
    last_digest_date: str | None = None,
) -> dict[str, Any]:
    alerts = 0
    digests = 0
    now = datetime.now(_CAIRO)
    if force_alerts or in_session_window(now):
        alerts = evaluate_alerts(session)
    due = force_digest or digest_due(now, last_digest_date=last_digest_date)
    new_digest_date = last_digest_date
    if due:
        digests = send_digests(session)
        new_digest_date = now.strftime("%Y-%m-%d")
    return {
        "alerts_fired": alerts,
        "digests_sent": digests,
        "digest_date": new_digest_date,
        "cairo": now.strftime("%Y-%m-%d %H:%M"),
    }
