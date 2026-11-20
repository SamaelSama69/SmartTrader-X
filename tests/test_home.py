"""Session clock, watch alerts, book concentration, and the extra bands."""

from datetime import datetime

import pandas as pd

from recommender.indicators import atr, bollinger
from recommender.market_clock import session
from recommender.performance import summarize
from recommender.watch import Watch, load_watch, save_watch


def test_regular_session_is_open_and_a_holiday_is_not():
    wednesday = datetime(2026, 11, 18, 10, 0)
    assert session(wednesday)["state"] == "open"
    assert session(datetime(2026, 11, 21, 10, 0))["state"] == "closed"
    assert session(datetime(2026, 10, 2, 10, 0))["state"] == "holiday"
    assert session(datetime(2026, 11, 18, 16, 0))["state"] == "closed"


def test_an_alert_fires_only_outside_the_band():
    row = Watch("RELIANCE", above=1500, below=1200)
    assert row.symbol == "RELIANCE.NS"
    assert row.status(1400) == "inside"
    assert row.status(1500) == "above"
    assert row.status(1100) == "below"


def test_watchlist_round_trips(tmp_path):
    path = tmp_path / "watch.json"
    save_watch(path, [Watch("TCS", above=4000)])
    loaded = load_watch(path)
    assert loaded[0].symbol == "TCS.NS"
    assert loaded[0].above == 4000


def test_one_name_dominates_the_book():
    report = summarize(
        [
            {"name": "Reliance", "platform": "zerodha", "kind": "equity", "invested": 800, "value": 900},
            {"name": "UTI Nifty", "platform": "groww", "kind": "fund", "invested": 200, "value": 100},
        ]
    )
    assert report["value"] == 1000
    assert report["pnl"] == 0
    assert report["top_name"] == "Reliance"
    assert report["top_weight"] == 0.9
    assert report["by_kind"]["equity"] == 0.9


def test_bands_wrap_the_average_and_range_is_positive():
    close = pd.Series([100 + (i % 5) for i in range(40)], dtype=float)
    bands = bollinger(close)
    last = bands.dropna().iloc[-1]
    assert last["upper"] > last["middle"] > last["lower"]
    frame = pd.DataFrame({"High": close + 1, "Low": close - 1, "Close": close})
    assert float(atr(frame).dropna().iloc[-1]) > 0
