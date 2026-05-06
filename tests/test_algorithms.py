"""
Tests for algorithms.py
"""

import pytest
from strategies.algorithms import AlgorithmSelector


def test_regime_routing():
    """Test that regime keys from IndianMarketRegime match regime_preferences."""
    sel = AlgorithmSelector(market='IN')
    # Mock IndianMarketRegime to return BULL_TREND
    sel.regime_detector.get_regime = lambda: 'BULL_TREND'
    result = sel.recommend_algorithm('RELIANCE.NS')

    # Must NOT be the default ['buffett_value', 'dalio_all_weather']
    # For BULL_TREND, the preferred algorithms are ['indian_momentum', 'bulls_ai_momentum', 'buffett_value', 'momentum_breakout']
    assert result.get('recommended_algorithm') != 'buffett_value', \
        "Algorithm should not fall back to default buffett_value for BULL_TREND"
    assert result.get('recommended_algorithm') != 'dalio_all_weather', \
        "Algorithm should not fall back to default dalio_all_weather for BULL_TREND"
    assert result.get('recommended_algorithm') in ['indian_momentum', 'bulls_ai_momentum', 'buffett_value', 'momentum_breakout'], \
        f"Expected one of indian_momentum, bulls_ai_momentum, buffett_value, momentum_breakout, got {result.get('recommended_algorithm')}"


def test_regime_routing_bear_trend():
    """Test that BEAR_TREND regime routes to correct algorithms."""
    sel = AlgorithmSelector(market='IN')
    # Mock IndianMarketRegime to return BEAR_TREND
    sel.regime_detector.get_regime = lambda: 'BEAR_TREND'
    result = sel.recommend_algorithm('RELIANCE.NS')

    # For BEAR_TREND, dalio_all_weather is NOT available for Indian markets
    # Preferred algorithms include 'buffett_value', 'nifty_options_writer', 'sector_rotation', 'mean_reversion'
    assert result.get('recommended_algorithm') in ['buffett_value', 'nifty_options_writer', 'sector_rotation', 'mean_reversion'], \
        f"Expected one of buffett_value, nifty_options_writer, sector_rotation, mean_reversion, got {result.get('recommended_algorithm')}"


def test_regime_routing_sideways_low_vol():
    """Test that SIDEWAYS_LOW_VOL regime routes to correct algorithms."""
    sel = AlgorithmSelector(market='IN')
    # Mock IndianMarketRegime to return SIDEWAYS_LOW_VOL
    sel.regime_detector.get_regime = lambda: 'SIDEWAYS_LOW_VOL'
    result = sel.recommend_algorithm('RELIANCE.NS')

    # For SIDEWAYS_LOW_VOL, dalio_all_weather is NOT available for Indian markets
    # Preferred algorithms are ['nifty_options_writer', 'buffett_value', 'sector_rotation', 'mean_reversion']
    assert result.get('recommended_algorithm') in ['nifty_options_writer', 'buffett_value', 'sector_rotation', 'mean_reversion'], \
        f"Expected one of nifty_options_writer, buffett_value, sector_rotation, mean_reversion, got {result.get('recommended_algorithm')}"


def test_regime_detector_initialized():
    """Test that regime_detector is properly initialized in AlgorithmSelector."""
    sel = AlgorithmSelector(market='IN')
    assert hasattr(sel, 'regime_detector'), "AlgorithmSelector should have regime_detector attribute"
    assert sel.regime_detector is not None, "regime_detector should not be None"


def test_run_all_algorithms_uses_regime_detector():
    """Test that run_all_algorithms uses regime_detector instead of get_market_regime."""
    sel = AlgorithmSelector(market='IN')
    # Mock IndianMarketRegime to return a known regime
    sel.regime_detector.get_regime = lambda: 'BULL_TREND'
    result = sel.run_all_algorithms('RELIANCE.NS')

    # Verify the result contains the mocked regime
    assert result.get('market_regime') == 'BULL_TREND', \
        f"Expected market_regime to be BULL_TREND, got {result.get('market_regime')}"
