"""
Prebuilt Algorithm Strategies
Based on real profitable traders and platforms like Bulls AI
Includes Indian market-specific algorithms
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

from utils.indian_indicators import calculate_vwap, calculate_supertrend, calculate_cpr, is_expiry_day, is_budget_day
from utils.nse_data import convert_to_nse_format
from utils.multilingual_sentiment import get_sentiment_engine, get_news_aggregator
from utils.market_regime import IndianMarketRegime

try:
    _yf_cache = Path(__file__).resolve().parents[1] / "data" / "yfinance_cache"
    _yf_cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(_yf_cache))
except Exception:
    pass

_INFO_CACHE = {}

def _get_cached_info(ticker: str) -> dict:
    if ticker not in _INFO_CACHE:
        try:
            _INFO_CACHE[ticker] = yf.Ticker(ticker).info
        except Exception:
            _INFO_CACHE[ticker] = {}
    return _INFO_CACHE[ticker]


class BaseAlgorithm:
    """Base class for all trading algorithms"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.signals = []

    def analyze(self, ticker: str, hist: pd.DataFrame) -> Dict:
        """Analyze ticker and return signal"""
        raise NotImplementedError

    def get_score(self, ticker: str, hist: pd.DataFrame) -> float:
        """Return confidence score (0-1)"""
        raise NotImplementedError


class BuffettValueAlgorithm(BaseAlgorithm):
    """
    Warren Buffett Value Strategy
    - Focus on quality companies with moat
    - Low P/E, consistent growth, strong ROE
    - "Be fearful when others are greedy, greedy when others are fearful"
    """

    def __init__(self):
        super().__init__(
            "Buffett Value",
            "Value investing strategy focusing on quality companies with strong fundamentals"
        )

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            info = _get_cached_info(ticker)

            # Value metrics
            pe_ratio = info.get('trailingPE', 999)
            forward_pe = info.get('forwardPE', 999)
            roe = info.get('returnOnEquity', 0)
            debt_to_equity = info.get('debtToEquity', 999)
            profit_margin = info.get('profitMargins', 0)

            # Buffett criteria
            score = 0
            signals = []

            # P/E thresholds (Nifty 50 trades at 22-24x historically)
            if pe_ratio and pe_ratio < 20:
                score += 2
                signals.append("Low P/E ratio")
            elif pe_ratio and pe_ratio < 28:
                score += 1

            # 2. Strong ROE (> 15%)
            if roe and roe > 0.20:
                score += 2
                signals.append("Strong ROE")
            elif roe and roe > 0.15:
                score += 1

            # Debt-to-equity (Indian large-caps carry more leverage)
            if debt_to_equity and debt_to_equity < 1.0:
                score += 1
                signals.append("Low debt")

            # Profit margin (lower for Indian FMCG and banking)
            if profit_margin and profit_margin > 0.10:
                score += 1
                signals.append("High profit margin")

            # Add dividend yield check (PSU stocks: ONGC, Coal India pay high dividends)
            div_yield = info.get('dividendYield', 0) or 0
            if div_yield > 0.03:
                score += 1
                signals.append("High dividend yield")

            # 5. Long-term price trend (200-day MA)
            if hist is not None and len(hist) >= 200:
                ma_200 = hist['Close'].iloc[-200:].mean()
                current = hist['Close'].iloc[-1]
                if current > ma_200:
                    score += 1
                    signals.append("Above 200-day MA")

            # Generate signal
            max_score = 8
            confidence = min(score / max_score, 1.0)

            if score >= 4:
                signal = 'BUY'
            elif score <= 2:
                signal = 'SELL'
            else:
                signal = 'HOLD'

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': confidence,
                'score': score,
                'max_score': max_score,
                'signals': signals,
                'metrics': {
                    'pe_ratio': pe_ratio,
                    'forward_pe': forward_pe,
                    'roe': roe,
                    'profit_margin': profit_margin,
                    'debt_to_equity': debt_to_equity
                }
            }

        except Exception as e:
            return {'error': str(e)}


class DalioAllWeatherAlgorithm(BaseAlgorithm):
    """
    Ray Dalio's All-Weather Strategy
    - Risk parity approach
    - Works in all economic environments
    - Balanced exposure to growth/inflation scenarios
    """

    def __init__(self):
        super().__init__(
            "Dalio All-Weather",
            "Risk-parity strategy for all economic conditions"
        )
        self._market_cache: dict = {}
        self._cache_expiry: dict = {}

    def _get_market_returns(self, symbol: str) -> pd.Series:
        """Cached market data fetch — TTL 1 hour."""
        import time
        if symbol in self._market_cache and time.time() < self._cache_expiry.get(symbol, 0):
            return self._market_cache[symbol]
        data = yf.Ticker(symbol).history(period='3mo')['Close'].pct_change().dropna()
        self._market_cache[symbol] = data
        self._cache_expiry[symbol] = time.time() + 3600
        return data

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            info = _get_cached_info(ticker)

            # Look at asset type (stock vs ETF)
            is_etf = info.get('quoteType', '') == 'ETF'

            score = 0
            signals = []

            if is_etf:
                # For ETFs, check diversification
                category = info.get('category', '').lower()

                # Favor broad market ETFs
                if 's&p' in category or 'total market' in category:
                    score += 2
                    signals.append("Broad market exposure")
                elif 'bond' in category or 'treasury' in category:
                    score += 1
                    signals.append("Fixed income exposure")
                elif 'commodity' in category or 'gold' in category:
                    score += 1
                    signals.append("Inflation hedge")
            else:
                # For stocks, check stability
                beta = info.get('beta', 1.0)
                volatility = info.get('volatility', 0)

                if beta and beta < 1.0:
                    score += 1
                    signals.append("Low beta (defensive)")

                # Replace info.get('volatility') with realized volatility
                if hist is not None and len(hist) >= 20:
                    realized_vol = hist['Close'].pct_change().dropna().std() * (252 ** 0.5)
                    if realized_vol < 0.20:
                        score += 1
                        signals.append(f"Low realized volatility ({realized_vol:.1%})")
                elif volatility and volatility < 0.20:
                    score += 1
                    signals.append("Low volatility")

                # Consistent dividend
                div_yield = info.get('dividendYield', 0)
                if div_yield and div_yield > 0.02:
                    score += 1
                    signals.append("Pays dividend")

            # Check correlation to market (simplified)
            if hist is not None and len(hist) >= 60:
                returns = hist['Close'].pct_change().dropna()
                # Use correct market benchmark: Nifty 50 for Indian stocks, SPY for US
                _market_symbol = '^NSEI' if '.NS' in ticker or '.BO' in ticker else 'SPY'
                market = self._get_market_returns(_market_symbol)

                if len(returns) > 0 and len(market) > 0:
                    # Align dates
                    min_len = min(len(returns), len(market))
                    corr = returns.iloc[-min_len:].corr(market.iloc[-min_len:])
                    if corr < 0.5:
                        score += 1
                        signals.append("Low market correlation")

            confidence = min(score / 5, 1.0)

            if score >= 3:
                signal = 'BUY'
            elif score <= 1:
                signal = 'SELL'
            else:
                signal = 'HOLD'

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': confidence,
                'score': score,
                'signals': signals,
                'diversification_score': score
            }

        except Exception as e:
            return {'error': str(e)}


