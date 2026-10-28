"""Startup warm must not block readiness / health."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import egxdesk.main as main
from egxdesk.main import app


@pytest.fixture()
def client_with_hanging_warm(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    async def _hang(_svc: object) -> None:
        await asyncio.Event().wait()  # never completes

    monkeypatch.setattr(main.settings, "fetch_quotes_on_startup", True)
    monkeypatch.setattr(main.settings, "auto_refresh_quotes", False)
    monkeypatch.setattr(main.settings, "enable_yahoo_finance", False)
    monkeypatch.setattr(main, "_warm_quote_cache", _hang)
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok_while_startup_warm_hangs(client_with_hanging_warm: TestClient) -> None:
    resp = client_with_hanging_warm.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
