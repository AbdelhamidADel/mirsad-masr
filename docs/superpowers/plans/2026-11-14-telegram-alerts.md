# Telegram-First Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Telegram-first threshold alerts (max 3 rules/chat) with optional confirmed email digest, inside the existing egx-desk alerts stack on Render.

**Architecture:** Extend `Subscriber` with `telegram_chat_id`; add a Bot API client + conversation handler + webhook. Change `evaluate_alerts` to send Telegram (not email) for Telegram-active subscribers; keep digests on email only when confirmed. Reuse existing rule engine, prices, tick, and cron wake.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, httpx (Telegram Bot API), existing Resend/SMTP mailer, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-telegram-alerts-design.md`

## Global Constraints

- Secrets only in env (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `DATABASE_URL`, `ALERTS_*`, Resend/SMTP) — never commit
- `ALERTS_ENABLED=false` by default; webhook may reply “alerts offline”
- Instant delivery = Telegram; email = digest only after confirm
- Max **3** active rules per Telegram subscriber; default cooldown **6h**
- Set `last_fired_at` only after successful Telegram send
- Combine multiple fires for one chat into one message per tick when possible
- No second `mirsad-market-monitor` service; no web push in this plan
- Language `en` | `ar` chosen in bot
- Digest time remains **16:30 Africa/Cairo**

---

## File map

| File | Role |
|---|---|
| `src/egxdesk/config.py` | `telegram_bot_token`, `telegram_webhook_secret`, `alerts_max_rules` |
| `src/egxdesk/alerts/models.py` | Nullable `email`; add `telegram_chat_id`, `telegram_linked_at` |
| `src/egxdesk/alerts/telegram.py` | `send_message(chat_id, text) -> bool` + outbox for tests |
| `src/egxdesk/alerts/bot.py` | Parse Update → reply text; wizard state (in-process TTL) |
| `src/egxdesk/alerts/service.py` | Telegram upsert, rule caps, Telegram evaluate path, digest gates |
| `src/egxdesk/alerts/telegram_router.py` | `POST /v1/telegram/webhook` |
| `src/egxdesk/main.py` | Mount telegram router |
| `.env.example` / `render.yaml` | Document new secrets |
| `tests/test_telegram_bot.py` | Conversation state machine |
| `tests/test_telegram_alerts_service.py` | Upsert, cap, evaluate → Telegram outbox |
| `tests/test_alerts_service.py` | Adjust for nullable email / digest-only email path |

---

### Task 1: Schema + config for Telegram subscribers

**Files:**
- Modify: `src/egxdesk/config.py`
- Modify: `src/egxdesk/alerts/models.py`
- Modify: `.env.example`
- Modify: `render.yaml`
- Test: `tests/test_telegram_alerts_service.py` (create file; schema smoke)

**Interfaces:**
- Consumes: existing `Subscriber`, `settings`
- Produces: `settings.telegram_bot_token: str`, `settings.telegram_webhook_secret: str`, `settings.alerts_max_rules: int = 3`; `Subscriber.telegram_chat_id: str | None`, `Subscriber.telegram_linked_at: datetime | None`; `Subscriber.email` nullable

- [ ] **Step 1: Write failing schema test**

```python
# tests/test_telegram_alerts_service.py
from datetime import datetime, timezone

from egxdesk.alerts.db import init_db, reset_engine, session_scope
from egxdesk.alerts.models import Subscriber
from egxdesk.config import settings


