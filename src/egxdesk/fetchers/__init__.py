from __future__ import annotations

from egxdesk.fetchers.alpha_vantage import AlphaVantageFetcher
from egxdesk.fetchers.egx_watch import EgxMarketWatchFetcher
from egxdesk.fetchers.finnhub import FinnhubFetcher
from egxdesk.fetchers.starta import StartaFetcher
from egxdesk.fetchers.yahoo import YahooFetcher

__all__ = [
    "AlphaVantageFetcher",
    "EgxMarketWatchFetcher",
    "FinnhubFetcher",
    "StartaFetcher",
    "YahooFetcher",
]
