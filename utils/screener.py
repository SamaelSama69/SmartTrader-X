"""
Stock Screener - Find promising Indian companies using free data
Focuses compute on few high-potential tickers from NSE/BSE
Includes batch API calls and optimized data passing for performance
"""

import yfinance as yf
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import numpy as np
import time
import logging

from config import MAX_TICKERS_TO_ANALYZE, SCREEN_CRITERIA
from utils.data_fetcher import MarketDataFetcher
import indian_config

# Set up logger
logger = logging.getLogger(__name__)


class SmartScreener:
    """
    Screens Indian stocks to find few promising ones
    Uses free yfinance data and pre-computed indicators when possible
    Optimized with batch API calls and data passing between functions
    """

    def __init__(self):
        self.data_fetcher = MarketDataFetcher()
        self.major_tickers = self._get_major_tickers()
        self._last_api_call = 0
        self._min_api_interval = 0.5  # 500ms between API calls

    def _rate_limit(self):
        """Apply rate limiting between API calls"""
        now = time.time()
        elapsed = now - self._last_api_call
        if elapsed < self._min_api_interval:
            time.sleep(self._min_api_interval - elapsed)
        self._last_api_call = time.time()

    def _get_major_tickers(self) -> List[str]:
        """Get list of major Indian tickers to screen (NSE/BSE)"""
        # Flatten the popular Indian stocks dictionary
        tickers = []
        for category, stocks in indian_config.POPULAR_INDIAN_STOCKS.items():
            if isinstance(stocks, list):
                tickers.extend(stocks)
            elif isinstance(stocks, dict):
                # Handle sectors sub-dictionary
                for sector, sector_stocks in stocks.items():
                    tickers.extend(sector_stocks)
        return tickers[:MAX_TICKERS_TO_ANALYZE]  # Respect the limit

    def screen_by_market_cap(self, min_cap: float = 1e9) -> List[str]:
        """Quick filter by market cap using yfinance batch queries"""
        qualified = []

        # Batch process to minimize API calls
        batch_size = 20
        for i in range(0, len(self.major_tickers), batch_size):
            batch = self.major_tickers[i:i+batch_size]
            try:
                self._rate_limit()
                # Use batch download for price data (period=5d for valid closes)
                data = yf.download(batch, period='5d', progress=False, auto_adjust=True)

                # Process downloaded data to find active tickers with valid close prices
                if isinstance(data.columns, pd.MultiIndex):
                    # Multiple tickers: data['Close'] is DataFrame with ticker columns
                    closes = data['Close']
                    active_tickers = [t for t in batch if t in closes.columns and closes[t].dropna().shape[0] > 0]
                else:
                    # Single ticker: data['Close'] is Series
                    ticker = batch[0]
                    closes = data['Close']
                    active_tickers = [ticker] if closes.dropna().shape[0] > 0 else []

                # Only fetch company info for active tickers (avoid unnecessary API calls)
                for ticker in active_tickers:
                    try:
                        # Use cached company info to avoid individual API calls
                        info = self.data_fetcher.get_company_info(ticker)
                        if info.get('market_cap', 0) >= min_cap:
                            qualified.append(ticker)
                    except Exception:
                        continue

            except Exception as e:
                logger.error(f"Batch screen error: {e}")
                continue

        return qualified

    def screen_by_momentum(self, tickers: List[str], min_rsi: float = 30, max_rsi: float = 70) -> List[Dict]:
        """
        Screen for momentum setups using batch data fetching
        Passes data between calculations to avoid refetching
        """
        results = []
        tickers_to_screen = tickers[:50]  # Limit to top 50 for compute efficiency

        if not tickers_to_screen:
            return results

        try:
            self._rate_limit()
            # Batch download historical data for all tickers at once
            batch_data = self.data_fetcher.get_batch_stock_data(
                tickers_to_screen, period='3mo'
            )

            for ticker in tickers_to_screen:
                try:
                    if ticker not in batch_data:
                        continue

                    hist = batch_data[ticker]

                    if hist.empty or len(hist) < 20:
                        continue

                    # Calculate RSI locally (lightweight)
                    delta = hist['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss
                    rsi = 100 - (100 / (1 + rs))
                    current_rsi = rsi.iloc[-1]

                    if pd.isna(current_rsi) or current_rsi < min_rsi or current_rsi > max_rsi:
                        continue

                    # Price momentum
                    price_change_1m = (hist['Close'].iloc[-1] / hist['Close'].iloc[-22] - 1) if len(hist) >= 22 else 0
                    price_change_1w = (hist['Close'].iloc[-1] / hist['Close'].iloc[-5] - 1) if len(hist) >= 5 else 0

                    # Volume surge and illiquidity filter (exclude <50k daily volume)
                    avg_volume = hist['Volume'].rolling(20).mean().iloc[-1]
                    if pd.isna(avg_volume) or avg_volume < 50000:
                        continue
                    current_volume = hist['Volume'].iloc[-1]
                    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

                    # Moving averages
                    ma_50 = hist['Close'].rolling(50).mean().iloc[-1]
                    ma_200 = hist['Close'].rolling(200).mean().iloc[-1] if len(hist) >= 200 else ma_50
                    current_price = hist['Close'].iloc[-1]

                    # Score the setup
                    score = 0
                    if price_change_1m > 0: score += 2
                    if price_change_1w > 0: score += 1
                    if current_price > ma_50: score += 2
                    if current_price > ma_200: score += 2
                    if volume_ratio > 1.5: score += 1
                    if 40 < current_rsi < 60: score += 1  # Not overbought/oversold

                    results.append({
                        'ticker': ticker,
                        'score': score,
                        'rsi': round(current_rsi, 2),
                        'price_change_1m': round(price_change_1m * 100, 2),
                        'price_change_1w': round(price_change_1w * 100, 2),
                        'volume_surge': round(volume_ratio, 2),
                        'price': round(current_price, 2),
                        'ma_50': round(ma_50, 2),
                        'ma_200': round(ma_200, 2),
                    })

                except Exception as e:
                    logger.error(f"Error screening {ticker}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Batch momentum screen error: {e}")

        return sorted(results, key=lambda x: x['score'], reverse=True)

    def screen_by_volatility(self, tickers: List[str], min_atr_pct: float = 0.02) -> List[Dict]:
        """
        Screen for volatility (good for options trading)
        Uses batch data fetching to avoid individual API calls
        """
        results = []
        tickers_to_screen = tickers[:30]  # Limit for compute

        if not tickers_to_screen:
            return results

        try:
            self._rate_limit()
            # Batch download historical data
            batch_data = self.data_fetcher.get_batch_stock_data(
                tickers_to_screen, period='3mo'
            )

            for ticker in tickers_to_screen:
                try:
                    if ticker not in batch_data:
                        continue

                    hist = batch_data[ticker]

                    if hist.empty or len(hist) < 14:
                        continue

                    # Calculate ATR (Average True Range)
                    high_low = hist['High'] - hist['Low']
                    high_close = np.abs(hist['High'] - hist['Close'].shift())
                    low_close = np.abs(hist['Low'] - hist['Close'].shift())
                    ranges = pd.concat([high_low, high_close, low_close], axis=1)
                    true_range = np.max(ranges, axis=1)
                    atr = true_range.rolling(14).mean().iloc[-1]
                    atr_pct = atr / hist['Close'].iloc[-1]

                    if atr_pct >= min_atr_pct:
                        results.append({
                            'ticker': ticker,
                            'atr_pct': round(atr_pct * 100, 2),
                            'price': round(hist['Close'].iloc[-1], 2),
                            'volatility_score': round(atr_pct * 100, 2)
                        })

                except Exception as e:
                    continue

        except Exception as e:
            logger.error(f"Batch volatility screen error: {e}")

        return sorted(results, key=lambda x: x['atr_pct'], reverse=True)

    def get_top_opportunities(self, max_results: int = MAX_TICKERS_TO_ANALYZE) -> List[Dict]:
        """
        Main method: Get top trading opportunities
        Returns only the best few tickers to focus compute on
        Uses optimized batch processing
        """
        logger.info("Screening for top opportunities...")

        # Step 1: Quick market cap filter
        logger.info("  Step 1: Filtering by market cap...")
        qualified = self.screen_by_market_cap(SCREEN_CRITERIA['min_market_cap'])
        logger.info(f"  Qualified tickers after market cap filter: {len(qualified)}")

        # Step 2: Momentum screen (uses batch data fetching)
        logger.info("  Step 2: Screening for momentum...")
        momentum_results = self.screen_by_momentum(qualified)
        logger.info(f"  Momentum candidates: {len(momentum_results)}")

        # Step 3: Return top N
        top = momentum_results[:max_results]
        logger.info(f"  Top {len(top)} opportunities identified")

        return top

    def get_sector_performance(self) -> Dict:
        """Get Indian sector index performance using batch API calls"""
        sectors = {
            'Banking': '^NSEBANK',
            'IT': '^CNXIT',
            'Auto': '^CNXAUTO',
            'Pharma': '^CNXPHARMA',
            'FMCG': '^CNXFMCG',
            'Metal': '^CNXMETAL',
            'Realty': '^CNXREALTY',
            'Energy': '^CNXENERGY'
        }

        performance = {}

        try:
            self._rate_limit()
            # Batch download all sector ETF data at once
            etf_tickers = list(sectors.values())
            batch_data = yf.download(
                etf_tickers,
                period='1mo',
                group_by='ticker',
                progress=False,
                auto_adjust=True
            )

            for sector, etf in sectors.items():
                try:
                    if len(etf_tickers) == 1:
                        hist = batch_data
                    else:
                        hist = batch_data[etf]

                    if not hist.empty and len(hist) > 0:
                        perf = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                        performance[sector] = round(perf, 2)
                    else:
                        performance[sector] = 0.0
                except Exception:
                    performance[sector] = 0.0

        except Exception as e:
            logger.error(f"Sector performance error: {e}")
            # Fallback to individual calls
            for sector, etf in sectors.items():
                try:
                    self._rate_limit()
                    hist = yf.Ticker(etf).history(period='1mo')
                    if not hist.empty:
                        perf = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                        performance[sector] = round(perf, 2)
                except:
                    performance[sector] = 0.0

        return performance
