# Replace Yahoo with EGX market watch + Investing.com

**Date:** 2026-11-09  
**Status:** Approved (Hybrid approach)  
**Surface:** Quote chain, charts, market strip, indices; landing/docs attribution copy

## Goal

Stop using Yahoo Finance for market data. Use **official EGX market watch** as the primary source for Egyptian equities, with **Investing.com as backup** for equities and as the primary source for charts, FX, oil, gold futures, and index levels that EGX does not expose cleanly.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Primary equity quotes | `beta.egx.com.eg` market watch |
| Equity quote fallback | Investing.com |
| Yahoo for quotes | Removed from the quote chain |
| Charts | Must leave Yahoo in this pass → Investing history |
| Scope | Remove Yahoo everywhere possible (stocks, indices, FX, oil, gold futures) |
| Egypt karat gold/silver | Keep Starta (unchanged) |

## Non-goals

- Licensed real-time / Level-2 depth / trade tape
- Guaranteeing zero delay vs the exchange floor
- Scraping Investing HTML as the long-term preferred path if a stable JSON endpoint exists — prefer JSON/chart APIs when discoverable
- Rewriting the Next.js `apps/web` surface
- Removing Alpha Vantage / Finnhub optional keys (they may remain after EGX/Investing in the chain)

## Proven EGX endpoint

```
GET https://beta.egx.com.eg/api/bff/egx/market-watch
Header: x-egx-bff-request: 1
```

Paginated board (`pageNumber`, `pageSize`, `totalPages`). Rows include `reuters` (e.g. `COMI.CA`), `lastPrice`, `chgPer`, `openPrice`, `prevClose`, `high`, `low`, `volume`, `trades`, `mc`, `name` / `nameA`, `sector` / `sectorA`, `writeTime`.

Fetch all pages (or a large `pageSize` if accepted) into an in-process board cache with a short TTL (align with `CACHE_TTL_SECONDS`, default 300s).

## Architecture

```
Quote request
  → EgxMarketWatchFetcher (board cache lookup by symbol / reuters)
  → InvestingFetcher (if EGX miss)
  → optional Alpha Vantage / Finnhub (if keys configured)
  → fail

Chart / FX / oil / gold futures / index snapshot
  → Investing chart/quote helpers (replace yahoo.chart_history / chart_snapshot)
  → EGX board only where a matching instrument exists (indices if available)

Metals karat pages
  → Starta (unchanged)
```

### New modules

| Module | Responsibility |
|---|---|
| `fetchers/egx_watch.py` | Download/paginate market-watch BFF; map row → `QuoteData`; board TTL cache |
| `fetchers/investing.py` | Quote + OHLC history for equities fallback, FX, Brent, gold futures, indices |
| `services/charts.py` (or desk helpers) | Range charts via Investing; no Yahoo URLs |

### Wiring

- `_build_fetchers`: EGX → Investing → (optional AV/FH). No `YahooFetcher`. `StartaFetcher` optional only if still needed for symbols EGX omits; default **off** for equity quotes once EGX board covers the catalog.
- `ENABLE_YAHOO_FINANCE` default `false`; Yahoo code paths unused for production data.
- Attribution: `ATTRIBUTIONS["egx"]`, `ATTRIBUTIONS["investing"]`; `X-Data-Source` reflects the winning provider.

### Symbol mapping

- Canonical app symbols stay as today (`COMI`, etc.).
- EGX match: strip `.CA` from `reuters`, also try bare symbol and catalog aliases.
- Investing: maintain a small map for non-equity instruments (USD/EGP, EUR/EGP, gold futures, Brent, EGX index tickers) plus equity pair IDs discovered once and cached.

## Data flow

1. **Warm / refresh:** background or on-demand load of all EGX market-watch pages into `_board`.
2. **`GET /v1/quote/{symbol}`:** EGX board hit → `QuoteData`; else Investing; else optional keys; else 502.
3. **Bulk `/v1/quotes`:** primarily from EGX board (one refresh serves many symbols).
4. **Company charts:** Investing historical series for the mapped pair; empty/error if unavailable.
5. **Markets strip / indices:** Investing snapshots (and EGX index fields if a dedicated BFF is found later).

## Error handling

- EGX HTTP/parse failure → treat board as empty for that refresh; Investing serves equity requests.
- Investing blocked/rate-limited → log warning; equities still work from EGX; charts/FX may empty.
- Never fall back to Yahoo in this design.
- Cache negative Investing lookups briefly to avoid hammering.

## Testing

- Unit: parse fixture of EGX market-watch JSON → `QuoteData` for `COMI` / `COMI.CA`.
- Unit: pagination assembles `totalCount` rows.
- Unit: Investing mapper returns expected OHLC shape for desk charts (fixture).
- Integration-style: fetcher chain prefers EGX over Investing when both would answer (mock).
- Update docs/landing “data sources” copy: EGX + Investing; remove Yahoo as primary.

## Risks (honest)

- Public EGX/Investing data remain **delayed / indicative**, not licensed live.
- Investing endpoints/HTML change often; isolate behind one module with fixtures.
- Chart parity with Yahoo ranges may be approximate (interval/range mapping).

## Acceptance

- With Yahoo disabled, board loads equity quotes from EGX.
- Killing EGX in tests still returns a quote via Investing mock.
- Company chart endpoint no longer calls Yahoo chart URLs.
- Market strip / indices do not call Yahoo.
- Landing/docs no longer claim Yahoo as the equity source of truth.
