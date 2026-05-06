from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils.walk_forward import WalkForwardConfig, WalkForwardValidator


class AlwaysBuyAlgorithm:
    name = "AlwaysBuy"

    def analyze(self, ticker, hist):
        return {"signal": "BUY", "confidence": 0.8}


def _sample_ohlcv(rows=320):
    idx = pd.date_range("2024-01-01", periods=rows, freq="B")
    close = [100 + i * 0.1 for i in range(rows)]
    return pd.DataFrame({
        "Open": close,
        "High": [c + 1 for c in close],
        "Low": [c - 1 for c in close],
        "Close": close,
        "Volume": [250_000] * rows,
    }, index=idx)


def test_walk_forward_validator_creates_out_of_sample_folds():
    validator = WalkForwardValidator(WalkForwardConfig(train_bars=180, test_bars=60))
    result = validator.evaluate_algorithm(AlwaysBuyAlgorithm(), "RELIANCE.NS", _sample_ohlcv())

    assert "error" not in result
    assert result["summary"]["fold_count"] == 2
    assert result["folds"][0]["train_end"] < result["folds"][0]["test_start"]
    assert result["summary"]["profitable_fold_rate"] >= 0.5


def test_decayed_weights_penalize_recent_underperformance():
    with patch("utils.performance_tracker.PERF_FILE", Path("memory/test_perf_decay.json")):
        from utils.performance_tracker import StrategyPerformanceTracker

        tracker = StrategyPerformanceTracker()
        now = datetime.now()
        tracker.data["MomentumBreakout"] = {
            "signals": [
                {"outcome": "WIN", "pnl_pct": 8, "closed_at": (now - timedelta(days=180)).isoformat()},
                {"outcome": "WIN", "pnl_pct": 6, "closed_at": (now - timedelta(days=150)).isoformat()},
                {"outcome": "WIN", "pnl_pct": 5, "closed_at": (now - timedelta(days=120)).isoformat()},
                {"outcome": "LOSS", "pnl_pct": -4, "closed_at": (now - timedelta(days=2)).isoformat()},
                {"outcome": "LOSS", "pnl_pct": -3, "closed_at": (now - timedelta(days=1)).isoformat()},
            ],
            "stats": {},
        }

        weights = tracker.get_decayed_algorithm_weights(half_life_days=30, min_closed=5)
        assert weights["MomentumBreakout"] < 1.0
