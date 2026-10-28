"""Starta Markets gold/silver page fetch + parse.

Adapted from the proven stdlib extractor (decode ``__next_f`` ranges, hero,
builder, performance, karat/fineness cards, extras, funds, zakat).
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

UA = "Mozilla/5.0"
GRAMS_PER_TROY_OZ = 31.1035
PAGES = {
    "gold": ("https://startamarkets.com/gold", "Gold price in Egypt"),
    "silver": ("https://startamarkets.com/silver", "Silver price in Egypt"),
}

GOLD_CARD_RE = re.compile(
    r">(24K|22K|21K|18K|14K|12K)</span>"
    r"[\s\S]{0,500}?Purity<!-- -->: <!-- -->([\d.]+)<!-- -->%"
    r"[\s\S]{0,250}?<bdi[^>]*>([\d,.]+)</bdi>"
    r"[\s\S]{0,100}?>EGP<"
    r"[\s\S]{0,500}?([+\-]\d+\.\d+)<!-- -->%",
    re.I,
)
SILVER_CARD_RE = re.compile(
    r">((?:999|925|900|800))(?:\s*silver)?</span>"
    r"[\s\S]{0,500}?Purity<!-- -->: <!-- -->([\d.]+)<!-- -->%"
    r"[\s\S]{0,250}?<bdi[^>]*>([\d,.]+)</bdi>"
    r"[\s\S]{0,100}?>EGP<"
    r"[\s\S]{0,500}?([+\-]\d+\.\d+)<!-- -->%",
    re.I,
)
HERO_RE = re.compile(
    r'<p class="mt-6 text-sm font-semibold text-muted">([^<]+)</p>'
    r'[\s\S]{0,200}?<p class="font-mono text-5xl[^"]*"[^>]*>([\d,.]+)</p>'
    r'[\s\S]{0,400}?>EGP<'
    r'[\s\S]{0,400}?([+\-]\d+\.\d+)<!-- -->%',
    re.I,
)
BUILDER_ASIDE_RE = re.compile(
    r'aria-label="How the price is built"[\s\S]{0,1200}?'
    r"Ounce, global</dt><dd[^>]*>\$<!-- -->([\d,.]+)</dd>"
    r"[\s\S]{0,400}?USD/EGP</dt><dd[^>]*>([\d,.]+)</dd>"
    r"[\s\S]{0,400}?÷ </span>([\d.]+)<!-- --> <!-- -->grams per ounce"
    r"[\s\S]{0,400}?24K gram</dt><dd[^>]*>([\d,.]+)</dd>",
    re.I,
)
PERF_RE = re.compile(
    r'<dt class="text-xs text-muted">(1 week|1 month|1 year|5 years)</dt>'
    r"[\s\S]{0,300}?([+\-])(?:<!-- -->)?([\d.]+)<!-- -->%",
    re.I,
)
EXTRA_POUND_RE = re.compile(
    r">Gold pound</span>[\s\S]{0,400}?<bdi[^>]*>([\d,.]+)</bdi>"
    r"[\s\S]{0,200}?>EGP<"
    r"[\s\S]{0,300}?([+\-]\d+\.\d+)<!-- -->%",
    re.I,
)
EXTRA_OUNCE_EGP_RE = re.compile(
    r">Ounce in EGP</span>[\s\S]{0,400}?<bdi[^>]*>([\d,.]+)</bdi>"
    r"[\s\S]{0,200}?>EGP<"
    r"[\s\S]{0,300}?([+\-]\d+\.\d+)<!-- -->%",
    re.I,
)
EXTRA_OUNCE_USD_RE = re.compile(
    r">Ounce in USD</span>[\s\S]{0,300}?<bdi[^>]*>\$<!-- -->([\d,.]+)</bdi>",
    re.I,
)
FUND_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*"
    r'<a class="font-semibold[^"]*" href="(/Funds/[^"]+)">([^<]+)</a></td>'
    r'<td[^>]*dir="ltr">([\d.]+)<!-- --> <span[^>]*>EGP</span></td>'
    r"<td[^>]*>(.*?)</td>"
    r"<td[^>]*>(.*?)</td>"
    r"\s*</tr>",
    re.I | re.S,
)
FUND_PCT_RE = re.compile(r"([+\-])(?:<!-- -->)?([\d.]+)<!-- -->%")
ZAKAT_RE = re.compile(
    r"Gold zakat nisab today</h2>[\s\S]{0,200}?"
    r'<p class="font-mono text-3xl[^"]*"[^>]*>([\d,.]+)<!-- --> '
    r"<span[^>]*>EGP</span></p>"
    r"[\s\S]{0,500}?EGP ([\d,.]+) today if valued at 21K"
    r"[\s\S]{0,200}?EGP ([\d,.]+) valued at pure 24K"
    r"[\s\S]{0,200}?Zakat is ([\d.]+)%",
    re.I,
)
UPDATED_RE = re.compile(r"Updated (\d{1,2}:\d{2} Cairo time)", re.I)
CHART_META_RE = re.compile(
    r'aria-label="([^"]*per gram[^"]*)"[\s\S]{0,2500}?'
    r"([+\-])(?:<!-- -->)?([\d.]+)<!-- -->%"
    r"[\s\S]{0,120}?>High<!-- --> <!-- -->([\d,.]+)</span>"
    r"[\s\S]{0,120}?>Low<!-- --> <!-- -->([\d,.]+)</span>",
    re.I,
)
SILVER_PROSE_RE = re.compile(
    r"international silver ounce \(USD ([\d,.]+)\) and the dollar rate \(EGP ([\d,.]+)\)",
    re.I,
)
GOLD_PROSE_RE = re.compile(
    r"international ounce price \(USD ([\d,.]+)\) and the dollar rate \(EGP ([\d,.]+)\)",
    re.I,
)

NOTE = (
    "Indicative metal value in Egypt from Starta Markets. "
    "Jewellers add workmanship and margin; buy-back differs from the selling price."
)


def _fnum(s: str | None) -> float | None:
    if s is None or s == "":
        return None
    return float(str(s).replace(",", ""))


def _pct(sign: str, num: str) -> float:
    v = float(num)
    return -v if sign == "-" else v


def fetch_html(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def decode_next_f_strings(html: str) -> list[str]:
    out: list[str] = []
    for p in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html):
        try:
            out.append(p.encode("utf-8").decode("unicode_escape"))
        except Exception:
            out.append(p.replace('\\"', '"').replace("\\n", "\n"))
    return out


def _resolve_point(val: Any, ranges: list[dict], depth: int = 0) -> dict | None:
    if isinstance(val, dict) and "d" in val and "v" in val:
        return {"d": val["d"], "v": float(val["v"])}
    if isinstance(val, str) and val.startswith("$") and depth < 8:
        m = re.search(r"ranges:(\d+):points:(\d+)$", val)
        if m:
            ri, pi = int(m.group(1)), int(m.group(2))
            return _resolve_point(ranges[ri]["points"][pi], ranges, depth + 1)
    return None


def extract_hero(html: str) -> dict[str, Any] | None:
    m = HERO_RE.search(html)
    if not m:
        return None
    return {
        "label": m.group(1).strip(),
        "price": _fnum(m.group(2)),
        "change_percent": float(m.group(3)),
        "currency": "EGP",
    }


def extract_karat_or_fineness_cards(html: str, metal: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    pat = GOLD_CARD_RE if metal == "gold" else SILVER_CARD_RE
    for m in pat.finditer(html):
        label = m.group(1)
        if metal == "silver" and "silver" not in label.lower():
            label = f"{label} silver"
        key = label.upper()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "label": label,
                "purity": f"{m.group(2)}%",
                "price": _fnum(m.group(3)),
                "change_percent": float(m.group(4)),
                "unit": "EGP per gram",
            }
        )
    return rows


def extract_price_builder(html: str, metal: str) -> dict[str, Any] | None:
    m = BUILDER_ASIDE_RE.search(html)
    if m:
        return {
            "source": "aside",
            "ounce_usd": _fnum(m.group(1)),
            "usd_egp": _fnum(m.group(2)),
            "grams_per_oz": _fnum(m.group(3)),
            "base_label": "24K gram",
            "base_price_egp": _fnum(m.group(4)),
        }

    prose = SILVER_PROSE_RE.search(html) if metal == "silver" else GOLD_PROSE_RE.search(html)
    ounce = EXTRA_OUNCE_USD_RE.search(html)
    ounce_usd = _fnum(ounce.group(1)) if ounce else (_fnum(prose.group(1)) if prose else None)
    usd_egp = _fnum(prose.group(2)) if prose else None

    base_label = "999 silver" if metal == "silver" else "24K gram"
    base_price = None
    cards = extract_karat_or_fineness_cards(html, metal)
    for c in cards:
        if metal == "silver" and str(c["label"]).startswith("999"):
            base_price = c["price"]
            break
        if metal == "gold" and c["label"] == "24K":
            base_price = c["price"]
            break

    if ounce_usd is None and usd_egp is None:
        return None
    return {
        "source": "prose+cards",
        "ounce_usd": ounce_usd,
        "usd_egp": usd_egp,
        "grams_per_oz": GRAMS_PER_TROY_OZ,
        "base_label": base_label,
        "base_price_egp": base_price,
    }


def extract_performance(html: str) -> dict[str, float] | None:
    found: dict[str, float] = {}
    key_map = {
        "1 week": "1w",
        "1 month": "1m",
        "1 year": "1y",
        "5 years": "5y",
    }
    for m in PERF_RE.finditer(html):
        found[key_map[m.group(1).lower()]] = _pct(m.group(2), m.group(3))
    return found or None


def extract_extras(html: str, metal: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if metal == "gold":
        m = EXTRA_POUND_RE.search(html)
        if m:
            out["gold_pound"] = {
                "label": "Gold pound (8 g of 21K)",
                "price_egp": _fnum(m.group(1)),
                "change_percent": float(m.group(2)),
            }
        m = EXTRA_OUNCE_EGP_RE.search(html)
        if m:
            out["ounce_egp"] = {
                "label": "Ounce in EGP",
                "price_egp": _fnum(m.group(1)),
                "change_percent": float(m.group(2)),
            }
    m = EXTRA_OUNCE_USD_RE.search(html)
    if m:
        out["ounce_usd"] = {
            "label": "Ounce in USD",
            "price_usd": _fnum(m.group(1)),
        }
    return out


def _parse_fund_pct_cell(cell_html: str) -> float | None:
    if ("—" in cell_html or "&mdash;" in cell_html.lower()) and not FUND_PCT_RE.search(cell_html):
        return None
    m = FUND_PCT_RE.search(cell_html)
    if not m:
        return None
    return _pct(m.group(1), m.group(2))


def extract_funds(html: str) -> list[dict[str, Any]]:
    funds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in FUND_ROW_RE.finditer(html):
        href = m.group(1)
        if href in seen or "/category/" in href:
            continue
        seen.add(href)
        funds.append(
            {
                "name": m.group(2).strip(),
                "href": "https://startamarkets.com" + href,
                "unit_price_egp": _fnum(m.group(3)),
                "return_6m_percent": _parse_fund_pct_cell(m.group(4)),
                "return_ytd_percent": _parse_fund_pct_cell(m.group(5)),
            }
        )
    return funds


def extract_chart_ranges(html: str) -> tuple[list[dict[str, Any]], str | None]:
    ranges_raw = None
    for s in decode_next_f_strings(html):
        if '"ranges"' not in s or '"points"' not in s:
            continue
        idx = s.find('"ranges":')
        if idx < 0:
            continue
        start = idx + len('"ranges":')
        try:
            ranges_raw, _ = json.JSONDecoder().raw_decode(s[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(ranges_raw, list) and ranges_raw and "points" in ranges_raw[0]:
            break
        ranges_raw = None

    caption = None
    meta = CHART_META_RE.search(html)
    if meta:
        caption = meta.group(1).strip()

    if not ranges_raw:
        return [], caption

    resolved: list[dict[str, Any]] = []
    for r in ranges_raw:
        pts = []
        for p in r.get("points") or []:
            rp = _resolve_point(p, ranges_raw)
            if rp:
                pts.append({"time": str(rp["d"]), "value": float(rp["v"])})
        resolved.append(
            {
                "key": str(r.get("key") or ""),
                "label": str(r.get("label") or r.get("key") or ""),
                "points": pts,
            }
        )
    return resolved, caption


def extract_zakat(html: str) -> dict[str, Any] | None:
    m = ZAKAT_RE.search(html)
    if not m:
        return None
    return {
        "nisab_headline_egp": _fnum(m.group(1)),
        "nisab_21k_egp": _fnum(m.group(2)),
        "nisab_24k_egp": _fnum(m.group(3)),
        "zakat_rate_percent": _fnum(m.group(4)),
        "nisab_grams": 85.0,
        "convention": "85 g valued at 21K (Egyptian common) or 24K pure",
    }


def parse_metal_page(html: str, metal: str) -> dict[str, Any]:
    url, title = PAGES[metal]
    chart_ranges, chart_caption = extract_chart_ranges(html)
    updated_match = UPDATED_RE.search(html)
    updated = updated_match.group(1) if updated_match else None
    extras = extract_extras(html, metal)
    zakat = extract_zakat(html) if metal == "gold" else None

    return {
        "metal": metal,
        "title": title,
        "hero": extract_hero(html),
        "builder": extract_price_builder(html, metal),
        "performance": extract_performance(html),
        "rows": extract_karat_or_fineness_cards(html, metal),
        "extras": extras or None,
        "funds": extract_funds(html),
        "chart_ranges": chart_ranges,
        "chart_caption": chart_caption,
        "zakat": zakat,
        "note": NOTE,
        "source": "Starta Markets",
        "source_url": url,
        "updated": updated,
    }


def load_metal(metal: str) -> dict[str, Any]:
    metal = metal.lower().strip()
    if metal not in PAGES:
        metal = "gold"
    url, title = PAGES[metal]
    try:
        html = fetch_html(url)
    except Exception:
        return {
            "metal": metal,
            "title": title,
            "hero": None,
            "builder": None,
            "performance": None,
            "rows": [],
            "extras": None,
            "funds": [],
            "chart_ranges": [],
            "chart_caption": None,
            "zakat": None,
            "note": NOTE,
            "source": "Starta Markets",
            "source_url": url,
            "updated": None,
        }
    return parse_metal_page(html, metal)
