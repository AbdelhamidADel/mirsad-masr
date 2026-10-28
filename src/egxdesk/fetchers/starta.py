from __future__ import annotations

import asyncio
import re
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import structlog

from egxdesk.data.symbols import (
    _canonical,
    get_symbol_name,
    get_symbol_name_ar,
    get_symbol_sector,
)
from egxdesk.models import ATTRIBUTIONS, QuoteData

log = structlog.get_logger()

_ATTRIBUTION = ATTRIBUTIONS["starta"]
_CAIRO = ZoneInfo("Africa/Cairo")
_PAGE = "https://startamarkets.com/companies"
_TTL = 15 * 60
_BIDI = str.maketrans("", "", "\u2066\u2067\u2068\u2069\u200e\u200f")
_PRICE = re.compile(r"(-?\d+(?:\.\d+)?)")
_CHANGE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")
_CAP = re.compile(r"(\d+(?:\.\d+)?)\s*([KMBT])", re.IGNORECASE)
_CELL = re.compile(r'<td class="px-4 py-2\.5 text-right[^"]*">([^<]*)</td>')
_SYMBOL = re.compile(r'href="/symbol/([^"]+)"')
_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}


class StartaFetcher:
    """Daily EGX board from Starta. Used only after Yahoo returns nothing."""

    name = "starta"
    _lock = asyncio.Lock()
    _rows: dict[str, dict[str, object]] | None = None
    _loaded_at = 0.0

    async def fetch_quote(self, symbol: str) -> QuoteData | None:
        start = time.monotonic()
        try:
            rows = await self._rows_cached()
        except Exception as exc:
            log.warning("starta_board_failed", error=str(exc))
            return None
        row = _lookup(rows, symbol)
        if row is None:
            return None
        return QuoteData(
            symbol=symbol.upper(),
            company=get_symbol_name(symbol) or symbol,
            company_ar=get_symbol_name_ar(symbol),
            sector=get_symbol_sector(symbol),
            price=float(row["price"]),
            change=row["change"],
            change_percent=row["change_percent"],
            market_cap=row["market_cap"],
            previous_close=row["previous_close"],
            exchange="EGX",
            currency=str(row["currency"]),
            source=f"Starta Markets ({row['symbol']})",
            api_symbol=str(row["symbol"]),
            fetch_duration=round(time.monotonic() - start, 3),
            updated_cairo=datetime.now(_CAIRO).strftime("%Y-%m-%d %H:%M:%S"),
            attribution=_ATTRIBUTION,
        )

    async def _rows_cached(self) -> dict[str, dict[str, object]]:
        async with self._lock:
            if self._rows is not None and time.monotonic() - self._loaded_at < _TTL:
                return self._rows
            html = await asyncio.get_event_loop().run_in_executor(None, _download)
            self._rows = _parse(html)
            self._loaded_at = time.monotonic()
            log.info("starta_board_loaded", priced=len(self._rows))
            return self._rows


def _lookup(rows: dict[str, dict[str, object]], symbol: str) -> dict[str, object] | None:
    canonical = _canonical(symbol)
    bare = canonical[:-3] if canonical.endswith(".CA") else canonical
    for key in (canonical, bare, symbol.upper()):
        row = rows.get(key)
        if row is not None:
            return row
    return None


def _download() -> str:
    request = urllib.request.Request(_PAGE, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def _parse(html: str) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for chunk in html.split("<tr "):
        found = _SYMBOL.search(chunk)
        if found is None:
            continue
        cells = [cell.translate(_BIDI).strip() for cell in _CELL.findall(chunk)]
        if len(cells) < 2:
            continue
        price, currency = _price(cells[0])
        if price is None or price <= 0:
            continue
        change_percent, change, previous = _change(cells[1], price)
        rows[found.group(1).upper()] = {
            "symbol": found.group(1).upper(),
            "price": price,
            "currency": currency,
            "change_percent": change_percent,
            "change": change,
            "previous_close": previous,
            "market_cap": _market_cap(cells[2]) if len(cells) > 2 else None,
        }
    return rows


def _price(text: str) -> tuple[float | None, str]:
    if not text or text in {"—", "-", "–"}:
        return None, "EGP"
    currency = "USD" if "USD" in text.upper() else "EGP"
    match = _PRICE.search(text.replace(",", ""))
    if match is None:
        return None, currency
    return float(match.group(1)), currency


def _change(text: str, price: float) -> tuple[str | None, float | None, float | None]:
    match = _CHANGE.search(text.translate(_BIDI))
    if match is None:
        return None, None, None
    percent = float(match.group(1))
    label = f"{percent:+.2f}%"
    if percent == 0:
        return label, 0.0, round(price, 4)
    previous = price / (1 + percent / 100)
    return label, round(price - previous, 4), round(previous, 4)


def _market_cap(text: str) -> float | None:
    cleaned = text.translate(_BIDI).strip()
    if not cleaned or cleaned in {"—", "-", "–"}:
        return None
    match = _CAP.fullmatch(cleaned.replace(",", ""))
    if match is None:
        return None
    return round(float(match.group(1)) * _MULTIPLIERS[match.group(2).upper()], 4)
