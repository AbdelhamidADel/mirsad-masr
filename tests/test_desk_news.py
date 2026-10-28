"""Company headlines parsed from a Mubasher listing page."""

import re

from egxdesk.models import Headline
from egxdesk.services.desk import (
    _about_company,
    _announcements_from_mubasher,
    _egx_news_search,
    _egypt_headlines,
    _headlines_from_egx_news,
    _headlines_from_mubasher,
    _world_topic,
)

_NEWS = """
<section class="mi-news-results">
  <span class="mi-article-media-block__date">13 May 05:44 AM</span>
  <a class="mi-article-media-block__title" href="/news/4611928/CIB-profits/">CIB&#39;s consolidated profits</a>
</section>
<section class="mi-popular-news">
  <span class="mi-article-media-block__date">1 Jan 01:00 AM</span>
  <a class="mi-article-media-block__title" href="/news/1/other/">Unrelated sidebar story</a>
</section>
"""

_ANNOUNCEMENTS = """
<section class="mi-news-results">
  <span class="mi-announcement__date" data-publish-date="2026-09-28T09:02Z">28 September 09:02 AM</span>
  <span class="mi-announcement__source">Egyptian Stock Exchange</span>
  </span>
  <a href="/news/4677740/POCO-board/">Port Said Containers &amp; Cargo (POCO.CA) - Board of Directors&#39; Decisions</a>
</section>
"""


def test_company_news_ignores_the_sidebar() -> None:
    articles = _headlines_from_mubasher(_NEWS, "COMI")
    assert len(articles) == 1
    assert articles[0].title == "CIB's consolidated profits"
    assert articles[0].publisher == "Mubasher"
    assert articles[0].link == "https://english.mubasher.info/news/4611928/CIB-profits/"
    assert articles[0].published == "13 May 05:44 AM"
    assert articles[0].topic == "COMI"


def test_a_general_market_story_is_left_out_when_the_company_is_named() -> None:
    articles = [
        Headline(title="CIB unveils dividends", publisher="Mubasher"),
        Headline(title="Egypt closes 2025 as best-performing market in MENA", publisher="Mubasher"),
    ]
    kept = _about_company(articles, "COMI", "Commercial International Bank Egypt (CIB) S.A.E.")
    assert [article.title for article in kept] == ["CIB unveils dividends"]


def test_announcements_keep_the_exchange_timestamp() -> None:
    articles = _announcements_from_mubasher(_ANNOUNCEMENTS, "POCO")
    assert len(articles) == 1
    assert (
        articles[0].title
        == "Port Said Containers & Cargo (POCO.CA) - Board of Directors' Decisions"
    )
    assert articles[0].publisher == "Egyptian Stock Exchange"
    assert articles[0].published == "2026-09-28 09:02 UTC"
    assert articles[0].link == "https://english.mubasher.info/news/4677740/POCO-board/"


def test_world_topics_keep_wars_and_route_disruptions() -> None:
    assert _world_topic("Anthropic warns of catastrophic risk ahead of its listing") is None
    assert _world_topic("Airport lounges: how did they get so horribly decadent?") is None
    assert _world_topic("Algeria to send troops to Niger in first foreign deployment") == "wars"
    assert _world_topic("Sudan paramilitary drone strikes cause mass power cuts") == "wars"
    assert (
        _world_topic("Two killed in Houthi attack on airport in eastern Saudi Arabia") == "flights"
    )
    assert _world_topic("Oil spill washes up on UAE beaches after tanker strike") == "shipping"
    assert (
        _world_topic("UK airlines to be banned from charging parents to sit with children")
        == "flights"
    )
    assert _world_topic("Tanker disabled near Strait of Hormuz after reported attack") == "shipping"
    assert (
        _world_topic("US bans vehicles from China’s BYD at Japan military base, calling them risk")
        is None
    )
    assert (
        _world_topic("Melting glaciers in Dolomites reveal cache of first world war munitions")
        is None
    )


_EGX_ITEMS = [
    {
        "code": 1001,
        "dateStamp": "2026-10-26T22:00:00",
        "content": (
            "العنوان : قرار لجنة القيد لشركة تجريبية (DEMO.CA)<BR>\nاسم الشركة : شركة تجريبية<br/>"
        ),
        "contentArabic": None,
        "attachments": [
            {
                "attachmentId": 1,
                "fileName": "1001_220000.pdf",
                "webFlag": "Y",
            }
        ],
    },
    {
        "code": 1002,
        "dateStamp": "2026-10-26T20:37:00",
        "content": (
            "Subject : Board decisions for Demo Co (DEMO.CA)<BR>\n"
            "العنوان : قرارات مجلس الإدارة لشركة تجريبية (DEMO.CA)<BR>\n"
        ),
        "contentArabic": "العنوان : قرارات مجلس الإدارة لشركة تجريبية (DEMO.CA)<BR>",
        "attachments": [],
    },
    {
        "code": 1001,
        "dateStamp": "2026-10-26T22:00:00",
        "content": "العنوان : duplicate should be ignored<BR>",
        "attachments": [],
    },
    {
        "code": 1000,
        "dateStamp": "2026-10-25T09:00:00",
        "content": "موضوع الإعلان :<BR>\nإفصاح عن نتائج الأعمال الربع سنوية<br/>",
        "attachments": [{"fileName": "note.txt", "webFlag": "Y"}],
    },
    {
        "code": 1003,
        "dateStamp": "2026-10-26T18:00:00",
        "content": (
            "Company Name : Faisal Islamic Bank of Egypt<BR>\n"
            "Content : <BR>\n"
            "The company sent its disclosure form for the BoD.<br/>"
        ),
        "contentArabic": (
            "اسم الشركة : بنك فيصل الاسلامي المصرية بالجنية<BR>\n"
            "مضمون الاعلان : <BR>\n"
            "أفصحت الشركة عن هيكل المساهمين.<br/>"
        ),
        "attachments": [],
    },
    {
        # Live disclosures: English ``heading`` beats body noise like Interest Type.
        "code": 1004,
        "dateStamp": "2026-10-26T19:00:00",
        "heading": (
            "Egyptian Co for Securitization 11th Issue (EGECSE11C=CA) "
            "Declares Bond Dividends for Coupon No. (58)"
        ),
        "headingArabic": "سندات المصرية للتوريق إصدار الحادي عشر يعلن عن توزيع كوبون",
        "content": (
            "Issuer Name : Egyptian Co for Securitization<BR>\n"
            "Interest Type : Floating<BR>\n"
            "ISIN Code : EGB692C1S341<br/>"
        ),
        "contentArabic": "المصدر : سندات المصرية للتوريق<br/>",
        "attachments": [],
    },
]


