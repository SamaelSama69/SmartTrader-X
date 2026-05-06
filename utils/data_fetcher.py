"""
Data Fetcher - Free market data from multiple sources
Uses yfinance, News API, Reddit, Finnhub (free tiers)
Includes caching and rate limiting for performance
"""

import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import time
import logging
import asyncio
import aiohttp
import json
from pathlib import Path
from functools import wraps
from utils.cache import (
    market_data_cache, company_info_cache,
    cached
)

# Optional BeautifulSoup for scraping
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

# Set up logger
logger = logging.getLogger(__name__)

# NSE stock list cache (refresh every 24h)
NSE_CACHE_DIR = Path("./.cache")
NSE_STOCKS_CACHE = NSE_CACHE_DIR / "nse_stocks.json"
NSE_CACHE_TTL = 86400  # 24 hours in seconds


def retry_with_backoff(max_retries=3, delay=1, backoff=2, exceptions=(requests.exceptions.RequestException,)):
    """Retry decorator with exponential backoff for API calls"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries >= max_retries:
                        raise
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator

class MarketDataFetcher:
    """Fetch stock market data using free sources
    Includes caching and rate limiting for performance
    """

    def __init__(self):
        self.session = requests.Session()
        self._last_api_call = 0
        self._min_api_interval = 0.5  # 500ms between API calls

    def _rate_limit(self):
        """Apply rate limiting between API calls"""
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < self._min_api_interval:
            time.sleep(self._min_api_interval - elapsed)
        self._last_api_call = time.time()

    @cached(market_data_cache, ttl=300)  # Cache for 5 minutes
    def get_stock_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch historical stock data from Yahoo Finance (cached)"""
        try:
            self._rate_limit()
            # Use download for batch capability, but single ticker here
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            
            if df is None or df.empty:
                logger.warning(f"No data returned for {ticker} (period: {period})")
                return pd.DataFrame()
                
            # Handle potential multi-index columns if download returned them
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                
            df.reset_index(inplace=True)
            return df
        except ConnectionError as e:
            logger.error(f"Connection error while fetching {ticker}: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Unexpected error fetching stock data for {ticker}: {e}", exc_info=True)
            return pd.DataFrame()

    @cached(market_data_cache, ttl=60)  # Cache for 1 minute (price changes frequently)
    def get_current_price(self, ticker: str) -> Optional[float]:
        """Get current/live price (cached with short TTL)"""
        try:
            self._rate_limit()
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            return info.get('currentPrice') or info.get('regularMarketPrice')
        except Exception as e:
            logger.debug(f"get_current_price failed: {e}")
            return None

    @cached(market_data_cache, ttl=3600)  # Cache for 1 hour
    def get_options_chain(self, ticker: str) -> Dict:
        """Fetch options chain data (cached)"""
        try:
            self._rate_limit()
            stock = yf.Ticker(ticker)
            expirations = stock.options
            if not expirations:
                return {}

            options_data = {}
            for exp in expirations[:5]:  # Limit to 5 nearest expirations
                chain = stock.option_chain(exp)
                options_data[exp] = {
                    'calls': chain.calls.to_dict('records'),
                    'puts': chain.puts.to_dict('records')
                }
            return options_data
        except Exception as e:
            logger.error(f"Error fetching options for {ticker}: {e}")
            return {}

    @cached(company_info_cache, ttl=3600)  # Cache for 1 hour
    def get_company_info(self, ticker: str) -> Dict:
        """Get company fundamentals (cached)"""
        try:
            self._rate_limit()
            stock = yf.Ticker(ticker)
            info = stock.info
            return {
                'name': info.get('longName', ''),
                'sector': info.get('sector', ''),
                'industry': info.get('industry', ''),
                'market_cap': info.get('marketCap', 0),
                'pe_ratio': info.get('trailingPE', None),
                'forward_pe': info.get('forwardPE', None),
                'dividend_yield': info.get('dividendYield', 0),
                'beta': info.get('beta', None),
                '52w_high': info.get('fiftyTwoWeekHigh', None),
                '52w_low': info.get('fiftyTwoWeekLow', None),
                'avg_volume': info.get('averageVolume', 0),
                'revenue_growth': info.get('revenueGrowth', None),
                'profit_margin': info.get('profitMargins', None),
            }
        except Exception as e:
            logger.error(f"Error fetching company info for {ticker}: {e}")
            return {}

    def get_batch_stock_data(self, tickers: List[str], period: str = "1y") -> Dict[str, pd.DataFrame]:
        """
        Fetch stock data for multiple tickers in a single batch call
        Returns dict mapping ticker to DataFrame
        """
        try:
            self._rate_limit()
            # Use yfinance batch download
            data = yf.download(
                tickers,
                period=period,
                group_by='ticker',
                progress=False,
                auto_adjust=True
            )

            if data.empty:
                return {}

            result = {}
            if len(tickers) == 1:
                # Single ticker returns different format
                data = data.reset_index()
                result[tickers[0]] = data
            else:
                # Multiple tickers - group_by='ticker' returns multi-level columns
                for ticker in tickers:
                    try:
                        if ticker in data.columns.levels[0]:
                            ticker_data = data[ticker].copy().reset_index()
                            result[ticker] = ticker_data
                    except Exception as e:
                        logger.debug(f"Failed to fetch {ticker}: {e}")
                        continue

            return result
        except Exception as e:
            logger.error(f"Error batch fetching stock data: {e}")
            return {}


