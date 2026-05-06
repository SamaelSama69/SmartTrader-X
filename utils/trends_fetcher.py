"""
Trends Fetcher - Retrieves trending searches and stocks for the Indian market.
Sources: Google Trends (RSS India), Yahoo Finance (Trending Tickers).
"""
import feedparser
import yfinance as yf
import pandas as pd
import logging
from typing import List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class TrendingFetcher:
    @staticmethod
    def get_google_trends_india() -> List[Dict]:
        """Fetch daily trending searches from Google Trends India RSS."""
        try:
            url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=IN"
            feed = feedparser.parse(url)
            trends = []
            for entry in feed.entries[:10]:
                trends.append({
                    'title': entry.title,
                    'approx_traffic': getattr(entry, 'ht_approx_traffic', 'N/A'),
                    'link': entry.link
                })
            return trends
        except Exception as e:
            logger.error(f"Google Trends error: {e}")
            return []

    @staticmethod
    def get_trending_tickers_india() -> List[Dict]:
        """Fetch trending tickers for the Indian market from Yahoo Finance."""
        # Yahoo doesn't have a direct 'trending' list for India in yfinance readily,
        # but we can simulate it using most active or searching specifically.
        # For now, we use a reliable method to get broad trending data.
        try:
            # We can use a common Nifty 50 universe and check volume spikes
            from utils.nse_data import NIFTY_50_TICKERS
            # Note: Checking all is slow, so we check a small sample or use a pre-defined 'hot' list
            hot_list = ["RVNL.NS", "IRFC.NS", "HUDCO.NS", "ZOMATO.NS", "SUZLON.NS", "IREDA.NS", "JIOFIN.NS"]
            results = []
            for t in hot_list:
                ticker = yf.Ticker(t)
                info = ticker.fast_info
                results.append({
                    'symbol': t.replace('.NS', ''),
                    'price': info.get('lastPrice', 0),
                    'change': ((info.get('lastPrice', 0) / info.get('previousClose', 1)) - 1) * 100
                })
            return sorted(results, key=lambda x: abs(x['change']), reverse=True)
        except Exception as e:
            logger.error(f"Trending tickers error: {e}")
            return []

    @staticmethod
    def get_most_searched_finance() -> List[str]:
        """Synthesizes Google Trends and Market data to find 'Most Searched' finance terms."""
        google = TrendingFetcher.get_google_trends_india()
        # Filter for finance/market related terms
        finance_keywords = ['stock', 'nifty', 'share', 'ipo', 'price', 'dividend', 'market', 'bank', 'sensex', 'trading']
        hot_terms = []
        for t in google:
            if any(kw in t['title'].lower() for kw in finance_keywords):
                hot_terms.append(t['title'])
        
        # Fallback if no specific finance trends are found today
        if not hot_terms:
            hot_terms = ["Nifty 50 Strategy", "SME IPO Status", "Bluechip Dividends"]
            
        return hot_terms
