"""Tests for earnings season detection and position size reduction."""
import pytest
from datetime import datetime
from indian_config import is_earnings_season


class TestEarningsSeason:
    """Verify is_earnings_season() returns correct values."""

    @pytest.mark.parametrize("month,day,expected", [
        (1, 15, True),   # January = earnings
        (4, 1, True),    # April = earnings
        (7, 20, True),   # July = earnings
        (10, 31, True),  # October = earnings
        (2, 5, True),    # Feb 5 = tail end of earnings (first week)
        (5, 7, True),    # May 7 = last day of tail
        (2, 8, False),   # Feb 8 = past first week
        (3, 15, False),  # March = not earnings
        (6, 1, False),   # June = not earnings
        (9, 10, False),  # September = not earnings
        (12, 25, False), # December = not earnings
    ])
    def test_earnings_month_detection(self, month, day, expected):
        test_date = datetime(2025, month, day)
        assert is_earnings_season(test_date) == expected, \
            f"is_earnings_season({month}/{day}) should be {expected}"

    def test_boundary_feb_7_is_earnings(self):
        """Feb 7 is the last day of the earnings tail."""
        assert is_earnings_season(datetime(2025, 2, 7)) is True

    def test_boundary_feb_8_is_not_earnings(self):
        """Feb 8 is past the earnings tail."""
        assert is_earnings_season(datetime(2025, 2, 8)) is False

    def test_default_uses_current_date(self):
        """Calling with no argument should not crash."""
        result = is_earnings_season()
        assert isinstance(result, bool)
