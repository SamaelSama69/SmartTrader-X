"""
TestingEngine — Unified interface for all backtest and validation methods.
Used by both the dashboard Testing Lab and StrategyGatekeeper.
Results are cached to memory/test_results.json so the autobot can read them.
"""
import json
import logging
import time
import shutil
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from strategies.algorithms import AlgorithmSelector
from utils.backtester import Backtester
from utils.walk_forward import WalkForwardValidator, WalkForwardConfig
from utils.portfolio_backtester import PortfolioBacktester
from config import BACKTEST_INITIAL_CAPITAL

logger = logging.getLogger(__name__)

RESULTS_PATH = Path("memory/test_results.json")
RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

# Thresholds for a strategy to be considered "validated"
VALIDATION_THRESHOLDS = {
    "min_sharpe":              0.8,
    "min_win_rate":            0.52,
    "max_drawdown_pct":       -30.0,   # e.g. -30 means max allowed drawdown is -30%
    "min_profitable_fold_rate": 0.55,  # walk-forward: fraction of folds that were profitable
    "min_return_pct":           8.0,   # minimum annualized return
}

def _rebuild_curve_from_trades(trades: list, initial_capital: float,
                                final_value: float) -> list:
    """
    Reconstructs an approximate equity curve from the trade log.
    Each closed trade produces one equity point.
    Works with the backtester's trade dict format:
      {'type': 'BUY'|'SELL'|'CLOSE'|'COVER', 'date': str, 'price': float, 'profit': float}
    """
    if not trades:
        return []

    curve = []
    running_capital = initial_capital

    for t in trades:
        trade_type = t.get("type", "")
        date = t.get("date", "")
        profit = t.get("profit", 0) or 0

        if trade_type == "BUY":
            # Entry — mark at current capital (no change yet)
            curve.append({"date": date, "value": round(running_capital, 2)})
        elif trade_type in ("SELL", "CLOSE", "COVER", "OPTIONS_EXPIRE", "CIRCUIT_CLOSE"):
            running_capital += float(profit)
            curve.append({"date": date, "value": round(running_capital, 2)})

    # Ensure the final value matches the backtester's reported final
    if curve and abs(curve[-1]["value"] - final_value) > 1:
        curve.append({"date": "final", "value": round(final_value, 2)})

    return curve


def _enrich_trades(trades: list) -> list:
    """
    Adds profit_pct to each closed trade using the BUY price as entry reference.
    Backtester stores absolute 'profit' in ₹ but not profit_pct.
    This is required for Monte Carlo resampling.
    """
    enriched = []
    last_entry_price = None
    last_shares = None

    for t in trades:
        t = dict(t)  # copy
        trade_type = t.get("type", "")

        if trade_type == "BUY":
            last_entry_price = t.get("price")
            last_shares = t.get("shares", 1)
            t["profit_pct"] = 0.0

        elif trade_type in ("SELL", "CLOSE", "COVER", "OPTIONS_EXPIRE", "CIRCUIT_CLOSE"):
            profit = t.get("profit", 0) or 0
            if last_entry_price and last_shares and last_entry_price > 0:
                cost_basis = last_entry_price * last_shares
                t["profit_pct"] = round(profit / cost_basis * 100, 3)
            else:
                t["profit_pct"] = 0.0
            # Also add readable field aliases for the trade log table
            t["entry_price"] = last_entry_price
            t["exit_price"] = t.get("price")
            t["entry_date"] = None  # date of entry not stored per-exit

        enriched.append(t)

    return enriched

