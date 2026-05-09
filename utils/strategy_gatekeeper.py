"""
StrategyGatekeeper — AutoBot consults this before opening any trade.

Logic:
  1. Load test results from TestingEngine's cache (memory/test_results.json).
  2. For each strategy+ticker pair, check if it has a PASSING verdict.
  3. If no test result exists, return ALLOW with a warning (don't block cold-start).
  4. If test result is FAILING, return BLOCK with the reason.

The autobot calls: gatekeeper.allow_trade(strategy, ticker) → (bool, reason)
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict, Optional

logger = logging.getLogger(__name__)

RESULTS_PATH = Path("memory/test_results.json")

# How old a test result can be before we consider it stale (days)
STALE_AFTER_DAYS = 7


class StrategyGatekeeper:

    def __init__(self):
        self._cache: Dict = {}
        self._loaded_at: Optional[datetime] = None

    def _load(self):
        """Load/refresh the results cache from disk (max once per minute)."""
        now = datetime.now()
        if self._loaded_at and (now - self._loaded_at).total_seconds() < 60:
            return
        try:
            if RESULTS_PATH.exists():
                self._cache = json.loads(RESULTS_PATH.read_text())
        except Exception as e:
            logger.warning(f"Gatekeeper: could not load test results: {e}")
            self._cache = {}
        self._loaded_at = now

    def _find_result(self, strategy: str, ticker: str) -> Optional[Dict]:
        """
        Find the most relevant test result for this strategy/ticker pair.
        Priority: walk_forward > single > portfolio
        """
        self._load()
        for test_type in ("walk_forward", "single", "portfolio"):
            key = f"{test_type}::{strategy}::{ticker}"
            entry = self._cache.get(key)
            if entry:
                # Check staleness
                ts = entry.get("_cached_at")
                if ts:
                    age_days = (datetime.now() - datetime.fromisoformat(ts)).days
                    if age_days > STALE_AFTER_DAYS:
                        continue  # Skip stale results
                return entry
        return None

    def allow_trade(self, strategy: str, ticker: str) -> Tuple[bool, str]:
        """
        Main decision method. Returns (allowed: bool, reason: str).

        Possible outcomes:
          (True,  "No test data — proceeding with caution")   ← cold start
          (True,  "Walk-forward: 3/4 checks passed")          ← validated
          (False, "Drawdown > -30%: failed")                  ← blocked
        """
        result = self._find_result(strategy, ticker)

        if result is None:
            # No test data — don't block, but warn
            logger.debug(f"Gatekeeper: no test data for {strategy}/{ticker} — allowing with warning")
            return True, "No backtest data available — run Testing Lab to validate first"

        verdict = result.get("verdict") or result.get("summary", {})
        if not verdict:
            return True, "Verdict unavailable — allowing with caution"

        passed = verdict.get("pass", True)
        reason = verdict.get("reason", "")
        score = verdict.get("score", "?")

        if passed:
            return True, f"Validated ({score}): {reason}"
        else:
            logger.warning(f"Gatekeeper BLOCKED {strategy}/{ticker}: {reason}")
            return False, f"Strategy failed validation ({score}): {reason}"

    def get_best_validated_strategy(self, ticker: str) -> Optional[str]:
        """
        Scan all cached results for this ticker and return the strategy
        with the highest Sharpe ratio that also passed validation.
        Useful for the autobot to auto-select the best tested strategy.
        """
        self._load()
        best_strategy = None
        best_sharpe = -999.0

        for key, entry in self._cache.items():
            if entry.get("_ticker") != ticker:
                continue
            if entry.get("_test_type") not in ("single", "walk_forward"):
                continue
            verdict = entry.get("verdict", {})
            if not verdict.get("pass", False):
                continue
            sharpe = entry.get("sharpe_ratio") or entry.get("summary", {}).get("avg_return_pct", 0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_strategy = entry.get("_strategy")

        return best_strategy

    def summary(self) -> Dict:
        """Dashboard-friendly summary of all validated strategies."""
        self._load()
        total = len(self._cache)
        passed = sum(1 for e in self._cache.values()
                     if e.get("verdict", {}).get("pass", False))
        failed = sum(1 for e in self._cache.values()
                     if not e.get("verdict", {}).get("pass", True))
        return {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / max(total, 1) * 100, 1),
        }