def test_subscriber_telegram_without_email(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 't.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    reset_engine()
    init_db()
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
```

- [ ] **Step 2: Run test — expect fail (missing columns / NOT NULL email)**

Run: `pytest tests/test_telegram_alerts_service.py::test_subscriber_telegram_without_email -v`  
Expected: FAIL (AttributeError or IntegrityError on email)

- [ ] **Step 3: Update model + config**

In `models.py` `Subscriber`:
- `email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True, nullable=True)`
- `telegram_chat_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)`
- `telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)`

In `config.py` add:
```python
telegram_bot_token: str = ""
telegram_webhook_secret: str = ""
alerts_max_rules: int = 3
```

Document in `.env.example` and `render.yaml` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` as `sync: false`).

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/test_telegram_alerts_service.py::test_subscriber_telegram_without_email -v`  
Expected: PASS

- [ ] **Step 5: Fix any broken email-only tests that assume non-null email at construction; keep email subscribe path working with a real email string**

Run: `pytest tests/test_alerts_service.py tests/test_telegram_alerts_service.py -v`  
Expected: PASS (adjust constructs only if needed)

- [ ] **Step 6: Commit**

```bash
git add src/egxdesk/config.py src/egxdesk/alerts/models.py .env.example render.yaml tests/test_telegram_alerts_service.py
git commit -m "feat(alerts): allow Telegram subscribers with nullable email"
```

---

### Task 2: Telegram client with test outbox

**Files:**
- Create: `src/egxdesk/alerts/telegram.py`
- Modify: `tests/test_telegram_alerts_service.py`

**Interfaces:**
- Consumes: `settings.telegram_bot_token`, `httpx`
- Produces:
  - `use_outbox(enabled: bool = True) -> list[dict[str, str]]`
  - `clear_outbox() -> None`
  - `send_message(*, chat_id: str, text: str, parse_mode: str | None = None) -> bool`

- [ ] **Step 1: Write failing test**

```python
from egxdesk.alerts import telegram as tg

def test_telegram_outbox_records_send(monkeypatch):
    monkeypatch.setattr(settings, "telegram_bot_token", "test-token")
    tg.use_outbox(True)
    tg.clear_outbox()
    assert tg.send_message(chat_id="99", text="hello") is True
    assert tg._outbox[0]["chat_id"] == "99"
    assert tg._outbox[0]["text"] == "hello"
    tg.use_outbox(False)
```

- [ ] **Step 2: Run — expect fail (module missing)**

Run: `pytest tests/test_telegram_alerts_service.py::test_telegram_outbox_records_send -v`  
Expected: FAIL ImportError

- [ ] **Step 3: Implement `telegram.py`**

```python
"""Telegram Bot API send helper with optional outbox for tests."""

from __future__ import annotations

import structlog
import httpx

from egxdesk.config import settings

log = structlog.get_logger()
_outbox: list[dict[str, str]] | None = None


def use_outbox(enabled: bool = True) -> list[dict[str, str]]:
    global _outbox
    _outbox = [] if enabled else None
    return _outbox if _outbox is not None else []


def clear_outbox() -> None:
    if _outbox is not None:
        _outbox.clear()


def send_message(*, chat_id: str, text: str, parse_mode: str | None = None) -> bool:
    if _outbox is not None:
        _outbox.append({"chat_id": str(chat_id), "text": text})
        return True
    token = settings.telegram_bot_token.strip()
    if not token:
        log.warning("telegram_send_skipped_no_token")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, object] = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        with httpx.Client(timeout=20.0) as client:
            res = client.post(url, json=payload)
        if res.status_code == 429:
            log.warning("telegram_rate_limited", chat_id=str(chat_id))
            return False
        data = res.json()
        if not data.get("ok"):
            desc = str(data.get("description") or "")
            if "blocked" in desc.lower() or "deactivated" in desc.lower():
                log.info("telegram_chat_blocked", chat_id=str(chat_id))
            log.warning("telegram_send_failed", status=res.status_code, body=desc[:200])
            return False
        return True
    except Exception as exc:
        log.warning("telegram_send_error", error=str(exc))
        return False
