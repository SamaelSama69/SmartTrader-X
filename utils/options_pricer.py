"""
Black-Scholes options premium calculator.
Used by NiftyOptionsWriter to simulate real premium collection,
NOT naked short-selling of the underlying stock.
"""
import numpy as np
from scipy.stats import norm


def black_scholes_premium(S: float, K: float, T: float,
                           r: float, sigma: float,
                           option_type: str = 'call') -> float:
    """
    S     = spot price
    K     = strike price
    T     = time to expiry in years (days/365)
    r     = risk-free rate (use 0.065 for India)
    sigma = implied volatility (India VIX / 100)
    """
    if T <= 0 or sigma <= 0:
        return max(0.0, S - K) if option_type == 'call' else max(0.0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == 'call':
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def simulate_options_write(spot_price: float, india_vix: float,
                            days_to_expiry: int = 1,
                            lot_size: int = 1) -> dict:
    """
    Simulate a short strangle (sell OTM call + sell OTM put).
    Returns premium collected and strike levels.
    india_vix: current India VIX value (e.g. 14.5)
    """
    sigma = india_vix / 100
    T = days_to_expiry / 365
    call_strike = spot_price * 1.015   # 1.5% OTM call
    put_strike  = spot_price * 0.985   # 1.5% OTM put
    lot_size = max(int(lot_size or 1), 1)
    call_prem = black_scholes_premium(spot_price, call_strike, T, 0.065, sigma, 'call')
    put_prem  = black_scholes_premium(spot_price, put_strike,  T, 0.065, sigma, 'put')
    point_premium = call_prem + put_prem
    total_premium = point_premium * lot_size
    return {
        'call_premium': round(call_prem, 2),
        'put_premium':  round(put_prem, 2),
        'point_premium': round(point_premium, 2),
        'lot_size': lot_size,
        'total_premium': round(total_premium, 2),
        'call_strike':  round(call_strike, 2),
        'put_strike':   round(put_strike, 2),
        'max_profit':   round(total_premium, 2),
        'call_breakeven': round(call_strike + point_premium, 2),
        'put_breakeven':  round(put_strike  - point_premium, 2),
    }
