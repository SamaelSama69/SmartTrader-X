"""
Regression tests for current NSE derivative rules and regime routing.
These avoid live network calls.
"""

from indian_config import (
    WEEKLY_EXPIRY_DAYS,
    get_index_derivative_spec,
    get_lot_size,
    is_weekly_index_options_enabled,
)
from utils.market_regime import IndianMarketRegime
from utils.options_pricer import simulate_options_write


def test_only_nifty_weekly_index_options_enabled():
    assert WEEKLY_EXPIRY_DAYS == {"NIFTY": 3}
    assert is_weekly_index_options_enabled("NIFTY")
    assert not is_weekly_index_options_enabled("BANKNIFTY")
    assert not is_weekly_index_options_enabled("FINNIFTY")
    assert not is_weekly_index_options_enabled("MIDCPNIFTY")


def test_index_lot_sizes_are_current_contract_specs():
    assert get_lot_size("NIFTY") == 65
    assert get_lot_size("BANKNIFTY") == 30
    assert get_lot_size("FINNIFTY") == 60
    assert get_lot_size("MIDCPNIFTY") == 120
    assert get_index_derivative_spec("BANKNIFTY")["last_weekly_expiry"] == "2024-11-13"


def test_regime_preferred_strategies_are_implemented_router_ids():
    # Get actual algorithm keys from AlgorithmSelector (excluding None values)
    from strategies.algorithms import AlgorithmSelector
    sel = AlgorithmSelector(market='IN')
    router_ids = {name for name, algo in sel.algorithms.items() if algo is not None}

    detector = IndianMarketRegime()
    for regime in [
        "BULL_TREND", "BULL_VOLATILE", "BEAR_TREND", "BEAR_VOLATILE",
        "SIDEWAYS_LOW_VOL", "SIDEWAYS_HIGH_VOL", "CRISIS",
    ]:
        preferred = detector.get_preferred_strategies(regime)
        assert preferred
        assert set(preferred).issubset(router_ids), \
            f"Preferred strategies {preferred} for {regime} contain unknown IDs not in {router_ids}"


def test_options_write_scales_premium_by_lot_size():
    one_lot = simulate_options_write(spot_price=22000, india_vix=14, lot_size=1)
    nifty_lot = simulate_options_write(spot_price=22000, india_vix=14, lot_size=65)
    assert nifty_lot["lot_size"] == 65
    assert nifty_lot["total_premium"] > one_lot["total_premium"] * 60
    assert nifty_lot["call_breakeven"] > nifty_lot["call_strike"]
    assert nifty_lot["put_breakeven"] < nifty_lot["put_strike"]
