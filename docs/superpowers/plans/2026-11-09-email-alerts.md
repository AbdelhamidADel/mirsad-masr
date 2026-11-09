# Email Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship email-only price alerts + 16:30 Cairo digests with Postgres, Gmail SMTP, and an Alerts UI on the board.

**Architecture:** New `egxdesk.alerts` package: SQLAlchemy models (Postgres prod / SQLite for unit tests), pure rule evaluation, SMTP mailer, FastAPI router, in-app 15‑min tick + digest. Existing desk/EGX/Starta helpers supply prices.

**Tech Stack:** FastAPI, SQLAlchemy 2.x, psycopg (Postgres), smtplib, pytest.

## Global Constraints

- Secrets only in env (`DATABASE_URL`, `SMTP_*`, `ALERTS_*`) — never commit
- `ALERTS_ENABLED=false` by default until configured
- Confirm before any alert/digest send
- Language EN/AR per subscriber
- Cooldown on fired rules

---

## File map

| File | Role |
|---|---|
| `src/egxdesk/alerts/__init__.py` | Package |
| `src/egxdesk/alerts/db.py` | Engine, session, `init_db()` |
| `src/egxdesk/alerts/models.py` | Subscriber, AlertRule, AlertEvent |
| `src/egxdesk/alerts/rules.py` | `evaluate_rule(kind, threshold, price, previous) -> bool` |
| `src/egxdesk/alerts/prices.py` | `resolve_quote(target_type, target_id) -> {price, previous}` |
| `src/egxdesk/alerts/mail.py` | SMTP send + templates |
| `src/egxdesk/alerts/service.py` | subscribe/confirm/manage/unsubscribe/tick |
| `src/egxdesk/alerts/scheduler.py` | Background loop |
| `src/egxdesk/alerts/router.py` | `/v1/alerts/*` |
| `src/egxdesk/config.py` | Alert/SMTP settings |
| `src/egxdesk/main.py` | Mount router + start scheduler |
| `src/egxdesk/board.html` | Alerts UI |
| `tests/test_alert_rules.py` | Pure evaluation |
| `tests/test_alerts_service.py` | Subscribe/confirm/fire with SQLite + mock mail |
| `.env.example` / `render.yaml` | Env docs |

---

### Task 1: Config + DB schema

**Files:** `config.py`, `alerts/db.py`, `alerts/models.py`, `pyproject.toml` (sqlalchemy, psycopg), `.env.example`

- [ ] Add settings: `alerts_enabled`, `database_url`, `smtp_*`, `alerts_public_base_url`, `alerts_tick_secret`
- [ ] SQLAlchemy models matching spec tables
- [ ] `init_db()` create_all; tests use `sqlite+pysqlite:///:memory:`
- [ ] Commit `feat: add alerts database models and settings`

### Task 2: Rule evaluation (TDD)

**Files:** `alerts/rules.py`, `tests/test_alert_rules.py`

- [ ] Failing tests for above/below/pct_move/points_move edge cases
- [ ] Implement `evaluate_rule` + `cooldown_clear`
- [ ] Commit `feat: evaluate alert rule thresholds`

### Task 3: Mailer (TDD with mock)

**Files:** `alerts/mail.py`, tests

- [ ] `send_email(to, subject, text, html)` via SMTP; no-op or record when `smtp_password` empty in tests
- [ ] Templates: confirm, alert, digest (EN/AR strings)
- [ ] Commit `feat: add Gmail SMTP alert mailer`

### Task 4: Service + API

**Files:** `alerts/service.py`, `alerts/router.py`, `alerts/prices.py`, `main.py`, `tests/test_alerts_service.py`

- [ ] subscribe → pending + confirm email
- [ ] confirm token
- [ ] CRUD rules via manage token
- [ ] unsubscribe
- [ ] tick: evaluate rules + optional force digest
- [ ] Mount router; rate-limit lightly
- [ ] Commit `feat: expose /v1/alerts subscribe and manage API`

### Task 5: Scheduler

**Files:** `alerts/scheduler.py`, `main.py` lifespan

- [ ] Loop every 15 min when enabled; session window Cairo; 16:30 digest once/day
- [ ] Commit `feat: run in-app alert tick and Cairo digest`

### Task 6: Board UI

**Files:** `board.html`

- [ ] Alerts tab/panel: signup form; manage via token query `?alerts=TOKEN`
- [ ] i18n EN/AR
- [ ] Commit `feat: add board Alerts signup and manage UI`

### Task 7: Wire docs + verify

- [ ] `.env.example`, `render.yaml` DATABASE_URL sync false, SMTP secrets
- [ ] Full pytest + ruff + mypy on new modules
- [ ] Push
