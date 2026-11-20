"""Trend filters used by the live desk.

A name clears the screen only when the recent swing is larger than the
round trip and the trend filters agree. Clearing the screen is not a
promise that the next move pays.
"""

from __future__ import annotations

import pandas as pd


def review(close: pd.Series, cost_share: float) -> dict | None:
    """Read the last bar. Returns None when fewer than 60 closes are present."""
    series = close.dropna()
    if len(series) < 60:
        return None
    last = float(series.iloc[-1])
    sma_20 = float(series.rolling(20).mean().iloc[-1])
    sma_50 = float(series.rolling(50).mean().iloc[-1])
    rsi_now = float(_rsi(series).iloc[-1])
    hist = float(_macd_hist(series).iloc[-1])
    ret_20 = float(series.iloc[-1] / series.iloc[-21] - 1)

    gaps = []
    if not (last > sma_20 > sma_50):
        gaps.append("Price is not above both the 20-day and the 50-day average.")
    if not (45 <= rsi_now <= 68):
        gaps.append("RSI is outside 45 to 68.")
    if hist <= 0:
        gaps.append("The MACD histogram is not positive.")
    if ret_20 <= cost_share:
        gaps.append("The 20-day move does not cover a round trip at this ticket.")

    if gaps:
        note = " ".join(gaps)
    else:
        note = (
            "The last 20 sessions moved more than this round trip costs, "
            "and the trend filters agree. That is a screen, not a promise the next move pays."
        )
    return {
        "last": round(last, 2),
        "sma20": round(sma_20, 2),
        "sma50": round(sma_50, 2),
        "rsi": round(rsi_now, 2),
        "macd_hist": round(hist, 4),
        "ret_20": ret_20,
        "cleared": not gaps,
        "note": note,
        "sma20_series": series.rolling(20).mean(),
        "sma50_series": series.rolling(50).mean(),
        "rsi_series": _rsi(series),
        "macd_series": _macd_hist(series),
    }


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _macd_hist(close: pd.Series) -> pd.Series:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    line = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line - signal
