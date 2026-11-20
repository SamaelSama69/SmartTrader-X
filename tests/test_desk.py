"""Charts, fund fees, and the local holdings book."""

from pathlib import Path

import pandas as pd

from recommender.funds import fee_hurdle, fund_exit
from recommender.indicators import review
from recommender.ledger import Holding, load_book, sample_book, save_book


def _wavy_rise() -> pd.Series:
    price = 100.0
    closes = []
    for i in range(90):
        if i >= 88:
            price *= 1.004
        elif i % 3 == 2:
            price *= 0.994
        else:
            price *= 1.005
        closes.append(price)
    return pd.Series(closes)


def test_a_wavy_rise_clears_a_small_round_trip():
    row = review(_wavy_rise(), cost_share=0.002)
    assert row is not None
    assert row["cleared"] is True
    assert "not a promise" in row["note"]


def test_a_fall_does_not_clear():
    falling = pd.Series([140 - i * 0.5 for i in range(80)])
    row = review(falling, cost_share=0.002)
    assert row is not None
    assert row["cleared"] is False


def test_a_round_trip_larger_than_the_swing_blocks_the_screen():
    row = review(_wavy_rise(), cost_share=0.50)
    assert row is not None
    assert row["cleared"] is False
    assert "does not cover" in row["note"]


def test_a_straight_rise_still_reviews():
    row = review(pd.Series([100 + i * 0.2 for i in range(80)]), cost_share=0.01)
    assert row is not None
    assert row["rsi"] == 100
    assert row["cleared"] is False
    assert review(pd.Series([100.0] * 20), cost_share=0.01) is None


def test_early_exit_costs_more_than_holding_through_the_load_window():
    early = fee_hurdle("122639", early_exit=True)
    held = fee_hurdle("122639", early_exit=False)
    assert early["rise_to_clear_fees"] > held["rise_to_clear_fees"]
    assert early["min_sip"] == 1000
    assert fund_exit("122639", 10_000, early_exit=True) == 100
    assert fund_exit("120716", 10_000, early_exit=True) == 0


def test_book_round_trips_through_a_file(tmp_path: Path):
    path = tmp_path / "holdings.json"
    save_book(path, sample_book())
    loaded = load_book(path)
    assert len(loaded) == 4
    assert loaded[0].symbol == "RELIANCE.NS"
    equity = Holding("Primary", "zerodha", "equity", "INFY", "Infosys", 5, 1500)
    assert equity.invested() == 7500
    assert equity.unrealized(1600) == 500
