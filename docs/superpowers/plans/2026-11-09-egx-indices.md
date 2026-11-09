# EGX Indices Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load all 8 EGX index cards from `beta.egx.com.eg` `index-data` instead of Yahoo chart snapshots.

**Architecture:** Extend `egx_watch.py` with a TTL-cached `index_live(index_name)` helper that reads `liveIndex`. Update `desk._INDICES` / `_index` to use EGX keys. Keep Yahoo only for FX/gold/Brent strip instruments.

**Tech Stack:** Python urllib JSON BFF (same as market-watch), pytest, existing `IndexInsight` model + board grid.

## Global Constraints

- Public delayed EGX BFF only — not a licensed real-time feed
- Same headers as market-watch (`x-egx-bff-request: 1`)
- TTL ~30s aligned with board cache
- No Yahoo calls for index levels after this plan
- Expand catalog to 8 indices (add EGX 35 LV + EGX 30 TR)

---

## File map

| File | Role |
|---|---|
| `src/egxdesk/fetchers/egx_watch.py` | `index_live` + cache |
| `src/egxdesk/services/desk.py` | `_INDICES` catalog + `_index` wiring |
| `tests/test_egx_watch.py` | Fixture + mapping tests |
| `tests/test_desk_indices.py` (new or extend existing) | Desk uses EGX, not Yahoo |
| `src/egxdesk/landing.html` | Data-sources copy |
| `docs/superpowers/specs/2026-11-09-egx-indices-design.md` | Spec (already written) |

---

### Task 1: EGX `index-data` fetcher (TDD)

**Files:**
- Modify: `src/egxdesk/fetchers/egx_watch.py`
- Modify: `tests/test_egx_watch.py`
- Create fixture under `tests/fixtures/` if useful

- [ ] **Step 1: Failing test** — monkeypatch urllib/`_fetch` so `index_live("CASE30")` returns price/change/change_percent from a `liveIndex` fixture; assert unknown/empty liveIndex → nulls.

- [ ] **Step 2: Run test — expect FAIL** (helper missing).

- [ ] **Step 3: Implement** `INDEX_DATA` URL, `index_live(name)`, per-key TTL cache (or one dict of all requested names), parse `indexClose`/`change`/`changePer` into `{price, change, change_percent}` (`change_percent` as `+1.19%` string matching desk format, or raw float + format in desk — match existing `_index` which formats percent).

- [ ] **Step 4: Tests pass; commit** `feat: fetch EGX index-data live levels`

---

### Task 2: Desk catalog of 8 + drop Yahoo for indices

**Files:**
- Modify: `src/egxdesk/services/desk.py`
- Test: extend or add desk markets test

- [ ] **Step 1: Failing test** — with EGX helper mocked, `get_markets` (or `_index`) yields 8 indices and never calls `yahoo_chart_snapshot` for index keys.

- [ ] **Step 2: Update `_INDICES`** to the 8-row catalog with `index_name` field; `_index` calls `index_live`; leave `_instrument` / `_external_snapshot` for strip FX/gold/Brent only.

- [ ] **Step 3: Tests pass; commit** `feat: serve 8 EGX indices without Yahoo`

---

### Task 3: Landing copy + verify

**Files:**
- Modify: `src/egxdesk/landing.html`

- [ ] **Step 1:** Note EGX owns index levels; Yahoo only FX/gold/Brent.
- [ ] **Step 2:** Run `pytest tests/test_egx_watch.py` (+ desk test) and ruff.
- [ ] **Step 3: Commit + push** `docs: attribute EGX indices on landing`
