"""Alert email sender: Resend HTTPS (Render-safe) or Gmail SMTP (local/paid)."""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import structlog

from egxdesk.config import settings

log = structlog.get_logger()

# Test hook: when set, emails are appended here instead of the network.
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


def _from_addr() -> str:
    return (settings.smtp_from or settings.smtp_user or "alerts@mirsad.local").strip()


def _send_resend(*, to: str, subject: str, text: str, html: str) -> bool:
    key = settings.resend_api_key.strip()
    if not key:
        return False
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "from": _from_addr(),
                "to": [to],
                "subject": subject,
                "text": text,
                "html": html,
            },
            timeout=30.0,
        )
        if resp.status_code >= 400:
            log.warning(
                "email_send_failed",
                provider="resend",
                to=to,
                status=resp.status_code,
                error=resp.text[:300],
            )
            return False
        log.info("email_sent", provider="resend", to=to, subject=subject)
        return True
    except Exception as exc:
        log.warning("email_send_failed", provider="resend", to=to, error=str(exc))
        return False


def _send_smtp(*, to: str, subject: str, text: str, html: str) -> bool:
    user = settings.smtp_user.strip()
    # Gmail App Passwords are often pasted with spaces ("xxxx xxxx ..."); SMTP wants 16 chars.
    password = "".join(settings.smtp_password.split())
    if not user or not password:
        return False
    from_addr = _from_addr()
    host = (settings.smtp_host or "smtp.gmail.com").strip()
    port = int(settings.smtp_port or 587)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(user, password)
            smtp.sendmail(from_addr, [to], msg.as_string())
        log.info("email_sent", provider="smtp", to=to, subject=subject)
        return True
    except Exception as exc:
        log.warning("email_send_failed", provider="smtp", to=to, error=str(exc))
        return False


def send_email(*, to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email. Prefers Resend (HTTPS); falls back to SMTP."""
    payload_html = html or text
    if _outbox is not None:
        _outbox.append(
            {
                "to": to,
                "subject": subject,
                "text": text,
                "html": payload_html,
            }
        )
        return True
    if settings.resend_api_key.strip():
        return _send_resend(to=to, subject=subject, text=text, html=payload_html)
    if _send_smtp(to=to, subject=subject, text=text, html=payload_html):
        return True
    if not settings.smtp_user.strip() or not "".join(settings.smtp_password.split()):
        log.warning("smtp_not_configured")
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
