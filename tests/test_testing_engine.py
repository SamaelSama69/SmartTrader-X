"""Tests for TestingEngine and StrategyGatekeeper."""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from utils.testing_engine import TestingEngine, VALIDATION_THRESHOLDS
from utils.strategy_gatekeeper import StrategyGatekeeper


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def engine(tmp_path, monkeypatch):
    """TestingEngine with results file redirected to tmp dir."""
    monkeypatch.setattr("utils.testing_engine.RESULTS_PATH", tmp_path / "test_results.json")
    return TestingEngine(initial_capital=100_000)


@pytest.fixture
def gatekeeper(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", tmp_path / "test_results.json")
    return StrategyGatekeeper()


# ─── TestingEngine: persistence ────────────────────────────────────────────

def test_store_and_retrieve(engine):
    engine._store("single", "test_strat", "TCS.NS", {"return_pct": 25.0, "verdict": {"pass": True}})
    cached = engine.get_cached("single", "test_strat", "TCS.NS")
    assert cached is not None
    assert cached["return_pct"] == 25.0


def test_cache_miss_returns_none(engine):
    assert engine.get_cached("single", "nonexistent", "XYZ.NS") is None


def test_list_results_sorted(engine):
    engine._store("single", "strat_a", "TCS.NS", {"return_pct": 10})
    engine._store("walk_forward", "strat_b", "INFY.NS", {"return_pct": 20})
    results = engine.list_results()
    assert len(results) == 2
    # Most recently stored should be first
    assert results[0]["_strategy"] == "strat_b"


# ─── TestingEngine: verdict logic ──────────────────────────────────────────

def test_verdict_all_pass(engine):
    result = {
        "sharpe_ratio": 1.5,
        "win_rate": 0.60,
        "max_drawdown_pct": -15.0,
        "return_pct": 25.0,
    }
    verdict = engine._verdict(result)
    assert verdict["pass"] is True
    assert verdict["score"] == "4/4"


def test_verdict_low_sharpe_fails(engine):
    result = {
        "sharpe_ratio": 0.3,     # below 0.8 threshold
        "win_rate": 0.60,
        "max_drawdown_pct": -15.0,
        "return_pct": 25.0,
    }
    verdict = engine._verdict(result)
    assert verdict["checks"]["Sharpe ≥ 0.8"] is False


def test_verdict_bad_drawdown_fails(engine):
    result = {
        "sharpe_ratio": 1.2,
        "win_rate": 0.60,
        "max_drawdown_pct": -45.0,   # below -30% threshold
        "return_pct": 25.0,
    }
    verdict = engine._verdict(result)
    assert verdict["checks"]["Drawdown > -30%"] is False


def test_verdict_needs_3_of_4_to_pass(engine):
    """Pass if 3/4 checks pass — borderline case."""
    result = {
        "sharpe_ratio": 0.5,    # FAIL
        "win_rate": 0.60,
        "max_drawdown_pct": -15.0,
        "return_pct": 25.0,
    }
    verdict = engine._verdict(result)
    # 3 pass: win_rate, drawdown, return — should still pass overall
    assert verdict["pass"] is True
    assert verdict["score"] == "3/4"


# ─── TestingEngine: Monte Carlo ─────────────────────────────────────────────

def test_monte_carlo_requires_base_backtest(engine):
    """Monte Carlo errors gracefully when no base backtest exists."""
    # Patch run_single_backtest to return no trades
    engine.run_single_backtest = MagicMock(return_value={"trades": []})
    result = engine.run_monte_carlo("indian_momentum", "TCS.NS", days=365)
    assert "error" in result


def test_monte_carlo_distribution_shape(engine):
    """Monte Carlo returns correct percentile keys."""
    # Inject a fake base result with trades
    fake_trades = [{"profit_pct": 5.0}, {"profit_pct": -2.0}, {"profit_pct": 8.0},
                   {"profit_pct": -3.0}, {"profit_pct": 12.0}, {"profit_pct": -1.0}]
    engine.run_single_backtest = MagicMock(return_value={
        "trades": fake_trades,
        "_cached_at": "2099-01-01T00:00:00",
    })
    result = engine.run_monte_carlo("indian_momentum", "TCS.NS", n_simulations=200, force=True)
    assert "error" not in result
    assert "p5_return_pct"  in result
    assert "p95_return_pct" in result
    assert result["p5_return_pct"] <= result["median_return_pct"] <= result["p95_return_pct"]
    assert 0 <= result["pct_profitable"] <= 100


# ─── StrategyGatekeeper ─────────────────────────────────────────────────────

def test_gatekeeper_allows_when_no_data(gatekeeper):
    allowed, reason = gatekeeper.allow_trade("indian_momentum", "TCS.NS")
    assert allowed is True
    assert "No backtest data" in reason


def test_gatekeeper_blocks_failing_strategy(tmp_path, monkeypatch):
    """Gatekeeper blocks when verdict.pass is False."""
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        "single::indian_momentum::TCS.NS": {
            "_test_type": "single",
            "_strategy": "indian_momentum",
            "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "verdict": {"pass": False, "score": "1/4", "reason": "Sharpe ≥ 0.8"},
        }
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    allowed, reason = gk.allow_trade("indian_momentum", "TCS.NS")
    assert allowed is False
    assert "failed validation" in reason


def test_gatekeeper_allows_passing_strategy(tmp_path, monkeypatch):
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        "walk_forward::indian_momentum::TCS.NS": {
            "_test_type": "walk_forward",
            "_strategy": "indian_momentum",
            "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "verdict": {"pass": True, "score": "4/4", "reason": "All checks passed"},
        }
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    allowed, reason = gk.allow_trade("indian_momentum", "TCS.NS")
    assert allowed is True


def test_gatekeeper_skips_stale_results(tmp_path, monkeypatch):
    """Results older than STALE_AFTER_DAYS are ignored (treated as no data)."""
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        "single::indian_momentum::TCS.NS": {
            "_test_type": "single",
            "_strategy": "indian_momentum",
            "_ticker": "TCS.NS",
            "_cached_at": "2020-01-01T00:00:00",   # Very old
            "verdict": {"pass": False, "score": "0/4", "reason": "All failed"},
        }
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    # Stale result should be ignored → allow with "no data" message
    allowed, reason = gk.allow_trade("indian_momentum", "TCS.NS")
    assert allowed is True


def test_gatekeeper_walk_forward_prioritised_over_single(tmp_path, monkeypatch):
    """Walk-forward result takes priority over single backtest."""
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        # Single says FAIL
        "single::indian_momentum::TCS.NS": {
            "_test_type": "single", "_strategy": "indian_momentum", "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "verdict": {"pass": False, "score": "1/4", "reason": "Low sharpe"},
        },
        # Walk-forward says PASS — should take priority
        "walk_forward::indian_momentum::TCS.NS": {
            "_test_type": "walk_forward", "_strategy": "indian_momentum", "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "verdict": {"pass": True, "score": "4/4", "reason": "All checks passed"},
        },
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    allowed, reason = gk.allow_trade("indian_momentum", "TCS.NS")
    assert allowed is True   # walk_forward wins


def test_get_best_validated_strategy(tmp_path, monkeypatch):
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        "single::momentum_breakout::TCS.NS": {
            "_test_type": "single", "_strategy": "momentum_breakout", "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "sharpe_ratio": 1.2,
            "verdict": {"pass": True},
        },
        "single::indian_momentum::TCS.NS": {
            "_test_type": "single", "_strategy": "indian_momentum", "_ticker": "TCS.NS",
            "_cached_at": "2099-01-01T00:00:00",
            "sharpe_ratio": 0.9,
            "verdict": {"pass": True},
        },
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    best = gk.get_best_validated_strategy("TCS.NS")
    assert best == "momentum_breakout"   # higher Sharpe wins


def test_gatekeeper_summary(tmp_path, monkeypatch):
    import json
    results_path = tmp_path / "test_results.json"
    results_path.write_text(json.dumps({
        "single::a::TCS.NS": {"_cached_at": "2099-01-01T00:00:00", "verdict": {"pass": True}},
        "single::b::TCS.NS": {"_cached_at": "2099-01-01T00:00:00", "verdict": {"pass": False}},
        "single::c::TCS.NS": {"_cached_at": "2099-01-01T00:00:00", "verdict": {"pass": True}},
    }))
    monkeypatch.setattr("utils.strategy_gatekeeper.RESULTS_PATH", results_path)
    gk = StrategyGatekeeper()
    summary = gk.summary()
    assert summary["total_tests"] == 3
    assert summary["passed"] == 2
    assert summary["failed"] == 1
    assert summary["pass_rate"] == pytest.approx(66.7, abs=0.1)
