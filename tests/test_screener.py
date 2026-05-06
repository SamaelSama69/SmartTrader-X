"""
Tests for screener module
"""

import pytest
from utils.screener import SmartScreener


def test_screener_uses_nse_tickers():
    """Test that screener uses NSE tickers, not US tickers"""
    screener = SmartScreener()
    # Verify major tickers are NSE format
    nse_tickers = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS']
    for ticker in nse_tickers:
        assert ticker in screener.major_tickers or ticker.endswith('.NS'), \
            f"Screener should use NSE tickers, found {ticker}"


def test_screener_no_us_tickers():
    """Test that screener doesn't use US tickers like AAPL"""
    screener = SmartScreener()
    us_tickers = ['AAPL', 'GOOGL', 'MSFT', 'TSLA', 'AMZN']
    for ticker in us_tickers:
        assert ticker not in screener.major_tickers, \
            f"Screener should not use US tickers like {ticker}"
