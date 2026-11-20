"""Price panels for the recommender.

Demo frames are deterministic so the CLI and tests can run without a network.
Live frames come from Yahoo Finance using the NSE large-cap list.
"""

from __future__ import annotations

import pandas as pd

import indian_config

DEFAULT_UNIVERSE = list(indian_config.POPULAR_INDIAN_STOCKS["large_cap"])


def sector_map(tickers: list[str] | None = None) -> dict[str, str]:
    """Map a bare symbol or a .NS symbol to its configured sector."""
    lookup: dict[str, str] = {}
    for sector, names in indian_config.POPULAR_INDIAN_STOCKS["sectors"].items():
        for name in names:
            lookup[name] = sector
            lookup[f"{name}.NS"] = sector
    if tickers is None:
        return lookup
    return {ticker: lookup.get(ticker, lookup.get(_bare(ticker), "other")) for ticker in tickers}


def demo_frames() -> dict[str, pd.DataFrame]:
    """Eight synthetic names covering trend, drift, and a falling name."""
    specs = {
        "RELIANCE.NS": (100, 130, "steady"),
        "TCS.NS": (100, 125, "steady"),
        "HDFCBANK.NS": (100, 118, "steady"),
        "INFY.NS": (100, 140, "late_push"),
        "ICICIBANK.NS": (100, 122, "steady"),
        "ITC.NS": (100, 108, "steady"),
        "SBIN.NS": (100, 115, "late_push"),
        "TATASTEEL.NS": (100, 72, "steady"),
    }
    return {ticker: _path(start, end, kind) for ticker, (start, end, kind) in specs.items()}


def fetch_closes(tickers: list[str] | None = None, period: str = "6mo") -> dict[str, pd.DataFrame]:
    """Download adjusted closes. Symbols without a suffix are treated as NSE."""
    import yfinance as yf

    requested = tickers or DEFAULT_UNIVERSE
    symbols = [_nse(ticker) for ticker in requested]
    downloaded = yf.download(
        symbols,
        period=period,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    frames: dict[str, pd.DataFrame] = {}
    if downloaded is None or downloaded.empty:
        return frames
    if isinstance(downloaded.columns, pd.MultiIndex):
        for symbol in symbols:
            if symbol not in downloaded.columns.get_level_values(0):
                continue
            frame = downloaded[symbol].dropna(subset=["Close"])
            if not frame.empty:
                frames[symbol] = frame
    else:
        frame = downloaded.dropna(subset=["Close"])
        if not frame.empty and symbols:
            frames[symbols[0]] = frame
    return frames


def _path(start: float, end: float, kind: str, n: int = 80) -> pd.DataFrame:
    if kind == "late_push":
        # Quiet drift, then a choppy 20-day push. Volatility is high enough
        # that the name fits the trading sleeve better than a long hold.
        price = float(start)
        close = []
        for i in range(n):
            if i < n - 20:
                shock = 0.004 if i % 3 == 0 else -0.0005
            else:
                shock = 0.028 if i % 2 == 0 else -0.014
            price *= 1 + shock
            close.append(price)
    else:
        step = (end - start) / (n - 1)
        close = [start + step * i for i in range(n)]
    index = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"Close": close, "Volume": [1_000_000] * n}, index=index)


def as_ohlcv(close: pd.Series) -> pd.DataFrame:
    """Build a candle frame from closes so the desk can chart the sample market."""
    series = close.dropna()
    prev = series.shift(1).fillna(series.iloc[0])
    high = pd.concat([series, prev], axis=1).max(axis=1) * 1.002
    low = pd.concat([series, prev], axis=1).min(axis=1) * 0.998
    return pd.DataFrame(
        {
            "Open": prev,
            "High": high,
            "Low": low,
            "Close": series,
            "Volume": 100_000,
        },
        index=series.index,
    )


def fetch_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Download one NSE candle history. Empty when the feed returns nothing."""
    import yfinance as yf

    symbol = _nse(ticker)
    frame = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if frame is None or frame.empty or "Close" not in frame.columns:
        return pd.DataFrame()
    frame = frame.dropna(subset=["Close"])
    if hasattr(frame.index, "tz") and frame.index.tz is not None:
        frame.index = frame.index.tz_convert(None)
    columns = [name for name in ("Open", "High", "Low", "Close", "Volume") if name in frame.columns]
    return frame[columns]


def _nse(ticker: str) -> str:
    if ticker.endswith((".NS", ".BO")) or ticker.startswith("^"):
        return ticker
    return f"{ticker}.NS"


def _bare(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "")
