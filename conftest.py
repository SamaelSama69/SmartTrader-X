import os
import tempfile
from pathlib import Path


_TEST_TMP = Path(__file__).resolve().parent / ".test_tmp"
_TEST_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(_TEST_TMP))
os.environ.setdefault("TEMP", str(_TEST_TMP))
tempfile.tempdir = str(_TEST_TMP)
_orig_tempdir = tempfile.TemporaryDirectory


class _SafeTemporaryDirectory:
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ignore_cleanup_errors", True)
        self._inner = _orig_tempdir(*args, **kwargs)

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._inner.__exit__(exc_type, exc, tb)
        except PermissionError:
            return True

    def cleanup(self):
        try:
            self._inner.cleanup()
        except PermissionError:
            pass


def _safe_tempdir(*args, **kwargs):
    return _SafeTemporaryDirectory(*args, **kwargs)


tempfile.TemporaryDirectory = _safe_tempdir


def pytest_addoption(parser):
    """Register --include-costs flag for pytest."""
    parser.addoption('--include-costs', action='store_true',
                    help='Enable transaction costs for backtests')

import pandas as pd
import numpy as np
import pytest
from unittest.mock import MagicMock

def _fake_ohlcv(period="1y", *args, **kwargs):
    n = 252 if "y" in str(period) else 65
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq="B")
    c = [1000 + i + np.random.normal(0, 3) for i in range(n)]
    return pd.DataFrame({
        "Open": [x * 0.99 for x in c], "High": [x * 1.01 for x in c],
        "Low":  [x * 0.98 for x in c], "Close": c,
        "Volume": [500_000] * n,
    }, index=idx)

@pytest.fixture(autouse=True)
def no_live_api(monkeypatch):
    """Block all yfinance network calls in every test."""
    mock_t = MagicMock()
    mock_t.history.side_effect = _fake_ohlcv
    mock_t.fast_info = {"lastPrice": 1500.0}
    monkeypatch.setattr("yfinance.Ticker", lambda *a, **kw: mock_t)

    def _fake_download(tickers, period="1y", **kw):
        tlist = [tickers] if isinstance(tickers, str) else list(tickers)
        dfs = {t: _fake_ohlcv(period) for t in tlist}
        if len(tlist) == 1:
            return dfs[tlist[0]]
        return pd.concat(dfs, axis=1)

    monkeypatch.setattr("yfinance.download", _fake_download)
    yield
