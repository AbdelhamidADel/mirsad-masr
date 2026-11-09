"""EGX indices on the markets desk (no Yahoo for index levels)."""

from __future__ import annotations

from egxdesk.services import desk


def test_indices_catalog_has_eight_egx_keys() -> None:
    keys = [item["index_name"] for item in desk._INDICES]
    assert keys == [
        "CASE30",
        "EGX_SHARIAH",
        "EGX35LV",
        "EGX100_EWI",
        "EGX70_EWI",
        "EGX30_CAP",
        "EGX30_TR",
        "TAMAYUZ",
    ]


def test_index_uses_egx_live_not_yahoo(monkeypatch) -> None:
    calls: list[str] = []

    def fake_live(index_name: str) -> dict[str, float | None]:
        calls.append(index_name)
        return {"price": 100.0, "change": 1.5, "change_percent": 1.52}

    def boom(ticker: str) -> dict:
        raise AssertionError(f"Yahoo snapshot must not run for indices: {ticker}")

    monkeypatch.setattr(desk, "index_live", fake_live)
    monkeypatch.setattr(desk, "yahoo_chart_snapshot", boom)

    card = desk._index(desk._INDICES[0])
    assert card.id == "egx30"
    assert card.price == 100.0
    assert card.change == 1.5
    assert card.change_percent == "+1.52%"
    assert card.ticker == "CASE30"
    assert calls == ["CASE30"]

    # New cards from the EGX page expansion
    lv = desk._index(next(i for i in desk._INDICES if i["id"] == "egx35_lv"))
    tr = desk._index(next(i for i in desk._INDICES if i["id"] == "egx30_tr"))
    assert lv.price == 100.0
    assert tr.price == 100.0
    assert "EGX35LV" in calls and "EGX30_TR" in calls
