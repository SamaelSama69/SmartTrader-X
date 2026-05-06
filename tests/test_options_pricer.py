"""
Tests for options pricer module
"""

import pytest
from utils.options_pricer import black_scholes_premium, simulate_options_write


def test_black_scholes_call_atm():
    """Test Black-Scholes call option pricing for ATM option."""
    # Known: ATM call with 30-day expiry, 20% vol ≈ 2.3% of spot
    prem = black_scholes_premium(S=100, K=100, T=30/365, r=0.065, sigma=0.20)
    assert 1.5 < prem < 4.0, f"Unreasonable premium: {prem:.2f}"


def test_black_scholes_put_atm():
    """Test Black-Scholes put option pricing for ATM option."""
    # Put-call parity: put ≈ call + K*exp(-rT) - S
    prem = black_scholes_premium(S=100, K=100, T=30/365, r=0.065, sigma=0.20, option_type='put')
    assert 1.0 < prem < 4.0, f"Unreasonable premium: {prem:.2f}"


def test_black_scholes_otm_call():
    """Test Black-Scholes for OTM call option."""
    # OTM call should have lower premium
    prem = black_scholes_premium(S=100, K=110, T=30/365, r=0.065, sigma=0.20)
    assert 0.0 < prem < 1.0, f"OTM call premium too high: {prem:.2f}"


def test_black_scholes_itm_call():
    """Test Black-Scholes for ITM call option."""
    # ITM call should have higher premium
    prem = black_scholes_premium(S=100, K=90, T=30/365, r=0.065, sigma=0.20)
    assert 10.0 < prem < 15.0, f"ITM call premium too low: {prem:.2f}"


def test_black_scholes_zero_time():
    """Test Black-Scholes with zero time to expiry."""
    # At expiry, option value = intrinsic value
    prem = black_scholes_premium(S=100, K=95, T=0, r=0.065, sigma=0.20)
    assert abs(prem - 5.0) < 0.01, f"Expected 5.0, got {prem:.2f}"


def test_simulate_options_write():
    """Test options write simulation."""
    result = simulate_options_write(spot_price=100, india_vix=14.0, days_to_expiry=1)

    # Check all required keys
    required_keys = ['call_premium', 'put_premium', 'total_premium',
                    'call_strike', 'put_strike', 'max_profit',
                    'call_breakeven', 'put_breakeven']
    for key in required_keys:
        assert key in result, f"Missing key: {key}"

    # Check strike levels
    assert result['call_strike'] > 100, "Call strike should be OTM"
    assert result['put_strike'] < 100, "Put strike should be OTM"

    # Check premium is positive
    assert result['total_premium'] >= 0, "Total premium should be non-negative"

    # Check max profit equals total premium
    assert result['max_profit'] == result['total_premium'], "Max profit should equal total premium"


def test_simulate_options_write_high_vix():
    """Test options write with high volatility."""
    result = simulate_options_write(spot_price=100, india_vix=25.0, days_to_expiry=1)

    # Higher VIX should result in higher premium than low VIX
    low_vix_result = simulate_options_write(spot_price=100, india_vix=14.0, days_to_expiry=1)
    assert result['total_premium'] > low_vix_result['total_premium'], \
        f"High VIX should give higher premium: {result['total_premium']} vs {low_vix_result['total_premium']}"


def test_simulate_options_write_longer_expiry():
    """Test options write with longer time to expiry."""
    result = simulate_options_write(spot_price=100, india_vix=14.0, days_to_expiry=7)

    # Longer expiry should result in higher premium
    assert result['total_premium'] > 0.1, f"Premium too low for 7-day expiry: {result['total_premium']}"