class BullsAIStyleAlgorithm(BaseAlgorithm):
    """
    Bulls AI-Inspired Momentum Algorithm
    - Trend following with AI signals
    - Volume confirmation
    - Multiple timeframe analysis
    - "The trend is your friend until it ends"
    """

    def __init__(self):
        super().__init__(
            "Bulls AI Momentum",
            "AI-inspired momentum strategy with volume confirmation"
        )

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            if hist is None:
                hist = yf.Ticker(ticker).history(period='6mo')

            if hist.empty or len(hist) < 50:
                return {'error': 'Insufficient data'}

            # Optimize for backtesting speed
            hist = hist.tail(250)

            score = 0
            signals = []

            # 1. Trend confirmation (multiple MAs)
            ma_20 = hist['Close'].iloc[-20:].mean()
            ma_50 = hist['Close'].iloc[-50:].mean()
            ma_200 = hist['Close'].iloc[-200:].mean() if len(hist) >= 200 else ma_50

            current = hist['Close'].iloc[-1]

            if current > ma_20 > ma_50 > ma_200:
                score += 3
                signals.append("Strong uptrend (price > MA20 > MA50 > MA200)")
            elif current > ma_20 > ma_50:
                score += 2
                signals.append("Uptrend confirmed")
            elif current < ma_20 < ma_50:
                score -= 2
                signals.append("Downtrend confirmed")

            # 2. Volume confirmation
            avg_volume = hist['Volume'].iloc[-20:].mean()
            current_volume = hist['Volume'].iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            if volume_ratio > 2.0:
                score += 2
                signals.append(f"High volume surge ({volume_ratio:.1f}x)")
            elif volume_ratio > 1.5:
                score += 1
                signals.append("Volume above average")

            # 3. Momentum (RSI) - Wilder's smoothing (correct for NSE)
            delta = hist['Close'].diff().dropna()
            gain = delta.where(delta > 0, 0)
            loss = -delta.where(delta < 0, 0)
            # Wilder's smoothing: average gain/loss = (prev_avg * 13 + current) /14
            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            current_rsi = rsi.iloc[-1]

            if 50 < current_rsi < 70:
                score += 2
                signals.append("RSI in sweet spot (50-70)")
            elif current_rsi > 80:
                score -= 1  # Overbought
                signals.append("Overbought (RSI > 80)")
            elif current_rsi < 30:
                score -= 1
                signals.append("Oversold (potential bounce)")

            # 4. MACD
            ema_12 = hist['Close'].ewm(span=12, adjust=False).mean()
            ema_26 = hist['Close'].ewm(span=26, adjust=False).mean()
            macd = ema_12 - ema_26
            signal_line = macd.ewm(span=9, adjust=False).mean()

            if macd.iloc[-1] > signal_line.iloc[-1] and macd.iloc[-2] <= signal_line.iloc[-2]:
                score += 2
                signals.append("MACD bullish crossover")
            elif macd.iloc[-1] < signal_line.iloc[-1] and macd.iloc[-2] >= signal_line.iloc[-2]:
                score -= 2
                signals.append("MACD bearish crossover")

            # Generate signal
            confidence = abs(score) / 7.0

            if score >= 4:
                signal = 'BUY'
            elif score <= -3:
                signal = 'SELL'
            else:
                signal = 'HOLD'

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': min(confidence, 1.0),
                'score': score,
                'signals': signals,
                'metrics': {
                    'rsi': round(current_rsi, 2),
                    'macd': round(macd.iloc[-1], 4),
                    'volume_ratio': round(volume_ratio, 2),
                    'ma_20': round(ma_20, 2),
                    'ma_50': round(ma_50, 2),
                }
            }

        except Exception as e:
            return {'error': str(e)}


class WoodDisruptiveGrowthAlgorithm(BaseAlgorithm):
    """
    Cathie Wood ARK-Style Disruptive Growth
    - Focus on disruptive innovation
    - High growth, scalable tech
    "Buy the future at a discount"
    """

    def __init__(self):
        super().__init__(
            "Wood Disruptive Growth",
            "ARK-style strategy focusing on disruptive technology and innovation"
        )

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            info = _get_cached_info(ticker)

            score = 0
            signals = []

            # 1. Sector check (tech, healthare, innovation)
            sector = info.get('sector', '').lower()
            industry = info.get('industry', '').lower()

            innovation_keywords = ['tech', 'software', 'ai', 'biotech', 'genomic', 'robot', 'cloud', 'fintech']

            if any(kw in sector or kw in industry for kw in innovation_keywords):
                score += 2
                signals.append("Disruptive sector/industry")

            # 2. Revenue growth
            revenue_growth = info.get('revenueGrowth', 0)
            if revenue_growth and revenue_growth > 0.30:
                score += 2
                signals.append(f"High revenue growth ({revenue_growth*100:.0f}%)")
            elif revenue_growth and revenue_growth > 0.20:
                score += 1

            # 3. Forward P/E (growth premium is OK)
            forward_pe = info.get('forwardPE', 999)
            if forward_pe and 15 < forward_pe < 40:
                score += 1
                signals.append("Reasonable forward P/E for growth")

            # 4. Price momentum (6-month)
            if hist is not None and len(hist) >= 126:  # ~6 months
                price_change = (hist['Close'].iloc[-1] / hist['Close'].iloc[-126] - 1) * 100
                if price_change > 20:
                    score += 1
                    signals.append(f"Strong 6M momentum (+{price_change:.0f}%)")
                elif price_change < -20:
                    score -= 1
                    signals.append(f"Down 20%+ (potential value)")

            # 5. Market cap (prefer mid-cap for growth)
            market_cap = info.get('marketCap', 0)
            if 1e9 < market_cap < 1e11:  # $1B - $100B
                score += 1
                signals.append("Mid-cap sweet spot")

            confidence = min(score / 6, 1.0)

            if score >= 4:
                signal = 'BUY'
            elif score <= 1:
                signal = 'SELL'
            else:
                signal = 'HOLD'

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': confidence,
                'score': score,
                'signals': signals,
                'metrics': {
                    'revenue_growth': revenue_growth,
                    'forward_pe': forward_pe,
                    'market_cap_b': market_cap / 1e9 if market_cap else 0,
                }
            }

        except Exception as e:
            return {'error': str(e)}


