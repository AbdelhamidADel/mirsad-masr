"""Gmail SMTP sender and alert email templates."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from egxdesk.config import settings

log = structlog.get_logger()

# Test hook: when set, emails are appended here instead of SMTP.
_outbox: list[dict[str, str]] | None = None


def use_outbox(enabled: bool = True) -> list[dict[str, str]]:
    """Route mail to an in-memory outbox (unit tests)."""
    global _outbox
    _outbox = [] if enabled else None
    return _outbox if _outbox is not None else []


def clear_outbox() -> None:
    global _outbox
    if _outbox is not None:
        _outbox.clear()


def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email. Returns False if SMTP is not configured or send fails."""
    payload = {
        "to": to,
        "subject": subject,
        "text": text,
        "html": html or text,
    }
    if _outbox is not None:
        _outbox.append(payload)
        return True
    user = settings.smtp_user.strip()
    password = settings.smtp_password.strip()
    if not user or not password:
        log.warning("smtp_not_configured")
        return False
    from_addr = (settings.smtp_from or user).strip()
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())
        log.info("email_sent", to=to, subject=subject)
        return True
    except Exception as exc:
        log.warning("email_send_failed", to=to, error=str(exc))
        return False


def _links(manage_token: str) -> tuple[str, str]:
    base = settings.alerts_public_base_url.rstrip("/")
    manage = f"{base}/app?alerts={manage_token}"
    unsub = f"{base}/v1/alerts/unsubscribe?token={manage_token}"
    return manage, unsub


def confirm_email(lang: str, email: str, confirm_token: str) -> bool:
    base = settings.alerts_public_base_url.rstrip("/")
    link = f"{base}/v1/alerts/confirm?token={confirm_token}"
    if lang == "ar":
        subject = "تأكيد اشتراك تنبيهات مِرصاد مصر"
        text = (
            f"مرحباً،\n\nاضغط لتأكيد اشتراكك في تنبيهات مِرصاد مصر:\n{link}\n\n"
            "الرابط صالح لمدة ٢٤ ساعة.\n\nبيانات مؤشرية متأخرة — ليست نصيحة استثمارية."
        )
    else:
        subject = "Confirm your MIRSAD MASR alerts"
        text = (
            f"Hello,\n\nConfirm your MIRSAD MASR alert subscription:\n{link}\n\n"
            "This link expires in 24 hours.\n\nDelayed indicative data — not financial advice."
        )
    html = f"<p>{text.replace(chr(10), '<br>')}</p>"
    return send_email(to=email, subject=subject, text=text, html=html)


def alert_fired_email(
    lang: str,
    email: str,
    manage_token: str,
    *,
    title: str,
    detail: str,
) -> bool:
    manage, unsub = _links(manage_token)
    if lang == "ar":
        subject = f"تنبيه: {title}"
        text = (
            f"{detail}\n\nإدارة التنبيهات: {manage}\nإلغاء الاشتراك: {unsub}\n\n"
            "بيانات مؤشرية متأخرة — ليست نصيحة استثمارية."
        )
    else:
        subject = f"Alert: {title}"
        text = (
            f"{detail}\n\nManage alerts: {manage}\nUnsubscribe: {unsub}\n\n"
            "Delayed indicative data — not financial advice."
        )
    html = f"<p>{text.replace(chr(10), '<br>')}</p>"
    return send_email(to=email, subject=subject, text=text, html=html)


def digest_email(lang: str, email: str, manage_token: str, body: str) -> bool:
    manage, unsub = _links(manage_token)
    if lang == "ar":
        subject = "ملخص يومي — مِرصاد مصر"
        footer = (
            f"\n\nإدارة التنبيهات: {manage}\nإلغاء الاشتراك: {unsub}\n\n"
            "بيانات مؤشرية متأخرة — ليست نصيحة استثمارية."
        )
    else:
        subject = "Daily summary — MIRSAD MASR"
        footer = (
            f"\n\nManage alerts: {manage}\nUnsubscribe: {unsub}\n\n"
            "Delayed indicative data — not financial advice."
        )
    text = body + footer
    html = f"<pre style='font-family:sans-serif;white-space:pre-wrap'>{text}</pre>"
    return send_email(to=email, subject=subject, text=text, html=html)


# Keep a typed alias for injectability in tests.
MailSender = Callable[..., bool]
