"""Pure alert rule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def evaluate_rule(
    kind: str,
    threshold: float,
    price: float | None,
    previous: float | None = None,
) -> bool:
    """Return True when the live price trips the rule.

    - ``above`` / ``below``: absolute level vs ``price``
    - ``pct_move``: abs percent change vs ``previous`` >= threshold
    - ``points_move``: abs points vs ``previous`` >= threshold
    """
    if price is None:
        return False
    kind = kind.strip().lower()
    if kind == "above":
        return price >= threshold
    if kind == "below":
        return price <= threshold
    if previous is None or previous == 0:
        return False
    delta = price - previous
    if kind == "pct_move":
        return abs(delta / previous * 100.0) >= abs(threshold)
    if kind == "points_move":
        return abs(delta) >= abs(threshold)
    return False


def cooldown_clear(
    last_fired_at: datetime | None,
    cooldown_hours: float,
    *,
    now: datetime | None = None,
) -> bool:
    if last_fired_at is None:
        return True
    current = now or datetime.now(UTC)
    fired = last_fired_at
    if fired.tzinfo is None:
        fired = fired.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current - fired >= timedelta(hours=float(cooldown_hours))
