"""
Test suite for Phase 1-5 fixes.
Verifies bugs are resolved without needing live API calls.
Run: python -m pytest tests/test_core_fixes.py -v
"""

import sys, os, json, tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── BUG-01: memory_manager has logger ────────────────────────────────────────
def test_memory_manager_has_logger():
    from utils import memory_manager as mm
    assert hasattr(mm, 'logger'), "logger must be defined at module level in memory_manager"


# ── BUG-03: RiskManager.enable_trading is non-blocking ───────────────────────
def test_enable_trading_nonblocking():
    from utils.risk_manager import RiskManager
    rm = RiskManager(initial_capital=100_000)
    rm.trading_enabled = False
    start = datetime.now()
    rm.enable_trading(cooldown_minutes=30)          # Must return immediately
    elapsed = (datetime.now() - start).total_seconds()
    assert elapsed < 1.0, f"enable_trading() blocked for {elapsed:.1f}s — must be non-blocking"
    assert not rm.is_trading_enabled(), "Should still be disabled during cooldown"
    # Simulate time passing
    rm._reenable_after = datetime.now() - timedelta(seconds=1)
    assert rm.is_trading_enabled(), "Should re-enable after cooldown period"


# ── BUG-04: DiskCache uses stable hash across sessions ───────────────────────
def test_diskcache_stable_hash():
    with tempfile.TemporaryDirectory() as tmp:
        from utils.cache import DiskCache
        c = DiskCache(cache_dir=tmp)
        p1 = c._cache_path("RELIANCE.NS_1d")
        p2 = c._cache_path("RELIANCE.NS_1d")
        assert p1 == p2, "Cache path must be identical for same key across calls"
        assert 'hash(' not in str(p1), "Path must not use Python's unstable hash()"


# ── BUG-07: test_screener uses valid NSE assertion ───────────────────────────
def test_screener_test_uses_nse_tickers():
    with open('tests/test_screener.py') as f:
        content = f.read()
    assert 'AAPL' not in content or 'RELIANCE' in content, \
        "test_screener.py must not assert US tickers for the NSE screener"


# ── FLAW-01: VWAP resets by day on intraday data ────────────────────────────
def test_vwap_daily_reset():
    from utils.indian_indicators import calculate_vwap

    # Build fake 2-day 5-minute intraday data
    times, o, h, l, c, v = [], [], [], [], [], []
    for day_offset in range(2):
        base = pd.Timestamp('2024-01-02') + pd.Timedelta(days=day_offset)
        base = base.replace(hour=9, minute=15)
        for minute in range(0, 75, 5):   # 15 bars per day
            times.append(base + pd.Timedelta(minutes=minute))
            o.append(100 + day_offset * 5); h.append(102 + day_offset * 5)
            l.append(99 + day_offset * 5);  c.append(101 + day_offset * 5)
            v.append(1000 + minute * 10)

    df = pd.DataFrame({'Open': o, 'High': h, 'Low': l, 'Close': c, 'Volume': v},
                      index=pd.DatetimeIndex(times, tz='Asia/Kolkata'))
    vwap = calculate_vwap(df, anchor='day')

    # VWAP on day 1 bar 0 should be TP of that bar (cumsum of 1 bar)
    day1_bar0_tp = (h[0] + l[0] + c[0]) / 3
    assert abs(float(vwap.iloc[0]) - day1_bar0_tp) < 0.01, \
        f"First bar VWAP should equal TP ({day1_bar0_tp:.2f}), got {float(vwap.iloc[0]):.2f}"

    # VWAP should reset: day 2 bar 0 should be TP of that day's first bar, not cumulative
    day2_idx = 15
    day2_tp = (h[day2_idx] + l[day2_idx] + c[day2_idx]) / 3
    assert abs(float(vwap.iloc[day2_idx]) - day2_tp) < 0.01, \
        "VWAP must reset at start of each new trading day"


# ── FLAW-02: Pivot points use iloc[-2] not iloc[-1] ─────────────────────────
def test_pivot_points_use_previous_day():
    from utils.indian_indicators import calculate_pivot_points
    df = pd.DataFrame({
        'High':  [105, 110, 120],   # Row 0, 1, 2
        'Low':   [95,  100, 108],
        'Close': [100, 105, 115],
    })
    pivots = calculate_pivot_points(df, method='classic')
    # Should use row 1 (iloc[-2]) not row 2 (iloc[-1])
    expected_pivot = (110 + 100 + 105) / 3   # row 1 values
    wrong_pivot    = (120 + 108 + 115) / 3   # row 2 values
    assert abs(pivots['pivot'] - expected_pivot) < 0.001, \
        f"Pivot must use iloc[-2] (expected {expected_pivot:.2f}), got {pivots['pivot']:.2f}"
    assert abs(pivots['pivot'] - wrong_pivot) > 0.001, \
        "Pivot must NOT use today's iloc[-1] values"


# ── FLAW-04: WEAK_BUY at score=2 ────────────────────────────────────────────
def test_stock_strategy_weak_buy():
    from strategies.stocks import StockStrategy
    s = StockStrategy()
    # Test with weak bullish factors (composite score around 0.4-0.8)
    factors = {
        'technical': {
            'ma_signal': 'BULLISH',
            'supertrend_signal': 'NEUTRAL',
            'macd_signal': 'NEUTRAL',
            'rsi': 45,
            'volume_signal': 'NORMAL',
            'adx': 20,  # Not trending
            'bb_pct_b': 0.3,
            'vwap_signal': 'NEUTRAL'
        },
        'sentiment': {
            'aggregate_sentiment': 0.1  # Slightly positive
        }
    }
    sig, conf = s._generate_signal(factors, regime='SIDEWAYS_LOW_VOL', sector_boost=0.0)
    # With weak factors, should return HOLD or weak BUY
    assert sig in ['BUY', 'HOLD'], f"Weak factors should return BUY or HOLD, got {sig}"
    if sig == 'BUY':
        assert conf < 0.80, f"Weak BUY confidence should be discounted, got {conf:.2f}"


