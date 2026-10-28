from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import date
from typing import Annotated, Any

import structlog
import uvicorn
from pathlib import Path as FilePath

from fastapi import Depends, FastAPI, Path, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from egxdesk import __version__
from egxdesk.api_docs import API_DESCRIPTION, OPENAPI_TAGS, scalar_docs_response
from egxdesk.config import settings
from egxdesk.exceptions import DemoRateLimitExceeded, SymbolNotFoundError
from egxdesk.data.symbols import is_valid_symbol
from egxdesk.fetchers.alpha_vantage import AlphaVantageFetcher
from egxdesk.fetchers.base import Fetcher
from egxdesk.fetchers.finnhub import FinnhubFetcher
from egxdesk.fetchers.starta import StartaFetcher
from egxdesk.fetchers.yahoo import YahooFetcher
from egxdesk.logging_config import configure_logging
from egxdesk.middleware import RequestIDMiddleware
from egxdesk.models import (
    BatchQuoteResponse,
    ChartResponse,
    HealthResponse,
    MarketsResponse,
    MetalsResponse,
    NewsResponse,
    QuoteData,
    StatusResponse,
    SymbolListResponse,
)
from egxdesk.services.desk import get_chart, get_company_news, get_markets, get_metals
from egxdesk.services.cache import TTLCacheService
from egxdesk.services.stocks import StocksService

log = structlog.get_logger()

# Shared OpenAPI response fragments (documentation only — handlers unchanged).
_RESP_404: dict[int | str, dict[str, Any]] = {
    404: {
        "description": "Symbol or company not found in the EGX catalog.",
        "content": {
            "application/json": {
                "example": {"detail": "Symbol 'XXXX' not found in EGX symbol list."}
            }
        },
    }
}
_RESP_422: dict[int | str, dict[str, Any]] = {
    422: {"description": "Validation error (invalid path or query parameters)."}
}
_RESP_429: dict[int | str, dict[str, Any]] = {
    429: {
        "description": "Demo daily request limit exceeded (50/day global).",
        "content": {
            "application/json": {
                "example": {
                    "detail": (
                        "The demo endpoint has reached its daily limit of 50 requests. "
                        "Self-host MIRSAD MASR with your own keys for unlimited access."
                    )
                }
            }
        },
    }
}
_RESP_503: dict[int | str, dict[str, Any]] = {
    503: {
        "description": "All configured data providers failed for this request.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "message": "All data providers failed for symbol 'COMI'.",
                        "errors": ["yahoo: timeout"],
                    }
                }
            }
        },
    }
}


