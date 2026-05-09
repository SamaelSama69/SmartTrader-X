"""
Stock Trading Strategies
Combines sentiment, technical, and fundamental analysis
"""

import yfinance as yf
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import requests
import logging

logger = logging.getLogger(__name__)

from config import STOP_LOSS_ATR_MULTIPLIER, TAKE_PROFIT_RR_RATIO
from utils.multilingual_sentiment import get_sentiment_engine, get_news_aggregator
from utils.memory_manager import PredictionMemory
from utils.data_quality import assess_ohlcv_quality
from utils.indian_indicators import calculate_adx, calculate_bollinger_bands, calculate_supertrend


class StockStrategy:
    """Main stock trading strategy using multiple signals"""

    def __init__(self, memory: PredictionMemory = None):
        self.sentiment_engine = get_sentiment_engine()
        self.news_aggregator = get_news_aggregator()
        self.memory = memory if memory is not None else PredictionMemory()

    def analyze_ticker(self, ticker: str, detailed: bool = False,
                        regime: str = 'SIDEWAYS_LOW_VOL', sector_boost: float = 0.0) -> Dict:
        """
        Full analysis of a stock
        Returns trading signal based on multiple factors
        Accepts regime and sector_boost for regime-aware scoring.
        """
        # Check memory first (avoid recomputation)
        if not self.memory.should_recompute(ticker, min_hours=12):
            past = self.memory.get_past_predictions(ticker, days=1)
            if past:
                logger.debug(f"  Using cached analysis for {ticker}")
                return past[-1]['prediction']

        logger.info(f"  Analyzing {ticker}... [regime={regime}]")

        result = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'signal': 'HOLD',
            'confidence': 0.0,
            'factors': {},
            'price_target': None,
            'stop_loss': None,
        }

        try:
            # Fetch stock data
            stock = yf.Ticker(ticker)
            hist = stock.history(period='1y', auto_adjust=True)

            if hist.empty or len(hist) < 50:
                result['error'] = 'Insufficient data'
                return result

            # Drop rows with missing OHLCV
            hist = hist.dropna(subset=['Open', 'High', 'Low', 'Close', 'Volume'])

            # Guard: if too many NaN values leaked through, abort
            if len(hist) < 50:
                result['error'] = f'Insufficient clean data: only {len(hist)} valid rows'
                return result
            if hist['Close'].isna().mean() > 0.02:
                result['error'] = 'Data quality: >2% NaN in Close prices'
                return result

            quality = assess_ohlcv_quality(hist, min_rows=50)
            result['data_quality'] = quality
            if not quality.get('ok', False):
                result['signal'] = 'HOLD'
                result['confidence'] = 0.0
                result['reason'] = '; '.join(quality.get('issues', []))
                return result

            # 1. Sentiment Analysis
            news_data = self.news_aggregator.fetch_news(ticker, days=3)
            sentiment_data = self.news_aggregator.get_aggregate_sentiment_from_news(ticker, news_data)
            sentiment = sentiment_data['aggregate_sentiment']
            result['factors']['sentiment'] = sentiment

            # 2. Technical Analysis
            tech_signals = self._analyze_technicals(hist)
            result['factors']['technical'] = tech_signals

            # 3. Fundamental Check
            info = stock.info
            result['factors']['fundamentals'] = {
                'pe_ratio': info.get('trailingPE', None),
                'market_cap': info.get('marketCap', 0),
                'revenue_growth': info.get('revenueGrowth', 0),
                'profit_margin': info.get('profitMargins', 0),
            }

            # 4. Generate Signal (regime-aware)
            signal, confidence = self._generate_signal(
                result['factors'], regime=regime, sector_boost=sector_boost
            )
            result['signal'] = signal
            result['confidence'] = confidence

            # 5. Price targets
            current_price = float(hist['Close'].iloc[-1])
            if not (0 < current_price < 1_000_000):  # Sanity check for INR prices
                result['error'] = f'Invalid current price: {current_price}'
                return result
            result['current_price'] = round(current_price, 2)

            # ATR-based targets (matches get_swing_trade_setup logic)
            high_low = hist['High'] - hist['Low']
            high_close = np.abs(hist['High'] - hist['Close'].shift())
            low_close = np.abs(hist['Low'] - hist['Close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = np.max(ranges, axis=1)
            atr = true_range.rolling(14).mean().iloc[-1]

            if signal == 'BUY':
                result['price_target'] = round(current_price + atr * STOP_LOSS_ATR_MULTIPLIER * TAKE_PROFIT_RR_RATIO, 2)
                result['stop_loss'] = round(current_price - atr * STOP_LOSS_ATR_MULTIPLIER, 2)
            elif signal == 'SHORT':
                result['price_target'] = round(current_price - atr * STOP_LOSS_ATR_MULTIPLIER * TAKE_PROFIT_RR_RATIO, 2)
                result['stop_loss'] = round(current_price + atr * STOP_LOSS_ATR_MULTIPLIER, 2)

            # 6. Store in memory
            self.memory.add_prediction(ticker, result)

        except Exception as e:
            result['error'] = str(e)
            logger.error(f"Error analyzing {ticker}: {e}")

        return result

    def _analyze_technicals(self, hist: pd.DataFrame) -> Dict:
        """Full technical analysis — 8 indicators with trend strength."""
        signals = {}
        close   = hist['Close']
        high    = hist['High']
        low     = hist['Low']
        volume  = hist['Volume']
        current = float(close.iloc[-1])

        # --- Moving Averages ---
        ma_20  = close.iloc[-20:].mean()
        ma_50  = close.iloc[-50:].mean()
        ma_200 = close.iloc[-200:].mean() if len(hist) >= 200 else ma_50
        signals.update({'ma_20': round(ma_20, 2), 'ma_50': round(ma_50, 2), 'ma_200': round(ma_200, 2)})
        # MA signal: handle case when ma_200 == ma_50 (insufficient data)
        if current > ma_20 > ma_50 and (ma_200 is None or current > ma_200):
            signals['ma_signal'] = 'BULLISH'
        elif current < ma_20 < ma_50 and (ma_200 is None or current < ma_200):
            signals['ma_signal'] = 'BEARISH'
        else:
            signals['ma_signal'] = 'MIXED'

        # --- RSI ---
        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        # Avoid division-by-zero: when loss=0 → RSI=100; when gain=0 → RSI=0
        rs    = gain / loss
        rsi   = 100 - (100 / (1 + rs))
        rsi   = rsi.fillna(100.0)  # loss=0 → rs=inf → rsi=100
        signals['rsi']        = round(float(rsi.iloc[-1]), 2)
        signals['rsi_signal'] = ('OVERBOUGHT' if signals['rsi'] > 70
                                  else 'OVERSOLD' if signals['rsi'] < 30 else 'NEUTRAL')

        # --- MACD ---
        ema12  = close.ewm(span=12, adjust=False).mean()
        ema26  = close.ewm(span=26, adjust=False).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        signals['macd']         = round(float(macd.iloc[-1]), 4)
        signals['macd_hist']    = round(float((macd - signal).iloc[-1]), 4)
        signals['macd_signal']  = 'BULLISH' if macd.iloc[-1] > signal.iloc[-1] else 'BEARISH'
        signals['macd_crossover'] = (macd.iloc[-1] > signal.iloc[-1] and
                                      macd.iloc[-2] <= signal.iloc[-2])

        # --- ADX (NEW) ---
        adx = calculate_adx(hist, 14)
        signals['adx']         = round(float(adx.iloc[-1]), 2)
        signals['adx_trend']   = ('STRONG' if signals['adx'] > 25 else
                                   'WEAK'   if signals['adx'] < 20 else 'MODERATE')

        # --- Bollinger Bands (NEW) ---
        bb       = calculate_bollinger_bands(hist)
        signals['bb_upper']    = round(float(bb['upper'].iloc[-1]), 2)
        signals['bb_lower']    = round(float(bb['lower'].iloc[-1]), 2)
        signals['bb_pct_b']    = round(float(bb['pct_b'].iloc[-1]), 3)
        signals['bb_signal']   = ('OVERSOLD'  if signals['bb_pct_b'] < 0.2 else
                                   'OVERBOUGHT' if signals['bb_pct_b'] > 0.8 else 'NORMAL')

        # --- Supertrend ---
        try:
            st_df = calculate_supertrend(hist, period=10, multiplier=3.0)
            signals['supertrend_signal'] = ('BULLISH' if st_df['supertrend_signal'].iloc[-1] == 1
                                             else 'BEARISH')
        except Exception as e:
            logger.debug(f"Supertrend calculation failed: {e}")
            signals['supertrend_signal'] = 'UNKNOWN'

        # --- Volume ---
        avg_vol = volume.iloc[-20:].mean()
        cur_vol = float(volume.iloc[-1])
        signals['volume_surge']  = round(cur_vol / avg_vol if avg_vol > 0 else 1, 2)
        signals['volume_signal'] = 'HIGH' if signals['volume_surge'] > 1.5 else 'NORMAL'

        # --- VWAP ---
        tp   = (high + low + close) / 3
        vwap = (tp * volume).rolling(20).sum() / volume.rolling(20).sum()
        signals['vwap']        = round(float(vwap.iloc[-1]), 2)
        signals['vwap_signal'] = 'BULLISH' if current > signals['vwap'] else 'BEARISH'

        signals['current_price'] = round(current, 2)
        return signals

    def _generate_signal(self, factors: Dict, regime: str = 'SIDEWAYS_LOW_VOL', sector_boost: float = 0.0) -> tuple:
        """
        Regime-aware signal generation.
        Weights shift dynamically based on market conditions.
        ADX gates trend-following signals — avoids chopping in ranging markets.
        """
        from utils.market_regime import IndianMarketRegime
        weights = IndianMarketRegime().get_strategy_weights(regime)

        tech       = factors.get('technical', {})
        sentiment  = factors.get('sentiment', {}).get('aggregate_sentiment', 0)
        adx        = tech.get('adx', 20)

        # ── TREND SCORE (MA + Supertrend + MACD)
        # Dampen trend signals proportionally to ADX — never zero them out
        adx_factor = min(float(adx) / 25.0, 1.0)  # 0.0 at ADX=0, 1.0 at ADX>=25

        trend_score = 0
        if tech.get('ma_signal') == 'BULLISH':    trend_score += 1
        elif tech.get('ma_signal') == 'BEARISH':  trend_score -= 1
        if tech.get('supertrend_signal') == 'BULLISH':  trend_score += 1
        elif tech.get('supertrend_signal') == 'BEARISH': trend_score -= 1
        if tech.get('macd_crossover'):            trend_score += 0.5
        elif tech.get('macd_signal') == 'BULLISH': trend_score += 0.5
        else:                                      trend_score -= 0.5
        trend_score *= adx_factor  # Scale by ADX strength
        trend_score = max(-3, min(3, trend_score))

        # ── MOMENTUM SCORE (RSI + volume)
        momentum_score = 0
        rsi = tech.get('rsi', 50)
        if rsi < 30:   momentum_score += 1.5   # Strong oversold bounce
        elif rsi < 40: momentum_score += 0.5
        elif rsi > 70: momentum_score -= 1.5   # Overbought — risk of reversal
        elif rsi > 60: momentum_score -= 0.5
        if tech.get('volume_signal') == 'HIGH' and trend_score > 0:
            momentum_score += 0.5
        momentum_score = max(-2, min(2, momentum_score))

        # ── SENTIMENT SCORE
        sent_score = 2 * sentiment  # Scale to [-2, +2]
        sent_score = max(-2, min(2, sent_score))

        # ── VALUE SCORE (Bollinger + mean reversion)
        value_score = 0
        pct_b = tech.get('bb_pct_b', 0.5)
        if pct_b < 0.1:   value_score += 1.5
        elif pct_b < 0.2: value_score += 0.5
        elif pct_b > 0.9: value_score -= 1.5
        elif pct_b > 0.8: value_score -= 0.5
        if tech.get('vwap_signal') == 'BULLISH': value_score += 0.3
        else:                                     value_score -= 0.3
        value_score = max(-2, min(2, value_score))

        # ── WEIGHTED COMPOSITE
        w = weights
        composite = (
            w['trend']    * trend_score    +
            w['momentum'] * momentum_score +
            w['sentiment'] * sent_score    +
            w['value']    * value_score    +
            sector_boost
        )

        # Normalise by actual maximum achievable composite (not arbitrary constant 2.0)
        max_composite = (w.get('trend', 0.3) * 3 +
                         w.get('momentum', 0.2) * 2 +
                         w.get('value', 0.2) * 2 +
                         w.get('sentiment', 0.0) * 2 +
                         0.2)  # max sector_boost
        max_composite = max(max_composite, 0.01)  # Guard div/zero
        confidence = min(abs(composite) / max_composite, 1.0)

        if composite >= 0.8:    return 'BUY',  confidence
        elif composite >= 0.4:  return 'BUY',  confidence * 0.7
        elif composite <= -0.8: return 'SELL', confidence
        elif composite <= -0.4: return 'SELL', confidence * 0.7
        else:                   return 'HOLD', confidence

    def get_swing_trade_setup(self, ticker: str) -> Dict:
        """Identify swing trade opportunities"""
        analysis = self.analyze_ticker(ticker)

        if analysis.get('signal') == 'HOLD':
            return {'ticker': ticker, 'setup': None, 'reason': 'No clear signal'}

        hist = yf.Ticker(ticker).history(period='3mo')
        if hist.empty:
            return {'ticker': ticker, 'setup': None, 'reason': 'No data'}

        current_price = hist['Close'].iloc[-1]

        # ATR for stop loss
        high_low = hist['High'] - hist['Low']
        high_close = np.abs(hist['High'] - hist['Close'].shift())
        low_close = np.abs(hist['Low'] - hist['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        atr = true_range.rolling(14).mean().iloc[-1]

        setup = {
            'ticker': ticker,
            'signal': analysis['signal'],
            'confidence': analysis['confidence'],
            'entry_price': round(current_price, 2),
            'stop_loss': round(current_price - (atr * STOP_LOSS_ATR_MULTIPLIER), 2),
            'take_profit': round(current_price + (atr * STOP_LOSS_ATR_MULTIPLIER * TAKE_PROFIT_RR_RATIO), 2),
            'risk_reward_ratio': TAKE_PROFIT_RR_RATIO,
            'atr': round(atr, 2),
        }

        return setup


class MomentumBreakoutStrategy:
    """
    52-Week High Momentum Breakout — highest-return systematic strategy on NSE.
    Buys stocks breaking 52-week highs on 2x+ volume confirmation.
    Evidence base: NSE large-cap momentum factor has delivered 18-30% CAGR
    in trending years (2014-2019, 2020-2021, 2023-2024).
    """

    def __init__(self):
        self.min_volume_ratio  = 2.0    # Require 2x average volume on breakout
        self.lookback_weeks    = 52     # 52-week high window
        self.breakout_buffer   = 0.005  # 0.5% buffer — price within 0.5% of 52W high
        self.min_adv           = 500_000  # Minimum avg daily volume (liquidity filter)

    def find_breakouts(self, tickers: list) -> list:
        """
        Screen tickers for 52-week high breakouts with volume surge.
        Returns list of breakout candidates sorted by volume strength.
        """
        import yfinance as yf
        import logging
        logger = logging.getLogger(__name__)
        breakouts = []

        # Batch download for efficiency
        try:
            raw = yf.download(tickers, period='1y', progress=False, auto_adjust=True)
        except Exception as e:
            logger.error(f"Batch download failed: {e}")
            return []

        closes  = raw['Close']  if isinstance(raw.columns, __import__('pandas').MultiIndex) else raw[['Close']]
        highs   = raw['High']   if isinstance(raw.columns, __import__('pandas').MultiIndex) else raw[['High']]
        volumes = raw['Volume'] if isinstance(raw.columns, __import__('pandas').MultiIndex) else raw[['Volume']]

        for ticker in tickers:
            try:
                if ticker not in closes.columns:
                    continue
                close_s  = closes[ticker].dropna()
                high_s   = highs[ticker].dropna()
                volume_s = volumes[ticker].dropna()

                if len(close_s) < 252:
                    continue

                # 52-week high = rolling max of the prior 252 candles (exclude today)
                high_52w   = high_s.iloc[-253:-1].max()
                today_high = high_s.iloc[-1]
                today_vol  = volume_s.iloc[-1]
                avg_vol_20 = volume_s.iloc[-20:].mean()

                if avg_vol_20 < self.min_adv:
                    continue   # Skip illiquid stocks

                volume_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0

                # Breakout condition: today's high ≥ 52W high (with tiny buffer)
                is_breakout = today_high >= high_52w * (1 - self.breakout_buffer)

                if is_breakout and volume_ratio >= self.min_volume_ratio:
                    # ATR-based stop (14-day)
                    tr = (high_s.iloc[-15:] - close_s.shift(1).iloc[-15:]).abs()
                    atr = tr.iloc[-14:].mean()
                    entry      = float(close_s.iloc[-1])
                    stop       = round(entry - 2 * atr, 2)
                    target     = round(entry + 4 * atr, 2)  # 2:1 RR minimum

                    breakouts.append({
                        'ticker':        ticker,
                        'entry_price':   round(entry, 2),
                        'high_52w':      round(high_52w, 2),
                        'volume_ratio':  round(volume_ratio, 2),
                        'stop_loss':     stop,
                        'target':        target,
                        'atr':           round(atr, 2),
                        'signal':        'BUY',
                        'strategy':      '52W_HIGH_BREAKOUT',
                        'confidence':    min(0.50 + (volume_ratio - 2) * 0.10, 0.90),
                    })
            except Exception as e:
                logger.debug(f"Breakout check failed for {ticker}: {e}")
                continue

        return sorted(breakouts, key=lambda x: x['volume_ratio'], reverse=True)

    def analyze_ticker(self, ticker: str) -> dict:
        """Analyze a single ticker for breakout signal."""
        result = self.find_breakouts([ticker])
        if result:
            return result[0]
        return {'ticker': ticker, 'signal': 'HOLD', 'confidence': 0.0,
                'reason': 'No 52-week high breakout detected'}


class SectorRotationStrategy:
    """
    Macro-driven sector rotation for NSE.
    Rotates capital into outperforming sectors based on:
    - USD/INR trend  → IT outperforms when rupee weakens
    - Interest rates → Banking outperforms on rate cuts
    - FII flows      → Follow foreign institutional money
    - Commodity cycle → Metals, Oil outperform in inflation
    """

    SECTOR_TICKERS = {
        'IT':      ['TCS.NS', 'INFY.NS', 'HCLTECH.NS', 'WIPRO.NS', 'TECHM.NS'],
        'Banking': ['HDFCBANK.NS', 'ICICIBANK.NS', 'SBIN.NS', 'KOTAKBANK.NS', 'AXISBANK.NS'],
        'FMCG':    ['HINDUNILVR.NS', 'ITC.NS', 'NESTLEIND.NS', 'BRITANNIA.NS', 'DABUR.NS'],
        'Pharma':  ['SUNPHARMA.NS', 'DRREDDY.NS', 'CIPLA.NS', 'DIVISLAB.NS', 'APOLLOHOSP.NS'],
        'Metals':  ['TATASTEEL.NS', 'JSWSTEEL.NS', 'HINDALCO.NS', 'VEDL.NS', 'SAIL.NS'],
        'Auto':    ['MARUTI.NS', 'M&M.NS', 'BAJAJ-AUTO.NS', 'HEROMOTOCO.NS', 'EICHERMOT.NS'],
    }

    def get_sector_performance(self, period: str = '1mo') -> dict:
        """Return 1-month performance ranking of NSE sectors."""
        import yfinance as yf
        import logging
        logger = logging.getLogger(__name__)
        performance = {}

        for sector, tickers in self.SECTOR_TICKERS.items():
            try:
                data    = yf.download(tickers, period=period, progress=False, auto_adjust=True)
                closes  = data['Close'] if isinstance(data.columns, __import__('pandas').MultiIndex) else data
                returns = []
                for t in tickers:
                    if t in closes.columns:
                        s = closes[t].dropna()
                        if len(s) >= 2:
                            returns.append((s.iloc[-1] / s.iloc[0] - 1) * 100)
                if returns:
                    performance[sector] = round(sum(returns) / len(returns), 2)
            except Exception as e:
                logger.debug(f"Sector perf error ({sector}): {e}")

        return dict(sorted(performance.items(), key=lambda x: x[1], reverse=True))

    def recommend_sectors(self) -> list:
        """Return top 2 sectors to overweight this month."""
        perf = self.get_sector_performance()
        return list(perf.keys())[:2]


class OpeningRangeBreakout:
    """
    Opening Range Breakout (ORB) — high win-rate intraday strategy for NSE.

    The Opening Range is defined as the High and Low of the first 15 minutes
    of the trading session (9:15 AM – 9:30 AM IST). A breakout above/below
    this range with VWAP confirmation is one of the most reliable intraday
    setups on NSE.

    Entry rules:
    - Price breaks above ORB high → BUY (with VWAP below price, confirming trend)
    - Price breaks below ORB low  → SELL (with VWAP above price, confirming trend)
    - Stop: other side of ORB
    - Target: 2× ORB width
    - No new entries after 1:30 PM IST (too little time before 3:30 PM close)
    """

    ORB_END_MINUTES = 15          # First 15 minutes define the range
    NO_ENTRY_AFTER  = (13, 30)    # (hour, minute) IST — no entries after this

    def __init__(self):
        import pytz
        self.ist = pytz.timezone('Asia/Kolkata')

    def get_opening_range(self, ticker: str) -> Optional[Dict]:
        """
        Fetch today's 1-minute bars and compute the 9:15–9:30 opening range.
        Returns {'high': ..., 'low': ..., 'width': ..., 'vwap': ...} or None.
        """
        import yfinance as yf
        import pandas as pd
        import logging
        logger = logging.getLogger(__name__)

        try:
            df = yf.download(ticker, period='1d', interval='1m',
                             progress=False, auto_adjust=True)
            if df.empty:
                return None

            # Localise index to IST
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(self.ist)
            else:
                df.index = df.index.tz_convert(self.ist)

            # First 15 minutes: 9:15 AM to 9:29 AM
            session_start = df.index[0].replace(hour=9, minute=15, second=0)
            session_end   = session_start + pd.Timedelta(minutes=self.ORB_END_MINUTES)
            orb_bars = df[(df.index >= session_start) & (df.index < session_end)]

            if orb_bars.empty:
                return None

            orb_high = float(orb_bars['High'].max())
            orb_low  = float(orb_bars['Low'].min())
            orb_width = orb_high - orb_low

            # VWAP for the full session so far
            tp = (df['High'] + df['Low'] + df['Close']) / 3
            vwap = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()
            current_vwap  = float(vwap.iloc[-1])
            current_price = float(df['Close'].iloc[-1])

            return {
                'orb_high':     round(orb_high, 2),
                'orb_low':      round(orb_low, 2),
                'orb_width':    round(orb_width, 2),
                'current_price': current_price,
                'current_vwap': round(current_vwap, 2),
                'orb_bars':     len(orb_bars),
            }
        except Exception as e:
            logger.error(f"ORB fetch error ({ticker}): {e}")
            return None

    def analyze(self, ticker: str) -> Dict:
        """
        Generate ORB signal for ticker.
        Returns signal dict with BUY/SELL/HOLD and stop/target levels.
        """
        from datetime import datetime
        import pytz
        logger = logging.getLogger(__name__)

        now_ist = datetime.now(self.ist)

        # Don't generate new signals after 1:30 PM IST
        if (now_ist.hour, now_ist.minute) > self.NO_ENTRY_AFTER:
            return {'ticker': ticker, 'signal': 'HOLD', 'confidence': 0.0,
                    'reason': 'Past ORB entry cutoff (1:30 PM IST)'}

        orb = self.get_opening_range(ticker)
        if not orb:
            return {'ticker': ticker, 'signal': 'HOLD', 'confidence': 0.0,
                    'reason': 'Unable to fetch opening range data'}

        price = orb['current_price']
        vwap  = orb['current_vwap']
        high  = orb['orb_high']
        low   = orb['orb_low']
        width = orb['orb_width']

        signal     = 'HOLD'
        confidence = 0.0
        stop       = None
        target     = None
        reason     = ''

        if price > high and price > vwap:
            # Bullish breakout: price above ORB high AND above VWAP
            signal     = 'BUY'
            stop       = round(low, 2)           # Stop at ORB low
            target     = round(high + 2 * width, 2)  # 2× ORB width target
            vwap_dist  = (price - vwap) / vwap
            confidence = min(0.60 + vwap_dist * 10, 0.90)
            reason     = f"Bullish ORB breakout above ₹{high:.2f} with VWAP support at ₹{vwap:.2f}"

        elif price < low and price < vwap:
            # Bearish breakdown: price below ORB low AND below VWAP
            signal     = 'SELL'
            stop       = round(high, 2)
            target     = round(low - 2 * width, 2)
            vwap_dist  = (vwap - price) / vwap
            confidence = min(0.60 + vwap_dist * 10, 0.90)
            reason     = f"Bearish ORB breakdown below ₹{low:.2f} with VWAP resistance at ₹{vwap:.2f}"

        else:
            reason = f"Price within ORB range (₹{low:.2f} – ₹{high:.2f}). Waiting for breakout."

        return {
            'ticker':        ticker,
            'signal':        signal,
            'confidence':    round(confidence, 3),
            'strategy':      'OPENING_RANGE_BREAKOUT',
            'current_price': price,
            'orb_high':      high,
            'orb_low':       low,
            'orb_width':     round(width, 2),
            'stop_loss':     stop,
            'price_target':  target,
            'vwap':          vwap,
            'reason':        reason,
        }
