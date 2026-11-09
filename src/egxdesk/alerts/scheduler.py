"""In-process alert tick loop."""

from __future__ import annotations

import asyncio

import structlog

from egxdesk.alerts.db import init_db, session_scope
from egxdesk.alerts.service import run_tick
from egxdesk.config import settings

log = structlog.get_logger()

_last_digest_date: str | None = None


async def alerts_loop(interval_seconds: int = 900) -> None:
    """Every ``interval_seconds`` (default 15 min) evaluate session alerts + digest."""
    global _last_digest_date
    while True:
        await asyncio.sleep(interval_seconds)
        if not settings.alerts_enabled:
            continue
        if not settings.database_url.strip():
            log.warning("alerts_loop_no_database")
            continue
        try:
            init_db()
            with session_scope() as session:
                result = run_tick(session, last_digest_date=_last_digest_date)
            if result.get("digest_date"):
                _last_digest_date = str(result["digest_date"])
            log.info("alerts_tick", **{k: v for k, v in result.items() if k != "cairo"})
        except Exception as exc:
            log.warning("alerts_tick_failed", error=str(exc))