async def _scheduled_quote_refresh(svc: StocksService, interval_seconds: int) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            results = await svc.refresh_all_quotes()
            log.info(
                "scheduled_quotes_refreshed",
                succeeded=len(results),
                interval=interval_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("scheduled_quotes_refresh_failed", error=str(exc))


async def _warm_quote_cache(svc: StocksService) -> None:
    try:
        results = await svc.get_all_quotes()
        log.info("startup_quotes_refreshed", succeeded=len(results))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning("startup_quotes_refresh_failed", error=str(exc))


# ── Rate limiter for /demo ────────────────────────────────────────────────────


class _DemoRateLimiter:
    def __init__(self, daily_limit: int) -> None:
        self._limit = daily_limit
        self._count = 0
        self._reset_date = date.today()

    def check_and_increment(self) -> bool:
        today = date.today()
        if today != self._reset_date:
            self._count = 0
            self._reset_date = today
        if self._count >= self._limit:
            return False
        self._count += 1
        return True

    @property
    def count_today(self) -> int:
        return self._count


# ── Service factory ───────────────────────────────────────────────────────────


def _build_fetchers(av_key: str, fh_key: str, enable_yahoo: bool) -> list[Fetcher]:
    """Build the fetcher chain: Yahoo, then Starta for the names Yahoo skips.

    Providers with no key configured are silently omitted.
    Yahoo Finance needs no key and has the best current EGX coverage.
    Starta fills listed companies that Yahoo does not price.
    """
    fetchers: list[Fetcher] = []
    if enable_yahoo:
        fetchers.append(YahooFetcher())
        fetchers.append(StartaFetcher())
    if av_key:
        fetchers.append(AlphaVantageFetcher(av_key))
    if fh_key:
        fetchers.append(FinnhubFetcher(fh_key))
    return fetchers


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level, settings.dev_mode)
    log.info("mirsad_masr_starting", version=__version__)

    normal_cache = TTLCacheService(ttl=settings.cache_ttl_seconds, maxsize=settings.cache_max_size)
    demo_cache = TTLCacheService(
        ttl=settings.demo_cache_ttl_seconds,
        maxsize=settings.cache_max_size,
    )

    app.state.stock_svc = StocksService(
        _build_fetchers(
            settings.alpha_vantage_key,
            settings.finnhub_key,
            settings.enable_yahoo_finance,
        ),
        normal_cache,
    )
    app.state.demo_svc = StocksService(
        _build_fetchers(
            settings.demo_alpha_vantage_key,
            settings.demo_finnhub_key,
            settings.enable_yahoo_finance,
        ),
        demo_cache,
    )
    app.state.demo_limiter = _DemoRateLimiter(settings.demo_daily_limit)

    log.info(
        "mirsad_masr_ready",
        v1_providers=list(app.state.stock_svc.provider_status().keys()),
        demo_providers=list(app.state.demo_svc.provider_status().keys()),
    )

    app.state.quote_refresh_tasks = []
    if settings.fetch_quotes_on_startup:
        app.state.quote_refresh_tasks.append(
            asyncio.create_task(_warm_quote_cache(app.state.stock_svc))
        )
    if settings.auto_refresh_quotes:
        app.state.quote_refresh_tasks.append(
            asyncio.create_task(
                _scheduled_quote_refresh(app.state.stock_svc, settings.cache_ttl_seconds)
            )
        )

    yield

    for task in app.state.quote_refresh_tasks:
        task.cancel()
    for task in app.state.quote_refresh_tasks:
        with suppress(asyncio.CancelledError):
            await task

    log.info("mirsad_masr_stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="MIRSAD MASR",
    summary="Keep Your Eye on Egypt's Markets. — unified EGX market data API",
    description=API_DESCRIPTION,
    version=__version__,
    contact={
        "name": "MIRSAD MASR",
    },
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    servers=[
        {"url": "http://127.0.0.1:8000", "description": "Local development"},
        {"url": "/", "description": "Current host"},
    ],
    openapi_tags=OPENAPI_TAGS,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["GET", "DELETE"],
    allow_headers=["*"],
)


# ── Dependency providers ──────────────────────────────────────────────────────


def get_stock_svc(request: Request) -> StocksService:
    return request.app.state.stock_svc  # type: ignore[no-any-return]


def get_demo_svc(request: Request) -> StocksService:
    return request.app.state.demo_svc  # type: ignore[no-any-return]


def get_demo_limiter(request: Request) -> _DemoRateLimiter:
    return request.app.state.demo_limiter  # type: ignore[no-any-return]


StockSvcDep = Annotated[StocksService, Depends(get_stock_svc)]
DemoSvcDep = Annotated[StocksService, Depends(get_demo_svc)]
DemoLimiterDep = Annotated[_DemoRateLimiter, Depends(get_demo_limiter)]


# ── /v1 router ────────────────────────────────────────────────────────────────

from fastapi import APIRouter  # noqa: E402

v1 = APIRouter(prefix="/v1")


@v1.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="Check service health",
    operation_id="get_health",
    responses={**_RESP_422},
)
async def health(svc: StockSvcDep) -> HealthResponse:
    """Return process status, package version, and which quote providers are configured.

    No auth. Safe to poll for readiness. Does not probe upstream provider APIs.
    """
    return HealthResponse(
        status="ok",
        version=__version__,
        providers_configured=svc.provider_status(),
    )


@v1.get(
    "/markets",
    response_model=MarketsResponse,
    tags=["Markets"],
    summary="List macro markets and headlines",
    operation_id="get_markets",
    responses={**_RESP_422, **_RESP_503},
)
async def markets(
    lang: Annotated[
        str,
        Query(
            description="Headline language: `en` or `ar`.",
            examples=["en"],
        ),
    ] = "en",
) -> MarketsResponse:
    """Dollar, euro, gold, and Brent instruments plus topic headlines.

    Prices are delayed indicative quotes (EGP / USD as noted per instrument).
    Headlines cover Egypt, currencies, oil, wars, flights, and shipping.
    """
    return await get_markets(lang)


