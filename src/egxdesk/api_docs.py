"""Scalar API Reference helpers for MIRSAD MASR docs at /docs."""

from __future__ import annotations

from fastapi.responses import HTMLResponse
from scalar_fastapi import AgentScalarConfig, Theme, get_scalar_api_reference

# Pinned @scalar/api-reference; vendored under /static/scalar for offline docs.
SCALAR_JS_VERSION = "1.76.0"
SCALAR_JS_URL = "/static/scalar/api-reference.min.js"
SCALAR_JS_CDN = (
    f"https://cdn.jsdelivr.net/npm/@scalar/api-reference@{SCALAR_JS_VERSION}"
    "/dist/browser/standalone.min.js"
)

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "Health",
        "description": "Liveness, provider configuration, and runtime counters.",
    },
    {
        "name": "Stocks",
        "description": "EGX symbol catalog and delayed equity quotes (EGP).",
    },
    {
        "name": "Markets",
        "description": "Macro instruments (FX, gold, Brent) and topic headlines.",
    },
    {
        "name": "Metals",
        "description": "Egypt gold and silver desk pages from Starta Markets.",
    },
    {
        "name": "Charts",
        "description": "OHLCV bars for a single EGX listing (Yahoo Finance).",
    },
    {
        "name": "News",
        "description": "Company headlines for a single EGX listing.",
    },
    {
        "name": "Demo",
        "description": "Rate-limited demo quote endpoint for try-before-self-host.",
    },
]

API_DESCRIPTION = """
**MIRSAD MASR** — *Keep Your Eye on Egypt's Markets.*

Unified REST API for Egyptian Exchange (EGX) market data: symbol catalog, delayed
quotes, macro instruments, company news, price charts, and Egypt gold/silver pages.

## Data sources & delay

Quotes and charts come from operator-configured providers (Yahoo Finance, Starta
Markets, optional Alpha Vantage / Finnhub). Values are **delayed / indicative**,
not exchange-grade real-time feeds. Cache TTL defaults to a few minutes.

## Base URL

Use the **Servers** dropdown. Local default: `http://127.0.0.1:8000`.

## Response format

JSON bodies. Quote endpoints set an `X-Data-Source` header with the provider name.
Every request echoes or assigns `X-Request-Id`.

## Auth

**Public — no API key.** Bring your own provider keys when self-hosting; they are
server-side only and never sent from this docs page.

## Rate limits

- `/v1/*` — no application-level rate limit (provider limits still apply).
- `/demo/quote/{symbol}` — **50 requests/day** shared across all visitors.

## Disclaimer

Indicative data only — **not financial advice.** Provider terms, redistribution,
and accuracy remain the operator's responsibility.
""".strip()

# Brand tokens from the MIRSAD MASR board (dark teal + warm paper + gold accent).
SCALAR_CUSTOM_CSS = """
/* MIRSAD MASR brand tokens — dark teal / warm paper / gold accent */
@import url("https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&display=swap");

.light-mode {
  --scalar-color-1: #14201f;
  --scalar-color-2: #3d4f4c;
  --scalar-color-3: #6a7c78;
  --scalar-color-accent: #a8741a;
  --scalar-background-1: #f3f1ea;
  --scalar-background-2: #fffefa;
  --scalar-background-3: #ebe7dc;
  --scalar-background-accent: #a8741a14;
  --scalar-border-color: #dcd8cb;
  --scalar-font: "Instrument Sans", ui-sans-serif, system-ui, sans-serif;
  --scalar-font-code: ui-monospace, "Cascadia Code", "Segoe UI Mono", Menlo, monospace;
  /* HTTP method colors — keep distinguishable, AA on light surfaces. */
  --scalar-color-green: #0c7454;
  --scalar-color-blue: #0a52af;
  --scalar-color-orange: #953800;
  --scalar-color-red: #a33224;
  --scalar-color-yellow: #8a5e12;
  --scalar-color-purple: #5b3d9a;
}
.dark-mode {
  --scalar-color-1: #e7efea;
  --scalar-color-2: #8aa09c;
  --scalar-color-3: #6b807c;
  --scalar-color-accent: #e3b768;
  --scalar-background-1: #0a1315;
  --scalar-background-2: #0e1b1e;
  --scalar-background-3: #112124;
  --scalar-background-accent: #e3b7681f;
  --scalar-border-color: #1f3438;
  --scalar-font: "Instrument Sans", ui-sans-serif, system-ui, sans-serif;
  --scalar-font-code: ui-monospace, "Cascadia Code", "Segoe UI Mono", Menlo, monospace;
  --scalar-color-green: #4fd1a1;
  --scalar-color-blue: #78bffd;
  --scalar-color-orange: #ffa656;
  --scalar-color-red: #ff7f73;
  --scalar-color-yellow: #e3b768;
  --scalar-color-purple: #d2a8ff;
}

.light-mode .sidebar,
.light-mode .t-doc__sidebar {
  --scalar-sidebar-background-1: #fffefa;
  --scalar-sidebar-border-color: #dcd8cb;
  --scalar-sidebar-color-1: #14201f;
  --scalar-sidebar-color-2: #3d4f4c;
  --scalar-sidebar-color-active: #a8741a;
  --scalar-sidebar-item-active-background: #f3e6c8;
  --scalar-sidebar-item-hover-background: #f3f1ea;
  --scalar-sidebar-search-background: #f3f1ea;
  --scalar-sidebar-search-border-color: #dcd8cb;
}
.dark-mode .sidebar,
.dark-mode .t-doc__sidebar {
  --scalar-sidebar-background-1: #0e1b1e;
  --scalar-sidebar-border-color: #1f3438;
  --scalar-sidebar-color-1: #e7efea;
  --scalar-sidebar-color-2: #8aa09c;
  --scalar-sidebar-color-active: #e3b768;
  --scalar-sidebar-item-active-background: #2c2616;
  --scalar-sidebar-item-hover-background: #112124;
  --scalar-sidebar-search-background: #112124;
  --scalar-sidebar-search-border-color: #1f3438;
}
""".strip()


def scalar_docs_response(*, openapi_url: str) -> HTMLResponse:
    """HTMLResponse for the branded Scalar docs page (offline-capable JS)."""
    return get_scalar_api_reference(
        openapi_url=openapi_url,
        title="MIRSAD MASR API",
        scalar_js_url=SCALAR_JS_URL,
        scalar_favicon_url="/static/mirsad-masr-favicon.png",
        theme=Theme.NONE,
        dark_mode=None,  # respect prefers-color-scheme; toggle still shown
        hide_dark_mode_toggle=False,
        with_default_fonts=False,
        custom_css=SCALAR_CUSTOM_CSS,
        default_open_all_tags=False,
        telemetry=False,
        agent=AgentScalarConfig(disabled=True),
        # Verified against Scalar config for @scalar/api-reference@1.76.0 /
        # scalar-fastapi 1.9.1: defaultHttpClient + featuredClients via overrides.
        overrides={
            "defaultHttpClient": {
                "targetKey": "python",
                "clientKey": "requests",
            },
            "featuredClients": [
                "python/requests",
                "shell/curl",
                "js/fetch",
            ],
        },
    )