class TestingEngine:
    """
    Central hub for running backtests, walk-forward, portfolio sims, and Monte Carlo.
    All results are persisted so StrategyGatekeeper and the dashboard can read them.
    """

    def __init__(self, initial_capital: float = BACKTEST_INITIAL_CAPITAL):
        self.initial_capital = initial_capital
        self._selector: Optional[AlgorithmSelector] = None   # lazy
        self._backtester: Optional[Backtester] = None        # lazy
        self.results_cache: Dict = self._load_results()

    @property
    def selector(self) -> AlgorithmSelector:
        if self._selector is None:
            self._selector = AlgorithmSelector(market='IN')
        return self._selector

    @property
    def backtester(self) -> Backtester:
        if self._backtester is None:
            self._backtester = Backtester(initial_capital=self.initial_capital)
        return self._backtester

    # ------------------------------------------------------------------ #
    #  RESULT PERSISTENCE                                                   #
    # ------------------------------------------------------------------ #

    def _load_results(self) -> Dict:
        try:
            if RESULTS_PATH.exists():
                return json.loads(RESULTS_PATH.read_text())
        except Exception:
            pass
        return {}

    def _refresh_cache(self):
        """Re-read from disk if the file is newer than our in-memory copy."""
        if not RESULTS_PATH.exists():
            return
        try:
            mtime = RESULTS_PATH.stat().st_mtime
            if not hasattr(self, '_cache_mtime') or mtime > self._cache_mtime:
                self.results_cache = json.loads(RESULTS_PATH.read_text())
                self._cache_mtime = mtime
        except Exception:
            pass

    def _save_results(self):
        """Saves the results cache to disk with retries for Windows file locks."""
        tmp = RESULTS_PATH.with_suffix(".tmp")
        try:
            for attempt in range(5):
                try:
                    # Write to temporary file first
                    tmp.write_text(json.dumps(self.results_cache, indent=2, default=str))
                    
                    # Try atomic replace
                    if RESULTS_PATH.exists():
                        # On Windows, replace can fail if the destination is open.
                        try:
                            tmp.replace(RESULTS_PATH)
                        except PermissionError:
                            # Fallback for Windows: copy + remove tmp
                            shutil.copy2(tmp, RESULTS_PATH)
                            tmp.unlink(missing_ok=True)
                    else:
                        tmp.rename(RESULTS_PATH)
                    return
                except (PermissionError, OSError) as e:
                    if attempt == 4:
                        logger.error(f"TestingEngine: failed to save results after 5 attempts: {e}")
                    else:
                        time.sleep(0.1 * (2 ** attempt)) # Exponential backoff: 0.1, 0.2, 0.4, 0.8s
                except Exception as e:
                    logger.error(f"TestingEngine: unexpected error saving results: {e}")
                    break
        finally:
            if tmp.exists():
                try: tmp.unlink(missing_ok=True)
                except: pass

    def _result_key(self, test_type: str, strategy: str, ticker: str) -> str:
        return f"{test_type}::{strategy}::{ticker}"

    def get_cached(self, test_type: str, strategy: str, ticker: str) -> Optional[Dict]:
        self._refresh_cache()   # ADD THIS LINE at the top
        key = self._result_key(test_type, strategy, ticker)
        entry = self.results_cache.get(key)
        if not entry:
            return None
        # Expire cache after 24 hours
        ts = entry.get("_cached_at")
        if ts:
            age_hours = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
            if age_hours > 24:
                return None
        return entry

    def _store(self, test_type: str, strategy: str, ticker: str, result: Dict):
        result["_cached_at"] = datetime.now().isoformat()
        result["_strategy"] = strategy
        result["_ticker"] = ticker
        result["_test_type"] = test_type
        key = self._result_key(test_type, strategy, ticker)
        self.results_cache[key] = result
        self._save_results()

    def list_results(self) -> List[Dict]:
        """Return all stored results as a flat list, newest first."""
        self._refresh_cache()
        items = list(self.results_cache.values())
        items.sort(key=lambda x: x.get("_cached_at", ""), reverse=True)
        return items

    # ------------------------------------------------------------------ #
    #  DATA HELPERS                                                         #
    # ------------------------------------------------------------------ #

    def _fetch(self, ticker: str, days: int) -> pd.DataFrame:
        # Check disk cache first (FIX PERF-4)
        cache_key = f"{ticker}_{days}_w400"
        if hasattr(self, '_data_cache') and cache_key in self._data_cache:
            cached_at, df = self._data_cache[cache_key]
            age_minutes = (datetime.now() - cached_at).total_seconds() / 60
            if age_minutes < 60:   # Cache data for 1 hour
                return df

        start, end = self._date_range(days + 400) # extra 400 days for warmup
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        df = self.backtester._flatten_df(df)
        df = df.dropna(subset=['Close'])

        # Store in in-memory data cache
        if not hasattr(self, '_data_cache'):
            self._data_cache = {}
        self._data_cache[cache_key] = (datetime.now(), df)
        return df

    def _date_range(self, days: int):
        end = datetime.now()
        start = end - timedelta(days=days)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ #
    #  TEST 1: SINGLE TICKER BACKTEST                                       #
    # ------------------------------------------------------------------ #

    def run_single_backtest(self, strategy: str, ticker: str, days: int = 365,
                            force: bool = False) -> Dict:
        """
        Run a single-ticker backtest using the existing Backtester.backtest_algorithm.
        Wraps the result with a validation verdict.
        """
        cached = self.get_cached("single", strategy, ticker)
        if cached and not force:
            return cached

        algo = self.selector.algorithms.get(strategy)
        if algo is None:
            return {"error": f"Strategy '{strategy}' not found.", "_test_type": "single"}

        start, end = self._date_range(days)
        logger.info(f"[TestingEngine] Single backtest: {strategy} on {ticker} ({days}d)")
        result = self.backtester.backtest_algorithm(algo, ticker, start, end)

        if "error" in result:
            result["_test_type"] = "single"   # FIX BUG-3: tag errors too
            return result

        # FIX BUG-1: Reconstruct capital_curve from trades if missing
        if "capital_curve" not in result or not result.get("capital_curve"):
            result["capital_curve"] = _rebuild_curve_from_trades(
                result.get("trades", []),
                result.get("initial_capital", self.initial_capital),
                result.get("final_value", self.initial_capital),
            )

        # FIX BUG-2: Add profit_pct to every trade that has absolute profit
        result["trades"] = _enrich_trades(result.get("trades", []))

        result["verdict"] = self._verdict(result)
        self._store("single", strategy, ticker, result)
        return result

    # ------------------------------------------------------------------ #
    #  TEST 2: WALK-FORWARD VALIDATION                                      #
    # ------------------------------------------------------------------ #

    def run_walk_forward(self, strategy: str, ticker: str, days: int = 756,
                         train_bars: int = 180, test_bars: int = 60,
                         force: bool = False) -> Dict:
        """
        Expanding walk-forward over multiple out-of-sample folds.
        The gold standard for avoiding overfitting.
        """
        cached = self.get_cached("walk_forward", strategy, ticker)
        if cached and not force:
            return cached

        algo = self.selector.algorithms.get(strategy)
        if algo is None:
            return {"error": f"Strategy '{strategy}' not found."}

        logger.info(f"[TestingEngine] Walk-forward: {strategy} on {ticker} ({days}d, {train_bars}/{test_bars} bars)")
        data = self._fetch(ticker, days)
        if data.empty:
            return {"error": "No market data available."}

        validator = WalkForwardValidator(WalkForwardConfig(
            initial_capital=self.initial_capital,
            train_bars=train_bars,
            test_bars=test_bars,
        ))
        result = validator.evaluate_algorithm(algo, ticker, data)

        if "error" in result:
            return result

        result["verdict"] = self._verdict_walk_forward(result)
        self._store("walk_forward", strategy, ticker, result)
        return result

    # ------------------------------------------------------------------ #
    #  TEST 3: PORTFOLIO SIMULATION                                         #
    # ------------------------------------------------------------------ #

    def run_portfolio_sim(self, strategy: str, tickers: List[str],
                          days: int = 365, max_positions: int = 10,
                          force: bool = False) -> Dict:
        """
        Multi-stock portfolio simulation with capital constraints and Kelly sizing.
        """
        ticker_key = "+".join(sorted(tickers))
        cached = self.get_cached("portfolio", strategy, ticker_key)
        if cached and not force:
            return cached

        algo = self.selector.algorithms.get(strategy)
        if algo is None:
            return {"error": f"Strategy '{strategy}' not found."}

        start, end = self._date_range(days)
        logger.info(f"[TestingEngine] Portfolio sim: {strategy} on {len(tickers)} tickers ({days}d)")
        pb = PortfolioBacktester(
            initial_capital=self.initial_capital,
            max_positions=max_positions,
        )
        result = pb.run_backtest(algo, tickers, start, end)

        if "error" in result:
            return result

        # Add unified verdict
        summary = result.get("summary", {})
        synthetic_result = {
            "return_pct": summary.get("return_pct", 0),
            "sharpe_ratio": summary.get("sharpe", 0),
            "max_drawdown_pct": self._calc_drawdown_from_curve(result.get("capital_curve", [])),
            "win_rate": self._calc_win_rate(result.get("trade_log", [])),
        }
        result["verdict"] = self._verdict(synthetic_result)
        self._store("portfolio", strategy, ticker_key, result)
        return result

    # ------------------------------------------------------------------ #
    #  TEST 4: MONTE CARLO SIMULATION                                       #
    # ------------------------------------------------------------------ #

    def run_monte_carlo(self, strategy: str, ticker: str, days: int = 365,
                        n_simulations: int = 500, force: bool = False) -> Dict:
        """
        Shuffles the trade sequence N times to estimate return distribution.
        Shows best-case, worst-case, and median outcome.
        Does NOT re-run the backtest; it resamples the existing trade log.
        """
        cached = self.get_cached("monte_carlo", strategy, ticker)
        if cached and not force:
            return cached

        # We need the base backtest trade log first
        base = self.run_single_backtest(strategy, ticker, days, force=force)
        if "error" in base:
            return base

        trades = base.get("trades", [])
        if len(trades) < 5:
            return {"error": "Need at least 5 trades to run Monte Carlo simulation."}

        # Extract P&L per trade as percentage
        pnls = []
        for t in trades:
            pnl_pct = t.get("profit_pct") or t.get("pnl_pct") or 0.0
            if pnl_pct != 0:
                pnls.append(float(pnl_pct) / 100.0)

        if not pnls:
            return {"error": "No completed trades with P&L found."}

        logger.info(f"[TestingEngine] Monte Carlo: {n_simulations} sims, {len(pnls)} trades")
        pnl_array = np.array(pnls)
        # Shape: (n_simulations, n_trades) — one row = one simulation
        samples = np.random.choice(pnl_array, size=(n_simulations, len(pnl_array)), replace=True)
        # Product along each simulation row = final equity multiplier
        equity_multiples = np.prod(1.0 + samples, axis=1)
        final_returns = sorted(((equity_multiples - 1.0) * 100.0).tolist())

        result = {
            "n_simulations": n_simulations,
            "n_trades": len(pnls),
            "p5_return_pct":     round(float(np.percentile(final_returns, 5)), 2),
            "p25_return_pct":    round(float(np.percentile(final_returns, 25)), 2),
            "median_return_pct": round(float(np.percentile(final_returns, 50)), 2),
            "p75_return_pct":    round(float(np.percentile(final_returns, 75)), 2),
            "p95_return_pct":    round(float(np.percentile(final_returns, 95)), 2),
            "pct_profitable":    round(float(np.mean([r > 0 for r in final_returns])) * 100, 1),
            "all_returns":       [round(r, 2) for r in final_returns],
        }
        result["verdict"] = {
            "pass": result["median_return_pct"] > VALIDATION_THRESHOLDS["min_return_pct"]
                    and result["pct_profitable"] > 60,
            "reason": (
                f"Median: {result['median_return_pct']:.1f}% | "
                f"Profitable in {result['pct_profitable']:.0f}% of simulations"
            ),
        }
        self._store("monte_carlo", strategy, ticker, result)
        return result

    # ------------------------------------------------------------------ #
    #  TEST 5: COMPARE ALL STRATEGIES                                       #
    # ------------------------------------------------------------------ #

    def run_strategy_comparison(self, ticker: str, days: int = 365,
                                 force: bool = False) -> Dict:
        """
        Runs all IN-market strategies on the same ticker and date range.
        Returns a ranked leaderboard.
        """
        logger.info(f"[TestingEngine] Strategy comparison: {ticker} ({days}d)")
        strategies = [k for k, v in self.selector.algorithms.items()
                      if v is not None and k != 'dalio_all_weather']

        # PERF-2: Download data once, reuse for all strategies
        # Pre-warm the data cache so each run_single_backtest hits it
        logger.info(f"[TestingEngine] Pre-fetching data for {ticker}...")
        prefetched = self._fetch(ticker, days)   # stores in self._data_cache

        leaderboard = []
        # PERF-3: Collect results, write disk once at the end
        pending_stores = []

        for strat in strategies:
            logger.info(f"  -> Testing {strat} in comparison loop...")
            cached = self.get_cached("single", strat, ticker)
            if cached and not force:
                result = cached
            else:
                algo = self.selector.algorithms.get(strat)
                if algo is None:
                    continue
                start, end = self._date_range(days)
                result = self.backtester.backtest_algorithm(algo, ticker, start, end, data=prefetched)
                if "error" in result:
                    continue

                if "capital_curve" not in result or not result.get("capital_curve"):
                    result["capital_curve"] = _rebuild_curve_from_trades(
                        result.get("trades", []),
                        result.get("initial_capital", self.initial_capital),
                        result.get("final_value", self.initial_capital),
                    )
                result["trades"] = _enrich_trades(result.get("trades", []))
                result["verdict"] = self._verdict(result)
                # Queue store instead of writing immediately
                pending_stores.append(("single", strat, ticker, result))

            leaderboard.append({
                "strategy":         strat,
                "return_pct":       result.get("return_pct", 0),
                "sharpe_ratio":     result.get("sharpe_ratio", 0),
                "max_drawdown_pct": result.get("max_drawdown_pct", 0),
                "win_rate":         result.get("win_rate", 0),
                "total_trades":     result.get("total_trades", 0),
                "verdict":          result.get("verdict", {}).get("pass", False),
            })

        # Apply all pending stores then write disk once
        for test_type, strat, tkr, res in pending_stores:
            res["_cached_at"] = datetime.now().isoformat()
            res["_strategy"] = strat
            res["_ticker"] = tkr
            res["_test_type"] = test_type
            key = self._result_key(test_type, strat, tkr)
            self.results_cache[key] = res
        self._save_results()   # ONE write for all

        leaderboard.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
        comparison = {
            "ticker":        ticker,
            "days":          days,
            "leaderboard":   leaderboard,
            "best_strategy": leaderboard[0]["strategy"] if leaderboard else None,
        }
        self._store("comparison", "all", ticker, comparison)
        return comparison

    # ------------------------------------------------------------------ #
    #  VERDICT HELPERS                                                      #
    # ------------------------------------------------------------------ #

    def _verdict(self, result: Dict) -> Dict:
        """Single-ticker backtest verdict."""
        t = VALIDATION_THRESHOLDS
        checks = {
            "Sharpe ≥ 0.8":        bool(result.get("sharpe_ratio", 0) >= t["min_sharpe"]),
            "Win rate ≥ 52%":      bool(result.get("win_rate", 0) >= t["min_win_rate"]),
            "Drawdown > -30%":     bool(result.get("max_drawdown_pct", -100) >= t["max_drawdown_pct"]),
            "Return ≥ 8%":         bool(result.get("return_pct", 0) >= t["min_return_pct"]),
        }
        passed = sum(checks.values())
        return {
            "pass": bool(passed >= 3),  # Must pass at least 3 of 4 checks
            "score": f"{passed}/4",
            "checks": checks,
            "reason": "; ".join(k for k, v in checks.items() if not v) or "All checks passed",
        }

    def _verdict_walk_forward(self, result: Dict) -> Dict:
        """Walk-forward specific verdict."""
        t = VALIDATION_THRESHOLDS
        summary = result.get("summary", {})
        checks = {
            "Profitable fold rate ≥ 55%": bool(summary.get("profitable_fold_rate", 0) >= t["min_profitable_fold_rate"]),
            "Median return ≥ 8%":         bool(summary.get("median_return_pct", 0) >= t["min_return_pct"]),
            "Drawdown > -30%":            bool(summary.get("worst_drawdown_pct", -100) >= t["max_drawdown_pct"]),
            "Robust score > 0":           bool(summary.get("robust_score", -1) > 0),
        }
        passed = sum(checks.values())
        return {
            "pass": bool(passed >= 3),
            "score": f"{passed}/4",
            "checks": checks,
            "reason": "; ".join(k for k, v in checks.items() if not v) or "All checks passed",
        }

    def _calc_drawdown_from_curve(self, curve: List[Dict]) -> float:
        if not curve:
            return 0.0
        values = [c["value"] for c in curve]
        s = pd.Series(values)
        dd = ((s - s.cummax()) / s.cummax()).min()
        return round(float(dd) * 100, 2)

    def _calc_win_rate(self, trade_log: List[Dict]) -> float:
        exits = [t for t in trade_log if t.get("action") == "EXIT"]
        if not exits:
            return 0.0
        wins = [t for t in exits if t.get("pnl", 0) > 0]
        return round(len(wins) / len(exits), 3)
