"""Pure alert rule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from egxdesk.alerts.rules import cooldown_clear, evaluate_rule


def test_above_and_below() -> None:
    assert evaluate_rule("above", 130.0, 130.0) is True
    assert evaluate_rule("above", 130.0, 129.9) is False
    assert evaluate_rule("below", 100.0, 99.0) is True
    assert evaluate_rule("below", 100.0, 100.0) is True
    assert evaluate_rule("below", 100.0, 101.0) is False


def test_pct_and_points_move() -> None:
    assert evaluate_rule("pct_move", 2.0, 102.0, 100.0) is True
    assert evaluate_rule("pct_move", 2.0, 101.0, 100.0) is False
    assert evaluate_rule("points_move", 5.0, 110.0, 100.0) is True
    assert evaluate_rule("points_move", 5.0, 104.0, 100.0) is False


def test_missing_price_or_previous() -> None:
    assert evaluate_rule("above", 1.0, None) is False
    assert evaluate_rule("pct_move", 1.0, 101.0, None) is False
    assert evaluate_rule("points_move", 1.0, 101.0, 0.0) is False


def test_cooldown() -> None:
    now = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert cooldown_clear(None, 6.0, now=now) is True
    recent = now - timedelta(hours=2)
    assert cooldown_clear(recent, 6.0, now=now) is False
    old = now - timedelta(hours=7)
    assert cooldown_clear(old, 6.0, now=now) is True
