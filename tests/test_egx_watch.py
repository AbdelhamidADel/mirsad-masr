"""EGX market-watch BFF → QuoteData mapping and pagination."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from egxdesk.fetchers import egx_watch

FIXTURES = Path(__file__).parent / "fixtures"


def _page(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_row_to_quote_maps_comi() -> None:
    row = _page("egx_market_watch_page1.json")["data"]["data"][0]
    quote = egx_watch.row_to_quote(row, fetch_duration=0.01)
    assert quote is not None
    assert quote.symbol == "COMI"
    assert quote.api_symbol == "COMI.CA"
    assert quote.price == pytest.approx(128.33)
    assert quote.previous_close == pytest.approx(127.31)
    assert quote.change == pytest.approx(1.02)
    assert quote.change_percent == "+0.61%"
    assert quote.volume == 1434965
    assert quote.high == pytest.approx(128.5)
    assert quote.low == pytest.approx(127.0)
    assert quote.open == pytest.approx(127.31)
    assert quote.currency == "EGP"
    assert quote.attribution.provider == "Egyptian Exchange"


def test_index_board_merges_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        1: _page("egx_market_watch_page1.json"),
        2: _page("egx_market_watch_page2.json"),
    }

    def fake_fetch(page: int, page_size: int = 250) -> dict:
        assert page_size == 250
        return pages[page]

    monkeypatch.setattr(egx_watch, "_fetch_page", fake_fetch)
    board = egx_watch.load_board()
    assert set(board) >= {"COMI", "ETEL", "HRHO", "COMI.CA", "ETEL.CA", "HRHO.CA"}
    assert board["COMI"]["lastPrice"] == 128.33
    assert board["HRHO"]["lastPrice"] == 20.0


@pytest.mark.asyncio
async def test_fetcher_returns_quote_from_cached_board(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {1: _page("egx_market_watch_page1.json"), 2: _page("egx_market_watch_page2.json")}
    monkeypatch.setattr(egx_watch, "_fetch_page", lambda page, page_size=250: pages[page])
    egx_watch._board_cache = None
    egx_watch._board_loaded_at = 0.0
    fetcher = egx_watch.EgxMarketWatchFetcher()
    quote = await fetcher.fetch_quote("comi")
    assert quote is not None
    assert quote.symbol == "COMI"
    assert "Egyptian Exchange" in quote.source


def test_chart_history_builds_bars_from_points(monkeypatch: pytest.MonkeyPatch) -> None:
    board_row = {
        "reuters": "COMI.CA",
        "isin": "EGS60121C018",
        "currShort": "L.E",
        # No lastPrice → do not append a live "today" tip bar in this unit test.
    }
    monkeypatch.setattr(
        egx_watch,
        "load_board",
        lambda page_size=250, force=False: {"COMI": board_row, "COMI.CA": board_row},
    )
    monkeypatch.setattr(
        egx_watch,
        "_price_volume_points",
        lambda isin, days: [
            {"tradeDate": "2026-11-01T00:00:00", "closePrice": 120.0, "tradeVolume": 10},
            {"tradeDate": "2026-11-08T00:00:00", "closePrice": 128.0, "tradeVolume": 20},
        ],
    )
    payload = egx_watch.chart_history("COMI", "1mo")
    assert payload["ticker"] == "COMI.CA"
    assert payload["source"] == "Egyptian Exchange (COMI.CA)"
    assert len(payload["bars"]) == 2
    assert payload["bars"][0]["open"] == 120.0
    assert payload["bars"][1]["open"] == 120.0  # previous close
    assert payload["bars"][1]["close"] == 128.0
    assert payload["bars"][1]["high"] == 128.0
    assert payload["bars"][1]["low"] == 120.0
    assert payload["bars"][-1]["volume"] == 20


def test_index_live_maps_case30(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _page("egx_index_data_case30.json")

    def fake_fetch(index_name: str) -> dict:
        assert index_name == "CASE30"
        return payload

    monkeypatch.setattr(egx_watch, "_fetch_index_data", fake_fetch)
    egx_watch._index_cache.clear()
    egx_watch._index_loaded_at.clear()
    snap = egx_watch.index_live("CASE30")
    assert snap["price"] == pytest.approx(51414.93)
    assert snap["change"] == pytest.approx(602.86)
    assert snap["change_percent"] == pytest.approx(1.1864503847215828)


def test_index_live_empty_when_no_live_index(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        egx_watch,
        "_fetch_index_data",
        lambda index_name: {"success": True, "data": {"liveIndex": None}},
    )
    egx_watch._index_cache.clear()
    egx_watch._index_loaded_at.clear()
    snap = egx_watch.index_live("EGX35LV")
    assert snap["price"] is None
    assert snap["change"] is None
    assert snap["change_percent"] is None


def test_chart_history_appends_live_board_price(monkeypatch: pytest.MonkeyPatch) -> None:
    board_row = {
        "reuters": "COMI.CA",
        "isin": "EGS60121C018",
        "currShort": "L.E",
        "lastPrice": 129.5,
        "volume": 99,
    }
    monkeypatch.setattr(
        egx_watch,
        "load_board",
        lambda page_size=250, force=False: {"COMI": board_row, "COMI.CA": board_row},
    )
    monkeypatch.setattr(
        egx_watch,
        "_price_volume_points",
        lambda isin, days: [
            {"tradeDate": "2026-11-08T00:00:00", "closePrice": 128.0, "tradeVolume": 20},
        ],
    )
    payload = egx_watch.chart_history("COMI", "1mo")
    assert payload["bars"][-1]["close"] == 129.5
    assert payload["bars"][-1]["open"] == 128.0
    assert payload["bars"][-1]["volume"] == 99