async def fetch_nse_stock_list(force_refresh: bool = False) -> List[Dict]:
    """Fetch NSE stock list with disk cache (24h TTL)"""
    NSE_CACHE_DIR.mkdir(exist_ok=True)
    # Check cache if not forcing refresh
    if not force_refresh and NSE_STOCKS_CACHE.exists():
        try:
            with open(NSE_STOCKS_CACHE, 'r') as f:
                cache = json.load(f)
            if time.time() - cache.get('timestamp', 0) < NSE_CACHE_TTL:
                return cache.get('stocks', [])
        except Exception:
            pass
    # Fetch fresh list from NSE (requires cookie handshake)
    stocks = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            # Get cookies from NSE homepage (required for API access)
            async with session.get("https://www.nseindia.com", timeout=10) as resp:
                pass
            # Fetch equity master list
            url = "https://www.nseindia.com/api/equity-master?response=json"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get('data', []):
                        if item.get('status') == 'Active':
                            stocks.append({
                                'symbol': item['symbol'],
                                'name': item.get('companyName', ''),
                                'sector': item.get('industry', 'Unknown'),
                                'isin': item.get('isin', '')
                            })
    except Exception as e:
        logger.error(f"Failed to fetch NSE stock list: {e}")
        # Fallback to cached data if available
        if NSE_STOCKS_CACHE.exists():
            try:
                with open(NSE_STOCKS_CACHE, 'r') as f:
                    cache = json.load(f)
                return cache.get('stocks', [])
            except Exception:
                pass
        return []
    # Save to cache
    try:
        with open(NSE_STOCKS_CACHE, 'w') as f:
            json.dump({
                'timestamp': time.time(),
                'stocks': stocks
            }, f)
    except Exception as e:
        logger.error(f"Failed to cache NSE stock list: {e}")
    return stocks


async def _fetch_multiple_stocks_async(tickers: List[str], period: str = "1y") -> Dict[str, pd.DataFrame]:
    """Async fetch multiple NSE stocks (max 10 concurrent)"""
    semaphore = asyncio.Semaphore(10)
    results = {}

    # Convert period to start timestamp
    period_days = {"1y": 365, "6mo": 180, "3mo": 90, "1mo": 30}
    days = period_days.get(period, 365)
    start_ts = int(time.time() - days * 86400)
    end_ts = int(time.time())

    async def fetch_single(session, ticker):
        async with semaphore:
            ticker_ns = ticker if ticker.endswith('.NS') else f"{ticker}.NS"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_ns}?period1={start_ts}&period2={end_ts}&interval=1d&events=history"
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return ticker, None
                    data = await resp.json()
                    chart = data.get('chart', {}).get('result', [{}])[0]
                    if not chart:
                        return ticker, None
                    timestamps = chart.get('timestamp', [])
                    quotes = chart.get('indicators', {}).get('quote', [{}])[0]
                    if not timestamps or not quotes:
                        return ticker, None
                    df = pd.DataFrame({
                        'Open': quotes.get('open', []),
                        'High': quotes.get('high', []),
                        'Low': quotes.get('low', []),
                        'Close': quotes.get('close', []),
                        'Volume': quotes.get('volume', [])
                    }, index=pd.to_datetime(timestamps, unit='s'))
                    df.reset_index(inplace=True)
                    df.rename(columns={'index': 'Date'}, inplace=True)
                    return ticker, df
            except Exception as e:
                logger.error(f"Error fetching {ticker}: {e}")
                return ticker, None

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_single(session, ticker) for ticker in tickers]
        responses = await asyncio.gather(*tasks)
        for ticker, df in responses:
            if df is not None:
                results[ticker] = df
    return results


def fetch_multiple_stocks(tickers: List[str], period: str = "1y") -> Dict[str, pd.DataFrame]:
    """Sync wrapper for async multi-stock fetch (matches test command)"""
    return asyncio.run(_fetch_multiple_stocks_async(tickers, period))
