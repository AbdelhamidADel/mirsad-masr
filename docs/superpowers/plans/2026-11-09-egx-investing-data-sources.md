# EGX + Investing Data Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Yahoo market data with EGX market-watch quotes (primary) and Investing.com (backup + charts/FX/commodities/indices).

**Architecture:** New `EgxMarketWatchFetcher` reads `GET /api/bff/egx/market-watch` into a TTL board cache. New `InvestingFetcher` + chart helpers cover fallback quotes and non-equity series. Quote chain becomes EGX → Investing → optional AV/FH. Desk stops calling Yahoo chart helpers.

**Tech Stack:** FastAPI, httpx/urllib, pytest/respx, existing `QuoteData` / desk models.

**Spec:** `docs/superpowers/specs/2026-11-09-egx-investing-data-sources-design.md`

## Global Constraints

- No Yahoo in the production quote or chart path after this plan.
- EGX BFF: `GET https://beta.egx.com.eg/api/bff/egx/market-watch` with `x-egx-bff-request: 1`.
- Keep Starta for karat gold/silver pages only.
- Prefer fixtures over live network in unit tests.
- Do not claim licensed real-time data in copy.

---

## File map

| File | Role |
|---|---|
| `src/egxdesk/fetchers/egx_watch.py` | EGX board download + quote mapping |
| `src/egxdesk/fetchers/investing.py` | Investing quotes + OHLC |
| `src/egxdesk/fetchers/__init__.py` | Export new fetchers |
| `src/egxdesk/main.py` | Rebuild fetcher chain |
| `src/egxdesk/models.py` | Attribution entries |
| `src/egxdesk/services/desk.py` | Replace Yahoo chart/snapshot imports |
| `src/egxdesk/config.py` / `.env.example` | Flags defaults |
| `tests/test_egx_watch.py` | EGX parse/pagination |
| `tests/test_investing_charts.py` | Investing OHLC mapping |
| `src/egxdesk/landing.html` / `api_docs.py` | Source copy |

---

### Task 1: EGX market-watch fetcher (quotes)

**Files:**
- Create: `src/egxdesk/fetchers/egx_watch.py`
- Create: `tests/test_egx_watch.py`
- Modify: `src/egxdesk/models.py` (attribution)
- Modify: `src/egxdesk/fetchers/__init__.py`

- [ ] **Step 1: Write failing tests** for mapping a fixture row (`reuters: COMI.CA`) → `QuoteData` with price/change/volume/high/low/open/prev_close, and for merging multiple pages by `totalPages`.

- [ ] **Step 2: Run tests — expect fail**

- [ ] **Step 3: Implement `EgxMarketWatchFetcher`**
  - `GET` paginated board with `x-egx-bff-request: 1`
  - In-process board dict keyed by bare symbol + reuters
  - TTL aligned with settings (default 300s)
  - `fetch_quote(symbol)` looks up board; returns `None` on miss

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit** `feat: add EGX market-watch quote fetcher`

---

### Task 2: Wire EGX into quote chain (Yahoo off)

**Files:**
- Modify: `src/egxdesk/main.py` (`_build_fetchers`)
- Modify: `src/egxdesk/config.py`, `.env.example`
- Modify: tests that assume Yahoo-first

- [ ] **Step 1: Failing test** that fetcher order starts with EGX and excludes Yahoo when disabled

- [ ] **Step 2: Implement chain** `EgxMarketWatchFetcher` → (Investing placeholder or skip until Task 3) → optional AV/FH; `ENABLE_YAHOO_FINANCE` default `false`; do not append `YahooFetcher` when false

- [ ] **Step 3: Tests pass; commit** `feat: prefer EGX over Yahoo in quote chain`

---

### Task 3: Investing quote fallback + instrument map

**Files:**
- Create: `src/egxdesk/fetchers/investing.py`
- Create: `tests/test_investing_quotes.py`

- [ ] **Step 1: Discover stable Investing JSON/chart endpoint** (document URL + params in module docstring); fixture from real capture

- [ ] **Step 2: Failing tests** for equity fallback quote + FX/oil/gold map keys used by desk strip

- [ ] **Step 3: Implement `InvestingFetcher.fetch_quote`** + insert after EGX in `_build_fetchers`

- [ ] **Step 4: Tests pass; commit** `feat: add Investing.com quote fallback`

---

### Task 4: Charts / snapshots without Yahoo

**Files:**
- Modify: `src/egxdesk/services/desk.py` (and any yahoo chart imports)
- Extend: `src/egxdesk/fetchers/investing.py` with `chart_history` / `chart_snapshot` equivalents
- Create: `tests/test_investing_charts.py`
- Leave `yahoo.py` in tree but unused by desk/main (or gate behind flag only)

- [ ] **Step 1: Failing tests** for range→bars mapping from Investing fixture

- [ ] **Step 2: Point desk `chart_history` / market instrument snapshots at Investing helpers**

- [ ] **Step 3: Grep confirms no desk/main import of yahoo chart helpers for runtime paths**

- [ ] **Step 4: Tests pass; commit** `feat: serve charts and strip from Investing`

---

### Task 5: Docs / landing copy + verification

**Files:**
- Modify: `src/egxdesk/landing.html`, `src/egxdesk/api_docs.py`, README data-source mentions as needed

- [ ] **Step 1: Update source lists** to EGX + Investing (+ Starta metals); remove Yahoo as equity source of truth

- [ ] **Step 2: Run** `ruff check`, `mypy src`, `pytest`

- [ ] **Step 3: Commit** `docs: attribute EGX and Investing as market data sources`
