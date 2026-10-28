"""Market strip and headlines around the Egyptian Exchange.

Gold, Brent, and the pound are read from Yahoo's chart feed. Market headlines
for the pound, gold, and oil come from Yahoo search plus Google News RSS when
Yahoo is thin or noisy. When ``lang=ar``, those wires are skipped and real
Arabic sources are fetched instead (Google News EG/ar, BBC Arabic) — never
machine-translated English titles. Egyptian exchange headlines come from the
official EGX media-center BFF (trading session news plus disclosures / members /
listing). English (``lang=en``) prefers the same fields as ``/en/media-center``
(``heading``, ``Subject`` / Latin content) and skips Arabic-only trading bodies;
Arabic keeps العنوان / مضمون lines unchanged. War, flight, and shipping headlines
come from public BBC and Guardian feeds (plus Google News for thin topics), and
only a story whose title is about that subject is kept. Company headlines come
from the public Mubasher page for that listing (Arabic host when ``lang=ar``;
news, then exchange announcements). Yahoo search is only an English fallback for
company pages. A miss returns an empty list rather than a made-up story.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from egxdesk.data.symbols import get_symbol_name
from egxdesk.fetchers.yahoo import chart_history, chart_snapshot
from egxdesk.models import (
    ChartBar,
    ChartResponse,
    Headline,
    IndexInsight,
    MarketInstrument,
    MarketsResponse,
    MetalBuilder,
    MetalChartPoint,
    MetalChartRange,
    MetalExtraItem,
    MetalExtras,
    MetalFund,
    MetalHero,
    MetalRow,
    MetalZakat,
    MetalsResponse,
    NewsResponse,
)
from egxdesk.services.starta_metals import load_metal

_CAIRO = ZoneInfo("Africa/Cairo")
_SEARCH = "https://query2.finance.yahoo.com/v1/finance/search?q={query}&newsCount={count}&quotesCount=0"
_MUBASHER = "https://english.mubasher.info/markets/EGX/stocks/{symbol}/{kind}"
_MUBASHER_AR = "https://www.mubasher.info/markets/EGX/stocks/{symbol}/{kind}"
_MUBASHER_HOST = "https://english.mubasher.info"
_MUBASHER_HOST_AR = "https://www.mubasher.info"
_TTL = 300.0
_NEWS_CARD = re.compile(
    r'class="mi-article-media-block__date">([^<]*)</span>\s*'
    r'.*?<a class="mi-article-media-block__title" href="([^"]+)">([^<]*)</a>',
    re.S,
)
_GENERIC_NAME = {
    "bank",
    "banks",
    "company",
    "egypt",
    "egyptian",
    "group",
    "holding",
    "holdings",
    "industries",
    "industry",
    "international",
    "investment",
    "investments",
    "limited",
    "national",
}
_ANNOUNCEMENT_CARD = re.compile(
    r'class="mi-announcement__date"(?:\s+data-publish-date="([^"]*)")?[^>]*>'
    r'([^<]*)</span>\s*'
    r'<span class="mi-announcement__source">([^<]*)</span>\s*'
    r'</span>\s*<a href="([^"]+)">([^<]*)</a>',
    re.S,
)
_cache: dict[str, tuple[float, object]] = {}

_INSTRUMENTS = (
    {
        "id": "usd_egp",
        "name": "US dollar",
        "name_ar": "الدولار الأمريكي",
        "ticker": "EGP=X",
        "unit": "EGP per USD",
        "unit_ar": "جنيه لكل دولار",
        "topic": "currency",
    },
    {
        "id": "eur_egp",
        "name": "Euro",
        "name_ar": "اليورو",
        "ticker": "EUREGP=X",
        "unit": "EGP per EUR",
        "unit_ar": "جنيه لكل يورو",
        "topic": "currency",
    },
    {
        "id": "gold",
        "name": "Gold",
        "name_ar": "الذهب",
        "ticker": "GC=F",
        "unit": "USD per ounce",
        "unit_ar": "دولار للأونصة",
        "topic": "gold",
    },
    {
        "id": "brent",
        "name": "Brent oil",
        "name_ar": "خام برنت",
        "ticker": "BZ=F",
        "unit": "USD per barrel",
        "unit_ar": "دولار للبرميل",
        "topic": "petrol",
    },
)
_INDICES = (
    {
        "id": "egx30",
        "name": "EGX 30",
        "name_ar": "مؤشر EGX 30",
        "ticker": "^CASE30",
        "description": "The benchmark index tracking the 30 most liquid and largest companies by market capitalization.",
        "description_ar": "المؤشر الرئيسي الذي يتتبع أكثر ٣٠ شركة سيولة وكبراً من حيث القيمة السوقية.",
    },
    {
        "id": "egx30_capped",
        "name": "EGX 30 Capped",
        "name_ar": "مؤشر EGX 30 المحدود",
        "ticker": "^EGX30CAPPED.CA",
        "description": "A variant of the EGX 30 that sets a maximum weight limit per company to avoid index dominance by single large-cap stocks.",
        "description_ar": "نسخة من EGX 30 تضع حداً أقصى لوزن كل شركة حتى لا تهيمن الأسهم الكبيرة على المؤشر.",
    },
    {
        "id": "egx70_ewi",
        "name": "EGX 70 EWI",
        "name_ar": "مؤشر EGX 70 متساوي الأوزان",
        "ticker": "^EGX70EWI.CA",
        "description": "Equal-Weighted Index measuring the performance of the top 70 medium and small-cap companies.",
        "description_ar": "مؤشر متساوي الأوزان يقيس أداء أكبر ٧٠ شركة متوسطة وصغيرة.",
    },
    {
        "id": "egx100_ewi",
        "name": "EGX 100 EWI",
        "name_ar": "مؤشر EGX 100 متساوي الأوزان",
        "ticker": "^EGX100EWI.CA",
        "description": "Combines the constituents of EGX 30 and EGX 70 using an equal-weighted methodology.",
        "description_ar": "يجمع مكونات EGX 30 وEGX 70 بمنهجية الأوزان المتساوية.",
    },
    {
        "id": "egx_shariah",
        "name": "EGX Shariah Index",
        "name_ar": "مؤشر الشريعة",
        "ticker": "^SHARIAH.CA",
        "description": "Tracks listed companies compliant with Islamic Shariah financial standards.",
        "description_ar": "يتتبع الشركات المدرجة المتوافقة مع معايير الشريعة الإسلامية.",
    },
    {
        "id": "tamayuz",
        "name": "Tamayuz Market",
        "name_ar": "سوق التميّز",
        "ticker": "^TAMAYUZ.CA",
        "description": "Dedicated index for Small and Medium-sized Enterprises (SMEs).",
        "description_ar": "مؤشر مخصص للشركات الصغيرة والمتوسطة.",
    },
)
_TOPIC_CAP = 6
# Yahoo search queries per topic. Several are tried because ticker-style queries
# often return identical AP wires or miner stocks.
_MARKET_QUERIES: dict[str, tuple[str, ...]] = {
    "currency": ("USD/EGP", "Egyptian pound", "EGP forex", "Egypt currency", "EGP=X"),
    "gold": ("gold price", "XAU", "gold bullion", "spot gold", "GC=F"),
    "petrol": ("Brent", "crude oil"),
}
# Strong price/bullion signals — beat miner/stock noise when both match.
_GOLD_PRICE = re.compile(
    r"\b(?:gold\s+prices?|spot\s+gold|bullion|xau(?:/?usd)?|troy|per\s+ounce|"
    r"gold\s+(?:falls|rises|slides|jumps|hits|surges|slips|holds|trades|futures|market|fell|slid)|"
    r"precious\s+metals?|lbma|comex\s+gold)\b",
    re.I,
)
_GOLD_DROP = re.compile(
    r"\b(?:stock(?:s)?|shares?|ipo|earnings|drill(?:ing)?|intersects?|miner|mining|"
    r"project|ffo|reit|q[1-4]\s+20\d{2}|price target|can .+ stock jump|"
    r"etf\s+flows?|diamond\s+drill|metre(?:s)?\s+diamond)\b",
    re.I,
)
_CURRENCY_KEEP = re.compile(
    r"\b(?:egp|egyptian\s+pounds?|usd\s*/?\s*egp|egypt(?:ian)?\s+(?:currency|pound|fx|forex)|"
    r"pound\s+(?:hits|falls|slides|drops|weakens|plunge|devalu|flex)|"
    r"devaluation|forex\s+regime|cbe|central\s+bank)\b",
    re.I,
)
_CURRENCY_DROP = re.compile(
    r"(?:^BC-US-Foreign Exchange$|\b(?:eastgroup|reit|ffo|earnings call|price target)\b)",
    re.I,
)
_GOOGLE_NEWS = (
    (
        "currency",
        'Egyptian pound OR EGP OR "USD/EGP" OR "Egypt currency" when:14d',
    ),
    (
        "gold",
        '("gold price" OR "spot gold" OR bullion OR XAU OR "gold falls" OR "gold rises") when:7d',
    ),
    (
        "flights",
        "airport OR flight OR airline OR aviation (delay OR cancel OR disrupt OR attack OR closed OR suspend OR grounded) when:14d",
    ),
    (
        "shipping",
        'shipping OR tanker OR maritime OR "Red Sea" OR Suez OR Hormuz OR vessel (attack OR delay OR disrupt OR strike OR spill OR sank) when:14d',
    ),
)
# Arabic Google News (hl=ar&gl=EG) — real Arabic headlines, not translated wires.
_GOOGLE_NEWS_AR = (
    ("currency", 'دولار OR جنيه OR "سعر الصرف" OR EGP OR "البنك المركزي" when:14d'),
    ("gold", 'ذهب OR "سعر الذهب" OR عيار OR سبائك when:7d'),
    ("petrol", 'نفط OR برنت OR "خام برنت" OR بترول OR أوبك when:7d'),
    ("wars", "حرب OR صراع OR قصف OR غارات OR هجوم عسكري when:14d"),
    (
        "flights",
        "طيران OR مطار OR خطوط جوية OR طائرة (تأخير OR إلغاء OR إغلاق OR هجوم OR تعليق) when:14d",
    ),
    (
        "shipping",
        'شحن OR "قناة السويس" OR "البحر الأحمر" OR ناقلة OR سفينة OR ميناء when:14d',
    ),
)
_WORLD_FEEDS_AR = (
    ("بي بي سي عربي", "https://feeds.bbci.co.uk/arabic/rss.xml"),
    ("بي بي سي عربي", "https://feeds.bbci.co.uk/arabic/middleeast/rss.xml"),
    ("بي بي سي عربي", "https://feeds.bbci.co.uk/arabic/business/rss.xml"),
)
_CURRENCY_AR = re.compile(r"دولار|جنيه|صرف|عملات|البنك المركزي|EGP|USD", re.I)
_GOLD_AR = re.compile(r"ذهب|عيار|أونصة|اونصة|سبائك")
_PETROL_AR = re.compile(r"نفط|برنت|بترول|خام|أوبك|اوبك|وقود")
_WAR_AR = re.compile(r"حرب|صراع|قصف|غارات|صاروخ|عسكري|هجوم|معارك|غزو|اشتباك")
_FLIGHT_AR = re.compile(r"طيران|مطار|خطوط جوية|طائرة|مجال جوي")
_SHIP_AR = re.compile(r"شحن|سفينة|ناقلة|قناة السويس|البحر الأحمر|البحر الاحمر|ميناء|بحري")
_SHIP_NOISE_AR = re.compile(r"طقس|بروق|سماء|بعدسة|Facebook|إنستغرام|انستجرام")
_EGX_NEWS_SEARCH = "https://beta.egx.com.eg/api/bff/egx/news-search"
_EGX_PDF = "https://www.egx.com.eg/downloads/News/{fileName}"
_EGX_MEDIA = {
    "ar": "https://beta.egx.com.eg/ar/media-center",
    "en": "https://beta.egx.com.eg/en/media-center",
}
_EGX_DISC_SEC_IDS = (3, 4, 5, 6, 7, 8, 16, 10, 11, 12, 13)
_EGYPT_LIMIT = 10
# Labels mirrored from beta.egx.com.eg media-center TITLE_LABELS / CONTENT_LABELS / META.
_EGX_TITLE_LABELS = (
    "العنوان",
    "عنوان",
    "Subject",
    "موضوع الاعلان",
    "موضوع الإعلان",
)
_EGX_CONTENT_LABELS = ("مضمون الاعلان", "مضمون الإعلان", "Content")
_EGX_COMPANY_LABELS = ("اسم الشركة", "Company Name", "Issuer Name", "Company")
_EGX_SUBJECT = re.compile(r"^Subject\s*[:：]\s*(.+)$", re.I)
_AR_SCRIPT = re.compile(r"[\u0600-\u06FF]")
_AR_CLOCK = re.compile(r"(\d{1,2})\s+([^\s\d]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*([صم])")
_WORLD_FEEDS = (
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("BBC", "https://feeds.bbci.co.uk/news/business/economy/rss.xml"),
    ("The Guardian", "https://www.theguardian.com/world/rss"),
    ("The Guardian", "https://www.theguardian.com/world/middleeast/rss"),
    ("The Guardian", "https://www.theguardian.com/business/rss"),
    ("The Guardian", "https://www.theguardian.com/business/theairlineindustry/rss"),
)
# Specialist feeds — trusted for that topic (no dual-keyword gate).
_FLIGHT_FEEDS = (("FlightGlobal", "https://www.flightglobal.com/rss"),)
_SHIPPING_FEEDS = (
    ("gCaptain", "https://gcaptain.com/feed/"),
    ("Hellenic Shipping News", "https://www.hellenicshippingnews.com/feed/"),
)
_METAL_PAGES = {
    "gold": ("https://startamarkets.com/gold", "Gold price in Egypt"),
    "silver": ("https://startamarkets.com/silver", "Silver price in Egypt"),
}
_WAR = re.compile(
    r"\b(?:wars?|warfare|invasions?|invade[ds]?|airstrikes?|air strikes?|missiles?|"
    r"ceasefires?|troops|bombarded|bombardment|shelling|paramilitary|drones?|"
    r"artillery|offensive|combat|battlefield|"
    r"military (?:leaders?|forces|junta|coup|offensive|strike|attack|deployment|to attack)|"
    r"armed conflict)\b",
    re.I,
)
_WAR_NOISE = re.compile(
    r"\b(?:first\s+world\s+war|second\s+world\s+war|world\s+war\s+(?:i|ii|one|two|1|2)|"
    r"ww(?:i|ii|1|2)|civil\s+war\s+munitions|military\s+base|military\s+spending|"
    r"ex-?military)\b",
    re.I,
)
_FLIGHT = re.compile(
    r"\b(?:flights?|airlines?|airports?|airspace|runways?|pilots?|aviation|aircraft)\b",
    re.I,
)
# Airport alone stays disruption-gated; these terms are enough on their own.
_FLIGHT_CORE = re.compile(r"\b(?:flights?|airlines?|airspace|aviation)\b", re.I)
_SHIP = re.compile(
    r"\b(?:shipping|ships?|tankers?|cargo|ports?|suez|straits?|vessels?|maritime|freight|"
    r"container\s+ships?|red\s+sea|hormuz)\b",
    re.I,
)
_SHIP_CORE = re.compile(
    r"\b(?:shipping|tankers?|suez|red\s+sea|hormuz|container\s+ships?)\b",
    re.I,
)
_SHIP_NOISE = re.compile(
    r"\b(?:maritime\s+strike|tomahawk|naval|navy|warship|destroyer|frigate)\b",
    re.I,
)
_DISRUPTION = re.compile(
    r"\b(?:delays?|delayed|disrupt(?:ion|ed|ions)?|clos(?:ed|ure|ing)|cancels?|cancell?ed|"
    r"cancellations?|diverted|diversions?|blocked|attacks?|attacked|strikes?|struck|"
    r"grounded|suspend(?:ed|s|ing)?|halts?|halted|rerout(?:e|ed|ing)|spills?|shutdowns?|shut|"
    r"fatigued?|collisions?|collided|crashes?|crashed|stuck|stranded|sank|sunk|"
    r"disabled|emergency|bans?|banned|threat(?:en|ened|s)?|resume[ds]?|reopen(?:ed|ing)?|"
    r"hits?|killed|dead)\b",
    re.I,
)
_LIFESTYLE = re.compile(
    r"\b(?:lounges?|decadent|destinations?|holiday|vacation|travel tips?|ski resorts?|"
    r"bucket list|cheapest flights?)\b",
    re.I,
)
_ITEM = re.compile(r"<item\b[^>]*>(.*?)</item>", re.S)
_TITLE = re.compile(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", re.S)
_LINK = re.compile(r"<link[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", re.S)
_PUBLISHED = re.compile(
    r"<(?:pubDate|dc:date)[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:pubDate|dc:date)>",
    re.S,
)


def _lang(value: str | None) -> str:
    return "ar" if (value or "").strip().lower() == "ar" else "en"


async def get_markets(lang: str = "en") -> MarketsResponse:
    lang = _lang(lang)
    return await _cached(f"markets:{lang}", lambda: _load_markets(lang))


async def get_metals(metal: str) -> MetalsResponse:
    metal = metal.lower().strip()
    if metal not in _METAL_PAGES:
        metal = "gold"
    return await _cached(f"metals:{metal}", lambda: _load_metals(metal))


async def get_chart(symbol: str, range_key: str) -> ChartResponse:
    symbol = symbol.upper()
    payload = await _cached(f"chart:{symbol}:{range_key}", lambda: chart_history(symbol, range_key))
    ticker = payload.get("ticker")
    return ChartResponse(
        symbol=symbol,
        currency=payload.get("currency"),
        range=range_key,
        interval=payload.get("interval") or "",
        source=f"Yahoo Finance ({ticker})" if ticker else None,
        bars=[ChartBar(**bar) for bar in payload.get("bars") or []],
    )


async def get_company_news(symbol: str, lang: str = "en") -> NewsResponse:
    symbol = symbol.upper()
    lang = _lang(lang)
    company = get_symbol_name(symbol)
    articles = await _cached(
        f"news:{symbol}:{lang}",
        lambda: _company_news(symbol, company, lang),
    )
    return NewsResponse(symbol=symbol, company=company, articles=articles)


async def _cached(key: str, loader):
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _TTL:
        return hit[1]
    value = await asyncio.to_thread(loader)
    _cache[key] = (now, value)
    return value


def _load_markets(lang: str = "en") -> MarketsResponse:
    instruments = [_instrument(item) for item in _INSTRUMENTS]
    indices = [_index(item) for item in _INDICES]
    headlines: list[Headline] = []
    seen: set[str] = set()
    if lang == "ar":
        streams = (
            _market_topic_headlines_ar,
            _world_headlines_ar,
            lambda: _egypt_headlines(lang),
        )
    else:
        streams = (
            _market_topic_headlines,
            _world_headlines,
            lambda: _egypt_headlines(lang),
        )
    for loader in streams:
        for article in loader():
            if article.title in seen:
                continue
            seen.add(article.title)
            headlines.append(article)
    return MarketsResponse(
        updated_cairo=datetime.now(_CAIRO).strftime("%Y-%m-%d %H:%M"),
        instruments=instruments,
        headlines=headlines[:48],
        indices=indices,
    )


def _market_topic_headlines() -> list[Headline]:
    grouped: dict[str, list[Headline]] = {topic: [] for topic in _MARKET_QUERIES}
    seen: set[str] = set()

    def take(topic: str, articles: list[Headline]) -> None:
        bucket = grouped[topic]
        for article in articles:
            title = _normalize_title(article.title)
            if not title or title in seen or not _topic_ok(topic, article.title):
                continue
            seen.add(title)
            article.topic = topic
            bucket.append(article)
            if len(bucket) >= _TOPIC_CAP:
                return

    for topic, queries in _MARKET_QUERIES.items():
        for query in queries:
            if len(grouped[topic]) >= _TOPIC_CAP:
                break
            take(topic, _search(query, 8))
    for topic, query in _GOOGLE_NEWS:
        if topic not in grouped:
            continue
        if len(grouped[topic]) >= _TOPIC_CAP:
            continue
        take(topic, _google_news(query, _TOPIC_CAP * 2))
    chosen: list[Headline] = []
    for topic in ("currency", "gold", "petrol"):
        chosen.extend(grouped.get(topic, [])[:_TOPIC_CAP])
    return chosen


def _market_topic_headlines_ar() -> list[Headline]:
    """Arabic pound / gold / oil headlines from Google News EG:ar."""
    topics = ("currency", "gold", "petrol")
    grouped: dict[str, list[Headline]] = {topic: [] for topic in topics}
    seen: set[str] = set()
    filters = {"currency": _CURRENCY_AR, "gold": _GOLD_AR, "petrol": _PETROL_AR}

    def take(topic: str, articles: list[Headline]) -> None:
        bucket = grouped[topic]
        keep = filters[topic]
        for article in articles:
            title = _normalize_title(article.title)
            if not title or title in seen or not keep.search(article.title):
                continue
            seen.add(title)
            article.topic = topic
            bucket.append(article)
            if len(bucket) >= _TOPIC_CAP:
                return

    for topic, query in _GOOGLE_NEWS_AR:
        if topic not in grouped:
            continue
        if len(grouped[topic]) >= _TOPIC_CAP:
            continue
        take(topic, _google_news(query, _TOPIC_CAP * 2, lang="ar"))
    chosen: list[Headline] = []
    for topic in topics:
        chosen.extend(grouped.get(topic, [])[:_TOPIC_CAP])
    return chosen


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).casefold()


def _topic_ok(topic: str, title: str) -> bool:
    if topic == "gold":
        has_gold = re.search(r"\b(?:gold|gld|xau)\b", title, re.I) is not None
        # Silver-only bullion pages should not fill the gold slot.
        if re.search(r"\bsilver\b", title, re.I) and not has_gold:
            return False
        if _GOLD_PRICE.search(title) and has_gold:
            return True
        if _GOLD_PRICE.search(title) and re.search(
            r"\b(?:bullion|precious\s+metals?|lbma|comex)\b", title, re.I
        ):
            return True
        # Bare "gold" / GLD is OK only when it is not miner/stock/ETF-flow noise.
        if _GOLD_DROP.search(title):
            return False
        return has_gold
    if topic == "currency":
        if _CURRENCY_DROP.search(title):
            return False
        # Drop generic AP FX wires and EastGroup (ticker EGP) REIT noise.
        return _CURRENCY_KEEP.search(title) is not None
    if topic == "petrol":
        return re.search(r"\b(?:oil|brent|crude|petroleum|opec)\b", title, re.I) is not None
    return True


def _load_metals(metal: str) -> MetalsResponse:
    raw = load_metal(metal)
    hero = MetalHero(**raw["hero"]) if raw.get("hero") else None
    builder = MetalBuilder(**raw["builder"]) if raw.get("builder") else None
    extras = None
    if raw.get("extras"):
        extras = MetalExtras(
            gold_pound=MetalExtraItem(**raw["extras"]["gold_pound"])
            if raw["extras"].get("gold_pound")
            else None,
            ounce_egp=MetalExtraItem(**raw["extras"]["ounce_egp"])
            if raw["extras"].get("ounce_egp")
            else None,
            ounce_usd=MetalExtraItem(**raw["extras"]["ounce_usd"])
            if raw["extras"].get("ounce_usd")
            else None,
        )
    zakat = MetalZakat(**raw["zakat"]) if raw.get("zakat") else None
    chart_ranges = [
        MetalChartRange(
            key=item["key"],
            label=item["label"],
            points=[MetalChartPoint(**pt) for pt in item.get("points") or []],
        )
        for item in raw.get("chart_ranges") or []
    ]
    updated = raw.get("updated")
    return MetalsResponse(
        metal=raw["metal"],
        title=raw.get("title") or _METAL_PAGES[metal][1],
        source=raw.get("source") or "Starta Markets",
        source_url=raw.get("source_url") or _METAL_PAGES[metal][0],
        updated=updated,
        updated_cairo=updated,
        note=raw.get("note") or "",
        hero=hero,
        builder=builder,
        performance=raw.get("performance"),
        rows=[MetalRow(**row) for row in raw.get("rows") or []],
        extras=extras,
        funds=[MetalFund(**fund) for fund in raw.get("funds") or []],
        chart_ranges=chart_ranges,
        chart_caption=raw.get("chart_caption"),
        zakat=zakat,
    )


def _instrument(item: dict[str, str]) -> MarketInstrument:
    snap = chart_snapshot(item["ticker"])
    price = _num(snap.get("price"))
    previous = _num(snap.get("previous_close"))
    change = None
    change_percent = None
    if price is not None and previous not in (None, 0):
        change = round(price - previous, 4)
        change_percent = f"{change / previous * 100:+.2f}%"
    return MarketInstrument(
        id=item["id"],
        name=item["name"],
        ticker=item["ticker"],
        price=round(price, 4) if price is not None else None,
        change=change,
        change_percent=change_percent,
        currency=snap.get("currency"),
        unit=item["unit"],
        name_ar=item.get("name_ar"),
        unit_ar=item.get("unit_ar"),
    )


def _index(item: dict[str, str | None]) -> IndexInsight:
    ticker = item.get("ticker")
    price = None
    change = None
    change_percent = None
    if ticker:
        try:
            snap = chart_snapshot(ticker)
        except Exception:
            snap = {}
        price = _num(snap.get("price"))
        previous = _num(snap.get("previous_close"))
        if price is not None:
            price = round(price, 2)
        if price is not None and previous not in (None, 0):
            change = round(price - previous, 2)
            change_percent = f"{change / previous * 100:+.2f}%"
    return IndexInsight(
        id=str(item["id"]),
        name=str(item["name"]),
        description=str(item["description"]),
        ticker=ticker,
        price=price,
        change=change,
        change_percent=change_percent,
        name_ar=item.get("name_ar"),
        description_ar=item.get("description_ar"),
    )


def _company_news(symbol: str, company: str | None, lang: str = "en") -> list[Headline]:
    bare = symbol[:-3] if symbol.endswith(".CA") else symbol
    articles = _about_company(_mubasher_company(bare, lang), bare, company)
    if articles:
        return articles
    if lang == "ar":
        # Prefer Arabic Google News over English Yahoo wires.
        query = f"{bare} OR {company}" if company else bare
        for article in _google_news(f"{query} مصر OR بورصة when:30d", 8, lang="ar"):
            article.topic = bare
            articles.append(article)
        return articles[:8]
    queries = [f"{bare}.CA", bare]
    if company:
        short = company.split(" S.A.E")[0].split(" SAE")[0].strip()
        queries.append(f"{short} Egypt")
    seen: set[str] = set()
    for query in queries:
        for article in _search(query, 6):
            if article.title in seen:
                continue
            seen.add(article.title)
            article.topic = bare
            articles.append(article)
        if len(articles) >= 8:
            break
    return articles[:8]


def _about_company(articles: list[Headline], symbol: str, company: str | None) -> list[Headline]:
    """Keep stories that name this listing. If none do, keep the source list."""
    matched = [article for article in articles if _mentions(article.title, symbol, company)]
    return (matched or articles)[:8]


def _mentions(title: str, symbol: str, company: str | None) -> bool:
    text = title.casefold()
    if re.search(rf"(?<![a-z0-9]){re.escape(symbol.casefold())}(?![a-z0-9])", text):
        return True
    if not company:
        return False
    for token in re.findall(r"[A-Za-z]{4,}", company):
        word = token.casefold()
        if word in _GENERIC_NAME:
            continue
        if word in text:
            return True
    for abbr in re.findall(r"\(([A-Za-z]{2,6})\)", company):
        if re.search(rf"(?<![a-z]){re.escape(abbr.casefold())}(?![a-z])", text):
            return True
    return False


def _mubasher_company(symbol: str, lang: str = "en") -> list[Headline]:
    """News and exchange releases Mubasher lists for one EGX symbol."""
    host = _MUBASHER_HOST_AR if lang == "ar" else _MUBASHER_HOST
    publisher = "مباشر" if lang == "ar" else "Mubasher"
    news = _headlines_from_mubasher(
        _mubasher_page(symbol, "news", lang), symbol, host=host, publisher=publisher
    )
    if len(news) >= 8:
        return news[:8]
    seen = {article.title.casefold() for article in news}
    exchange = "البورصة المصرية" if lang == "ar" else "Egyptian Stock Exchange"
    for article in _announcements_from_mubasher(
        _mubasher_page(symbol, "announcements", lang),
        symbol,
        host=host,
        default_publisher=exchange,
    ):
        if article.title.casefold() in seen:
            continue
        seen.add(article.title.casefold())
        news.append(article)
        if len(news) >= 8:
            break
    return news


def _mubasher_page(symbol: str, kind: str, lang: str = "en") -> str:
    template = _MUBASHER_AR if lang == "ar" else _MUBASHER
    url = template.format(symbol=urllib.parse.quote(symbol), kind=kind)
    request = urllib.request.Request(url, headers={"User-Agent": "MirsadMasr/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            final = response.geturl().upper()
            if symbol.upper() not in final:
                return ""
            return response.read().decode("utf-8", "replace")
    except Exception:
        return ""


def _headlines_from_mubasher(
    page: str,
    symbol: str,
    *,
    host: str = _MUBASHER_HOST,
    publisher: str = "Mubasher",
) -> list[Headline]:
    section = _results_section(page)
    headlines = []
    for published, href, title in _NEWS_CARD.findall(section):
        headline = _headline(title, href, publisher, published.strip(), symbol, host=host)
        if headline is not None:
            headlines.append(headline)
    return headlines


def _announcements_from_mubasher(
    page: str,
    symbol: str,
    *,
    host: str = _MUBASHER_HOST,
    default_publisher: str = "Egyptian Stock Exchange",
) -> list[Headline]:
    section = _results_section(page)
    headlines = []
    for stamp, visible, source, href, title in _ANNOUNCEMENT_CARD.findall(section):
        published = _iso_published(stamp) or visible.strip()
        publisher = html.unescape(source).strip() or default_publisher
        headline = _headline(title, href, publisher, published, symbol, host=host)
        if headline is not None:
            headlines.append(headline)
    return headlines


def _results_section(page: str) -> str:
    start = page.find("mi-news-results")
    if start < 0:
        return ""
    end = page.find("mi-popular-news", start)
    if end < 0:
        end = start + 120_000
    return page[start:end]


def _headline(
    title: str,
    href: str,
    publisher: str,
    published: str,
    symbol: str,
    *,
    host: str = _MUBASHER_HOST,
) -> Headline | None:
    text = html.unescape(title).strip()
    if not text:
        return None
    return Headline(
        title=text,
        publisher=publisher,
        link=_absolute(html.unescape(href).strip(), host=host),
        published=published or None,
        topic=symbol,
    )


def _absolute(href: str, *, host: str = _MUBASHER_HOST) -> str | None:
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return host + href
    return host + "/" + href


def _iso_published(value: str) -> str | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _egypt_headlines(lang: str = "en") -> list[Headline]:
    lang = _lang(lang)
    today = datetime.now(_CAIRO).date()
    date_to = today.isoformat()
    date_from = (today - timedelta(days=30)).isoformat()
    common = {
        "pageNumber": 1,
        "pageSize": 20,
        "interval": 50,
        "count": 50,
        "dateFrom": date_from,
        "dateTo": date_to,
    }
    trading = _egx_news_search({**common, "marketSessionNews": True})
    disclosures = _egx_news_search(
        {**common, "marketSessionNews": False, "secIds": list(_EGX_DISC_SEC_IDS)}
    )
    if trading is None and disclosures is None:
        return []
    # Same BFF for /en and /ar — no Accept-Language / culture knob. EGX's EN
    # media-center prefers disclosure bodies (often English in ``content``) and
    # shows an Arabic-only notice for trading; put disclosures first for EN.
    if lang == "en":
        items = list(disclosures or []) + list(trading or [])
    else:
        items = list(trading or []) + list(disclosures or [])
    return _headlines_from_egx_news(items, lang, limit=_EGYPT_LIMIT)


def _egx_news_search(body: dict) -> list[dict] | None:
    """POST the EGX media-center search BFF. ``None`` means the call failed."""
    payload = _post_json(_EGX_NEWS_SEARCH, body)
    if payload is None:
        return None
    if not payload.get("success", True):
        return None
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _post_json(url: str, body: dict) -> dict | None:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "x-egx-bff-request": "1",
            "User-Agent": "MirsadMasr/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _headlines_from_egx_news(
    items: list[dict],
    lang: str = "en",
    *,
    limit: int = _EGYPT_LIMIT,
) -> list[Headline]:
    lang = _lang(lang)
    publisher = "البورصة المصرية" if lang == "ar" else "EGX"
    fallback = _EGX_MEDIA[lang]
    seen: set[object] = set()
    ranked: list[tuple[str, Headline]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = item.get("code")
        if code is None or code in seen:
            continue
        # Mark before title filtering so an Arabic-only body does not leave the
        # code open for a later duplicate row of the same announcement.
        seen.add(code)
        title = _egx_item_title(item, lang)
        if not title:
            continue
        stamp = str(item.get("dateStamp") or "")
        ranked.append(
            (
                stamp,
                Headline(
                    title=title,
                    publisher=publisher,
                    link=_egx_item_link(item, fallback),
                    published=_egx_published(stamp),
                    topic="egypt",
                ),
            )
        )
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [article for _, article in ranked[:limit]]


def _egx_item_title(item: dict, lang: str) -> str | None:
    """Pick a headline the way beta.egx.com.eg media-center maps news items.

    The news-search BFF ignores Accept-Language / culture / lang body fields.
    ``/en/media-center`` prefers ``heading`` (then Subject / Content lines);
    Arabic-only trading bodies are omitted for ``lang=en``.
    """
    lang = _lang(lang)
    want_ar = lang == "ar"
    english_body = str(item.get("content") or "")
    arabic_body = str(item.get("contentArabic") or "")
    heading_en = _plain(item.get("heading") or "") or None
    heading_ar = _plain(item.get("headingArabic") or "") or None
    heading = _egx_pick_localized(
        heading_en or "", heading_ar or "", want_ar=want_ar
    ) or None

    extracted = None
    primary = _egx_pick_localized(english_body, arabic_body, want_ar=want_ar)
    for body in (primary, english_body, arabic_body):
        if not body:
            continue
        extracted = _egx_title_from_text(body)
        if extracted:
            break
    if not extracted:
        extracted = _egx_subject_from_text(english_body) or _egx_subject_from_text(
            arabic_body
        )

    # EGX ``T(heading, fallback=I(content))`` — heading wins when present.
    if want_ar:
        return heading or extracted or heading_ar or heading_en

    for candidate in (heading_en, heading, extracted):
        if candidate and not _AR_SCRIPT.search(candidate):
            return candidate
    return None


def _egx_pick_localized(english: str, arabic: str, *, want_ar: bool) -> str:
    """Prefer the locale body, but swap when script clearly mismatches (EGX ``L``)."""
    primary = arabic if want_ar else english
    alternate = english if want_ar else arabic
    if primary and alternate:
        primary_ar = bool(_AR_SCRIPT.search(primary))
        alternate_ar = bool(_AR_SCRIPT.search(alternate))
        if want_ar and not primary_ar and alternate_ar:
            return alternate
        if not want_ar and primary_ar and not alternate_ar:
            return alternate
    if primary:
        return primary
    return alternate


def _egx_title_from_text(text: str) -> str | None:
    lines = _egx_content_lines(text)
    titled = _egx_labeled_value(lines, _EGX_TITLE_LABELS)
    if titled:
        return titled
    content = _egx_labeled_value(lines, _EGX_CONTENT_LABELS)
    if content:
        return content
    company = _egx_labeled_value(lines, _EGX_COMPANY_LABELS)
    for line in lines:
        value = _plain(line)
        # Skip all "Label : value" rows (Interest Type, Coupon Interest, …).
        if re.match(r"^[^:：]{1,40}[:：]\s*\S", value):
            continue
        if len(value) > 12:
            return value
    return company


def _egx_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str | None:
    label_set = {label.casefold() for label in labels}
    for index, line in enumerate(lines):
        match = re.match(r"^([^:：]+)[:：]\s*(.*)$", line)
        if not match:
            continue
        if match.group(1).strip().casefold() not in label_set:
            continue
        value = _plain(match.group(2))
        if value:
            return value
        if index + 1 < len(lines):
            nxt = lines[index + 1]
            if re.match(r"^([^:：]+)[:：]", nxt):
                continue
            nxt_plain = _plain(nxt)
            if nxt_plain:
                return nxt_plain
    return None


def _egx_subject_from_text(text: str) -> str | None:
    for line in _egx_content_lines(text):
        match = _EGX_SUBJECT.match(line)
        if match:
            value = _plain(match.group(1))
            if value:
                return value
    return None


def _egx_content_lines(text: str) -> list[str]:
    cleaned = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned).replace("\u200b", "").replace("\xa0", " ")
    return [line.strip() for line in cleaned.splitlines() if line.strip()]


def _egx_item_link(item: dict, fallback: str) -> str:
    for attachment in item.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        if str(attachment.get("webFlag") or "").upper() != "Y":
            continue
        name = str(attachment.get("fileName") or "").strip()
        if name.lower().endswith(".pdf"):
            return _EGX_PDF.format(fileName=urllib.parse.quote(name))
    return fallback


def _egx_published(stamp: str) -> str | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.strftime("%Y-%m-%d %H:%M")


def _plain(value: str) -> str:
    text = html.unescape(value or "").replace("\u200b", "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _world_topic(title: str) -> str | None:
    if _LIFESTYLE.search(title):
        return None
    disrupted = _DISRUPTION.search(title) is not None
    # Prefer disruption + keyword; also accept core route/aviation terms alone
    # so thin BBC/Guardian days are not emptied by a strict dual-keyword AND.
    if _FLIGHT.search(title) and (disrupted or _FLIGHT_CORE.search(title)):
        return "flights"
    if (
        _SHIP.search(title)
        and not _SHIP_NOISE.search(title)
        and (disrupted or _SHIP_CORE.search(title))
    ):
        return "shipping"
    if _WAR.search(title) and not _WAR_NOISE.search(title):
        return "wars"
    return None


def _world_topic_ar(title: str) -> str | None:
    # Prefer route disruption topics over war when both match.
    if _FLIGHT_AR.search(title):
        return "flights"
    if _SHIP_AR.search(title) and not _SHIP_NOISE_AR.search(title):
        return "shipping"
    if _WAR_AR.search(title):
        return "wars"
    return None


def _world_headlines() -> list[Headline]:
    grouped: dict[str, list[Headline]] = {"wars": [], "flights": [], "shipping": []}
    seen: set[str] = set()

    def absorb(articles: list[Headline]) -> None:
        for article in articles:
            topic = _world_topic(article.title)
            key = _normalize_title(article.title)
            if topic is None or not key or key in seen:
                continue
            seen.add(key)
            article.topic = topic
            grouped[topic].append(article)

    def absorb_topic(topic: str, articles: list[Headline]) -> None:
        bucket = grouped[topic]
        for article in articles:
            if len(bucket) >= _TOPIC_CAP:
                return
            if _LIFESTYLE.search(article.title):
                continue
            key = _normalize_title(article.title)
            if not key or key in seen:
                continue
            seen.add(key)
            article.topic = topic
            bucket.append(article)

    for publisher, url in _WORLD_FEEDS:
        absorb(_rss(url, publisher))
    for publisher, url in _FLIGHT_FEEDS:
        absorb_topic("flights", _rss(url, publisher))
    for publisher, url in _SHIPPING_FEEDS:
        absorb_topic("shipping", _rss(url, publisher))
    for topic, query in _GOOGLE_NEWS:
        if topic not in grouped:
            continue
        if len(grouped[topic]) >= _TOPIC_CAP:
            continue
        absorb(_google_news(query, _TOPIC_CAP * 2))
    chosen: list[Headline] = []
    for topic in ("wars", "flights", "shipping"):
        grouped[topic].sort(key=lambda article: article.published or "", reverse=True)
        chosen.extend(grouped[topic][:_TOPIC_CAP])
    return chosen


def _world_headlines_ar() -> list[Headline]:
    """Wars / flights / shipping from BBC Arabic + Google News EG:ar."""
    grouped: dict[str, list[Headline]] = {"wars": [], "flights": [], "shipping": []}
    seen: set[str] = set()

    def absorb(articles: list[Headline]) -> None:
        for article in articles:
            topic = _world_topic_ar(article.title)
            key = _normalize_title(article.title)
            if topic is None or not key or key in seen:
                continue
            if len(grouped[topic]) >= _TOPIC_CAP:
                continue
            seen.add(key)
            article.topic = topic
            grouped[topic].append(article)

    def absorb_topic(topic: str, articles: list[Headline]) -> None:
        bucket = grouped[topic]
        for article in articles:
            if len(bucket) >= _TOPIC_CAP:
                return
            if topic == "shipping" and _SHIP_NOISE_AR.search(article.title):
                continue
            if topic == "shipping" and (article.publisher or "").casefold() == "facebook":
                continue
            key = _normalize_title(article.title)
            if not key or key in seen:
                continue
            seen.add(key)
            article.topic = topic
            bucket.append(article)

    for publisher, url in _WORLD_FEEDS_AR:
        absorb(_rss(url, publisher))
    for topic, query in _GOOGLE_NEWS_AR:
        if topic not in grouped:
            continue
        if len(grouped[topic]) >= _TOPIC_CAP:
            continue
        absorb_topic(topic, _google_news(query, _TOPIC_CAP * 2, lang="ar"))
    chosen: list[Headline] = []
    for topic in ("wars", "flights", "shipping"):
        grouped[topic].sort(key=lambda article: article.published or "", reverse=True)
        chosen.extend(grouped[topic][:_TOPIC_CAP])
    return chosen


def _google_news(query: str, limit: int, *, lang: str = "en") -> list[Headline]:
    if lang == "ar":
        locale = "&hl=ar&gl=EG&ceid=EG:ar"
        default_publisher = "أخبار Google"
    else:
        locale = "&hl=en-US&gl=US&ceid=US:en"
        default_publisher = "Google News"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + locale
    )
    articles = _rss(url, default_publisher)
    cleaned: list[Headline] = []
    for article in articles:
        title, publisher = _split_google_title(article.title)
        if not title:
            continue
        article.title = title
        if publisher:
            article.publisher = publisher
        cleaned.append(article)
        if len(cleaned) >= limit:
            break
    return cleaned


def _split_google_title(title: str) -> tuple[str, str | None]:
    text = re.sub(r"\s+", " ", (title or "").strip())
    if " - " not in text:
        return text, None
    headline, publisher = text.rsplit(" - ", 1)
    headline = headline.strip()
    publisher = publisher.strip()
    if not headline or not publisher or len(publisher) > 80:
        return text, None
    return headline, publisher


def _rss(url: str, publisher: str) -> list[Headline]:
    request = urllib.request.Request(url, headers={"User-Agent": "MirsadMasr/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            page = response.read().decode("utf-8", "replace")
    except Exception:
        return []
    headlines = []
    for block in _ITEM.findall(page):
        title_match = _TITLE.search(block)
        title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
        if not title:
            continue
        link_match = _LINK.search(block)
        published_match = _PUBLISHED.search(block)
        headlines.append(
            Headline(
                title=title,
                publisher=publisher,
                link=html.unescape(link_match.group(1).strip()) if link_match else None,
                published=_rss_time(published_match.group(1) if published_match else ""),
            )
        )
    return headlines


def _rss_time(value: str) -> str | None:
    text = html.unescape(value or "").strip()
    if not text:
        return None
    moment = None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        moment = None
    if moment is None:
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _search(query: str, count: int) -> list[Headline]:
    url = _SEARCH.format(query=urllib.parse.quote(query), count=count)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    headlines = []
    for item in payload.get("news") or []:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        headlines.append(
            Headline(
                title=title,
                publisher=item.get("publisher") or None,
                link=item.get("link") or None,
                published=_published(item.get("providerPublishTime")),
            )
        )
    return headlines


def _published(value) -> str | None:
    try:
        moment = datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return moment.strftime("%Y-%m-%d %H:%M UTC")


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number
