"""Backtester accounting tests that do not require market data downloads."""

from utils.backtester import Backtester


def test_compute_metrics_counts_only_closed_trades_for_win_rate():
    bt = Backtester(initial_capital=100_000)
    metrics = bt._compute_metrics(
        capital_curve=[100_000, 101_000, 100_500, 102_000],
        trades=[
            {"type": "BUY", "profit": 0},
            {"type": "SELL", "profit": 1000},
            {"type": "BUY", "profit": 0},
            {"type": "SELL", "profit": -500},
        ],
    )
    assert metrics["win_rate"] == 0.5
    assert metrics["total_trades"] == 4


def test_backtester_costs_enabled_by_default():
    bt = Backtester(initial_capital=100_000)
    assert bt.include_costs is True
    assert bt._calculate_transaction_costs(100_000, trade_type="delivery") > 0