```

- [ ] **Step 4: Run test — expect pass**

Run: `pytest tests/test_telegram_alerts_service.py::test_telegram_outbox_records_send -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/egxdesk/alerts/telegram.py tests/test_telegram_alerts_service.py
git commit -m "feat(alerts): add Telegram sendMessage client with test outbox"
```

---

### Task 3: Service — Telegram upsert, rule cap, evaluate via Telegram

**Files:**
- Modify: `src/egxdesk/alerts/service.py`
- Modify: `tests/test_telegram_alerts_service.py`
- Modify: `tests/test_alerts_service.py` (email path still fires email for email-only confirmed subs **or** document that email-only instant alerts are deprecated — **MVP: Telegram-active → Telegram; email-only confirmed without telegram_chat_id → keep existing email alert behavior for backward compatibility**)

**Interfaces:**
- Consumes: `telegram.send_message`, `settings.alerts_max_rules`, models
- Produces:
  - `upsert_telegram_subscriber(session, chat_id: str, *, lang: str = "en") -> Subscriber`
  - `stop_telegram(session, chat_id: str) -> Subscriber | None`
  - `add_rule_for_chat(session, chat_id: str, **rule_fields) -> AlertRule` (raises `ValueError` if cap exceeded)
  - `list_rules_for_chat(session, chat_id: str) -> list[AlertRule]`
  - `delete_rule_for_chat(session, chat_id: str, rule_id: str) -> bool`
  - `request_digest_email(session, chat_id: str, email: str) -> tuple[Subscriber, bool]`
  - `telegram_active_subscribers(session) -> list[Subscriber]`
  - `evaluate_alerts` sends Telegram for telegram-active; email only for confirmed email-only (no telegram_chat_id)
  - `send_digests` requires email + confirmed + digest_on (unchanged gate, but must not require telegram)

- [ ] **Step 1: Write failing tests**

```python
def test_upsert_and_max_three_rules(alerts_db_telegram):
    with session_scope() as session:
        sub = service.upsert_telegram_subscriber(session, "777", lang="en")
        assert sub.telegram_chat_id == "777"
        for i in range(3):
            service.add_rule_for_chat(
                session, "777",
                target_type="stock", target_id="COMI",
                rule_kind="above", threshold=100 + i,
            )
        with pytest.raises(ValueError, match="max"):
            service.add_rule_for_chat(
                session, "777",
                target_type="stock", target_id="HRHO",
                rule_kind="above", threshold=1.0,
            )


def test_evaluate_sends_telegram_not_email(alerts_db_telegram, monkeypatch):
    monkeypatch.setattr(
        service, "resolve_quote",
        lambda tt, tid: {"price": 150.0, "previous": 100.0, "label": "COMI"},
    )
    from egxdesk.alerts import telegram as tg
    tg.use_outbox(True)
    tg.clear_outbox()
    with session_scope() as session:
        service.upsert_telegram_subscriber(session, "777", lang="en")
        service.add_rule_for_chat(
            session, "777",
            target_type="stock", target_id="COMI",
            rule_kind="above", threshold=120.0,
        )
        fired = service.evaluate_alerts(session)
        assert fired == 1
    assert tg._outbox and "COMI" in tg._outbox[0]["text"]
    assert mail._outbox == []
```

Fixture `alerts_db_telegram`: same as `alerts_db` plus `telegram.use_outbox(True)`.

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_telegram_alerts_service.py -k "upsert or evaluate_sends" -v`  
Expected: FAIL (functions missing)

- [ ] **Step 3: Implement service helpers + change evaluate**

Key logic for `evaluate_alerts`:

```python
def _telegram_active(session: Session) -> list[Subscriber]:
    rows = session.scalars(select(Subscriber)).all()
    return [
        r for r in rows
        if r.telegram_chat_id and r.unsubscribed_at is None
    ]


def _email_alert_active(session: Session) -> list[Subscriber]:
    """Legacy email-only instant alerts (no telegram_chat_id)."""
    rows = session.scalars(select(Subscriber)).all()
    return [
        r for r in rows
        if not r.telegram_chat_id
        and r.email
        and r.confirmed_at is not None
        and r.unsubscribed_at is None
    ]
```

- For each telegram-active sub: collect fired rule details; `send_message` once with combined text; on success set `last_fired_at` + `AlertEvent` for each; if send fails, skip `last_fired_at`.
- Detect blocked: if send fails and caller/telegram layer logged blocked, `stop_telegram` / set `unsubscribed_at` (optional helper `mark_telegram_blocked(session, chat_id)`).
- Email-only path: keep existing `alert_fired_email` behavior.
- `add_rule_for_chat`: count `active` rules; if `>= settings.alerts_max_rules`, raise `ValueError("max rules reached")`.
- `request_digest_email`: set email, `digest_on=True`, new confirm token, send `confirm_email`; do not require prior email confirm for Telegram alerts.

- [ ] **Step 4: Run telegram + existing alert tests**

Run: `pytest tests/test_telegram_alerts_service.py tests/test_alerts_service.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/egxdesk/alerts/service.py tests/test_telegram_alerts_service.py tests/test_alerts_service.py
git commit -m "feat(alerts): Telegram upsert, rule cap, and Telegram delivery on tick"
```