def test_egx_media_center_items_become_egypt_headlines() -> None:
    arabic = _headlines_from_egx_news(_EGX_ITEMS, "ar", limit=12)
    assert [a.publisher for a in arabic] == ["البورصة المصرية"] * 5
    assert [a.topic for a in arabic] == ["egypt"] * 5
    assert arabic[0].title == "قرار لجنة القيد لشركة تجريبية (DEMO.CA)"
    assert arabic[0].published == "2026-10-26 22:00"
    assert arabic[0].link == "https://www.egx.com.eg/downloads/News/1001_220000.pdf"
    assert arabic[1].title == "قرارات مجلس الإدارة لشركة تجريبية (DEMO.CA)"
    assert arabic[1].link == "https://beta.egx.com.eg/ar/media-center"
    assert arabic[2].title == "سندات المصرية للتوريق إصدار الحادي عشر يعلن عن توزيع كوبون"
    assert arabic[3].title == "أفصحت الشركة عن هيكل المساهمين."
    assert arabic[4].title == "إفصاح عن نتائج الأعمال الربع سنوية"
    assert arabic[4].link == "https://beta.egx.com.eg/ar/media-center"

    english = _headlines_from_egx_news(_EGX_ITEMS, "en", limit=12)
    assert [a.publisher for a in english] == ["EGX"] * 3
    assert english[0].title == "Board decisions for Demo Co (DEMO.CA)"
    assert english[0].link == "https://beta.egx.com.eg/en/media-center"
    assert english[1].title == (
        "Egyptian Co for Securitization 11th Issue (EGECSE11C=CA) "
        "Declares Bond Dividends for Coupon No. (58)"
    )
    assert english[2].title == "The company sent its disclosure form for the BoD."
    # Arabic-only trading bodies are omitted in English (EGX EN media-center does the same).
    assert all(not re.search(r"[\u0600-\u06FF]", a.title) for a in english)
    assert "Interest Type" not in " ".join(a.title for a in english)


def test_egypt_headlines_return_empty_when_egx_bff_fails(monkeypatch) -> None:
    monkeypatch.setattr("egxdesk.services.desk._egx_news_search", lambda _body: None)
    assert _egypt_headlines("ar") == []
    assert _egypt_headlines("en") == []


def test_egx_en_uses_issuer_name_when_disclosure_has_no_subject() -> None:
    items = [
        {
            "code": 55,
            "dateStamp": "2026-10-26T10:00:00",
            "content": (
                "Issuer Name : Egyptian Co for Securitization Tranche C<BR>\n"
                "Interest Type : Floating<br/>\n"
                "Coupon Interest : 20.45%<br/>"
            ),
            "contentArabic": None,
            "attachments": [],
        }
    ]
    english = _headlines_from_egx_news(items, "en", limit=5)
    assert [a.title for a in english] == ["Egyptian Co for Securitization Tranche C"]


def test_egypt_en_prefers_english_disclosures_over_arabic_trading(monkeypatch) -> None:
    trading = [
        {
            "code": 1,
            "dateStamp": "2026-10-27T12:00:00",
            "content": "العنوان : قرار لجنة القيد لشركة عربية (ARAB.CA)<BR>",
            "contentArabic": None,
            "attachments": [],
        }
    ]
    disclosures = [
        {
            "code": 2,
            "dateStamp": "2026-10-26T12:00:00",
            "content": ("Company Name : Demo Bank<BR>\nContent : Board approved Q3 results.<BR>"),
            "contentArabic": "العنوان : نتائج الربع الثالث<br/>",
            "attachments": [],
        }
    ]

    def fake_search(body: dict):
        return trading if body.get("marketSessionNews") else disclosures

    monkeypatch.setattr("egxdesk.services.desk._egx_news_search", fake_search)
    english = _egypt_headlines("en")
    assert [a.title for a in english] == ["Board approved Q3 results."]
    arabic = _egypt_headlines("ar")
    assert arabic[0].title == "قرار لجنة القيد لشركة عربية (ARAB.CA)"


def test_egx_news_search_reads_success_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "egxdesk.services.desk._post_json",
        lambda _url, _body: {"success": True, "data": [{"code": 1}]},
    )
    assert _egx_news_search({"pageNumber": 1}) == [{"code": 1}]
    monkeypatch.setattr(
        "egxdesk.services.desk._post_json",
        lambda _url, _body: {"success": False, "data": [{"code": 1}]},
    )
    assert _egx_news_search({"pageNumber": 1}) is None
