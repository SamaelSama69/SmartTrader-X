import tempfile
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
    """Verify that recent losses reduce the decayed weight below 1.0."""
    with tempfile.TemporaryDirectory() as tmp:
        with patch('config.MEMORY_DIR', Path(tmp)):
            from utils.performance_tracker import StrategyPerformanceTracker
            from utils.database import Database

            tracker = StrategyPerformanceTracker()
            now = datetime.now()

            # Insert historical data directly into the SQLite backend
            # Old wins (180, 150, 120 days ago) — should decay heavily
            test_data = [
                ("MomentumBreakout", "BUY", 8.0, "WIN", (now - timedelta(days=180)).isoformat()),
                ("MomentumBreakout", "BUY", 6.0, "WIN", (now - timedelta(days=150)).isoformat()),
                ("MomentumBreakout", "BUY", 5.0, "WIN", (now - timedelta(days=120)).isoformat()),
                # Recent losses (2, 1 days ago) — high decay weight
                ("MomentumBreakout", "BUY", -4.0, "LOSS", (now - timedelta(days=2)).isoformat()),
                ("MomentumBreakout", "BUY", -3.0, "LOSS", (now - timedelta(days=1)).isoformat()),
            ]
            for algo, signal, pnl, outcome, ts in test_data:
                tracker.db.record_strategy_trade(algo, signal, pnl, outcome)
                # Overwrite timestamp to our desired value
                conn = tracker.db._get_connection()
                conn.execute(
                    "UPDATE strategy_performance SET timestamp = ? "
                    "WHERE algorithm = ? AND pnl_pct = ? AND timestamp != ?",
                    (ts, algo, pnl, ts)
                )
                conn.commit()
                conn.close()

            weights = tracker.get_decayed_algorithm_weights(half_life_days=30, min_closed=5)
            assert weights["MomentumBreakout"] < 1.0, \
                f"Recent losses should push weight below 1.0, got {weights['MomentumBreakout']}"