class IndianMomentumAlgorithm(BaseAlgorithm):
    """
    Indian Momentum Strategy
    - Uses VWAP (Volume Weighted Average Price) for entry
    - Uses Supertrend for trend confirmation and exit
    - Popular among Indian day traders
    - Works well for liquid Nifty stocks
    - Now includes OI (Open Interest) and sentiment filters
    """

    def __init__(self):
        super().__init__(
            "Indian Momentum",
            "VWAP + Supertrend based momentum strategy for Indian markets"
        )
        self.vwap_period = 1  # Daily VWAP reset
        self.supertrend_period = 10
        self.supertrend_multiplier = 3.0
        self.sentiment_engine = get_sentiment_engine()
        self.news_aggregator = get_news_aggregator()
        self._nse_fetcher = None

    def _get_nse_fetcher(self):
        """Lazy-load NSE data fetcher"""
        if self._nse_fetcher is None:
            from utils.nse_data import NSEDataFetcher
            self._nse_fetcher = NSEDataFetcher()
        return self._nse_fetcher

    def analyze(self, ticker: str, hist: pd.DataFrame = None, sentiment_score: float = 0.0, industry_sentiment: float = 0.0) -> Dict:
        """
        Analyze ticker with optional sentiment filters.

        Args:
            ticker: Stock ticker symbol
            hist: Historical price data (optional)
            sentiment_score: Overall sentiment score (-1 to 1)
            industry_sentiment: Industry-specific sentiment score (-1 to 1)
        """
        try:
            # Convert to NSE format if needed
            ticker = convert_to_nse_format(ticker)

            if hist is None:
                hist = yf.Ticker(ticker).history(period='3mo')

            if hist.empty or len(hist) < 50:
                return {'error': 'Insufficient data'}

            score = 0
            signals = []

            # 1. VWAP Analysis
            vwap = calculate_vwap(hist)
            current_price = float(hist['Close'].iloc[-1].item() if hasattr(hist['Close'].iloc[-1], 'item') else hist['Close'].iloc[-1])
            current_vwap = float(vwap.iloc[-1].item() if hasattr(vwap.iloc[-1], 'item') else vwap.iloc[-1])

            price_up = False
            price_down = False

            if not pd.isna(current_vwap):
                vwap_distance = ((current_price - current_vwap) / current_vwap) * 100

                if current_price > current_vwap:
                    score += 2
                    price_up = True
                    signals.append(f"Price above VWAP (+{vwap_distance:.2f}%)")
                else:
                    score -= 2
                    price_down = True
                    signals.append(f"Price below VWAP ({vwap_distance:.2f}%)")

                # Check VWAP slope (rising VWAP is bullish)
                if len(vwap) >= 5:
                    vwap_slope = float(vwap.iloc[-1]) - float(vwap.iloc[-5])
                    if vwap_slope > 0:
                        score += 1
                        signals.append("VWAP rising (bullish)")

            # 2. Supertrend Analysis
            df_with_st = calculate_supertrend(hist, self.supertrend_period, self.supertrend_multiplier)

            # Guard against missing direction column
            current_direction = 0
            prev_direction = 0
            if 'direction' in df_with_st.columns:
                current_direction = df_with_st['direction'].iloc[-1]
                prev_direction = df_with_st['direction'].iloc[-2] if len(df_with_st) > 1 else current_direction

                if current_direction == 1:
                    score += 2
                    signals.append("Supertrend: Uptrend (BUY mode)")
                elif current_direction == -1:
                    score -= 2
                    signals.append("Supertrend: Downtrend (SELL mode)")

                # Check for trend change (crossover)
                if current_direction == 1 and prev_direction == -1:
                    score += 2
                    signals.append("Supertrend: Bullish crossover (entry signal)")
                elif current_direction == -1 and prev_direction == 1:
                    score -= 2
                    signals.append("Supertrend: Bearish crossover (exit signal)")

            # 3. Volume Confirmation (important for Indian markets)
            avg_volume = hist['Volume'].iloc[-20:].mean()
            current_volume = hist['Volume'].iloc[-1]
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

            if volume_ratio > 1.5:
                score += 1
                signals.append(f"Volume confirmation ({volume_ratio:.1f}x average)")

            # 4. CPR (Central Pivot Range) for breakout
            cpr = calculate_cpr(hist)
            if cpr:
                if current_price > cpr['tc']:
                    score += 1
                    signals.append("Price above CPR Top (breakout)")
                elif current_price < cpr['bc']:
                    score -= 1
                    signals.append("Price below CPR Bottom (breakdown)")

                # Narrow CPR indicates strong move coming
                if cpr.get('cpr_narrow', False):
                    signals.append("Narrow CPR detected (expect big move)")

            # Skip live OI fetch during backtesting to prevent massive delays
            is_backtest = getattr(self, '_is_backtesting', False)

            # 5. Open Interest (OI) Analysis
            oi_data = None  # Initialize to None
            if not is_backtest:
                try:
                    nse_fetcher = self._get_nse_fetcher()
                    oi_data = nse_fetcher.get_nse_fno_oi(ticker)
                    oi_trend = oi_data.get('oi_trend', 'neutral')
                    total_oi = oi_data.get('total_oi', 0)

                    if oi_trend == 'increasing' and price_up:
                        score += 2
                        signals.append(f"OI increasing + price up (strong momentum, OI: {total_oi:,})")
                    elif oi_trend == 'decreasing' and price_down:
                        score -= 2
                        signals.append(f"OI decreasing + price down (weak momentum, OI: {total_oi:,})")
                    elif total_oi > 0:
                        signals.append(f"OI: {total_oi:,} (trend: {oi_trend})")
                except Exception as oi_error:
                    signals.append(f"OI data unavailable: {str(oi_error)}")

            # Generate initial signal based on technical indicators
            if score >= 4:
                initial_signal = 'BUY'
            elif score <= -4:
                initial_signal = 'SELL'
            else:
                initial_signal = 'HOLD'

            # 6. Sentiment Filter
            # Only take BUY if sentiment is positive
            if initial_signal == 'BUY':
                if not (sentiment_score > 0.05 and industry_sentiment > 0.05):
                    initial_signal = 'HOLD'
                    signals.append(f"Sentiment filter: BUY blocked (sentiment={sentiment_score:.2f}, industry={industry_sentiment:.2f})")
                else:
                    signals.append(f"Sentiment confirmed BUY (sentiment={sentiment_score:.2f}, industry={industry_sentiment:.2f})")

            # Only take SELL if sentiment is negative
            elif initial_signal == 'SELL':
                if not (sentiment_score < -0.05 and industry_sentiment < -0.05):
                    initial_signal = 'HOLD'
                    signals.append(f"Sentiment filter: SELL blocked (sentiment={sentiment_score:.2f}, industry={industry_sentiment:.2f})")
                else:
                    signals.append(f"Sentiment confirmed SELL (sentiment={sentiment_score:.2f}, industry={industry_sentiment:.2f})")

            signal = initial_signal

            # Normalize confidence against 4-point buy threshold
            buy_threshold = 4
            if abs(score) >= buy_threshold:
                confidence = min((abs(score) - buy_threshold + 1) / (11 - buy_threshold + 1), 1.0)
            else:
                confidence = 0.0

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': confidence,
                'score': score,
                'signals': signals,
                'sentiment_score': sentiment_score,
                'industry_sentiment': industry_sentiment,
                'metrics': {
                    'current_price': round(current_price, 2),
                    'vwap': round(current_vwap, 2) if not pd.isna(current_vwap) else None,
                    'vwap_distance_pct': round(vwap_distance, 2) if not pd.isna(current_vwap) else None,
                    'volume_ratio': round(volume_ratio, 2),
                    'supertrend_direction': 'UP' if current_direction == 1 else 'DOWN',
                    'cpr_tc': round(cpr.get('tc', 0), 2) if cpr else None,
                    'cpr_bc': round(cpr.get('bc', 0), 2) if cpr else None,
                    'oi_trend': oi_data.get('oi_trend', 'N/A') if oi_data is not None else 'N/A',
                    'total_oi': oi_data.get('total_oi', 0) if oi_data is not None else 0,
                }
            }

        except Exception as e:
            return {'error': str(e)}



