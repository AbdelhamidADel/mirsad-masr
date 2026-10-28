from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Attribution(BaseModel):
    model_config = ConfigDict(title="Attribution")

    provider: str = Field(
        description="Human-readable data provider name.",
        examples=["Yahoo Finance"],
    )
    url: str = Field(
        description="Provider homepage or attribution URL.",
        examples=["https://finance.yahoo.com"],
    )


ATTRIBUTIONS: dict[str, Attribution] = {
    "alpha_vantage": Attribution(provider="Alpha Vantage", url="https://www.alphavantage.co"),
    "finnhub": Attribution(provider="Finnhub", url="https://finnhub.io"),
    "yahoo": Attribution(provider="Yahoo Finance", url="https://finance.yahoo.com"),
    "starta": Attribution(provider="Starta Markets", url="https://startamarkets.com/companies"),
}


class QuoteData(BaseModel):
    """Delayed indicative equity quote for one EGX listing."""

    model_config = ConfigDict(title="StockQuote")

    symbol: str = Field(description="Canonical EGX symbol.", examples=["COMI"])
    company: str = Field(
        description="Company name (English).",
        examples=["Commercial International Bank Egypt (CIB) S.A.E."],
    )
    company_ar: str | None = Field(
        default=None,
        description="Company name (Arabic) when available.",
        examples=["البنك التجاري الدولي"],
    )
    sector: str | None = Field(
        default=None,
        description="Sector label from the catalog.",
        examples=["Banks"],
    )
    price: float = Field(description="Last price, typically in EGP.", examples=[122.03])
    change: float | None = Field(
        default=None,
        description="Absolute price change vs previous close.",
        examples=[1.25],
    )
    change_percent: str | None = Field(
        default=None,
        description="Percent change as returned by the provider (string).",
        examples=["+1.03%"],
    )
    volume: int | None = Field(default=None, description="Session volume.", examples=[3579806])
    high: float | None = Field(default=None, description="Session high.", examples=[123.5])
    low: float | None = Field(default=None, description="Session low.", examples=[120.1])
    open: float | None = Field(default=None, description="Session open.", examples=[121.0])
    previous_close: float | None = Field(
        default=None,
        description="Previous session close.",
        examples=[120.78],
    )
    market_cap: float | None = Field(
        default=None,
        description="Market capitalization when provided.",
        examples=[2.1e11],
    )
    fifty_two_week_high: float | None = Field(
        default=None,
        description="52-week high.",
        examples=[145.0],
    )
    fifty_two_week_low: float | None = Field(
        default=None,
        description="52-week low.",
        examples=[78.5],
    )
    average_volume: int | None = Field(
        default=None,
        description="Average volume when provided.",
        examples=[2500000],
    )
    exchange: str | None = Field(
        default=None,
        description="Exchange code when provided.",
        examples=["CAI"],
    )
    currency: str = Field(default="EGP", description="Quote currency.", examples=["EGP"])
    source: str = Field(
        description="Provider label including the ticker that answered.",
        examples=["Yahoo Finance (COMI.CA)"],
    )
    api_symbol: str = Field(
        description="Ticker format that actually returned data.",
        examples=["COMI.CA"],
    )
    fetch_duration: float = Field(
        description="Upstream fetch duration in seconds.",
        examples=[1.212],
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this payload was built.",
    )
    updated_cairo: str | None = Field(
        default=None,
        description="Cairo-local update label when available.",
        examples=["2026-10-28 14:32"],
    )
    attribution: Attribution = Field(description="Provider attribution block.")


class SymbolEntry(BaseModel):
    model_config = ConfigDict(title="SymbolEntry")

    symbol: str = Field(description="EGX symbol.", examples=["COMI"])
    name: str = Field(
        description="Company name (English).",
        examples=["Commercial International Bank Egypt (CIB) S.A.E."],
    )
    name_ar: str | None = Field(
        default=None,
        description="Company name (Arabic) when available.",
    )
    sector: str | None = Field(default=None, description="Sector name.", examples=["Banks"])


class SymbolListResponse(BaseModel):
    model_config = ConfigDict(title="SymbolListResponse")

    count: int = Field(description="Number of symbols in `symbols`.", examples=[180])
    symbols: list[SymbolEntry] = Field(description="Catalog entries.")


class BatchQuoteResponse(BaseModel):
    model_config = ConfigDict(title="BatchQuoteResponse")

    results: list[QuoteData] = Field(description="Successfully fetched quotes.")
    failed: list[str] = Field(
        description="Symbols that could not be fetched.",
        examples=[["XXXX"]],
    )


class ProviderStats(BaseModel):
    model_config = ConfigDict(title="ProviderStats")

    requests: int = Field(description="Total requests attempted.", examples=[42])
    successes: int = Field(description="Successful responses.", examples=[40])
    failures: int = Field(description="Failed responses.", examples=[2])


