# EGX index levels from beta.egx.com.eg

**Date:** 2026-11-09  
**Status:** Approved  
**Surface:** Markets indices grid (board `/v1/markets` indices)

## Goal

Stop reading EGX index levels from Yahoo chart snapshots. Use the official EGX beta BFF `index-data` endpoint for all index cards, expanding the board from 6 to **8** indices to match the public indices page.

## Proven endpoint

```
GET https://beta.egx.com.eg/api/bff/egx/index-data?interval=1&indexName={key}
Header: x-egx-bff-request: 1
Referer / Origin: https://beta.egx.com.eg
```

Relevant payload:

```json
{
  "success": true,
  "data": {
    "liveIndex": {
      "indexClose": 51414.93,
      "change": 602.86,
      "changePer": 1.18645,
      "indexOpen": 50812.07,
      "high": 51432.67,
      "low": 50812.07,
      "ytdPercent": 22.917,
      "indexDay": "2026-11-09T00:00:00"
    },
    "dailyIndex": [/* intraday points — unused this pass */]
  }
}
```

TTL: reuse the same ~30s board TTL as market-watch (`CACHE_TTL_SECONDS` / fetcher `_TTL`).

## Index catalog (8)

| App `id` | EN name | AR name | `indexName` (API) | UI label on EGX |
|---|---|---|---|---|
| `egx30` | EGX 30 | مؤشر EGX 30 | `CASE30` | EGX30 |
| `egx_shariah` | EGX Shariah Index | مؤشر الشريعة | `EGX_SHARIAH` | SHARIAH |
| `egx35_lv` | EGX 35 LV | مؤشر EGX 35 منخفض التقلب | `EGX35LV` | EGX35-LV |
| `egx100_ewi` | EGX 100 EWI | مؤشر EGX 100 متساوي الأوزان | `EGX100_EWI` | EGX100 EWI |
| `egx70_ewi` | EGX 70 EWI | مؤشر EGX 70 متساوي الأوزان | `EGX70_EWI` | EGX70 EWI |
| `egx30_capped` | EGX 30 Capped | مؤشر EGX 30 المحدود | `EGX30_CAP` | EGX30 CAP |
| `egx30_tr` | EGX 30 TR | مؤشر EGX 30 العائد الكلي | `EGX30_TR` | EGX30-TR |
| `tamayuz` | Tamayuz Market | سوق التميّز | `TAMAYUZ` | TAMAYUZ |

Display order follows the EGX page button order above.

## Wiring

1. **`egx_watch.py`**: `index_live(index_name) → {price, change, change_percent}` from `liveIndex`. Optional short-lived multi-index cache so one markets request does not hammer eight cold calls beyond TTL.
2. **`desk.py` `_INDICES`**: replace Yahoo tickers (`^CASE30`, …) with EGX `indexName` keys; `_index` calls EGX helper, not `_external_snapshot`.
3. **Attribution**: index levels are Egyptian Exchange (no Yahoo source string on these cards).
4. **Landing**: data-sources / FAQ copy — EGX owns equity **and** index levels; Yahoo remains only for FX / gold futures / Brent strip.

## Non-goals

- Index history charts / constituents / methodology tabs
- Sector indices (`SECTORS` on the EGX page)
- Replacing Yahoo for USD/EGP, EUR/EGP, `GC=F`, `BZ=F`
- Licensed real-time guarantee (public delayed BFF only)

## Acceptance

- `/v1/markets` returns 8 indices with non-null prices when EGX BFF is up (session permitting).
- No Yahoo `chart_snapshot` calls for former `^CASE30` / `^EGX*` / `^SHARIAH` / `^TAMAYUZ` tickers.
- Unit tests cover `liveIndex` mapping and the 8-key catalog.
- Board indices grid renders the two new cards (EGX 35 LV, EGX 30 TR) without UI rewrite beyond existing generic renderer.