class MomentumBreakoutAlgorithm(BaseAlgorithm):
    """
    Wraps MomentumBreakoutStrategy as a BaseAlgorithm for AlgorithmSelector.
    Highest-return strategy for BULL_TREND regime.
    """
    def __init__(self):
        super().__init__('momentum_breakout', '52W High + 2x Volume Breakout')

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            from strategies.stocks import MomentumBreakoutStrategy
            impl = MomentumBreakoutStrategy()
            result = impl.analyze_ticker(ticker)
            if result and result.get('signal') in ('BUY', 'SELL'):
                return {
                    'algorithm': self.name,
                    'signal': result['signal'],
                    'confidence': result.get('confidence', 0.5),
                    'score': 4 if result['signal'] == 'BUY' else -4,
                    'signals': [f"52W breakout: vol={result.get('volume_ratio', 0):.1f}x"],
                    'strategy': 'momentum_breakout',
                    'metrics': {
                        'entry_price': result.get('entry_price'),
                        'stop_loss': result.get('stop_loss'),
                        'target': result.get('target'),
                    }
                }
            return {'algorithm': self.name, 'signal': 'HOLD', 'confidence': 0.0, 'score': 0, 'signals': []}
        except Exception as e:
            return {'error': str(e)}


class SectorRotationAlgorithm(BaseAlgorithm):
    """
    Wraps SectorRotationStrategy as a BaseAlgorithm for AlgorithmSelector.
    Rotates into top-performing NSE sectors based on macro conditions.
    """
    def __init__(self):
        super().__init__('sector_rotation', 'NSE Sector Momentum Rotation')

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            from strategies.stocks import SectorRotationStrategy
            impl = SectorRotationStrategy()
            
            # Cache sector recommendations during backtesting to avoid massive network calls
            is_backtest = getattr(self, '_is_backtesting', False)
            if is_backtest:
                if not hasattr(self, '_cached_top_sectors'):
                    self._cached_top_sectors = impl.recommend_sectors()
                top_sectors = self._cached_top_sectors
            else:
                top_sectors = impl.recommend_sectors()
            # Simple sector mapping for NSE tickers
            sector_map = {
                'TCS.NS': 'IT', 'INFY.NS': 'IT', 'HCLTECH.NS': 'IT', 'WIPRO.NS': 'IT',
                'HDFCBANK.NS': 'Banking', 'ICICIBANK.NS': 'Banking', 'SBIN.NS': 'Banking',
                'RELIANCE.NS': 'Energy', 'ONGC.NS': 'Energy',
                'SUNPHARMA.NS': 'Pharma', 'DRREDDY.NS': 'Pharma',
                'TATASTEEL.NS': 'Metals', 'JSWSTEEL.NS': 'Metals',
                'MARUTI.NS': 'Auto', 'TATAMOTORS.NS': 'Auto',
            }
            ticker_sector = sector_map.get(ticker, None)
            if ticker_sector in top_sectors:
                return {
                    'algorithm': self.name,
                    'signal': 'BUY',
                    'confidence': 0.70,
                    'score': 4,
                    'signals': [f'Sector {ticker_sector} in top performers: {top_sectors}'],
                    'strategy': 'sector_rotation',
                }
            return {'algorithm': self.name, 'signal': 'HOLD', 'confidence': 0.30, 'score': 0, 'signals': []}
        except Exception as e:
            return {'error': str(e)}


