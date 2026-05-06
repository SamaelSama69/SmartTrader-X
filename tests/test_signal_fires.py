"""
Critical regression test: verifies the signal engine can produce BUY signals.
If this test fails, the confidence formula or ADX gate is broken.
"""
import pandas as pd
import numpy as np
from strategies.stocks import StockStrategy

# Shared mock technical signals for a clearly bullish scenario
BULLISH_TECH = {
    'adx': 30.0,  # Strong trend, adx_factor = min(30/25, 1.0) = 1.0
    'ma_signal': 'BULLISH',
    'supertrend_signal': 'BULLISH',
    'macd_crossover': True,
    'macd_signal': 'BULLISH',
    'rsi': 35.0,  # Oversold bounce - gives momentum bonus
    'volume_signal': 'HIGH',
    'bb_pct_b': 0.5,  # Middle of bands
    'vwap_signal': 'BULLISH',
}


def test_bullish_conditions_produce_buy_signal():
    """Test that a clearly bullish scenario produces BUY signal with sufficient confidence."""
    strategy = StockStrategy()
    factors = {'technical': BULLISH_TECH, 'sentiment': {'aggregate_sentiment': 0.0}, 'fundamentals': {}}
    signal, confidence = strategy._generate_signal(factors, regime='BULL_TREND')

    assert signal == 'BUY', f"Expected BUY, got {signal}"
    assert confidence >= 0.55, f"Expected confidence>=0.55, got {confidence:.3f}"


def test_confidence_not_permanently_below_execute_threshold():
    """The old normalisation min(abs/2.0) made max confidence ~0.4. This must never happen again."""
    strategy = StockStrategy()
    factors = {'technical': BULLISH_TECH, 'sentiment': {'aggregate_sentiment': 0.0}, 'fundamentals': {}}
    _, confidence = strategy._generate_signal(factors, regime='BULL_TREND')

    assert confidence >= 0.55, (
        f"Confidence {confidence:.3f} is below execute threshold 0.55. "
        "The confidence normalisation is broken — check _generate_signal() formula."
    )


def test_confidence_formula_uses_dynamic_max():
    """Verify the confidence formula uses dynamic max_composite, not arbitrary 2.0"""
    strategy = StockStrategy()
    # Same bullish tech as above
    factors = {'technical': BULLISH_TECH, 'sentiment': {'aggregate_sentiment': 0.0}, 'fundamentals': {}}

    # With BULLISH_TECH and BULL_TREND regime (weights: trend=0.50, momentum=0.30, value=0.10, sentiment=0.10):
    # trend_score = 1 (MA) + 1 (Supertrend) + 0.5 (MACD crossover) = 2.5, * adx_factor=1.0 → 2.5
    # momentum_score = 0 (RSI=50) + 0.5 (volume HIGH and trend>0) = 0.5
    # value_score = 0 (BB pct_b=0.5) + 0.3 (VWAP bullish) = 0.3
    # sent_score = 0
    # composite = 0.50*2.5 + 0.30*0.5 + 0.10*0.3 = 1.25 + 0.15 + 0.03 = 1.43
    # max_composite = 0.50*3 + 0.30*2 + 0.10*2 + 0.10*2 + 0.2 = 1.5 + 0.6 + 0.2 + 0.2 + 0.2 = 2.7
    # confidence = 1.43 / 2.7 = 0.53
    # Since composite >= 0.8, signal=BUY, confidence=0.53

    signal, confidence = strategy._generate_signal(factors, regime='BULL_TREND')
    assert confidence > 0.40, f"Confidence {confidence:.3f} too low - formula broken"
    assert signal == 'BUY', f"Expected BUY, got {signal}"
