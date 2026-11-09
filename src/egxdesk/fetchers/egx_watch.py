"""Egyptian Exchange market-watch board (beta.egx.com.eg BFF).

Primary equity quote source. Public delayed indicative prices — not a licensed
real-time feed.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, cast
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

_ATTRIBUTION = ATTRIBUTIONS["egx"]
_CAIRO = ZoneInfo("Africa/Cairo")
_BOARD = "https://beta.egx.com.eg/api/bff/egx/market-watch"
_POINTS = "https://beta.egx.com.eg/api/bff/egx/price-volume-points"
_TTL = 300.0
_PAGE_SIZE = 50
_CHART_DAYS = {
    "1d": 5,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "ytd": 280,
    "1y": 365,
    "5y": 365 * 3,
    "10y": 365 * 3,
    "max": 365 * 3,
}


_board_cache: dict[str, dict[str, Any]] | None = None
_board_loaded_at = 0.0
_board_lock = asyncio.Lock()


class EgxMarketWatchFetcher:
    """Bulk EGX board → per-symbol quotes."""

    name = "egx"

    async def fetch_quote(self, symbol: str) -> QuoteData | None:
        start = time.monotonic()
        try:
            board = await board_cached()
        except Exception as exc:
            log.warning("egx_board_failed", error=str(exc))
            return None
        row = _lookup(board, symbol)
        if row is None:
            return None
        return row_to_quote(row, fetch_duration=round(time.monotonic() - start, 3))


async def board_cached() -> dict[str, dict[str, Any]]:
    global _board_cache, _board_loaded_at
    async with _board_lock:
        if _board_cache is not None and time.monotonic() - _board_loaded_at < _TTL:
            return _board_cache
        board = await asyncio.to_thread(load_board)
        _board_cache = board
        _board_loaded_at = time.monotonic()
        log.info("egx_board_loaded", rows=len({k for k in board if "." not in k}))
        return _board_cache


def load_board(page_size: int = 250, *, force: bool = False) -> dict[str, dict[str, Any]]:
    """Download the market-watch board into a symbol → row map.

    The BFF accepts PascalCase ``Page`` / ``PageSize``. A large page size returns
    the full listed set in one call (~220 rows today). Sync callers share a TTL
    cache unless ``force`` is set.
    """
    global _board_cache, _board_loaded_at
    if (
        not force
        and _board_cache is not None
        and time.monotonic() - _board_loaded_at < _TTL
    ):
        return _board_cache
    first = _fetch_page(1, page_size)
    rows = list(_page_rows(first))
    total_pages = int(first.get("totalPages") or (first.get("data") or {}).get("totalPages") or 1)
    for page in range(2, total_pages + 1):
        rows.extend(_page_rows(_fetch_page(page, page_size)))
    board: dict[str, dict[str, Any]] = {}
    for row in rows:
        for key in _row_keys(row):
            board[key] = row
    _board_cache = board
    _board_loaded_at = time.monotonic()
    return board


def _fetch_page(page: int, page_size: int = _PAGE_SIZE) -> dict[str, Any]:
    query = urllib.parse.urlencode({"Page": page, "PageSize": page_size})
    url = f"{_BOARD}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "x-egx-bff-request": "1",
            "User-Agent": "MirsadMasr/0.1",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload: object = json.loads(response.read().decode("utf-8", "replace"))
    if not isinstance(payload, dict) or not payload.get("success", True):
        raise RuntimeError(f"egx market-watch page {page} failed")
    return cast(dict[str, Any], payload)


def _page_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _row_keys(row: dict[str, Any]) -> list[str]:
    reuters = str(row.get("reuters") or "").strip().upper()
    keys: list[str] = []
    if reuters:
        keys.append(reuters)
        bare = reuters[:-3] if reuters.endswith(".CA") else reuters
        if bare:
            keys.append(bare)
    return keys


def _lookup(board: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any] | None:
    canonical = _canonical(symbol)
    bare = canonical[:-3] if canonical.endswith(".CA") else canonical
    for key in (canonical, bare, symbol.upper(), f"{bare}.CA"):
        row = board.get(key)
        if row is not None:
            return row
    return None


def row_to_quote(row: dict[str, Any], *, fetch_duration: float) -> QuoteData | None:
    reuters = str(row.get("reuters") or "").strip().upper()
    if not reuters:
        return None
    bare = reuters[:-3] if reuters.endswith(".CA") else reuters
    price = _num(row.get("lastPrice"))
    if price is None:
        return None
    previous = _num(row.get("prevClose"))
    change = None if previous is None else round(price - previous, 4)
    chg = _num(row.get("chgPer"))
    change_percent = None if chg is None else f"{chg:+.2f}%"
    currency = _currency(row.get("currShort") or row.get("curr"))
    company = get_symbol_name(bare) or str(row.get("name") or bare)
    company_ar = get_symbol_name_ar(bare) or (str(row["nameA"]) if row.get("nameA") else None)
    sector = get_symbol_sector(bare) or (str(row["sector"]) if row.get("sector") else None)
    updated = _write_time(str(row.get("writeTime") or ""))
    return QuoteData(
        symbol=bare,
        company=company,
        company_ar=company_ar,
        sector=sector,
        price=price,
        change=change,
        change_percent=change_percent,
        volume=_int(row.get("volume")),
        high=_num(row.get("high")),
        low=_num(row.get("low")),
        open=_num(row.get("openPrice")),
        previous_close=previous,
        market_cap=_num(row.get("mc")),
        exchange="EGX",
        currency=currency,
        source=f"Egyptian Exchange ({reuters})",
        api_symbol=reuters,
        fetch_duration=fetch_duration,
        updated_cairo=updated or datetime.now(_CAIRO).strftime("%Y-%m-%d %H:%M:%S"),
        attribution=_ATTRIBUTION,
    )


def _num(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _currency(value: object) -> str:
    text = str(value or "").strip().upper()
    if "US" in text or text in {"$", "USD"}:
        return "USD"
    return "EGP"


def _write_time(stamp: str) -> str | None:
    # EGX writeTime looks like YYYYMMDDHHMM
    if len(stamp) != 12 or not stamp.isdigit():
        return None
    try:
        moment = datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=_CAIRO)
    except ValueError:
        return None
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def chart_history(symbol: str, range_key: str) -> dict[str, Any]:
    """Daily close/volume bars from EGX ``price-volume-points`` (lookback days)."""
    days = _CHART_DAYS.get(range_key, 180)
    board = load_board()
    row = _lookup(board, symbol)
    if row is None:
        return {"ticker": None, "currency": "EGP", "interval": "1d", "bars": []}
    isin = str(row.get("isin") or "").strip()
    reuters = str(row.get("reuters") or "").strip().upper()
    if not isin:
        return {"ticker": reuters or None, "currency": "EGP", "interval": "1d", "bars": []}
    points = _price_volume_points(isin, days)
    bars = []
    for point in points:
        close = _num(point.get("closePrice"))
        if close is None:
            continue
        stamp = str(point.get("tradeDate") or "")[:10]
        if not stamp:
            continue
        volume = _int(point.get("tradeVolume"))
        bars.append(
            {
                "time": stamp,
                "open": close,
                "high": close,
                "low": close,
                "close": round(close, 4),
                "volume": volume,
            }
        )
    return {
        "ticker": reuters or isin,
        "currency": _currency(row.get("currShort") or row.get("curr")),
        "interval": "1d",
        "bars": bars,
    }


def chart_snapshot_from_board(symbol_or_ticker: str) -> dict[str, Any]:
    """Session snapshot from the cached EGX board (equities only)."""
    board = load_board()
    row = _lookup(board, symbol_or_ticker)
    if row is None:
        return {"price": None}
    price = _num(row.get("lastPrice"))
    previous = _num(row.get("prevClose"))
    return {
        "price": price,
        "previous_close": previous,
        "high": _num(row.get("high")),
        "low": _num(row.get("low")),
        "open": _num(row.get("openPrice")),
        "volume": _num(row.get("volume")),
        "average_volume": None,
        "market_cap": _num(row.get("mc")),
        "year_high": None,
        "year_low": None,
        "currency": _currency(row.get("currShort") or row.get("curr")),
        "exchange": "EGX",
    }


def _price_volume_points(isin: str, days: int) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"isin": isin, "date": int(days)})
    url = f"{_POINTS}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "accept": "application/json",
            "x-egx-bff-request": "1",
            "User-Agent": "MirsadMasr/0.1",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        payload: object = json.loads(response.read().decode("utf-8", "replace"))
    if not isinstance(payload, dict) or not payload.get("success", True):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    rows = [item for item in data if isinstance(item, dict)]
    rows.sort(key=lambda item: str(item.get("tradeDate") or ""))
    return rows