class MeanReversionBBAlgorithm(BaseAlgorithm):
    """
    Bollinger Band + Wilder RSI mean reversion for sideways markets.
    Target regime: SIDEWAYS_LOW_VOL, SIDEWAYS_HIGH_VOL.
    """
    def __init__(self):
        super().__init__('mean_reversion', 'BB + RSI mean reversion for sideways markets')

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            if hist is None:
                hist = yf.Ticker(ticker).history(period='3mo')
            if hist is None or len(hist) < 25:
                return {'error': 'Insufficient data'}
            close = hist['Close'].tail(100)
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            bb_upper = sma20 + 2 * std20
            bb_lower = sma20 - 2 * std20
            bb_pct_b = (close - bb_lower) / (bb_upper - bb_lower + 1e-9)

            # Wilder's RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
            loss = (-delta).where(delta < 0, 0).ewm(alpha=1/14, adjust=False).mean()
            rsi = 100 - 100 / (1 + gain / (loss + 1e-9))

            pct_b = float(bb_pct_b.iloc[-1])
            cur_rsi = float(rsi.iloc[-1])
            score = 0
            signals_list = []

            if pct_b < 0.10:
                score += 3; signals_list.append(f'Near lower BB (pct_b={pct_b:.2f})')
            elif pct_b < 0.20:
                score += 1; signals_list.append(f'Below BB midline (pct_b={pct_b:.2f})')
            elif pct_b > 0.90:
                score -= 3; signals_list.append(f'Near upper BB (pct_b={pct_b:.2f})')
            elif pct_b > 0.80:
                score -= 1

            if cur_rsi < 35:
                score += 2; signals_list.append(f'RSI oversold ({cur_rsi:.0f})')
            elif cur_rsi < 45:
                score += 1
            elif cur_rsi > 65:
                score -= 2; signals_list.append(f'RSI overbought ({cur_rsi:.0f})')
            elif cur_rsi > 55:
                score -= 1

            signal = 'BUY' if score >= 4 else 'SELL' if score <= -4 else 'HOLD'
            confidence = min(abs(score) / 5.0, 1.0)
            return {
                'algorithm': self.name, 'signal': signal,
                'confidence': confidence, 'score': score,
                'signals': signals_list, 'strategy': 'mean_reversion',
                'metrics': {'pct_b': round(pct_b, 3), 'rsi': round(cur_rsi, 1)}
            }
        except Exception as e:
            return {'error': str(e)}


class NiftyOptionsWriter(BaseAlgorithm):
    """
    Nifty Options Writer Strategy (Credit Spreads)
    - Sells OTM options with credit spreads (limited risk)
    - For CALLS: Sell OTM call + Buy further OTM call
    - For PUTS: Sell OTM put + Buy further OTM put
    - Only writes strikes where OI > 1000
    - Filters by sentiment (skips if bearish)
    """

    def __init__(self):
        super().__init__(
            "Nifty Options Writer",
            "Credit spreads on OTM options with OI and sentiment filters"
        )
        self.max_otm_strikes = 2
        self.min_premium_pct = 1.0
        self.min_oi = 1000
        self.sentiment_threshold = -0.05
        self._nse_fetcher = None

    def _get_nse_fetcher(self):
        """Lazy-load NSE data fetcher"""
        if self._nse_fetcher is None:
            from utils.nse_data import NSEDataFetcher
            self._nse_fetcher = NSEDataFetcher()
        return self._nse_fetcher

    def analyze(self, ticker: str, hist: pd.DataFrame = None, sentiment_score: float = 0.0, **kwargs) -> dict:
        """
        Analyze for credit spread opportunities.

        Args:
            ticker: Stock ticker symbol
            hist: Historical price data
            sentiment_score: Sentiment score (-1 to 1). Skip if < -0.05
        """
        try:
            # Convert to NSE format if needed
            ticker = convert_to_nse_format(ticker)

            # Sentiment filter: Skip writing if bearish
            if sentiment_score < self.sentiment_threshold:
                return {
                    'algorithm': self.name,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'score': 0,
                    'signals': [f'Sentiment filter: bearish sentiment ({sentiment_score:.2f} < {self.sentiment_threshold})'],
                    'strategy_type': 'credit_spread',
                    'skipped': True
                }

            # Check if current day (from hist) is expiry day (Thursday)
            if hist is None or len(hist) == 0:
                return {
                    'algorithm': self.name,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'score': 0,
                    'signals': ['No historical data'],
                    'strategy_type': 'credit_spread'
                }

            current_date = hist.index[-1]
            is_thursday = current_date.weekday() == 3

            if not is_thursday:
                return {
                    'algorithm': self.name,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'score': 0,
                    'signals': ['Not expiry day (Thursday)'],
                    'strategy_type': 'credit_spread'
                }

            # Skip live F&O analysis during backtesting (options chains are not historical in yfinance)
            is_backtest = getattr(self, '_is_backtesting', False)

            if is_backtest:
                return {
                    'algorithm': self.name,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'score': 0,
                    'signals': ['Historical options chain data not available for backtesting'],
                    'strategy_type': 'credit_spread'
                }

            # Get options chain for credit spread analysis
            try:
                stock = yf.Ticker(ticker)
                expirations = stock.options

                if not expirations:
                    return {
                        'algorithm': self.name,
                        'signal': 'HOLD',
                        'confidence': 0.0,
                        'score': 0,
                        'signals': ['No F&O data available'],
                        'strategy_type': 'credit_spread'
                    }

                # Get nearest expiry
                nearest_exp = expirations[0]
                chain = stock.option_chain(nearest_exp)

                current_price = float(hist['Close'].iloc[-1])
                lot_size = self._get_lot_size(ticker)

                # Find suitable OTM strikes with OI > 1000
                call_spreads = self._find_call_spreads(chain.calls, current_price, lot_size)
                put_spreads = self._find_put_spreads(chain.puts, current_price, lot_size)

                signals = [f'Expiry day (Thursday {current_date.strftime("%Y-%m-%d")})']
                signals.append(f'Current price: {current_price:.2f}')

                if call_spreads or put_spreads:
                    return {
                        'algorithm': self.name,
                        'signal': 'CREDIT_SPREAD',
                        'confidence': 0.75,
                        'score': 4,
                        'signals': signals,
                        'strategy_type': 'credit_spread',
                        'call_spreads': call_spreads[:self.max_otm_strikes],
                        'put_spreads': put_spreads[:self.max_otm_strikes],
                        'execute': True,
                        'sentiment_score': sentiment_score
                    }
                else:
                    return {
                        'algorithm': self.name,
                        'signal': 'HOLD',
                        'confidence': 0.0,
                        'score': 0,
                        'signals': signals + ['No suitable strikes with OI > 1000'],
                        'strategy_type': 'credit_spread'
                    }

            except Exception as options_error:
                return {
                    'algorithm': self.name,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'score': 0,
                    'signals': [f'Options data error: {str(options_error)}'],
                    'strategy_type': 'credit_spread'
                }

        except Exception as e:
            return {'error': f'Options analysis error: {str(e)}'}

    def _find_call_spreads(self, calls_df, current_price: float, lot_size: int) -> list:
        """Find bull call credit spreads (sell OTM, buy further OTM)"""
        spreads = []
        try:
            # Filter for OTM calls (strike > current price) with OI > threshold
            otm_calls = calls_df[
                (calls_df['strike'] > current_price) &
                (calls_df['openInterest'] > self.min_oi)
            ].sort_values('strike')

            if len(otm_calls) >= 2:
                for i in range(len(otm_calls) - 1):
                    sell_call = otm_calls.iloc[i]
                    buy_call = otm_calls.iloc[i + 1]

                    strike_width = buy_call['strike'] - sell_call['strike']
                    premium_received = sell_call['lastPrice'] - buy_call['lastPrice']

                    if premium_received > 0:
                        max_loss = (strike_width * lot_size) - (premium_received * lot_size)

                        spreads.append({
                            'type': 'CALL_CREDIT_SPREAD',
                            'sell_strike': float(sell_call['strike']),
                            'buy_strike': float(buy_call['strike']),
                            'sell_oi': int(sell_call['openInterest']),
                            'buy_oi': int(buy_call['openInterest']),
                            'premium_received': float(premium_received),
                            'strike_width': float(strike_width),
                            'max_loss': float(max_loss),
                            'lot_size': lot_size
                        })
        except Exception:
            pass
        return spreads

    def _find_put_spreads(self, puts_df, current_price: float, lot_size: int) -> list:
        """Find bear put credit spreads (sell OTM, buy further OTM)"""
        spreads = []
        try:
            # Filter for OTM puts (strike < current_price) with OI > threshold
            otm_puts = puts_df[
                (puts_df['strike'] < current_price) &
                (puts_df['openInterest'] > self.min_oi)
            ].sort_values('strike', ascending=False)

            if len(otm_puts) >= 2:
                for i in range(len(otm_puts) - 1):
                    sell_put = otm_puts.iloc[i]
                    buy_put = otm_puts.iloc[i + 1]

                    strike_width = sell_put['strike'] - buy_put['strike']
                    premium_received = sell_put['lastPrice'] - buy_put['lastPrice']

                    if premium_received > 0:
                        max_loss = (strike_width * lot_size) - (premium_received * lot_size)

                        spreads.append({
                            'type': 'PUT_CREDIT_SPREAD',
                            'sell_strike': float(sell_put['strike']),
                            'buy_strike': float(buy_put['strike']),
                            'sell_oi': int(sell_put['openInterest']),
                            'buy_oi': int(buy_put['openInterest']),
                            'premium_received': float(premium_received),
                            'strike_width': float(strike_width),
                            'max_loss': float(max_loss),
                            'lot_size': lot_size
                        })
        except Exception:
            pass
        return spreads

    def _get_lot_size(self, ticker: str) -> int:
        """Get F&O lot size for the ticker"""
        try:
            fetcher = self._get_nse_fetcher()
            lot_sizes = fetcher.get_fno_lot_sizes()
            # Extract ticker without .NS suffix
            base_ticker = ticker.replace('.NS', '')
            return lot_sizes.get(base_ticker, 50)  # Default lot size
        except Exception:
            return 50  # Default lot size

