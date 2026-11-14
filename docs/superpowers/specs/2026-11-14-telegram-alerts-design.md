# Telegram-first alerts + optional email digest (MIRSAD MASR)

**Date:** 2026-11-14  
**Status:** Approved  
**Surface:** Telegram bot + existing `/v1/alerts/*` tick/rules + optional email digest  
**Supersedes (partially):** channel preference in `2026-11-09-email-alerts-design.md` — threshold rules, Postgres, and tick remain; **instant delivery moves to Telegram**; email is digest-only unless later paid/email tiers are added.

## Goal

Let users subscribe **from Telegram** (no password), set price **threshold rules** in chat, and receive:

1. **Instant alerts on Telegram** when a watched stock, Egypt gold, EGX index, or FX strip instrument hits a rule.
2. **Optional daily email digest** at a fixed Cairo time (email collected and confirmed only if the user opts in).

Web push is **phase 2** (out of this MVP).

## Decisions (locked)

| Topic | Choice |
|---|---|
| Product | Threshold rules on Telegram + optional daily email digest |
| Instant channel (MVP) | Telegram Bot API |
| Instant channel (later) | Web push |
| Signup | Telegram-first (`/start` → language → rules in chat) |
| Auth | No passwords; identity = `telegram_chat_id`; email only for digest |
| Storage | Postgres (Neon / Render) — extend existing alerts tables |
| Architecture | Single egx-desk FastAPI service on Render (Approach 1) |
| Rules | `above`, `below`, `pct_move`, `points_move` |
| Free-scale caps | Max **3** active rules per chat; default cooldown **6h** |
| Digest time | **16:30 Africa/Cairo** (same as existing email-alerts design) |
| Check cadence | ~**15 minutes** during EGX session window + external cron wake |
| Email transport | Resend HTTPS preferred on Render free; SMTP only if configured |
| Language | Chosen in bot (`en` \| `ar`) |

## Non-goals (MVP)

- Web push, SMS, WhatsApp
- Password / OAuth / JWT accounts
- Separate `mirsad-market-monitor` production deploy
- “Alert on any price change” (Apps Script personal-monitor model)
- Billing / freemium paywall (caps only; paid tier can come later)
- Admin console beyond env + DB
- Chart images in Telegram messages
- Guaranteed delivery if Render free dyno sleep without cron, or Telegram/user blocks the bot

## Architecture

```text
User ──Telegram──► Bot API webhook ──► egx-desk (Render)
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              subscribers          alert_rules           tick worker
           (telegram_chat_id,     (thresholds)         (15 min / cron)
            email optional)
                    │                    │                    │
                    │                    └────────┬───────────┘
                    │                             ▼
                    │                    rule engine (existing)
                    │                             │
                    ├──────── Telegram send ◄─────┤ (instant hit)
                    └──────── email (Resend) ◄────┘ (digest only, if confirmed)
```

**Do not** ship a second FastAPI that re-polls `/v1/markets` for production subscriptions. Keep Google Apps Script as a **personal** ops monitor only.

## Data model

### `subscribers` (extend)

| Column | Notes |
|---|---|
| `id` | UUID PK (existing) |
| `telegram_chat_id` | **New**, unique, nullable only for legacy email-only rows; required for Telegram-first users |
| `telegram_linked_at` | **New**, set on successful `/start` onboarding |
| `email` | **Nullable** until digest opt-in; unique when present (normalized lower-case) |
| `lang` | `en` \| `ar` |
| `digest_on` | bool |
| `confirm_token` / `confirm_expires_at` | email confirm for digest |
| `manage_token` | long-lived; used in digest email manage/unsubscribe links |
| `confirmed_at` | null until email confirmed (digest gate only) |
| `unsubscribed_at` | null if active; `/stop` sets this |
| `created_at` / `updated_at` | existing |

**Active for instant Telegram alerts:** `telegram_chat_id` present, `unsubscribed_at` null.  
**Active for email digest:** `digest_on`, email present, `confirmed_at` set, `unsubscribed_at` null.

Migration note: existing email-only subscribers (if any in prod) remain valid for digest; they do not receive Telegram until they link a chat (future `/link` optional — not required for MVP if production alerts were never enabled).

### `alert_rules` / `alert_events`

Unchanged from `2026-11-09-email-alerts-design.md`:

- `target_type`: `stock` \| `gold` \| `index` \| `fx`
- `target_id`: e.g. `COMI`, `gold_21k`, `CASE30`, `usd_egp`
- `rule_kind`: `above` \| `below` \| `pct_move` \| `points_move`
- `threshold`, `cooldown_hours` (default 6), `last_fired_at`, `active`
- Events: audit row per successful fire

### Bot conversation state (ephemeral)

**MVP choice:** in-process dict keyed by `telegram_chat_id` with TTL (~15 minutes). Acceptable on Render free single dyno; wizard progress resets on deploy/restart. Phase 2: move to a `telegram_sessions` table if multiple instances or reset pain appears. No Redis in MVP.

