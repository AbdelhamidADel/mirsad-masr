"""Resolve live prices for alert targets."""

from __future__ import annotations

from typing import Any

import structlog

from egxdesk.fetchers import egx_watch
from egxdesk.services.desk import _INDICES, _INSTRUMENTS, _external_snapshot
from egxdesk.services.starta_metals import load_metal

log = structlog.get_logger()


def resolve_quote(target_type: str, target_id: str) -> dict[str, Any]:
    """Return ``{price, previous, label}`` for a watch target."""
    kind = target_type.strip().lower()
    tid = target_id.strip()
    try:
        if kind == "stock":
            return _stock(tid)
        if kind == "index":
            return _index_level(tid)
        if kind == "fx":
            return _fx(tid)
        if kind == "gold":
            return _gold(tid)
    except Exception as exc:
        log.warning("alert_price_failed", type=kind, id=tid, error=str(exc))
    return {"price": None, "previous": None, "label": tid}


def _stock(symbol: str) -> dict[str, Any]:
    board = egx_watch.load_board()
    row = egx_watch._lookup(board, symbol)
    if row is None:
        return {"price": None, "previous": None, "label": symbol.upper()}
    price = egx_watch._num(row.get("lastPrice"))
    previous = egx_watch._num(row.get("prevClose"))
    reuters = str(row.get("reuters") or symbol).upper()
    return {"price": price, "previous": previous, "label": reuters}


def _index_level(index_name: str) -> dict[str, Any]:
    snap = egx_watch.index_live(index_name)
    price = snap.get("price")
    change = snap.get("change")
    previous = None
    if price is not None and change is not None:
        previous = price - change
    label = index_name
    for item in _INDICES:
        if item.get("index_name") == index_name:
            label = str(item.get("name") or index_name)
            break
    return {"price": price, "previous": previous, "label": label}


def _fx(fx_id: str) -> dict[str, Any]:
    key = fx_id.strip().lower()
    for item in _INSTRUMENTS:
        if item["id"] == key or item["ticker"].lower() == key:
            snap = _external_snapshot(item["ticker"])
            price = snap.get("price")
            previous = snap.get("previous_close")
            price = float(price) if isinstance(price, (int, float)) else None
            previous = float(previous) if isinstance(previous, (int, float)) else None
            return {"price": price, "previous": previous, "label": str(item["name"])}
    return {"price": None, "previous": None, "label": fx_id}


def _gold(gold_id: str) -> dict[str, Any]:
    """Starta Egypt gold — prefer 21K row buy/sell midpoint when present."""
    raw: dict[str, Any] = load_metal("gold")
    label = "Gold 21K"
    price: float | None = None
    previous: float | None = None
    hero = raw.get("hero") or {}
    if isinstance(hero, dict):
        for key in ("price", "egp", "value"):
            val = hero.get(key)
            if isinstance(val, (int, float)):
                price = float(val)
                break
    for row in raw.get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("label") or row.get("karat") or "").upper()
        if "21" in name or gold_id.upper() in ("GOLD_21K", "21K", "GOLD"):
            buy = row.get("buy") if isinstance(row.get("buy"), (int, float)) else None
            sell = row.get("sell") if isinstance(row.get("sell"), (int, float)) else None
            if buy is not None and sell is not None:
                price = (float(buy) + float(sell)) / 2.0
            elif sell is not None:
                price = float(sell)
            elif buy is not None:
                price = float(buy)
            label = str(row.get("label") or "Gold 21K")
            break
    # No reliable previous on Starta snapshot — pct/points rules need previous;
    # absolute above/below still work.
    return {"price": price, "previous": previous, "label": label}
