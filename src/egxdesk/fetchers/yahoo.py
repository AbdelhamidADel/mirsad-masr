from __future__ import annotations

import asyncio
import json
import math
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import Any, cast
from zoneinfo import ZoneInfo

import structlog

from egxdesk.data.symbols import (
    get_symbol_name,
    get_symbol_name_ar,
    get_symbol_sector,
    provider_formats,
)
from egxdesk.models import ATTRIBUTIONS, QuoteData

log = structlog.get_logger()

_ATTRIBUTION = ATTRIBUTIONS["yahoo"]
_CAIRO = ZoneInfo("Africa/Cairo")
_CHART = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={rng}"
)
_CHART_RANGES = {
    "1d": ("15m", "1d"),
    "1mo": ("1d", "1mo"),
    "3mo": ("1d", "3mo"),
    "6mo": ("1d", "6mo"),
    "ytd": ("1d", "ytd"),
    "1y": ("1d", "1y"),
    "5y": ("1d", "5y"),
    "10y": ("1d", "10y"),
    "max": ("1mo", "max"),
}


class YahooFetcher:
    """Yahoo chart client. A small pool keeps a full-catalog refresh from getting blocked."""

    name = "yahoo"
    _slots = asyncio.Semaphore(8)

    async def fetch_quote(self, symbol: str) -> QuoteData | None:
        async with self._slots:
            return await self._fetch_quote(symbol)

    async def _fetch_quote(self, symbol: str) -> QuoteData | None:
        start = time.monotonic()
        for fmt in provider_formats(symbol, "yahoo"):
            result = await self._try_format(symbol, fmt, start)
            if result is not None:
                return result
        log.warning("yahoo_all_formats_failed", symbol=symbol)
        return None

    async def _try_format(self, symbol: str, fmt: str, start: float) -> QuoteData | None:
        try:
            snapshot = await _run_sync(partial(_snapshot, fmt))
            price = _num(snapshot["price"])
            if price is None or price <= 0:
                return None

            previous = _num(snapshot["previous_close"])
            change: float | None = None
            change_pct: str | None = None
            if previous is not None and previous > 0:
                change = round(price - previous, 4)
                change_pct = f"{(change / previous * 100):.2f}%"

            volume = _int(snapshot["volume"])
            average_volume = _int(snapshot["average_volume"])
            return QuoteData(
                symbol=symbol.upper(),
                company=get_symbol_name(symbol) or symbol,
                company_ar=get_symbol_name_ar(symbol),
                sector=get_symbol_sector(symbol),
                price=round(price, 4),
                change=change,
                change_percent=change_pct,
                volume=volume,
                high=_round(snapshot["high"]),
                low=_round(snapshot["low"]),
                open=_round(snapshot["open"]),
                previous_close=_round(previous),
                market_cap=_round(snapshot["market_cap"]),
                fifty_two_week_high=_round(snapshot["year_high"]),
                fifty_two_week_low=_round(snapshot["year_low"]),
                average_volume=average_volume,
                exchange=snapshot["exchange"] or None,
                currency=snapshot["currency"] or "EGP",
                source=f"Yahoo Finance ({fmt})",
                api_symbol=fmt,
                fetch_duration=round(time.monotonic() - start, 3),
                updated_cairo=datetime.now(_CAIRO).strftime("%Y-%m-%d %H:%M:%S"),
                attribution=_ATTRIBUTION,
            )
        except Exception as exc:
            log.debug("yahoo_format_failed", fmt=fmt, error=str(exc))
            return None


async def _run_sync(fn: Callable[[], Any]) -> Any:
    return await asyncio.get_event_loop().run_in_executor(None, fn)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _int(value: Any) -> int | None:
    number = _num(value)
    if number is None:
        return None
    return int(number)


def _round(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number, 4)


def chart_snapshot(ticker: str) -> dict[str, Any]:
    """Last daily bar for any Yahoo ticker, including gold, oil, and FX."""
    return _snapshot(ticker)


def chart_history(symbol: str, range_key: str) -> dict[str, Any]:
    """OHLC bars for one catalog symbol. Empty bars mean Yahoo has no series."""
    interval, rng = _CHART_RANGES[range_key]
    ticker = None
    currency = None
    bars: list[dict[str, Any]] = []
    for fmt in provider_formats(symbol, "yahoo"):
        try:
            result = _chart(fmt, interval, rng)
        except Exception:
            continue
        if not result.get("meta") and not result.get("timestamp"):
            continue
        ticker = fmt
        currency = (result.get("meta") or {}).get("currency") or "EGP"
        bars = _bars(result, interval)
        break
    return {
        "ticker": ticker,
        "currency": currency,
        "interval": interval,
        "bars": bars,
    }


def _snapshot(fmt: str) -> dict[str, Any]:
    result = _chart(fmt)
    meta = result.get("meta") or {}
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    last = next((index for index in range(len(closes) - 1, -1, -1) if _num(closes[index])), None)
    if last is None:
        return {"price": None}

    def at(name: str) -> float | None:
        series = quote.get(name) or []
        if last >= len(series):
            return None
        return _num(series[last])

    previous = next(
        (
            _num(closes[index])
            for index in range(last - 1, -1, -1)
            if _num(closes[index]) is not None
        ),
        None,
    )
    if previous is None:
        previous = _num(meta.get("chartPreviousClose")) or _num(meta.get("previousClose"))
    volumes = [_num(value) for value in (quote.get("volume") or [])]
    known = [value for value in volumes if value is not None]
    average = round(sum(known) / len(known), 4) if known else None
    return {
        "price": _num(closes[last]),
        "previous_close": previous,
        "high": at("high"),
        "low": at("low"),
        "open": at("open"),
        "volume": at("volume"),
        "average_volume": average,
        "market_cap": None,
        "year_high": meta.get("fiftyTwoWeekHigh"),
        "year_low": meta.get("fiftyTwoWeekLow"),
        "currency": meta.get("currency") or "EGP",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
    }


def _bars(result: dict[str, Any], interval: str) -> list[dict[str, Any]]:
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    clock = "%Y-%m-%d" if interval in {"1d", "1wk", "1mo"} else "%Y-%m-%d %H:%M"
    bars = []
    for index, stamp in enumerate(stamps):
        close = _num(_at(closes, index))
        if close is None:
            continue
        try:
            moment = datetime.fromtimestamp(int(stamp), tz=_CAIRO)
        except (TypeError, ValueError, OSError):
            continue
        volume = _int(_at(volumes, index))
        bars.append(
            {
                "time": moment.strftime(clock),
                "open": _round(_at(opens, index)),
                "high": _round(_at(highs, index)),
                "low": _round(_at(lows, index)),
                "close": _round(close),
                "volume": volume,
            }
        )
    return bars


def _at(series: list[Any], index: int) -> Any:
    if index >= len(series):
        return None
    return series[index]


def _chart(fmt: str, interval: str = "1d", rng: str = "1y") -> dict[str, Any]:
    request = urllib.request.Request(
        _CHART.format(ticker=urllib.parse.quote(fmt), interval=interval, rng=rng),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    results = ((payload.get("chart") or {}).get("result")) or []
    if not results:
        return {}
    return cast(dict[str, Any], results[0])
