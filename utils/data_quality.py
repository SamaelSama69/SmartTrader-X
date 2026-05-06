"""
Data quality gates for trading signals.
Bad or stale market data should produce HOLD/no-trade, not false confidence.
"""

from datetime import datetime, timezone
from typing import Dict

import pandas as pd


REQUIRED_OHLCV = {"Open", "High", "Low", "Close", "Volume"}


def assess_ohlcv_quality(df: pd.DataFrame, min_rows: int = 60,
                         min_avg_traded_value: float = 10_000_000,
                         max_stale_days: int = 7) -> Dict:
    """Return a compact quality verdict for an OHLCV dataframe."""
    issues = []

    if df is None or df.empty:
        return {"ok": False, "issues": ["No OHLCV data"], "rows": 0}

    # Check for excessive NaN in Close before other checks
    if "Close" in df.columns:
        nan_pct = df['Close'].isna().mean()
        if nan_pct > 0.05:
            issues.append(f'Excessive NaN in Close: {nan_pct:.1%}')
            return {"ok": False, "issues": issues, "rows": len(df)}

    missing = sorted(REQUIRED_OHLCV.difference(df.columns))
    if missing:
        issues.append(f"Missing columns: {', '.join(missing)}")

    rows = len(df)
    if rows < min_rows:
        issues.append(f"Too few rows: {rows} < {min_rows}")

    if not missing:
        recent = df.tail(min(20, rows)).copy()
        avg_traded_value = float((recent["Close"] * recent["Volume"]).mean())
        if avg_traded_value < min_avg_traded_value:
            issues.append(f"Low traded value: {avg_traded_value:.0f} < {min_avg_traded_value:.0f}")

        bad_prices = (
            (df["Close"] <= 0)
            | (df["High"] < df["Low"])
            | (df["High"] < df["Close"])
            | (df["Low"] > df["Close"])
        )
        if bool(bad_prices.any()):
            issues.append("Invalid OHLC price relationship")

    last_date = None
    if getattr(df, "index", None) is not None and len(df.index) > 0:
        try:
            last_ts = pd.Timestamp(df.index[-1])
            if last_ts.tzinfo is None:
                last_ts = last_ts.tz_localize(timezone.utc)
            last_date = last_ts.date().isoformat()
            age_days = (datetime.now(timezone.utc).date() - last_ts.date()).days
            if age_days > max_stale_days:
                issues.append(f"Stale data: last bar {age_days} days old")
        except Exception:
            issues.append("Cannot parse last bar timestamp")

    return {
        "ok": not issues,
        "issues": issues,
        "rows": rows,
        "last_date": last_date,
    }