class BudgetDayStrategy(BaseAlgorithm):
    """
    Budget Day Special Strategy
    - Special handling for Budget day (February 1st)
    - Market is highly volatile on Budget day
    - Avoids large positions, uses hedging
    - Focuses on sector-specific plays based on budget expectations
    - Now includes macro sentiment filter (bearish macro changes BUY to HOLD)
    """

    def __init__(self):
        super().__init__(
            "Budget Day Strategy",
            "Special strategy for Budget day (Feb 1st) with reduced risk"
        )
        self.position_size_reduction = 0.5  # Reduce position size by 50%
        self.stop_loss_tight_pct = 1.0  # Tight 1% stop loss
        self.avoid_sectors = ['oil_gas', 'banking', 'infrastructure']  # Sensitive to budget
        self.sentiment_engine = get_sentiment_engine()
        self.news_aggregator = get_news_aggregator()

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            # Convert to NSE format if needed
            ticker = convert_to_nse_format(ticker)

            # Check if today is Budget day
            budget_day = is_budget_day()

            if not budget_day:
                # Normal analysis with standard strategy
                return self._normal_analysis(ticker, hist)

            # Budget day special handling
            score = 0
            signals = []

            # Get stock info
            stock = yf.Ticker(ticker)
            info = stock.info

            sector = info.get('sector', '').lower()
            industry = info.get('industry', '').lower()

            # Check if sector is budget-sensitive
            budget_sensitive = any(s in sector or s in industry for s in self.avoid_sectors)

            if budget_sensitive:
                score -= 2
                signals.append(f"Budget-sensitive sector ({sector}) - high volatility expected")
                signals.append("Reduce position size by 50%")

            # On Budget day, prefer:
            # 1. Defensive stocks (FMCG, Pharma)
            defensive_sectors = ['consumer defensive', 'healthcare', 'pharmaceuticals']
            if any(s in sector for s in defensive_sectors):
                score += 2
                signals.append("Defensive sector - more stable on Budget day")

            # 2. Stocks with low volatility
            if hist is not None and len(hist) >= 20:
                daily_returns = hist['Close'].pct_change().dropna()
                volatility = daily_returns.std() * np.sqrt(252)

                if volatility < 0.20:
                    score += 1
                    signals.append(f"Low volatility stock ({volatility:.1%}) - safer for Budget day")
                else:
                    score -= 1
                    signals.append(f"High volatility ({volatility:.1%}) - risky for Budget day")

            # 3. Avoid aggressive entries - use tight stops
            signals.append(f"Use tight stop loss ({self.stop_loss_tight_pct}%)")
            signals.append(f"Reduce position size to {self.position_size_reduction*100}%")

            # Check for pre-budget positioning
            # Usually markets rally before budget if expectations are positive
            if hist is not None and len(hist) >= 5:
                pre_budget_return = (hist['Close'].iloc[-1] / hist['Close'].iloc[-5] - 1) * 100
                if pre_budget_return > 2:
                    signals.append(f"Pre-budget rally (+{pre_budget_return:.1f}%) - book profits")
                    score -= 1
                elif pre_budget_return < -2:
                    signals.append(f"Pre-budget selloff ({pre_budget_return:.1f}%) - avoid fresh entries")
                    score -= 2

            # Generate signal (more conservative on Budget day)
            confidence = min(abs(score) / 6.0, 1.0)

            if score >= 2:
                signal = 'BUY'
                signals.append("BUDGET DAY: Small position BUY (50% size)")
            elif score <= -2:
                signal = 'SELL'
                signals.append("BUDGET DAY: SELL/avoid (high volatility)")
            else:
                signal = 'HOLD'
                signals.append("BUDGET DAY: HOLD - avoid new positions")

            # Macro sentiment filter: If bearish, change BUY to HOLD
            macro_sentiment = 0.0  # Default value
            try:
                macro_sentiment = self.news_aggregator.get_macro_sentiment()
                signals.append(f"Macro sentiment: {macro_sentiment:.2f}")

                if signal == 'BUY' and macro_sentiment < 0:
                    signal = 'HOLD'
                    signals.append(f"BUDGET DAY: BUY changed to HOLD due to bearish macro sentiment ({macro_sentiment:.2f})")
            except Exception as e:
                signals.append(f"Macro sentiment unavailable: {str(e)}")

            return {
                'algorithm': self.name,
                'signal': signal,
                'confidence': confidence,
                'score': score,
                'signals': signals,
                'is_budget_day': True,
                'position_size_multiplier': self.position_size_reduction,
                'stop_loss_pct': self.stop_loss_tight_pct,
                'recommendation': 'Avoid large positions. Use hedging. Book profits early.',
                'volatile_sectors': ['Banking', 'Oil & Gas', 'Infrastructure', 'Realty'],
                'stable_sectors': ['FMCG', 'Pharma', 'IT'],
                'macro_sentiment': macro_sentiment
            }

        except Exception as e:
            return {'error': str(e)}

    def _normal_analysis(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        """Delegate to IndianMomentumAlgorithm for non-Budget days"""
        try:
            algo = IndianMomentumAlgorithm()
            result = algo.analyze(ticker, hist)
            if 'algorithm' in result:
                result['algorithm'] = self.name
            result['is_budget_day'] = False
            return result
        except Exception as e:
            return {'error': f'Normal analysis error: {str(e)}'}


class NormalizedMomentumAlgorithm(BaseAlgorithm):
    """
    High-performance momentum strategy combining normalized returns, VCP, and Trend.
    Evidence-based: outperforms broad NSE indices in bull/trending markets.
    """
    def __init__(self):
        super().__init__("Normalized Momentum", "Momentum Scoring + VCP + Trend Filter")
        from strategies.indian_momentum import IndianMomentumStrategy
        self.strategy = IndianMomentumStrategy()
        self._bench_cache = None
        self._bench_time = None

    def analyze(self, ticker: str, hist: pd.DataFrame = None) -> Dict:
        try:
            if hist is None:
                hist = yf.Ticker(ticker).history(period='1y')
            
            if hist.empty:
                return {'error': 'History is empty'}

            # Cache benchmark data for 1 hour to avoid repeated downloads
            if (self._bench_cache is None or 
                self._bench_time is None or 
                (datetime.now() - self._bench_time) > timedelta(hours=1)):
                logger.info("Downloading benchmark data (^NSEI)...")
                bench_data = yf.Ticker("^NSEI").history(period='2y')
                if bench_data.empty:
                    return {'error': 'Benchmark data (^NSEI) is empty'}
                # Standardize to timezone-naive to avoid alignment issues
                if bench_data.index.tz is not None:
                    bench_data.index = bench_data.index.tz_convert(None)
                self._bench_cache = bench_data
                self._bench_time = datetime.now()
            
            # Standardize hist index to timezone-naive
            hist_copy = hist.copy()
            if hist_copy.index.tz is not None:
                hist_copy.index = hist_copy.index.tz_convert(None)
                
            # Align benchmark data with the specific timeframe of hist
            last_date = hist_copy.index[-1]
            aligned_bench = self._bench_cache[self._bench_cache.index <= last_date]
            
            if aligned_bench.empty:
                # If bench is empty for this date, maybe the bench data doesn't go back far enough
                # or there's a serious alignment issue. Return result without bench for now.
                result = self.strategy.analyze_ticker(ticker, hist, None)
            else:
                result = self.strategy.analyze_ticker(ticker, hist, aligned_bench)
            
            if not result:
                return {'error': 'Strategy returned empty result'}

            # Map result to algorithm format
            return {
                'algorithm': self.name,
                'signal': result.get('signal', 'HOLD'),
                'confidence': result.get('confidence', 0.0),
                'score': 4 if result.get('signal') == 'BUY' else -4 if result.get('signal') == 'SELL' else 0,
                'signals': [result.get('reason', '')],
                'metrics': result.get('factors', {}),
                'stop_loss': result.get('stop_loss'),
                'price_target': result.get('price_target')
            }
        except Exception as e:
            logger.error(f"Error in NormalizedMomentumAlgorithm.analyze: {e}")
            return {'error': str(e)}

class AlgorithmSelector:
    """
    Automatically selects the best algorithm based on market conditions
    Uses sentiment, volatility, and trend analysis
    Supports both US and Indian markets
    """

    def __init__(self, market: str = 'US'):
        """
        Initialize AlgorithmSelector
        market: 'US' for US markets, 'IN' for Indian markets
        """
        self.market = market.upper()
        self.regime_detector = IndianMarketRegime()

        # Common algorithms
        self.algorithms = {
            'buffett_value': BuffettValueAlgorithm(),
            'dalio_all_weather': DalioAllWeatherAlgorithm(),
            'bulls_ai_momentum': BullsAIStyleAlgorithm(),
            'wood_growth': WoodDisruptiveGrowthAlgorithm(),
        }

        # Add Indian-specific algorithms if market is IN
        if self.market == 'IN':
            # DalioAllWeather queries S&P/bond/treasury categories — don't exist on NSE
            self.algorithms.pop('dalio_all_weather', None)
            # Replace with a note
            self.algorithms['dalio_all_weather'] = None  # Not available for Indian markets

            self.algorithms['indian_momentum'] = NormalizedMomentumAlgorithm() # Use new logic
            self.algorithms['nifty_momentum_old'] = IndianMomentumAlgorithm() # Keep old one as option
            self.algorithms['nifty_options_writer'] = NiftyOptionsWriter()
            self.algorithms['budget_day'] = BudgetDayStrategy()
            self.algorithms['momentum_breakout'] = MomentumBreakoutAlgorithm()
            self.algorithms['sector_rotation'] = SectorRotationAlgorithm()
            self.algorithms['mean_reversion'] = MeanReversionBBAlgorithm()

    def recommend_algorithm(self, ticker: str, market_regime: str = None) -> Dict:
        """
        Recommend the best algorithm for current conditions
        """
        if market_regime is None:
            market_regime = self.regime_detector.get_regime()

        # Algorithm preference by regime (India-first ordering)
        regime_preferences = {
            'BULL_TREND':       ['momentum_breakout', 'indian_momentum', 'bulls_ai_momentum'],
            'BULL_VOLATILE':    ['sector_rotation', 'indian_momentum', 'dalio_all_weather'],
            'BEAR_TREND':       ['dalio_all_weather', 'buffett_value', 'nifty_options_writer'],
            'BEAR_VOLATILE':    ['nifty_options_writer', 'dalio_all_weather', 'buffett_value'],
            'SIDEWAYS_LOW_VOL': ['mean_reversion', 'nifty_options_writer', 'buffett_value'],
            'SIDEWAYS_HIGH_VOL':['nifty_options_writer', 'mean_reversion'],
            'CRISIS':           ['dalio_all_weather', 'buffett_value'],
            'UNKNOWN':           ['dalio_all_weather', 'buffett_value'],
        }

        # Use Indian preferences if market is IN, otherwise use US preferences
        if self.market != 'IN':
            regime_preferences = {
                'BULL_LOW_VOL': ['bulls_ai_momentum', 'wood_growth', 'buffett_value', 'dalio_all_weather'],
                'BULL_HIGH_VOL': ['dalio_all_weather', 'buffett_value', 'bulls_ai_momentum', 'wood_growth'],
                'BEAR': ['dalio_all_weather', 'buffett_value', 'bulls_ai_momentum'],
                'CRISIS': ['dalio_all_weather', 'buffett_value'],
                'NEUTRAL': ['buffett_value', 'dalio_all_weather', 'bulls_ai_momentum'],
                'UNKNOWN': ['dalio_all_weather', 'buffett_value'],
            }

            # Special handling for expiry day (Thursday)
            if is_expiry_day():
                regime_preferences['NEUTRAL'].insert(0, 'nifty_options_writer')

            # Special handling for Budget day (Feb 1st)
            if is_budget_day():
                regime_preferences['NEUTRAL'].insert(0, 'budget_day')

        preferences = regime_preferences.get(market_regime, list(self.algorithms.keys()))

        # Test each preferred algorithm. If market data is unavailable, still
        # return the regime route so offline tests and dashboards do not crash.
        try:
            hist = yf.Ticker(ticker).history(period='6mo')
        except Exception as e:
            first_available = next((name for name in preferences if name in self.algorithms), None)
            if first_available:
                return {
                    'recommended_algorithm': first_available,
                    'market_regime': market_regime,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'reasoning': f"Market data unavailable; selected first strategy for {market_regime}: {e}",
                    'all_results': {}
                }
            return {'error': f'Market data unavailable: {e}', 'market_regime': market_regime}

        if hist.empty:
            first_available = next((name for name in preferences if name in self.algorithms), None)
            if first_available:
                return {
                    'recommended_algorithm': first_available,
                    'market_regime': market_regime,
                    'signal': 'HOLD',
                    'confidence': 0.0,
                    'reasoning': f"No market data; selected first strategy for {market_regime}",
                    'all_results': {}
                }
            return {'error': 'No market data', 'market_regime': market_regime}

        results = []
        for algo_name in preferences:
            algo = self.algorithms.get(algo_name)
            if algo is None:
                continue  # Skip unavailable algorithms (e.g., dalio_all_weather for IN market)
            result = algo.analyze(ticker, hist)

            if 'error' not in result:
                results.append({
                    'algorithm': algo_name,
                    'result': result,
                    'priority': preferences.index(algo_name)
                })

        # Sort by priority (preference) then by confidence
        results.sort(key=lambda x: (x['priority'], -x['result']['confidence']))

        if results:
            best = results[0]
            return {
                'recommended_algorithm': best['algorithm'],
                'market_regime': market_regime,
                'signal': best['result']['signal'],
                'confidence': best['result']['confidence'],
                'reasoning': f"Best suited for {market_regime} market conditions",
                'all_results': {r['algorithm']: r['result'] for r in results}
            }

        return {'error': 'No algorithm produced valid results'}

    def run_all_algorithms(self, ticker: str) -> Dict:
        """Run all algorithms and return combined signal weighted by performance"""
        market_regime = self.regime_detector.get_regime()
        try:
            hist = yf.Ticker(ticker).history(period='6mo')
        except Exception as e:
            return {
                'ticker': ticker,
                'combined_signal': 'HOLD',
                'confidence': 0.0,
                'buy_score': 0,
                'sell_score': 0,
                'algorithm_results': {},
                'market_regime': market_regime,
                'error': f'Market data unavailable: {e}'
            }

        if hist.empty:
            return {
                'ticker': ticker,
                'combined_signal': 'HOLD',
                'confidence': 0.0,
                'buy_score': 0,
                'sell_score': 0,
                'algorithm_results': {},
                'market_regime': market_regime,
                'error': 'No market data'
            }

        # Get performance-based weights (Sharpe-based)
        try:
            from utils.performance_tracker import StrategyPerformanceTracker
            perf = StrategyPerformanceTracker()
            weights = perf.get_algorithm_weights()
        except Exception:
            weights = {}

        results = {}
        buy_score = 0
        sell_score = 0

        for name, algo in self.algorithms.items():
            if algo is None:
                continue  # Skip unavailable algorithms (e.g., dalio_all_weather for IN market)
            result = algo.analyze(ticker, hist)
            if 'error' not in result:
                results[name] = result
                w = weights.get(name, 1.0)  # Default weight 1.0

                if result['signal'] == 'BUY':
                    buy_score += result['confidence'] * w
                elif result['signal'] == 'SELL':
                    sell_score += result['confidence'] * w

        # Combined signal
        if buy_score > sell_score * 1.5:
            combined_signal = 'BUY'
            confidence = buy_score / len(results)
        elif sell_score > buy_score * 1.5:
            combined_signal = 'SELL'
            confidence = sell_score / len(results)
        else:
            combined_signal = 'HOLD'
            confidence = 0.5

        return {
            'ticker': ticker,
            'combined_signal': combined_signal,
            'confidence': min(confidence, 1.0),
            'buy_score': round(buy_score, 2),
            'sell_score': round(sell_score, 2),
            'algorithm_results': results,
            'market_regime': market_regime
        }