## Bot flow (MVP)

1. `/start` — create/update subscriber by `telegram_chat_id`; welcome; choose language.
2. `/add` — guided steps: target type → target id → rule kind → threshold; enforce max 3 active rules.
3. `/rules` — list active rules (short ids).
4. `/delete <id>` — deactivate/delete one rule.
5. `/stop` — set `unsubscribed_at`; stop all Telegram alerts and digests.
6. `/digest on` — ask for email → send confirm link → set `digest_on` after confirm.
7. `/digest off` — `digest_on=false`; Telegram rules keep working.

Unknown text → short help listing commands.

## Tick, delivery & digest

### Session tick (~15 min)

- Sun–Thu Cairo session window (approx 10:00–15:00 + short buffer), same spirit as existing alerts scheduler.
- Load active rules for Telegram-active subscribers.
- Resolve prices via existing EGX / Starta / strip helpers.
- Evaluate rules; respect cooldown.
- **Set `last_fired_at` only after successful Telegram send** (so failed sends can retry next tick without silent drops). Use a short in-tick dedupe so a single tick does not double-send.
- Prefer **one combined Telegram message per chat per tick** when multiple rules fire.
- Write `alert_events` on successful send.

### Digest (16:30 Cairo)

- For digest-eligible subscribers only.
- Email via Resend/SMTP templates (existing mail helpers).
- Footer: manage + unsubscribe; delayed data; not financial advice.
- Digest failures must not disable Telegram delivery.

### Wake mitigation

- Keep `POST /v1/alerts/tick` with shared secret for external cron (Render free sleep).
- Telegram webhook may cold-start; acceptable for MVP.

## API / HTTP surface

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/telegram/webhook` | Telegram updates (validate secret) |
| Existing | `/v1/alerts/*` | Confirm email, manage/unsubscribe links for digest, tick |
| `POST` | `/v1/alerts/tick` | Cron evaluate (+ digest if due) |

Board Alerts UI may remain for email-centric flows later; **MVP primary UX is Telegram**.

## Config / secrets

| Env | Purpose |
|---|---|
| `ALERTS_ENABLED` | Master switch |
| `DATABASE_URL` | Postgres |
| `TELEGRAM_BOT_TOKEN` | Bot API |
| `TELEGRAM_WEBHOOK_SECRET` | Path or header token so only Telegram (or ops) can POST |
| `ALERTS_PUBLIC_BASE_URL` | Confirm/manage links in digest email |
| `ALERTS_TICK_SECRET` | Cron tick |
| `RESEND_API_KEY` / SMTP_* | Digest email only |

Never commit tokens. `ALERTS_ENABLED=false` skips scheduler and ignores bot mutations safely (webhook can reply “alerts offline”).

## Error handling

- Webhook always finishes with HTTP 200 after handling (or intentional reject of bad secret with 403) so Telegram does not hammer retries incorrectly.
- Invalid user input → help text; no stack traces to users.
- Price source down → skip that target for the tick; do not corrupt rules or history.
- Telegram 429 → backoff, one retry; then leave for next tick if still failing.
- User blocked bot → set `unsubscribed_at` (no separate blocked flag in MVP).
- Missing token / alerts disabled → no-op with structured logs.

## Testing

- Unit: rule evaluation (existing + any Telegram delivery branching).
- Unit: bot conversation state machine with mocked Update payloads.
- Integration: tick → mock Telegram `sendMessage`; digest → mock email.
- Manual: `/start` → COMI `above` rule → force tick → message received; `/digest on` → confirm → digest email.

## Acceptance

- User can `/start`, set language, and create a COMI `above` rule without email.
- When price crosses threshold and cooldown is clear, **one** Telegram alert arrives.
- Max 3 active rules enforced with a clear bot message.
- `/stop` ends further Telegram alerts.
- `/digest on` + email confirm required before any digest; unconfirmed email gets no digest.
- Unconfirmed digest email does not block Telegram alerts.
- Secrets absent from repo; feature dark with `ALERTS_ENABLED=false`.
- No dependency on `mirsad-market-monitor` backend for production.

## Risks

- Render free cold starts delay webhook replies and ticks without cron.
- Telegram Bot API flood limits under sudden mass fires — mitigate with caps, cooldowns, combined messages.
- In-process session state lost on restart (use DB sessions if that becomes painful).
- Delayed public market data — alerts are indicative, not trading signals.
- Email digest still has ESP cost at large scale — caps and optional opt-in keep MVP viable; freemium can come later.

## Phase 2 (explicitly later)

- Web push (VAPID) as alternate/additional instant channel.
- Optional freemium (more than 3 rules, shorter cooldown).
- Richer bot UX (inline keyboards for symbol search).
- Queue workers when subscriber volume outgrows in-process tick.

## Relation to Apps Script prototype

`D:\Activaties\mirsad-market-monitor` remains a **personal** change-detector and template source. Production product behavior is **threshold + Telegram**, not any-tick email fan-out.
