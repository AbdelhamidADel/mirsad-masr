# AR/EN language toggle (option 2: chrome + full RTL)

**Date:** 2026-10-28  
**Surface:** `src/egxdesk/board.html` only (client-side)

## Decision

Ship a bilingual chrome toggle **EN | ع** next to the theme control. Arabic mode flips the whole board to RTL (`dir="rtl"`, `lang="ar"`) and translates UI chrome; live market content stays in its source language.

## Behavior

| Concern | Choice |
| --- | --- |
| Storage | `localStorage` key `egx-lang` → `en` \| `ar` |
| Default | English when unset |
| Document | `ar` → `lang="ar"` `dir="rtl"`; `en` → `lang="en"` `dir="ltr"` |
| Toggle | Persist, apply chrome, re-paint current Desk/Gold/Silver views — no full reload |
| Fonts | Prefer existing `--font-ar` / Noto Naskh for chrome in RTL |

## Translate (chrome)

Tabs (Desk / Gold / Silver), section headings, filters, market open/closed, theme button labels, relative times, empty/error/retry copy, news topic chip labels, metals chrome (karat/fineness, calculator, zakat UI, funds sort labels, builder/chart titles, etc.).

## Do not translate

Tickers/symbols, live prices and numeric values, company `name` / `name_ar` (already bilingual), raw news headlines, publisher brand names as content.

## Implementation sketch

- `STRINGS.en` / `STRINGS.ar` dictionaries + `t(key, vars?)` helper
- Static nodes marked with `data-i18n` (and attr variants where needed)
- Light RTL CSS so header/actions/tabs/columns flip correctly; keep `.num` LTR-isolated
- On change: update `documentElement`, persist, `paintChrome()`, then re-render list/detail/news/markets or metals from cached payloads
