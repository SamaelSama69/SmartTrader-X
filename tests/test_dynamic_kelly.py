"""Tests for Dynamic Kelly sizing and NSE holiday awareness."""
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from utils.risk_manager import RiskManager
from indian_config import get_nse_holidays


class TestDynamicKelly:
    """Verify size_position_dynamic uses real stats when available."""

    def test_dynamic_with_real_stats(self):
        """Dynamic sizing with strong win rate should return reasonable shares."""
        rm = RiskManager(initial_capital=500_000)
        stats = {'win_rate': 0.65, 'avg_return': 0.08, 'avg_loss': 0.04}
        shares = rm.size_position_dynamic(price=1000.0, confidence=0.7, perf_stats=stats)
        assert shares > 0, "Should size a position with strong stats"

    def test_dynamic_with_poor_stats(self):
        """Dynamic sizing with bad win rate should produce smaller positions."""
        rm = RiskManager(initial_capital=500_000)
        good = {'win_rate': 0.65, 'avg_return': 0.08, 'avg_loss': 0.04}
        bad = {'win_rate': 0.35, 'avg_return': 0.03, 'avg_loss': 0.07}
        shares_good = rm.size_position_dynamic(price=1000.0, confidence=0.7, perf_stats=good)
        shares_bad = rm.size_position_dynamic(price=1000.0, confidence=0.7, perf_stats=bad)
        # Bad stats should produce fewer or equal shares
        assert shares_bad <= shares_good, \
            f"Bad stats ({shares_bad}) should produce <= shares than good stats ({shares_good})"

    def test_dynamic_without_stats_uses_defaults(self):
        """With no perf_stats, should use default values and still work."""
        rm = RiskManager(initial_capital=500_000)
        shares = rm.size_position_dynamic(price=1000.0, confidence=0.7, perf_stats=None)
        assert shares >= 0, "Should handle None stats gracefully"

    def test_dynamic_zero_price_returns_zero(self):
        rm = RiskManager(initial_capital=500_000)
        assert rm.size_position_dynamic(price=0, confidence=0.7) == 0


class TestNSEHolidays:
    """Verify NSE holiday calendar works correctly."""

    def test_republic_day_is_holiday(self):
        """Jan 26 should be in the holiday list for 2025 and 2026."""
        assert '2025-01-26' in get_nse_holidays(2025)
        assert '2026-01-26' in get_nse_holidays(2026)

    def test_independence_day_is_holiday(self):
        assert '2025-08-15' in get_nse_holidays(2025)

    def test_unknown_year_returns_empty(self):
        """Years not in the calendar should return empty list."""
        assert get_nse_holidays(2030) == []

    def test_christmas_is_holiday(self):
        assert '2025-12-25' in get_nse_holidays(2025)


class TestBotMarketOpenWithHolidays:
    """Verify the bot respects NSE holidays."""

    def test_holiday_blocks_trading(self):
        """Bot should report market as closed on Republic Day."""
        from auto_bot import AutonomousBot
        with patch.object(AutonomousBot, '__init__', lambda self, **kw: None):
            bot = AutonomousBot.__new__(AutonomousBot)
            # Mock a Tuesday Republic Day at 10 AM (market hours)
            fake_now = datetime(2025, 1, 26, 10, 0)  # Sunday in 2025 actually, use 2026
            fake_now = datetime(2026, 1, 26, 10, 0)  # Monday in 2026
            with patch('auto_bot.datetime') as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                result = bot.is_market_open()
                assert result is False, "Market should be closed on Republic Day"
