"""
Indian Market Regime Detection
Multi-factor regime classifier using NIFTY50, India VIX, and realized volatility.
"""

import logging
import time as _time
from datetime import datetime, timedelta
from typing import Dict, Literal

import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

RegimeType = Literal[
    'BULL_TREND', 'BULL_VOLATILE', 'BEAR_TREND', 'BEAR_VOLATILE',
    'SIDEWAYS_LOW_VOL', 'SIDEWAYS_HIGH_VOL', 'CRISIS'
]


class IndianMarketRegime:
    """
    Cached NSE regime classifier.
    Uses NIFTY trend, India VIX, and 20-day realized volatility.
    """

    NIFTY = '^NSEI'
    INDIA_VIX = '^INDIAVIX'

    VIX_LOW = 13
    VIX_HIGH = 20
    VIX_CRISIS = 30
    _CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self._cached_regime: RegimeType = None
        self._cached_at: float = 0.0
        self.current_metrics: dict = {}

    def get_regime(self, force_refresh: bool = False) -> RegimeType:
        """Return current market regime. Cached for 5 minutes."""
        now = _time.time()
        if force_refresh or self._cached_regime is None or (now - self._cached_at) > self._CACHE_TTL:
            self._cached_regime = self._compute_regime()
            self._cached_at = now
        return self._cached_regime

    def _compute_regime(self) -> RegimeType:
        """Compute the current market regime from live data."""
        try:
            nifty = yf.Ticker(self.NIFTY).history(period='1y')
            if nifty.empty or len(nifty) < 50:
                self.current_metrics = {'trend': 'UNKNOWN', 'volatility': 0.0, 'vix': 0.0}
                return 'SIDEWAYS_LOW_VOL'

            close = nifty['Close']
            ma_20 = close.rolling(20).mean().iloc[-1]
            ma_50 = close.rolling(50).mean().iloc[-1]
            ma_200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else ma_50
            current = close.iloc[-1]

            daily_ret = close.pct_change().dropna()
            vol_20d = daily_ret.tail(20).std() * np.sqrt(252)

            try:
                vix_data = yf.Ticker(self.INDIA_VIX).history(period='5d')
                india_vix = float(vix_data['Close'].iloc[-1]) if not vix_data.empty else 16
            except Exception:
                india_vix = 16

            is_uptrend = current > ma_20 > ma_50
            is_downtrend = current < ma_20 < ma_50
            is_above_200 = current > ma_200

            if india_vix >= self.VIX_CRISIS:
                regime = 'CRISIS'
            elif is_uptrend and is_above_200:
                regime = 'BULL_VOLATILE' if india_vix >= self.VIX_HIGH else 'BULL_TREND'
            elif is_downtrend:
                regime = 'BEAR_VOLATILE' if india_vix >= self.VIX_HIGH else 'BEAR_TREND'
            else:
                regime = 'SIDEWAYS_HIGH_VOL' if india_vix >= self.VIX_HIGH else 'SIDEWAYS_LOW_VOL'

            logger.info(
                f"[REGIME] {regime} | NIFTY={current:.0f} | "
                f"India VIX={india_vix:.1f} | Vol={vol_20d:.1%}"
            )

            self.current_metrics = {
                'trend': 'UPTREND' if is_uptrend else 'DOWNTREND' if is_downtrend else 'SIDEWAYS',
                'volatility': float(vol_20d),
                'vix': float(india_vix)
            }
            return regime

        except Exception as e:
            logger.warning(f"Regime detection failed: {e}")
            self.current_metrics = {'trend': 'UNKNOWN', 'volatility': 0.0, 'vix': 0.0}
            return 'SIDEWAYS_LOW_VOL'

    def get_strategy_weights(self, regime: RegimeType) -> Dict[str, float]:
        """Return signal component weights for the given regime."""
        import os
        has_sentiment = bool(os.getenv('FINNHUB_API_KEY') or os.getenv('NEWS_API_KEY'))

        weights = {
            'BULL_TREND': {'trend': 0.50, 'momentum': 0.30, 'sentiment': 0.10, 'value': 0.10},
            'BULL_VOLATILE': {'trend': 0.30, 'momentum': 0.20, 'sentiment': 0.20, 'value': 0.30},
            'BEAR_TREND': {'trend': 0.40, 'momentum': 0.20, 'sentiment': 0.20, 'value': 0.20},
            'BEAR_VOLATILE': {'trend': 0.20, 'momentum': 0.10, 'sentiment': 0.30, 'value': 0.40},
            'SIDEWAYS_LOW_VOL': {'trend': 0.20, 'momentum': 0.20, 'sentiment': 0.20, 'value': 0.40},
            'SIDEWAYS_HIGH_VOL': {'trend': 0.20, 'momentum': 0.10, 'sentiment': 0.30, 'value': 0.40},
            'CRISIS': {'trend': 0.10, 'momentum': 0.00, 'sentiment': 0.40, 'value': 0.50},
        }

        # Redistribute sentiment weight to value when no API keys configured
        if not has_sentiment:
            for regime_name, w in weights.items():
                redirect = w.get('sentiment', 0.0)
                w['value'] = w.get('value', 0.2) + redirect
                w['sentiment'] = 0.0

        return weights.get(regime, weights['SIDEWAYS_LOW_VOL'])

    def get_preferred_strategies(self, regime: RegimeType) -> list:
        """Return preferred strategy names for the given regime."""
        # Mapping from regime to preferred strategy IDs (matches AlgorithmSelector.algorithms keys)
        regime_strategies = {
            'BULL_TREND': ['indian_momentum', 'bulls_ai_momentum', 'buffett_value', 'momentum_breakout'],
            'BULL_VOLATILE': ['indian_momentum', 'momentum_breakout', 'bulls_ai_momentum', 'sector_rotation'],
            'BEAR_TREND': ['buffett_value', 'nifty_options_writer', 'sector_rotation', 'mean_reversion'],
            'BEAR_VOLATILE': ['nifty_options_writer', 'buffett_value', 'sector_rotation', 'mean_reversion'],
            'SIDEWAYS_LOW_VOL': ['nifty_options_writer', 'buffett_value', 'sector_rotation', 'mean_reversion'],
            'SIDEWAYS_HIGH_VOL': ['nifty_options_writer', 'buffett_value', 'sector_rotation', 'mean_reversion'],
            'CRISIS': ['buffett_value', 'sector_rotation', 'mean_reversion'],
            'UNKNOWN': ['buffett_value', 'indian_momentum', 'sector_rotation'],
        }
        return regime_strategies.get(regime, regime_strategies['UNKNOWN'])

    def get_risk_multiplier(self, regime: RegimeType) -> float:
        """Scale risk by market regime before order sizing."""
        return {
            'BULL_TREND': 1.00,
            'BULL_VOLATILE': 0.70,
            'BEAR_TREND': 0.55,
            'BEAR_VOLATILE': 0.35,
            'SIDEWAYS_LOW_VOL': 0.65,
            'SIDEWAYS_HIGH_VOL': 0.45,
            'CRISIS': 0.00,
        }.get(regime, 0.50)
