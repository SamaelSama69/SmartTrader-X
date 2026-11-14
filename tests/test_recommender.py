"""The recommender turns a price panel into a sized book."""

import pandas as pd

from recommender.data import demo_frames, sector_map
from recommender.engine import recommend, score_frame
from recommender.models import InvestorProfile


def _frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": values})


def test_rising_name_outranks_a_falling_name():
    rising = score_frame("UP.NS", _line(100, 140), "it")
    falling = score_frame("DOWN.NS", _line(140, 80), "metal")
    assert rising is not None and falling is not None
    assert rising.invest_score > falling.invest_score
    assert falling.ret_60 < 0


def test_short_history_is_skipped():
    assert score_frame("SHORT.NS", _frame([100.0] * 20), "other") is None


def test_conservative_book_holds_more_cash_than_growth():
    frames = demo_frames()
    sectors = sector_map(list(frames))
    cautious = recommend(
        frames,
        InvestorProfile(capital=500_000, risk="conservative", horizon="investment", max_names=4),
        sectors=sectors,
        regime="SIDEWAYS",
    )
    growth = recommend(
        frames,
        InvestorProfile(capital=500_000, risk="growth", horizon="both", max_names=4),
        sectors=sectors,
        regime="BULL_TREND",
    )
    assert cautious.cash_weight > growth.cash_weight


def test_buy_weights_stay_inside_the_cap_and_cash_balances():
    profile = InvestorProfile(capital=500_000, risk="balanced", horizon="both", max_names=4)
    book = recommend(demo_frames(), profile, sectors=sector_map(), regime="BULL_TREND")
    buys = [item for item in book.recommendations if item.action == "buy"]
    assert buys
    assert all(item.weight <= 0.16 + 1e-9 for item in buys)
    spent = sum(item.amount for item in buys)
    assert abs(spent + book.cash_amount - profile.capital) < 1


def test_investment_horizon_does_not_open_trades():
    book = recommend(
        demo_frames(),
        InvestorProfile(capital=200_000, risk="balanced", horizon="investment", max_names=4),
        sectors=sector_map(),
        regime="BULL_TREND",
    )
    buys = [item for item in book.recommendations if item.action == "buy"]
    assert buys
    assert all(item.sleeve == "invest" for item in buys)
    assert all(item.horizon_days == 180 for item in buys)


def test_one_name_per_sector_when_the_book_has_room_to_choose():
    frames = {
        "TCS.NS": _line(100, 150),
        "INFY.NS": _line(100, 145),
        "HDFCBANK.NS": _line(100, 130),
    }
    book = recommend(
        frames,
        InvestorProfile(capital=300_000, risk="growth", horizon="investment", max_names=2),
        sectors=sector_map(list(frames)),
        regime="BULL_TREND",
    )
    buys = [item for item in book.recommendations if item.action == "buy"]
    sectors = {item.sector for item in buys}
    assert len(buys) == 2
    assert len(sectors) == 2


def test_falling_name_is_marked_avoid():
    frames = {"TATASTEEL.NS": _line(120, 70), "ITC.NS": _line(100, 130)}
    book = recommend(
        frames,
        InvestorProfile(capital=100_000, risk="balanced", horizon="investment", max_names=1),
        sectors={"TATASTEEL.NS": "metal", "ITC.NS": "fmcg"},
        regime="SIDEWAYS",
    )
    avoided = [item for item in book.recommendations if item.action == "avoid"]
    assert any(item.ticker == "TATASTEEL.NS" and item.amount == 0 for item in avoided)


def test_a_choppy_push_lands_in_the_trading_sleeve():
    book = recommend(
        demo_frames(),
        InvestorProfile(capital=500_000, risk="balanced", horizon="both", max_names=6),
        sectors=sector_map(),
        regime="BULL_TREND",
    )
    trades = [item for item in book.recommendations if item.action == "buy" and item.sleeve == "trade"]
    assert trades
    assert all(item.horizon_days == 15 for item in trades)


def test_bear_regime_raises_cash():
    frames = demo_frames()
    bull = recommend(
        frames,
        InvestorProfile(capital=500_000, risk="balanced", horizon="both"),
        sectors=sector_map(),
        regime="BULL_TREND",
    )
    bear = recommend(
        frames,
        InvestorProfile(capital=500_000, risk="balanced", horizon="both"),
        sectors=sector_map(),
        regime="BEAR_TREND",
    )
    assert bear.cash_weight > bull.cash_weight


def _line(start: float, end: float, n: int = 80) -> pd.DataFrame:
    step = (end - start) / (n - 1)
    return _frame([start + step * i for i in range(n)])