---

### Task 4: Bot conversation handler (TDD)

**Files:**
- Create: `src/egxdesk/alerts/bot.py`
- Create: `tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `service.*`, session_scope/init patterns via injected session factory in tests
- Produces: `handle_update(session, update: dict) -> str | None`  # reply text; None = no reply
- In-process `_sessions: dict[str, dict]` with TTL 15 minutes; keys = chat_id string
- Commands: `/start`, `/add`, `/rules`, `/delete`, `/stop`, `/digest`, help

- [ ] **Step 1: Write failing tests**

```python
def test_start_and_add_rule_flow(alerts_db_telegram):
    from egxdesk.alerts import bot
    bot.clear_sessions()
    with session_scope() as session:
        r1 = bot.handle_update(session, _msg("1", "/start"))
        assert r1 and "language" in r1.lower() or "en" in r1.lower()
        r2 = bot.handle_update(session, _msg("1", "en"))
        assert r2
        r3 = bot.handle_update(session, _msg("1", "/add"))
        assert r3
        bot.handle_update(session, _msg("1", "stock"))
        bot.handle_update(session, _msg("1", "COMI"))
        bot.handle_update(session, _msg("1", "above"))
        r_done = bot.handle_update(session, _msg("1", "100"))
        assert r_done and "rule" in r_done.lower()
        rules = service.list_rules_for_chat(session, "1")
        assert len(rules) == 1
        assert rules[0].target_id == "COMI"


def _msg(chat_id: str, text: str) -> dict:
    return {
        "message": {
            "chat": {"id": int(chat_id) if chat_id.isdigit() else chat_id},
            "text": text,
        }
    }
```

Cover: `/stop` sets unsubscribed; `/digest on` then email triggers confirm mail outbox; max 3 error message.

- [ ] **Step 2: Run — expect fail**

Run: `pytest tests/test_telegram_bot.py -v`  
Expected: FAIL ImportError / missing handle_update

- [ ] **Step 3: Implement `bot.py`**

Wizard states for `/add`: `await_type` → `await_id` → `await_kind` → `await_threshold`.  
`/start` → `await_lang` if new or always offer lang.  
`/digest on` → `await_email`.  
Normalize stock ids to upper case via `add_rule_for_chat`.  
EN/AR reply strings (minimal set).  
If `not settings.alerts_enabled`: return short “alerts offline”.

- [ ] **Step 4: Run — expect pass**

Run: `pytest tests/test_telegram_bot.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/egxdesk/alerts/bot.py tests/test_telegram_bot.py
git commit -m "feat(alerts): Telegram bot conversation for rules and digest opt-in"
```

---

### Task 5: Webhook router + mount

**Files:**
- Create: `src/egxdesk/alerts/telegram_router.py`
- Modify: `src/egxdesk/main.py` (include router)
- Test: `tests/test_telegram_webhook.py`

**Interfaces:**
- Consumes: `bot.handle_update`, `telegram.send_message`, `session_scope`, `settings.telegram_webhook_secret`
- Produces: FastAPI `APIRouter` prefix `/v1/telegram`
  - `POST /v1/telegram/webhook?secret=` **or** header `X-Telegram-Bot-Api-Secret-Token` matching `TELEGRAM_WEBHOOK_SECRET`
  - Always return `{"ok": true}` after handling when secret valid (HTTP 200)
  - HTTP 403 when secret invalid
  - On valid update: `handle_update` → if reply text, `send_message`

- [ ] **Step 1: Write failing TestClient test**

```python
from fastapi.testclient import TestClient
from egxdesk.main import app

