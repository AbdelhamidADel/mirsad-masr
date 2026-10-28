"""Smoke tests for Scalar /docs and OpenAPI tag metadata."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import egxdesk.main as main
from egxdesk.main import app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(main.settings, "fetch_quotes_on_startup", False)
    monkeypatch.setattr(main.settings, "auto_refresh_quotes", False)
    monkeypatch.setattr(main.settings, "alpha_vantage_key", "")
    monkeypatch.setattr(main.settings, "finnhub_key", "")
    monkeypatch.setattr(main.settings, "demo_alpha_vantage_key", "")
    monkeypatch.setattr(main.settings, "demo_finnhub_key", "")
    monkeypatch.setattr(main.settings, "enable_yahoo_finance", False)
    with TestClient(app) as test_client:
        yield test_client


EXPECTED_TAGS = {"Health", "Stocks", "Markets", "Metals", "Charts", "News", "Demo"}


def test_docs_returns_200(client: TestClient) -> None:
    resp = client.get("/docs")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert "MIRSAD MASR" in body
    assert "/static/scalar/api-reference.min.js" in body
    assert "/static/mirsad-masr-favicon.png" in body


def test_openapi_contains_expected_tags(client: TestClient) -> None:
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["info"]["title"] == "MIRSAD MASR"
    tag_names = {t["name"] for t in payload.get("tags", [])}
    assert EXPECTED_TAGS.issubset(tag_names)
    # Every documented path operation uses one of the expected tags.
    for path_item in payload["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags") or []
            assert tags, "operation missing tags"
            assert set(tags) <= EXPECTED_TAGS
