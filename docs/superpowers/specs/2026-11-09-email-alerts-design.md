# Email alerts & daily digest (MIRSAD MASR)

**Date:** 2026-11-09  
**Status:** Approved  
**Surface:** Board Alerts UI + `/v1/alerts/*` + in-app scheduler + Postgres + Gmail SMTP

## Goal

Let users subscribe by email (no password), confirm via link, and receive:

1. **Price alerts** when a watched stock, Egypt gold, EGX index, or FX strip instrument hits a rule.
2. **Daily summary** at a fixed Cairo time after the session.

## Decisions (locked)

| Topic | Choice |
|---|---|
| Product | Price alerts **and** daily digest |
| Auth | Email only + confirm link; manage/unsubscribe via token links |
| Storage | Postgres (Render / Neon) |
| Email transport | Gmail SMTP (`mirsadmasr@gmail.com`); credentials **only** in env / Render secrets |
| Rules | `above`, `below`, `pct_move` (±% vs previous close), `points_move` (points vs previous close) |
| Email language | Chosen at signup (`en` \| `ar`) |
| Digest time | Fixed **16:30 Africa/Cairo** for all digest subscribers |
| Check cadence | About every **15 minutes** during EGX session window |
| Architecture | In-app worker inside the FastAPI web process |
| Gold source | Starta Egypt gold (local karat context) |
| FX | Included in v1 (USD/EGP, EUR/EGP strip) |

## Non-goals (v1)

- Password / OAuth accounts
- Push, SMS, WhatsApp
- Chart image attachments
- Guaranteed delivery if Gmail daily caps or Render free dyno sleep
- Operator admin console beyond env + DB

## Signup & manage flow

1. Board **Alerts** panel: email, language, digest on/off → `POST /v1/alerts/subscribe`.
2. Create/update pending `subscribers` row; email confirm link (`confirm_token`, ~24h TTL).
3. `GET /v1/alerts/confirm?token=` sets `confirmed_at`. Unconfirmed users get no alerts/digests.
4. Every email includes **manage** + **unsubscribe** links (`manage_token`, long-lived until rotate/unsubscribe).
5. Manage UI (token URL): list/add/edit/delete rules, toggle digest, unsubscribe.

## Data model (Postgres)

### `subscribers`

| Column | Notes |
|---|---|
| `id` | UUID PK |
| `email` | unique, normalized lower-case |
| `lang` | `en` \| `ar` |
| `digest_on` | bool |
| `confirm_token` | nullable after confirm |
| `confirm_expires_at` | |
| `manage_token` | unique |
| `confirmed_at` | null until confirmed |
| `unsubscribed_at` | null if active |
| `created_at` / `updated_at` | |

### `alert_rules`

| Column | Notes |
|---|---|
| `id` | UUID PK |
| `subscriber_id` | FK |
| `target_type` | `stock` \| `gold` \| `index` \| `fx` |
| `target_id` | e.g. `COMI`, `gold_21k` (or Starta key), `CASE30`, `usd_egp` |
| `rule_kind` | `above` \| `below` \| `pct_move` \| `points_move` |
| `threshold` | float (absolute level, percent, or points) |
| `cooldown_hours` | default e.g. 6 |
| `last_fired_at` | nullable |
| `active` | bool |
| `created_at` / `updated_at` | |

### `alert_events`

Audit / dedupe: `id`, `rule_id`, `fired_at`, `price`, `previous`, `payload` (short text).

## Scheduler (in-process)

- **Session tick (~15 min):** Sun–Thu Cairo session window (approx 10:00–15:00 + short buffer). Load active rules for confirmed, non-unsubscribed subscribers. Resolve prices via existing EGX / Starta / strip helpers. Evaluate rules; respect cooldown; send alert email; write `alert_events` + `last_fired_at`.
- **Digest (16:30 Cairo):** For `digest_on` subscribers, send one summary of their watches (or a small default basket if digest-only). Skip unconfirmed / unsubscribed.
- **Rate guard:** Soft per-process hourly/daily send caps to reduce Gmail lockouts (~100–500/day practical SMTP ceiling on personal Gmail).
- **Wake mitigation:** `POST /v1/alerts/tick` with shared secret for external cron to ping a sleeping free dyno.

## Email

- SMTP: `smtp.gmail.com:587` STARTTLS.
- Env: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (app password), `SMTP_FROM`, `ALERTS_PUBLIC_BASE_URL`, `ALERTS_TICK_SECRET`, `DATABASE_URL`, `ALERTS_ENABLED`.
- Templates: confirm, alert fired, daily digest (plain text + simple HTML).
- Footer: manage + unsubscribe; delayed indicative data; not financial advice.
- **Never** commit mailbox passwords or app passwords to git. If secrets were pasted in chat, rotate the Gmail app password before production.

## API (rate-limited)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/alerts/subscribe` | Start signup |
| `GET` | `/v1/alerts/confirm` | Confirm email |
| `GET` | `/v1/alerts/manage` | Manage payload for UI |
| `POST` | `/v1/alerts/rules` | Create rule (manage token) |
| `PATCH` | `/v1/alerts/rules/{id}` | Update rule |
| `DELETE` | `/v1/alerts/rules/{id}` | Delete rule |
| `POST` | `/v1/alerts/unsubscribe` | Unsubscribe |
| `POST` | `/v1/alerts/tick` | Cron/evaluate (+ digest if due) |

## UI

- Board entry point **Alerts** / **تنبيهات**.
- Signup form + post-confirm manage page styled like the existing desk (no separate SPA).
- Rule builder: target type → target → rule kind → threshold → cooldown.

## Acceptance

- Confirmed subscriber receives confirm email and can add a COMI `above` rule.
- When price crosses threshold (and cooldown clear), one alert email in their language.
- At 16:30 Cairo (or forced digest via tick in tests), digest subscribers receive a summary.
- Unconfirmed / unsubscribed users receive nothing.
- Secrets absent from repo; `ALERTS_ENABLED=false` skips scheduler safely.
- Unit tests cover rule evaluation; integration tests mock SMTP + use test Postgres or SQLite-compatible layer if CI needs it (prefer Postgres in prod; CI may use Postgres service container).

## Risks

- Gmail personal SMTP caps and spam filtering.
- Render free sleep → missed 15‑min ticks without external ping.
- Delayed public EGX/Starta/Yahoo data — alerts are indicative, not trading signals.