def test_webhook_rejects_bad_secret(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "good")
    monkeypatch.setattr(settings, "alerts_enabled", True)
    client = TestClient(app)
    res = client.post("/v1/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "bad"})
    assert res.status_code == 403


def test_webhook_start_ok(alerts_db_telegram, monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "good")
    monkeypatch.setattr(settings, "alerts_enabled", True)
    monkeypatch.setattr(settings, "telegram_bot_token", "t")
    from egxdesk.alerts import telegram as tg
    tg.use_outbox(True)
    tg.clear_outbox()
    client = TestClient(app)
    res = client.post(
        "/v1/telegram/webhook",
        json={"message": {"chat": {"id": 42}, "text": "/start"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "good"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert tg._outbox  # bot replied
```

- [ ] **Step 2: Run — expect fail (404)**

Run: `pytest tests/test_telegram_webhook.py -v`  
Expected: FAIL 404

- [ ] **Step 3: Implement router + `app.include_router`**

```python
# telegram_router.py sketch
router = APIRouter(prefix="/v1/telegram", tags=["telegram"])

@router.post("/webhook")
async def telegram_webhook(request: Request, secret: str | None = None):
    expected = settings.telegram_webhook_secret.strip()
    header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not expected or (header != expected and secret != expected):
        raise HTTPException(403, "forbidden")
    update = await request.json()
    if not settings.alerts_enabled or not settings.database_url.strip():
        return {"ok": True, "disabled": True}
    init_db()
    with session_scope() as session:
        reply = bot.handle_update(session, update)
    if reply:
        msg = update.get("message") or update.get("edited_message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if chat is not None:
            telegram.send_message(chat_id=str(chat), text=reply)
    return {"ok": True}
```

- [ ] **Step 4: Run webhook + full alerts tests**

Run: `pytest tests/test_telegram_webhook.py tests/test_telegram_bot.py tests/test_telegram_alerts_service.py tests/test_alerts_service.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/egxdesk/alerts/telegram_router.py src/egxdesk/main.py tests/test_telegram_webhook.py
git commit -m "feat(alerts): expose Telegram webhook under /v1/telegram/webhook"
```

---

### Task 6: Ops docs + production wiring checklist

**Files:**
- Modify: `docs/self-hosting.md` (short Telegram section) **or** `README.md` alerts blurb — only if repo already documents alerts; prefer `.env.example` + `docs/superpowers/specs/2026-11-14-telegram-alerts-design.md` already done
- Modify: `.env.example`, `render.yaml` (if not fully done in Task 1)

- [ ] **Step 1: Document required Render steps in `.env.example` comments**

```bash
# Telegram alerts (instant). Set webhook after deploy:
# curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
#   -d "url=$ALERTS_PUBLIC_BASE_URL/v1/telegram/webhook" \
#   -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
```

- [ ] **Step 2: Manual verification checklist (run locally, do not commit secrets)**

1. `ALERTS_ENABLED=true` + SQLite/Postgres + dummy token with outbox in unit tests (already automated)
2. With real bot (optional): setWebhook to a tunnel URL; `/start` → `/add` → force `POST /v1/alerts/tick?force_alerts=1` with secret
3. Confirm digest: `/digest on` → email → open confirm link → force digest tick

- [ ] **Step 3: Run full related suite + ruff on touched modules**

Run:
```bash
pytest tests/test_alert_rules.py tests/test_alerts_service.py tests/test_telegram_alerts_service.py tests/test_telegram_bot.py tests/test_telegram_webhook.py -v
ruff check src/egxdesk/alerts src/egxdesk/config.py src/egxdesk/main.py
```
Expected: all PASS / clean

- [ ] **Step 4: Commit**

```bash
git add .env.example render.yaml docs/self-hosting.md
git commit -m "docs: wire Telegram alert env and webhook setup notes"
```

---

## Spec coverage checklist

| Spec requirement | Task |
|---|---|
| Telegram-first `/start` + language | 4 |
| `/add` threshold rules, max 3 | 3, 4 |
| `/rules`, `/delete`, `/stop` | 4 |
| `/digest on/off` + email confirm | 3, 4 |
| Instant via Telegram on tick | 3 |
| Combined message per chat | 3 |
| `last_fired_at` after successful send | 3 |
| Digest 16:30 email only | existing + 3 gates |
| Webhook + secret | 5 |
| Config/secrets, dark when disabled | 1, 4, 5 |
| No mirsad-market-monitor deploy | (constraint — no task creates it) |
| Web push deferred | (non-goal) |

---

## Out of this plan

- Web push
- Freemium billing
- `telegram_sessions` DB table (upgrade if multi-instance needed)
- Board UI changes for Telegram (bot is primary UX)
- Deploying/setting production webhook (ops checklist only)
