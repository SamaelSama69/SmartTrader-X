"""
Indian Momentum Strategy Logic
Includes Momentum Scoring and VCP Pattern Detection
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MomentumScorer:
    """Calculates normalized momentum scores for stock ranking"""
    
    def __init__(self, window_short: int = 90, window_long: int = 180):
        self.window_short = window_short
        self.window_long = window_long

    def calculate_score(self, df: pd.DataFrame) -> float:
        """
        Calculate Normalized Momentum Score:
        (Short-term Return / Volatility) + (Long-term Return / Volatility)
        """
        if df.empty or len(df) < self.window_long:
            return 0.0

        try:
            # Calculate daily returns
            returns = df['Close'].pct_change().dropna()
            
            # Short-term metrics (e.g. 90 days)
            st_data = df.tail(self.window_short)
            st_return = (st_data['Close'].iloc[-1] / st_data['Close'].iloc[0]) - 1
            st_vol = returns.tail(self.window_short).std() * np.sqrt(252) # Annualized
            
            # Long-term metrics (e.g. 180 days)
            lt_data = df.tail(self.window_long)
            lt_return = (lt_data['Close'].iloc[-1] / lt_data['Close'].iloc[0]) - 1
            lt_vol = returns.tail(self.window_long).std() * np.sqrt(252)
            
            # Avoid division by zero and extreme sensitivity to very low volatility
            epsilon = 0.001
            st_score = st_return / (st_vol + epsilon)
            lt_score = lt_return / (lt_vol + epsilon)
            
            return float(st_score + lt_score)
            
        except Exception:
            return 0.0

class VCPPatternDetector:
    """
    Detects Volatility Contraction Patterns (VCP) based on Mark Minervini's principles.
    Looks for:
    1. Sequential reduction in price volatility (the "cheeks")
    2. Volume drying up in the final contraction
    3. Tightening ranges near the pivot
    """
    def __init__(self, max_contractions: int = 4):
        self.max_contractions = max_contractions
    
    def analyze_vcp(self, df: pd.DataFrame) -> Dict:
        """
        Perform deep VCP analysis.
        Returns dict with is_vcp, num_contractions, and contraction_depths.
        """
        if df.empty or len(df) < 100:
            return {'is_vcp': False, 'count': 0, 'depths': [], 'vol_dryup': False}
            
        try:
            # Analyze last 80 days for contractions
            recent = df.tail(80).copy()
            
            # Divide into 4 windows of 20 days each to find contractions
            windows = []
            for i in range(4):
                windows.append(recent.iloc[i*20:(i+1)*20])
            
            # Calculate range % (Depth) for each window
            def get_depth(chunk):
                high = chunk['High'].max()
                low = chunk['Low'].min()
                avg = chunk['Close'].mean()
                return (high - low) / avg if avg > 0 else 0
            
            depths = [get_depth(w) for w in windows]
            
            # Check for sequential tightening (e.g. 25% -> 15% -> 8% -> 3%)
            # We look for at least 3 contractions in decreasing order
            tightening_count = 0
            for i in range(len(depths) - 1):
                if depths[i] > depths[i+1]:
                    tightening_count += 1
                else:
                    # If it stops tightening, we reset or break depending on strategy
                    # For now, we just count how many sequential tightenings we have
                    pass

            # Volume Dry-up check: Volume in last 10 days < 50-day Average Volume
            last_10_vol = df['Volume'].tail(10).mean()
            avg_vol_50 = df['Volume'].rolling(50).mean().iloc[-1]
            vol_dryup = last_10_vol < (avg_vol_50 * 0.8) # 20% reduction

            # VCP criteria: at least 2 tightenings (3 windows) and final depth < 10%
            is_vcp = tightening_count >= 2 and depths[-1] < 0.10
            
            return {
                'is_vcp': is_vcp,
                'count': tightening_count + 1,
                'depths': [round(d * 100, 1) for d in depths],
                'vol_dryup': vol_dryup,
                'final_tightness': depths[-1]
            }
            
        except Exception as e:
            logger.error(f"VCP Analysis Error: {e}")
            return {'is_vcp': False, 'count': 0, 'depths': [], 'vol_dryup': False}

    def is_tightening(self, df: pd.DataFrame) -> bool:
        """Legacy compatibility method."""
        res = self.analyze_vcp(df)
        return res['is_vcp']

class IndianMomentumStrategy:
    """
    High-performance momentum strategy tailored for the Indian Market (NSE/BSE).
    
    Combines:
    1. Trend Filtering (Price > 200 DMA)
    2. Momentum Scoring (Normalized Returns)
    3. Volatility Contraction (VCP)
    4. Relative Strength (vs NIFTY 50)
    """
    
    def __init__(self, momentum_window: int = 90):
        self.scorer = MomentumScorer(window_short=momentum_window, window_long=momentum_window*2)
        self.vcp_detector = VCPPatternDetector()
        self.benchmark_ticker = "^NSEI" # NIFTY 50
        
    def analyze_ticker(self, ticker: str, df: pd.DataFrame, 
                       benchmark_df: Optional[pd.DataFrame] = None,
                       sentiment_score: float = 0.0) -> Dict:
        """
        Analyze a single ticker using momentum, VCP, and news sentiment.
        """
        result = {
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'signal': 'HOLD',
            'confidence': 0.0,
            'factors': {},
            'reason': '',
            'stop_loss': None,
            'price_target': None,
            'current_price': None
        }
        
        if df.empty or len(df) < 200:
            result['reason'] = 'Insufficient data (min 200 days required)'
            return result
            
        try:
            # 0. Basic Price Info
            current_price = float(df['Close'].iloc[-1])
            result['current_price'] = current_price

            # 1. Trend Filter: Price above 200 DMA + EMA 50 > EMA 200
            sma_200 = df['Close'].rolling(window=200).mean().iloc[-1]
            ema_50 = df['Close'].ewm(span=50, adjust=False).mean().iloc[-1]
            ema_200 = df['Close'].ewm(span=200, adjust=False).mean().iloc[-1]
            
            is_uptrend = current_price > sma_200 and ema_50 > ema_200
            
            # Trend Intensity (Slope of EMA 50)
            ema_50_prev = df['Close'].ewm(span=50, adjust=False).mean().iloc[-5]
            trend_intensity = (ema_50 / ema_50_prev - 1) * 100 # % change in 5 days
            
            # 2. Momentum Score
            m_score = self.scorer.calculate_score(df)
            
            # 3. VCP Pattern (Deep Analysis)
            vcp_res = self.vcp_detector.analyze_vcp(df)
            is_vcp = vcp_res['is_vcp']
            vol_dryup = vcp_res['vol_dryup']
            
            # 4. Relative Strength (if benchmark data provided)
            rs_score = 0.0
            if benchmark_df is not None and not benchmark_df.empty:
                window = 126
                if len(df) >= window and len(benchmark_df) >= window:
                    stock_perf = (df['Close'].iloc[-1] / df['Close'].iloc[-window]) - 1
                    bench_perf = (benchmark_df['Close'].iloc[-1] / benchmark_df['Close'].iloc[-window]) - 1
                    rs_score = stock_perf - bench_perf
            
            # 5. Volume Confirmation
            avg_vol_50 = df['Volume'].rolling(window=50).mean().iloc[-1]
            current_vol = df['Volume'].iloc[-1]
            vol_ratio = current_vol / avg_vol_50 if avg_vol_50 > 0 else 1.0
            
            # 6. ATR-based Stop and Target
            # Simple ATR(14)
            high_low = df['High'] - df['Low']
            high_close = np.abs(df['High'] - df['Close'].shift())
            low_close = np.abs(df['Low'] - df['Close'].shift())
            tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            
            # 7. Contrarian Intelligence
            # Measures divergence between sentiment and momentum
            # High Positive = "Bullish Underdog" (Great news, lagging price)
            # High Negative = "Technical Runaway" (Bad news, surging price)
            m_score_norm = float(np.tanh(m_score / 3.0))  # tanh squashes ±3 → ±0.995
            contrarian_score = sentiment_score - m_score_norm
            
            # Unbreakable NaN checks
            m_score = float(np.nan_to_num(m_score, nan=0.0, posinf=0.0, neginf=0.0))
            vol_ratio = float(np.nan_to_num(vol_ratio, nan=1.0, posinf=1.0, neginf=1.0))
            trend_intensity = float(np.nan_to_num(trend_intensity, nan=0.0, posinf=0.0, neginf=0.0))
            atr = float(np.nan_to_num(atr, nan=0.0, posinf=0.0, neginf=0.0))
            rs_score = float(np.nan_to_num(rs_score, nan=0.0, posinf=0.0, neginf=0.0))
            contrarian_score = float(np.nan_to_num(contrarian_score, nan=0.0, posinf=0.0, neginf=0.0))
            sentiment_score = float(np.nan_to_num(sentiment_score, nan=0.0, posinf=0.0, neginf=0.0))
            
            # Store factors
            result['factors'] = {
                'price_vs_sma200': float(current_price / sma_200 - 1),
                'momentum_score': float(m_score),
                'vcp_pattern': bool(is_vcp),
                'rs_score': float(rs_score),
                'vol_ratio': float(vol_ratio),
                'trend_intensity': float(trend_intensity),
                'atr': float(atr),
                'sentiment_score': float(sentiment_score),
                'contrarian_score': float(contrarian_score),
                'vcp_details': vcp_res
            }
            
            # Signal Generation Logic
            # Sentiment Adjustments:
            # Positive sentiment increases BUY confidence, decreases SELL confidence
            # Negative sentiment increases SELL confidence, decreases BUY confidence
            sentiment_impact = sentiment_score * 0.15 # Max 15% shift
            
            # VCP Multiplier: Higher confidence if volume also dried up (Minervini logic)
            vcp_bonus = 0.05 if is_vcp and vol_dryup else 0.0

            # Contrarian adjustment at entry
            # Underdog (positive c_score) = smart money setup, boost confidence
            # Overextended (negative c_score) = chasing a run, penalise confidence
            contrarian_adj = contrarian_score * 0.08 # max ±16% shift

            if is_uptrend and m_score > 1.2 and is_vcp and vol_ratio > 1.1:
                # Strong BUY setup
                if sentiment_score < -0.3:
                    result['signal'] = 'HOLD'
                    result['reason'] = 'Potential breakout blocked by significant negative news sentiment'
                else:
                    result['signal'] = 'BUY'
                    # Confidence starts at 65%, adjusted by momentum, volume, sentiment, and contrarian logic
                    base_conf = 0.65 + (m_score / 15.0) + (vol_ratio / 25.0)
                    result['confidence'] = min(0.95, base_conf + sentiment_impact + vcp_bonus + contrarian_adj)
                    
                    # Label the setup type in the reason
                    if contrarian_score > 0.5:
                        result['reason'] = f"High momentum breakout with VCP ({vcp_res['count']} cheeks) — Underdog setup (sentiment lagging price)"
                    elif contrarian_score < -0.5:
                        result['reason'] = f"High momentum breakout with VCP ({vcp_res['count']} cheeks) — caution: Overextended (price running ahead of news)"
                    else:
                        result['reason'] = f"High momentum breakout with VCP ({vcp_res['count']} cheeks) and volume confirmation"
                        
                    if vol_dryup: result['reason'] += " (Volume Dry-up detected)"
                    result['stop_loss'] = round(current_price - 1.5 * atr, 2)
                    result['price_target'] = round(current_price + 6.0 * atr, 2)
            
            elif is_uptrend and m_score > 0.6 and vol_ratio > 1.0:
                # Moderate BUY setup
                if sentiment_score < -0.2:
                    result['signal'] = 'HOLD'
                    result['reason'] = 'Uptrend entry avoided due to negative news sentiment'
                else:
                    result['signal'] = 'BUY'
                    base_conf = 0.50 + (m_score / 15.0)
                    result['confidence'] = min(0.85, base_conf + sentiment_impact + contrarian_adj)
                    
                    if contrarian_score > 0.5:
                        result['reason'] = 'Uptrend Underdog setup (bullish news not yet priced in)'
                    elif contrarian_score < -0.5:
                        result['reason'] = 'Uptrend entry — caution: Overextended (technical run exceeds news sentiment)'
                    else:
                        result['reason'] = 'Uptrend with positive momentum and healthy volume'
                        
                    result['stop_loss'] = round(current_price - 2.0 * atr, 2)
                    result['price_target'] = round(current_price + 4.5 * atr, 2)
            
            elif not is_uptrend and m_score < -0.5:
                # SHORT setup (Technical Downtrend)
                if sentiment_score > 0.2:
                    result['signal'] = 'HOLD'
                    result['reason'] = 'Technical downtrend signal blocked by positive news/recovery sentiment'
                else:
                    result['signal'] = 'SHORT'
                    # Negative sentiment impact increases confidence for SHORT
                    base_conf = 0.55 + abs(m_score / 15.0)
                    # For SHORT, we invert the contrarian_adj because positive c_score (bullish news) 
                    # should penalize short conviction
                    result['confidence'] = min(0.90, base_conf - sentiment_impact - (contrarian_score * 0.10)) 
                    
                    if contrarian_score < -0.5:
                        result['reason'] = 'Panic Sell-off (Negative news + Technical breakdown)'
                    else:
                        result['reason'] = 'Sustained technical downtrend with negative news bias'
                        
                    result['stop_loss'] = round(current_price + 1.8 * atr, 2)
                    result['price_target'] = round(current_price - 5.0 * atr, 2)
            
            else:
                result['signal'] = 'HOLD'
                result['reason'] = 'Neutral momentum or contradictory technical/news indicators'
                
            return result
            
        except Exception as e:
            logger.error(f"Error analyzing {ticker}: {e}")
            result['reason'] = f"Analysis error: {str(e)}"
            return result