class StatusResponse(BaseModel):
    model_config = ConfigDict(title="StatusResponse")

    uptime_seconds: float = Field(description="Process uptime in seconds.", examples=[3600.5])
    total_symbols: int = Field(description="Symbols in the EGX catalog.", examples=[180])
    provider_stats: dict[str, ProviderStats] = Field(
        description="Per-provider request counters keyed by fetcher name."
    )
    cache_stats: dict[str, Any] = Field(description="Cache size / hit statistics.")
    demo_requests_today: int = Field(
        description="Demo endpoint requests counted today.",
        examples=[12],
    )
    demo_daily_limit: int = Field(
        description="Demo endpoint daily cap.",
        examples=[50],
    )


class HealthResponse(BaseModel):
    model_config = ConfigDict(title="HealthResponse")

    status: str = Field(description="Health status string.", examples=["ok"])
    version: str = Field(description="Package version.", examples=["0.1.0"])
    providers_configured: dict[str, bool] = Field(
        description="Configured quote providers (name → true when present)."
    )


class Headline(BaseModel):
    model_config = ConfigDict(title="Headline")

    title: str = Field(description="Headline text.", examples=["EGX closes mixed"])
    publisher: str | None = Field(default=None, description="Publisher name.", examples=["Reuters"])
    link: str | None = Field(default=None, description="Article URL when available.")
    published: str | None = Field(
        default=None,
        description="Publication timestamp as provided by the source.",
    )
    topic: str | None = Field(
        default=None,
        description="Topic bucket (e.g. egypt, oil, shipping).",
        examples=["egypt"],
    )


class MarketInstrument(BaseModel):
    model_config = ConfigDict(title="MarketInstrument")

    id: str = Field(description="Stable instrument id.", examples=["usd_egp"])
    name: str = Field(description="Display name (English).", examples=["US Dollar"])
    ticker: str = Field(description="Underlying ticker or code.", examples=["USD/EGP"])
    price: float | None = Field(default=None, description="Last price.", examples=[48.5])
    change: float | None = Field(default=None, description="Absolute change.")
    change_percent: str | None = Field(default=None, description="Percent change string.")
    currency: str | None = Field(default=None, description="Price currency when applicable.")
    unit: str = Field(description="Unit label (English).", examples=["EGP"])
    name_ar: str | None = Field(default=None, description="Display name (Arabic).")
    unit_ar: str | None = Field(default=None, description="Unit label (Arabic).")


class IndexInsight(BaseModel):
    model_config = ConfigDict(title="IndexInsight")

    id: str = Field(description="Insight id.", examples=["egx30"])
    name: str = Field(description="Display name.", examples=["EGX 30"])
    description: str = Field(description="Short English description.")
    ticker: str | None = Field(default=None, description="Related ticker when available.")
    price: float | None = Field(default=None, description="Index level when available.")
    change: float | None = Field(default=None, description="Absolute change.")
    change_percent: str | None = Field(default=None, description="Percent change string.")
    name_ar: str | None = Field(default=None, description="Arabic name.")
    description_ar: str | None = Field(default=None, description="Arabic description.")


class MarketsResponse(BaseModel):
    model_config = ConfigDict(title="MarketsResponse")

    updated_cairo: str = Field(description="Cairo-local update stamp.")
    instruments: list[MarketInstrument] = Field(description="FX, gold, Brent, and related.")
    headlines: list[Headline] = Field(description="Topic headlines.")
    indices: list[IndexInsight] = Field(
        default_factory=list,
        description="Optional index insight cards.",
    )


class NewsResponse(BaseModel):
    model_config = ConfigDict(title="NewsResponse")

    symbol: str = Field(description="Requested EGX symbol.", examples=["COMI"])
    company: str | None = Field(default=None, description="Resolved company name.")
    articles: list[Headline] = Field(description="Recent headlines (may be empty).")


class MetalRow(BaseModel):
    model_config = ConfigDict(title="MetalRow")

    label: str = Field(description="Karat / fineness label.", examples=["21K"])
    purity: str | None = Field(
        default=None, description="Purity fraction string.", examples=["0.875"]
    )
    price: float | None = Field(
        default=None,
        description="Price in the row unit (usually EGP per gram).",
        examples=[6337.0],
    )
    change_percent: float | None = Field(
        default=None,
        description="Percent change for this row.",
        examples=[-0.22],
    )
    unit: str = Field(
        default="EGP per gram",
        description="Price unit.",
        examples=["EGP per gram"],
    )


class MetalHero(BaseModel):
    model_config = ConfigDict(title="MetalHero")

    label: str | None = Field(default=None, description="Hero label.", examples=["21K per gram"])
    price: float | None = Field(default=None, description="Hero price.", examples=[6337.0])
    change_percent: float | None = Field(default=None, description="Hero percent change.")
    currency: str = Field(default="EGP", description="Hero currency.", examples=["EGP"])


class MetalBuilder(BaseModel):
    model_config = ConfigDict(title="MetalBuilder")

    source: str | None = Field(default=None, description="Builder source label.")
    ounce_usd: float | None = Field(default=None, description="Ounce price in USD.")
    usd_egp: float | None = Field(default=None, description="USD/EGP FX used in the build.")
    grams_per_oz: float | None = Field(
        default=None,
        description="Grams per troy ounce (typically 31.1035).",
        examples=[31.1035],
    )
    base_label: str | None = Field(default=None, description="Base karat/fineness label.")
    base_price_egp: float | None = Field(
        default=None,
        description="Base gram price in EGP.",
    )


