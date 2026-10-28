# MIRSAD MASR Landing Page Implementation Plan

> **For agentic workers:** Implement task-by-task; each task ends with a commit. Checkboxes track progress.

**Goal:** Put a marketing landing page at `GET /` while serving the existing dashboard at `GET /app`, without breaking `/v1/*` or dashboard behavior.

**Architecture:** New `landing.html` (self-contained HTML/CSS/JS) beside `board.html`. FastAPI serves `/` → landing, `/app` → board. Landing fetches live numbers from existing `/v1/markets`, `/v1/stocks`, `/v1/quotes`, and `/v1/metals/gold`. Optional `localStorage` key `mirsad-skip-landing` redirects `/` → `/app`. Theme uses the same `egx-theme` / `data-theme` pattern as the board.

**Tech Stack:** FastAPI static HTML responses, vanilla JS, existing CSS tokens (`--bg`, `--bg-alt`, `--surface`, `--accent`, Fraunces / Instrument Sans).

**Brand (override):** Product is **MIRSAD MASR** — tagline *Keep Your Eye on Egypt's Markets.* First dashboard tab is **Exchange** (not Desk). Feature cards: Exchange / Gold / Silver. Logo: `/static/mirsad-masr-emblem.png` + wordmark.

## Global Constraints

- Do not change `/v1/*` contracts or dashboard data-fetch logic.
- Never invent market numbers; hide cells/cards when data is missing.
- No purple theme; reuse board tokens; accent gold `#e3b768` (dark).
- First viewport is brand-forward marketing, not a dashboard mock.
- Commits in four logical chunks after this plan: routing → hero+stats → snapshot → features/data/FAQ/footer.
- Deep links: `/app#exchange`, `/app#gold`, `/app#silver`.

## File map

| File | Role |
|------|------|
| `docs/superpowers/plans/2026-10-28-landing-page.md` | This plan |
| `src/egxdesk/landing.html` | Marketing page (new) |
| `src/egxdesk/main.py` | `GET /` → landing; `GET /app` → board |
| `src/egxdesk/board.html` | Logo stays `href="/"`; no behavior change beyond that |
| `docs/superpowers/screenshots/landing/` | 1440/390 × light/dark captures |

## Live data mapping

| UI | Source | Notes |
|----|--------|-------|
| USD/EGP, EUR/EGP, Brent | `GET /v1/markets` → `instruments` by `id` (`usd_egp`, `eur_egp`, `brent`) | |
| Gold 21K / gram | `GET /v1/metals/gold` → `rows` where `label` is `21K` | Hide card if missing |
| Listed companies | `GET /v1/stocks` → `count` | |
| Companies with a price | `GET /v1/quotes` → `length` | |
| Gold karats tracked | `GET /v1/metals/gold` → `rows.length` | |
| FX/commodities tracked | `GET /v1/markets` → `instruments.length` | Expect 4 |
| Top gainers / losers | Derive from `/v1/quotes` by parsing `change_percent` | Omit section if quotes empty/unusable |
| As-of / Updated | `updated_cairo` from markets (and metals when shown) | |

## Sections checklist

- [ ] A Nav sticky blur — logo, Features / Live snapshot / Data / FAQ, theme + Open dashboard
- [ ] B Hero — live pill, Fraunces two-tone H1, tagline, Cairo as-of, dual CTAs, true reassurance
- [ ] C Stat strip — live counts, count-up, hide missing
- [ ] D Live snapshot mini-cards — USD/EGP, EUR/EGP, Gold 21K, Brent, gainers/losers if possible
- [ ] E Features — Exchange / Gold / Silver → `/app#…`
- [ ] F Data sources — Yahoo, EGX, Mubasher, Starta, BBC/Guardian/Google News; delay + disclaimer
- [ ] G FAQ `<details>` accordion
- [ ] H Final CTA + footer
- [ ] Meta title/description + OG; RTL-ready logical CSS; `prefers-reduced-motion`; skeletons then quiet fail

---

### Task 1: Plan + routing

**Files:** create plan (done); create `landing.html` shell; modify `main.py`.

- [ ] **Step 1:** Commit this plan.
- [ ] **Step 2:** Add `landing.html` with shared theme bootstrap, meta/OG, sticky nav shell, skip-landing redirect script.
- [ ] **Step 3:** In `main.py`: `GET /` → `landing.html`; `GET /app` → `board.html`. Keep `/static` and `/v1/*` unchanged.
- [ ] **Step 4:** Commit: `feat: serve marketing landing at / and dashboard at /app`.

### Task 2: Hero + stat strip

- [ ] **Step 1:** Hero (pill, H1, tagline, as-of, CTAs, reassurance) + soft accent radial.
- [ ] **Step 2:** Stat strip fetching stocks/quotes/markets/metals; count-up on scroll; hide missing.
- [ ] **Step 3:** Commit: `feat: add landing hero and live stat strip`.

### Task 3: Live snapshot

- [ ] **Step 1:** Mini-cards from markets + gold 21K; gainers/losers from quotes when possible.
- [ ] **Step 2:** Skeletons → quiet fail/hide; cards link to `/app` views.
- [ ] **Step 3:** Commit: `feat: add landing live market snapshot`.

### Task 4: Features, trust, FAQ, footer + verify

- [ ] **Step 1:** Features (Exchange/Gold/Silver), data sources, FAQ, final CTA, footer; skip checkbox.
- [ ] **Step 2:** Theme toggle parity with board; reduced-motion; mobile nav.
- [ ] **Step 3:** Restart uvicorn; screenshot 1440 & 390 × light & dark under `docs/superpowers/screenshots/landing/`.
- [ ] **Step 4:** Commit: `feat: complete landing features, trust, FAQ, and footer`.
- [ ] **Step 5:** End with Suggestions for any blocked/missing data.

## Verify

```bash
PYTHONPATH=src python -m uvicorn egxdesk.main:app --host 127.0.0.1 --port 8000
```

- Open `http://127.0.0.1:8000/` (landing) and `http://127.0.0.1:8000/app` (dashboard).
- Confirm `/v1/health` still 200.
- Confirm `/app#gold` opens Gold tab without landing.
