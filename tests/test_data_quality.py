import pandas as pd

from utils.data_quality import assess_ohlcv_quality


def test_ohlcv_quality_rejects_missing_columns():
    df = pd.DataFrame({"Close": [100, 101], "Volume": [1000, 1000]})
    quality = assess_ohlcv_quality(df, min_rows=1)
    assert not quality["ok"]
    assert any("Missing columns" in issue for issue in quality["issues"])


def test_ohlcv_quality_rejects_illiquid_data():
    idx = pd.date_range(pd.Timestamp.today().normalize(), periods=5, freq="B")
    df = pd.DataFrame({
        "Open": [100] * 5,
        "High": [101] * 5,
        "Low": [99] * 5,
        "Close": [100] * 5,
        "Volume": [10] * 5,
    }, index=idx)
    quality = assess_ohlcv_quality(df, min_rows=5, min_avg_traded_value=1_000_000)
    assert not quality["ok"]
    assert any("Low traded value" in issue for issue in quality["issues"])


def test_ohlcv_quality_accepts_liquid_recent_data():
    idx = pd.date_range(pd.Timestamp.today().normalize(), periods=5, freq="B")
    df = pd.DataFrame({
        "Open": [100] * 5,
        "High": [101] * 5,
        "Low": [99] * 5,
        "Close": [100] * 5,
        "Volume": [500_000] * 5,
    }, index=idx)
    quality = assess_ohlcv_quality(df, min_rows=5, min_avg_traded_value=1_000_000)
    assert quality["ok"]