class MetalExtraItem(BaseModel):
    model_config = ConfigDict(title="MetalExtraItem")

    label: str | None = Field(default=None, description="Extra item label.")
    price_egp: float | None = Field(default=None, description="Price in EGP.")
    price_usd: float | None = Field(default=None, description="Price in USD.")
    change_percent: float | None = Field(default=None, description="Percent change.")


class MetalExtras(BaseModel):
    model_config = ConfigDict(title="MetalExtras")

    gold_pound: MetalExtraItem | None = Field(default=None, description="Gold pound quote.")
    ounce_egp: MetalExtraItem | None = Field(default=None, description="Ounce in EGP.")
    ounce_usd: MetalExtraItem | None = Field(default=None, description="Ounce in USD.")


class MetalFund(BaseModel):
    model_config = ConfigDict(title="MetalFund")

    name: str = Field(description="Fund name.")
    href: str | None = Field(default=None, description="Fund detail URL.")
    unit_price_egp: float | None = Field(default=None, description="Unit price in EGP.")
    return_6m_percent: float | None = Field(default=None, description="6-month return %.")
    return_ytd_percent: float | None = Field(default=None, description="Year-to-date return %.")


class MetalChartPoint(BaseModel):
    model_config = ConfigDict(title="MetalChartPoint")

    time: str = Field(description="Point timestamp as provided by Starta.")
    value: float = Field(description="Series value.")


class MetalChartRange(BaseModel):
    model_config = ConfigDict(title="MetalChartRange")

    key: str = Field(
        description="Range key (e.g. `1M`, `6M`, `1Y`).",
        examples=["1M"],
    )
    label: str = Field(description="Display label.", examples=["1 Month"])
    points: list[MetalChartPoint] = Field(
        default_factory=list,
        description="Series points for this range.",
    )


class MetalZakat(BaseModel):
    model_config = ConfigDict(title="MetalZakat")

    nisab_headline_egp: float | None = Field(default=None, description="Headline nisab in EGP.")
    nisab_21k_egp: float | None = Field(default=None, description="21K nisab in EGP.")
    nisab_24k_egp: float | None = Field(default=None, description="24K nisab in EGP.")
    zakat_rate_percent: float | None = Field(default=None, description="Zakat rate percent.")
    nisab_grams: float | None = Field(
        default=85,
        description="Nisab weight in grams.",
        examples=[85],
    )
    convention: str | None = Field(default=None, description="Calculation convention note.")


class MetalsResponse(BaseModel):
    model_config = ConfigDict(title="MetalsResponse")

    metal: str = Field(description="Requested metal: `gold` or `silver`.", examples=["gold"])
    title: str = Field(description="Page title.")
    source: str = Field(description="Source label.", examples=["Starta Markets"])
    source_url: str = Field(description="Source page URL.")
    updated: str | None = Field(default=None, description="Source update stamp.")
    updated_cairo: str | None = Field(default=None, description="Cairo-local update stamp.")
    note: str = Field(description="Disclaimer / parsing note.")
    hero: MetalHero | None = Field(default=None, description="Hero price card.")
    builder: MetalBuilder | None = Field(default=None, description="Price build breakdown.")
    performance: dict[str, float] | None = Field(
        default=None,
        description="Performance map keyed by period label (e.g. 1W, 1M, 1Y).",
    )
    rows: list[MetalRow] = Field(
        default_factory=list,
        description="Karat / fineness price rows.",
    )
    extras: MetalExtras | None = Field(default=None, description="Pound / ounce extras.")
    funds: list[MetalFund] = Field(default_factory=list, description="Related funds.")
    chart_ranges: list[MetalChartRange] = Field(
        default_factory=list,
        description="Chart series by range key.",
    )
    chart_caption: str | None = Field(default=None, description="Chart caption.")
    zakat: MetalZakat | None = Field(default=None, description="Zakat helpers (gold).")


class ChartBar(BaseModel):
    model_config = ConfigDict(title="ChartBar")

    time: str = Field(description="Bar timestamp.")
    open: float | None = Field(default=None, description="Open.")
    high: float | None = Field(default=None, description="High.")
    low: float | None = Field(default=None, description="Low.")
    close: float | None = Field(default=None, description="Close.")
    volume: int | None = Field(default=None, description="Volume.")


class ChartResponse(BaseModel):
    model_config = ConfigDict(title="ChartResponse")

    symbol: str = Field(description="Requested EGX symbol.", examples=["COMI"])
    currency: str | None = Field(default=None, description="Bar currency.", examples=["EGP"])
    range: str = Field(description="Resolved range key.", examples=["1mo"])
    interval: str = Field(description="Bar interval (`15m`, `1d`, `1mo`, …).", examples=["1d"])
    source: str | None = Field(default=None, description="Data source label.")
    bars: list[ChartBar] = Field(description="OHLCV bars (may be empty).")