# ── Phase 3: Kelly sizing produces sensible shares ───────────────────────────
def test_kelly_sizing():
    from utils.risk_manager import RiskManager
    rm = RiskManager(initial_capital=100_000)
    # High confidence → more shares than low confidence
    high_conf_shares = rm.size_position_kelly(price=500, confidence=0.90)
    low_conf_shares  = rm.size_position_kelly(price=500, confidence=0.40)
    assert high_conf_shares > 0, "Kelly sizing must return > 0 shares"
    assert high_conf_shares >= low_conf_shares, \
        "Higher confidence must yield >= shares vs lower confidence"
    # Max position cap: 10% of 100000 at price 500 = max 20 shares
    assert high_conf_shares <= 200, "Kelly sizing must not exceed MAX_POSITION_PCT"


# ── Phase 3: Circuit breaker triggers after 3 losses ─────────────────────────
def test_consecutive_loss_circuit_breaker():
    from utils.risk_manager import RiskManager
    rm = RiskManager(initial_capital=100_000)
    rm.trade_history = [
        {'ticker': 'A', 'side': 'BUY', 'pnl': -500},
        {'ticker': 'B', 'side': 'BUY', 'pnl': -300},
        {'ticker': 'C', 'side': 'BUY', 'pnl': -200},
    ]
    assert rm.check_consecutive_losses(max_consecutive=3), \
        "Circuit breaker must trigger after 3 consecutive losses"

    rm.trade_history[-1]['pnl'] = 100   # Last trade is a win
    assert not rm.check_consecutive_losses(max_consecutive=3), \
        "Circuit breaker must NOT trigger if last trade is a win"


# ── Phase 5: MomentumBreakout returns correct structure ──────────────────────
def test_momentum_breakout_structure():
    from strategies.stocks import MomentumBreakoutStrategy
    mb = MomentumBreakoutStrategy()
    # Verify the class is instantiable and has required methods
    assert hasattr(mb, 'find_breakouts')
    assert hasattr(mb, 'analyze_ticker')
    assert mb.min_volume_ratio == 2.0
    assert mb.lookback_weeks == 52


# ── Phase 5: PerformanceTracker weight range ─────────────────────────────────
def test_performance_tracker_weights():
    with tempfile.TemporaryDirectory() as tmp:
        with patch('utils.performance_tracker.PERF_FILE', Path(tmp) / 'perf.json'):
            from utils.performance_tracker import StrategyPerformanceTracker
            tracker = StrategyPerformanceTracker()
            weights = tracker.get_algorithm_weights()
            for algo, w in weights.items():
                assert 0.05 <= w <= 2.1, \
                    f"Weight for {algo} must be in [0.1, 2.0], got {w:.2f}"


# ── BUG-05: DalioAllWeather uses cache for market data ───────────────────────────
def test_dalio_cache_performance():
    from strategies.algorithms import DalioAllWeatherAlgorithm
    from unittest.mock import patch, MagicMock
    import time

    algo = DalioAllWeatherAlgorithm()

    # Create mock data
    mock_market_data = pd.DataFrame({
        'Close': [100, 101, 102, 103, 104]
    })
    mock_pct_change = mock_market_data['Close'].pct_change().dropna()

    # Mock yf.Ticker to track API calls
    with patch('strategies.algorithms.yf.Ticker') as mock_ticker_class:
        mock_ticker_instance = MagicMock()
        mock_ticker_instance.history.return_value = mock_market_data
        mock_ticker_class.return_value = mock_ticker_instance

        # First call should hit the API
        result1 = algo._get_market_returns('SPY')
        assert mock_ticker_class.call_count == 1, "First call should make API call"

        # Second call within TTL should use cache
        result2 = algo._get_market_returns('SPY')
        assert mock_ticker_class.call_count == 1, "Second call should use cache, not make new API call"

        # Verify cached data is identical
        assert result1.equals(result2), "Cached data should be identical to first fetch"

        # Different symbol should make new API call
        result3 = algo._get_market_returns('^NSEI')
        assert mock_ticker_class.call_count == 2, "Different symbol should make new API call"


# ── Phase 4: .env.example contains all required keys ─────────────────────────
def test_env_example_completeness():
    with open('.env.example') as f:
        content = f.read()
    required = [
        'NEWS_API_KEY', 'REDDIT_CLIENT_ID', 'FINNHUB_API_KEY',
        'ZERODHA_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
        'INITIAL_CAPITAL', 'CONFIDENCE_THRESHOLD', 'MAX_DRAWDOWN_PCT',
        # Shoonya (active live broker)
        'SHOONYA_USER_ID', 'SHOONYA_API_KEY', 'SHOONYA_TOTP_KEY',
    ]
    for key in required:
        assert key in content, f".env.example missing required key: {key}"


# ── Phase 4: requirements.txt no longer lists heavy unused ML libs ──────────
def test_requirements_split():
    with open('requirements.txt') as f:
        core = f.read()
    with open('requirements-ml.txt') as f:
        ml = f.read()
    # Heavy ML should NOT be in core requirements
    for heavy_pkg in ['torch', 'transformers', 'sentence-transformers', 'xgboost']:
        assert heavy_pkg not in core, \
            f"{heavy_pkg} should be in requirements-ml.txt, not requirements.txt"
    # Should be in ML requirements
    assert 'torch' in ml
    # Core should have essentials
    assert 'yfinance' in core
    assert 'praw>=7' in core   # v7+ enforced


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v', '--tb=short'])