@v1.get(
    "/metals/{metal}",
    response_model=MetalsResponse,
    tags=["Metals"],
    summary="Get Egypt gold or silver desk",
    operation_id="get_metals",
    responses={**_RESP_422, **_RESP_503},
)
async def metals(
    metal: Annotated[
        str,
        Path(
            description="Metal desk to load: `gold` or `silver` (other values fall back to gold).",
            examples=["gold"],
        ),
    ],
) -> MetalsResponse:
    """Egypt gold or silver page from Starta Markets (hero, chart, karats, funds).

    Prices are typically **EGP per gram** for karat rows; ounce fields may be USD or EGP
    as labeled in the payload. Data is scraped/parsed from Starta and may lag the live site.
    """
    key = metal.lower().strip()
    if key not in {"gold", "silver"}:
        key = "gold"
    return await get_metals(key)


@v1.get(
    "/chart/{symbol}",
    response_model=ChartResponse,
    tags=["Charts"],
    summary="Get OHLCV chart bars",
    operation_id="get_chart",
    responses={**_RESP_404, **_RESP_422, **_RESP_503},
)
async def chart(
    symbol: Annotated[
        str,
        Path(description="EGX symbol, e.g. `COMI`.", examples=["COMI"]),
    ],
    range_key: Annotated[
        str,
        Query(
            alias="range",
            description=(
                "Lookback window: `1d`, `1mo`, `3mo`, `6mo`, `ytd`, `1y`, `5y`, `10y`, or `max`. "
                "Unknown values fall back to `1mo`. Intraday (`1d`) is often empty on Yahoo."
            ),
            examples=["1mo"],
        ),
    ] = "1mo",
) -> ChartResponse:
    """Daily or monthly Yahoo OHLCV bars for one listing. Currency is usually EGP.

    Bars may be sparse for short ranges. Not real-time.
    """
    if not is_valid_symbol(symbol):
        raise SymbolNotFoundError(symbol.upper())
    allowed = {"1d", "1mo", "3mo", "6mo", "ytd", "1y", "5y", "10y", "max"}
    if range_key not in allowed:
        range_key = "1mo"
    return await get_chart(symbol, range_key)


@v1.get(
    "/news/{symbol}",
    response_model=NewsResponse,
    tags=["News"],
    summary="List company news headlines",
    operation_id="get_company_news",
    responses={**_RESP_404, **_RESP_422, **_RESP_503},
)
async def company_news(
    symbol: Annotated[
        str,
        Path(description="EGX symbol, e.g. `COMI`.", examples=["COMI"]),
    ],
    lang: Annotated[
        str,
        Query(description="Headline language: `en` or `ar`.", examples=["en"]),
    ] = "en",
) -> NewsResponse:
    """Recent headlines for one listed company. Empty `articles` when Yahoo has none."""
    if not is_valid_symbol(symbol):
        raise SymbolNotFoundError(symbol.upper())
    return await get_company_news(symbol, lang)


@v1.get(
    "/stocks",
    response_model=SymbolListResponse,
    tags=["Stocks"],
    summary="List EGX symbols",
    operation_id="list_stocks",
    responses={**_RESP_422},
)
async def list_stocks(
    svc: StockSvcDep,
    sector: Annotated[
        str | None,
        Query(
            description="Optional sector filter (exact match, case-insensitive).",
            examples=["Banks"],
        ),
    ] = None,
) -> SymbolListResponse:
    """Return the EGX symbol catalog (symbol, English/Arabic name, sector)."""
    return svc.list_symbols(sector=sector)


@v1.get(
    "/quote/{symbol}",
    response_model=QuoteData,
    tags=["Stocks"],
    summary="Get one stock quote",
    operation_id="get_stock_quote",
    responses={**_RESP_404, **_RESP_422, **_RESP_503},
)
async def get_quote(
    symbol: Annotated[
        str,
        Path(description="EGX symbol, e.g. `COMI` or `CIBEA`.", examples=["COMI"]),
    ],
    svc: StockSvcDep,
    response: Response,
) -> QuoteData:
    """Delayed indicative quote for one listing (price typically in **EGP**).

    Sets `X-Data-Source` to the provider that answered. Cached per server TTL.
    """
    result = await svc.get_quote(symbol)
    response.headers["X-Data-Source"] = result.attribution.provider
    return result


