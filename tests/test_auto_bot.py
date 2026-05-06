"""
Tests for auto_bot.py — AutonomousBot core logic.
All external I/O is mocked. No real API calls are made.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from datetime import datetime, time as dtime


# ── is_market_open ─────────────────────────────────────────────────────────

def test_market_open_during_trading_hours():
    """Market is open on a weekday between 9:15 and 15:30 IST."""
    from auto_bot import AutonomousBot
    with patch.object(AutonomousBot, '__init__', lambda s, *a, **k: None):
        bot = AutonomousBot.__new__(AutonomousBot)
        
        # Test logic directly by patching datetime
        with patch('auto_bot.datetime') as mock_dt:
            # Monday 10:30 AM
            mock_now = datetime(2024, 6, 3, 10, 30)
            mock_dt.now.return_value = mock_now
            # Ensure the mocked class can still do replace() and produce real datetimes
            mock_dt.side_effect = datetime
            
            assert bot.is_market_open()


def test_market_closed_on_weekend():
    """Market is closed on Saturday and Sunday."""
    from auto_bot import AutonomousBot
    with patch.object(AutonomousBot, '__init__', lambda s, *a, **k: None):
        bot = AutonomousBot.__new__(AutonomousBot)
        with patch('auto_bot.datetime') as mock_dt:
            # Saturday June 1st, 2024
            mock_now = datetime(2024, 6, 1, 11, 0)
            mock_dt.now.return_value = mock_now
            assert not bot.is_market_open()


# ── manage_open_positions ──────────────────────────────────────────────────

def test_manage_positions_closes_on_stop_loss():
    """Positions that hit stop-loss must be closed."""
    from auto_bot import AutonomousBot
    with patch.object(AutonomousBot, '__init__', lambda s, *a, **k: None):
        bot = AutonomousBot.__new__(AutonomousBot)
        bot.mode = 'paper'
        bot.paper_mgr = MagicMock()
        bot.risk_mgr = MagicMock()
        bot.notifier = MagicMock()
        bot.shoonya = None

        # Simulate an open position
        bot.paper_mgr.get_open_positions.return_value = [{
            'id': 'trade-001',
            'ticker': 'RELIANCE.NS',
            'entry_price': 2800.0,
            'stop_loss': 2750.0,
            'target': 2900.0,
            'signal': 'BUY',
            'shares': 5,
        }]

        with patch('auto_bot.yf.Ticker') as mock_ticker:
            # A proper implementation calls paper_mgr.close_positions()
            bot.manage_open_positions()
            bot.paper_mgr.close_positions.assert_called_once()


# ── find_and_execute_trades ────────────────────────────────────────────────

def test_find_trades_respects_risk_block():
    """If RiskManager blocks a trade, it must not be placed."""
    from auto_bot import AutonomousBot
    with patch.object(AutonomousBot, '__init__', lambda s, *a, **k: None):
        bot = AutonomousBot.__new__(AutonomousBot)
        bot.mode = 'paper'
        bot.paper_mgr = MagicMock()
        bot.risk_mgr = MagicMock()
        bot.risk_mgr.check_trade.return_value = {'allowed': False, 'reason': 'max drawdown reached'}
        bot.compliance = MagicMock()
        bot.compliance.validate_order.return_value = (True, "Valid")
        bot.notifier = MagicMock()
        bot.momentum_strategy = MagicMock()
        bot.momentum_strategy.analyze_ticker.return_value = {
            'signal': 'BUY', 'confidence': 0.80, 'current_price': 500.0,
            'stop_loss': 480.0, 'price_target': 540.0, 'factors': {}
        }
        bot.risk_mgr.size_position_kelly.return_value = 10
        bot._fetch_data = MagicMock(return_value=MagicMock(empty=False))
        bot.regime_detector = MagicMock()
        bot.regime_detector.get_regime.return_value = "BULL_TREND"
        bot.regime_detector.get_risk_multiplier.return_value = 1.0
        
        # Initialize attributes that run_continuous_scan expects
        bot.last_full_rotation = datetime.now()
        bot.sector_queue = ["FMCG"]
        bot.sector_rotation = MagicMock()
        bot.sector_rotation.SECTOR_TICKERS = {"FMCG": ["ITC.NS"]}
        bot.news_aggregator = MagicMock()
        bot.sentiment_db = MagicMock()
        bot.signal_buffer_path = MagicMock()
        bot.global_signal_buffer = []
        bot._save_signal_buffer = MagicMock()
        bot._save_scan_results = MagicMock()
        bot.is_market_open = MagicMock(return_value=True)

        with patch('auto_bot.yf.download') as mock_download:
            # Mock yf.download return for one stock
            mock_df = pd.DataFrame({'Close': [100.0]*100, 'High': [101.0]*100, 'Low': [99.0]*100, 'Volume': [1000]*100})
            # Handle multi-index columns if needed, but for simplicity let's return a single-index df
            mock_download.return_value = mock_df

            # Simulate the loop logic
            bot.run_continuous_scan()

        # Trade must NOT be placed when risk manager blocks it
        bot.paper_mgr.open_trade.assert_not_called()