@v1.get(
    "/quotes",
    response_model=list[QuoteData],
    tags=["Stocks"],
    summary="Get all cached quotes",
    operation_id="get_all_quotes",
    responses={**_RESP_503},
)
async def get_all_quotes(svc: StockSvcDep, response: Response) -> list[QuoteData]:
    """Return every quote currently retrievable from the configured providers.

    Large payload. Prefer `/v1/quotes/batch` when you need a subset.
    """
    results = await svc.get_all_quotes()
    if results:
        response.headers["X-Data-Source"] = results[0].attribution.provider
    return results


@v1.get(
    "/quotes/batch",
    response_model=BatchQuoteResponse,
    tags=["Stocks"],
    summary="Get batch stock quotes",
    operation_id="get_batch_quotes",
    responses={**_RESP_422, **_RESP_503},
)
async def get_batch_quotes(
    svc: StockSvcDep,
    symbols: Annotated[
        str,
        Query(
            description="Comma-separated EGX symbols, e.g. `COMI,ETEL,FWRY`.",
            examples=["COMI,ETEL,FWRY"],
        ),
    ],
) -> BatchQuoteResponse:
    """Fetch several quotes in one call. Failed symbols appear in `failed`."""
    sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
    return await svc.get_batch_quotes(sym_list)


@v1.get(
    "/quote/by-company/{name}",
    response_model=QuoteData,
    tags=["Stocks"],
    summary="Get quote by company name",
    operation_id="get_quote_by_company",
    responses={**_RESP_404, **_RESP_422, **_RESP_503},
)
async def get_quote_by_company(
    name: Annotated[
        str,
        Path(
            description="Partial company name (English or Arabic), e.g. `telecom`.",
            examples=["commercial international"],
        ),
    ],
    svc: StockSvcDep,
    response: Response,
) -> QuoteData:
    """Resolve the first catalog match containing `name`, then return its quote."""
    result = await svc.find_by_company(name)
    response.headers["X-Data-Source"] = result.attribution.provider
    return result


@v1.get(
    "/status",
    response_model=StatusResponse,
    tags=["Health"],
    summary="Get runtime status counters",
    operation_id="get_status",
    responses={**_RESP_422},
)
async def status(
    svc: StockSvcDep,
    limiter: DemoLimiterDep,
) -> StatusResponse:
    """Uptime, symbol count, provider/cache stats, and demo quota usage."""
    return StatusResponse(
        uptime_seconds=round(svc.uptime_seconds(), 1),
        total_symbols=len(svc.list_symbols().symbols),
        provider_stats=svc.provider_stats(),
        cache_stats=svc.cache_stats(),
        demo_requests_today=limiter.count_today,
        demo_daily_limit=settings.demo_daily_limit,
    )


app.include_router(v1)


# ── /demo router ──────────────────────────────────────────────────────────────

demo = APIRouter(prefix="/demo")


@demo.get(
    "/quote/{symbol}",
    response_model=QuoteData,
    tags=["Demo"],
    summary="Demo quote with daily cap",
    operation_id="get_demo_quote",
    responses={**_RESP_404, **_RESP_422, **_RESP_429, **_RESP_503},
    description=(
        "Uses operator-provided demo keys. Hard-limited to **50 requests/day** across all "
        "visitors. Self-host MIRSAD MASR for unlimited access."
    ),
)
async def demo_quote(
    symbol: Annotated[
        str,
        Path(description="EGX symbol.", examples=["COMI"]),
    ],
    svc: DemoSvcDep,
    limiter: DemoLimiterDep,
    response: Response,
) -> QuoteData:
    if not limiter.check_and_increment():
        raise DemoRateLimitExceeded(settings.demo_daily_limit)
    result = await svc.get_quote(symbol)
    response.headers["X-Data-Source"] = result.attribution.provider
    return result


app.include_router(demo)


_HTML_DIR = FilePath(__file__).resolve().parent


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing() -> str:
    return (_HTML_DIR / "landing.html").read_text(encoding="utf-8")


@app.get("/app", response_class=HTMLResponse, include_in_schema=False)
async def board() -> str:
    return (_HTML_DIR / "board.html").read_text(encoding="utf-8")


@app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def scalar_docs() -> HTMLResponse:
    return scalar_docs_response(openapi_url=app.openapi_url or "/openapi.json")


_STATIC_DIR = _HTML_DIR / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "egxdesk.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=False,
    )
