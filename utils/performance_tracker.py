"""
Strategy Performance Tracker — Realized P&L and Sharpe Ratio per strategy.
Allows the bot to decay weights of underperforming algorithms.

Migrated to SQLite backend (utils/database.py) for thread safety.
The dashboard, bot, and testing engine can all write concurrently without
race conditions that plagued the old JSON file approach.
"""
import logging
from datetime import datetime
from typing import Dict, List
from pathlib import Path

from config import MEMORY_DIR

logger = logging.getLogger(__name__)


class StrategyPerformanceTracker:
    ALGORITHMS = [
        'IndianMomentum',
        'MomentumBreakout',
        'SectorRotation',
        'OptionsWriting',
        'BuffettValue',
        'AllWeather',
        # Lowercase IDs used by AlgorithmSelector / autobot
        'indian_momentum',
        'momentum_breakout',
        'sector_rotation',
        'nifty_options_writer',
        'buffett_value',
        'bulls_ai_momentum',
        'mean_reversion',
    ]

    def __init__(self):
        from utils.database import Database
        self.db = Database(db_path=str(MEMORY_DIR / 'smart_trader.db'))
        self._stats_cache: Dict[str, dict] = {}

    def record_trade_history(self, algorithm: str, signal: str, pnl_pct: float):
        """Record the outcome of a trade signal (thread-safe via SQLite)."""
        outcome = 'WIN' if pnl_pct > 0 else 'LOSS'
        self.db.record_strategy_trade(algorithm, signal, pnl_pct, outcome)
        # Invalidate cached stats for this algorithm
        self._stats_cache.pop(algorithm, None)

    def get_strategy_stats(self, algorithm: str) -> dict:
        """Returns statistics and raw returns for an algorithm."""
        signals = self.db.get_strategy_signals(algorithm, limit=100)
        if not signals:
            return {}
        returns = [s['pnl_pct'] for s in signals if s.get('pnl_pct') is not None]
        wins = [r for r in returns if r > 0]
        return {
            'total_signals': len(signals),
            'win_rate': len(wins) / max(len(returns), 1),
            'avg_return': sum(returns) / max(len(returns), 1),
            'returns': returns
        }

    def _compute_stats(self, algorithm: str) -> dict:
        """Compute detailed stats for a single algorithm."""
        signals = self.db.get_strategy_signals(algorithm, limit=100)
        closed = [s for s in signals if s.get('pnl_pct') is not None]
        if not closed:
            return {}

        import numpy as np
        returns = [s['pnl_pct'] for s in closed]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        avg_ret = sum(returns) / len(returns)
        win_rate = len(wins) / len(returns)

        std_ret = float(np.std(returns)) if len(returns) > 1 else 1.0
        sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0.0

        return {
            'total_signals':  len(closed),
            'win_rate':       round(win_rate, 3),
            'avg_return_pct': round(avg_ret, 3),
            'avg_win_pct':    round(sum(wins) / len(wins), 3) if wins else 0,
            'avg_loss_pct':   round(sum(losses) / len(losses), 3) if losses else 0,
            'sharpe_ratio':   round(sharpe, 3),
            'profit_factor':  round(abs(sum(wins)) / max(abs(sum(losses)), 0.01), 2),
            'last_updated':   datetime.now().isoformat(),
        }

    def get_algorithm_weights(self) -> Dict[str, float]:
        """
        Return dynamic weights for each algorithm based on Sharpe ratio.
        Used by AlgorithmSelector to weight consensus votes.
        """
        weights = {}
        for algo in self.ALGORITHMS:
            stats = self._compute_stats(algo)
            sharpe = stats.get('sharpe_ratio', 0.0)
            if not stats:
                weights[algo] = 1.0
            else:
                weights[algo] = max(0.1, min(2.0, 1.0 + sharpe * 0.5))
        return weights

    def get_decayed_algorithm_weights(self, half_life_days: int = 60,
                                      min_closed: int = 5) -> Dict[str, float]:
        """
        Return weights that favor recent realized performance.
        Old outcomes decay exponentially so the router can adapt when regimes shift.
        """
        import math
        weights = {}
        now = datetime.now()

        for algo in self.ALGORITHMS:
            signals = self.db.get_strategy_signals(algo, limit=100)
            closed = [s for s in signals
                      if s.get('outcome') is not None and s.get('pnl_pct') is not None]
            if len(closed) < min_closed:
                weights[algo] = 1.0
                continue

            weighted_returns = []
            weighted_wins = 0.0
            total_weight = 0.0
            weighted_profit = 0.0
            weighted_loss = 0.0

            for sig in closed:
                stamp = sig.get('timestamp')
                try:
                    ts = datetime.fromisoformat(stamp)
                except Exception:
                    ts = now
                age_days = max((now - ts).days, 0)
                decay = 0.5 ** (age_days / max(half_life_days, 1))
                pnl = float(sig.get('pnl_pct', 0.0))

                weighted_returns.append((pnl, decay))
                total_weight += decay
                if pnl > 0:
                    weighted_wins += decay
                    weighted_profit += pnl * decay
                else:
                    weighted_loss += abs(pnl) * decay

            if total_weight <= 0:
                weights[algo] = 1.0
                continue

            avg_return = sum(pnl * w for pnl, w in weighted_returns) / total_weight
            win_rate = weighted_wins / total_weight
            profit_factor = weighted_profit / max(weighted_loss, 0.01)

            score = 1.0 + (avg_return / 5.0) + (win_rate - 0.50) + min(profit_factor - 1.0, 1.0) * 0.25
            weights[algo] = round(max(0.10, min(2.00, score)), 3)
        return weights

    def get_algorithm_stats(self, algorithm: str) -> dict:
        """
        Returns live performance stats for a single algorithm.
        Returns empty dict if insufficient data (< 10 trades).
        """
        stats = self.get_strategy_stats(algorithm)
        if not stats or stats.get('total_signals', 0) < 10:
            return {}
        returns = [r for r in stats.get('returns', []) if r is not None]
        if not returns:
            return {}
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        return {
            'win_rate': len(wins) / max(len(returns), 1),
            'avg_return': sum(wins) / max(len(wins), 1),
            'avg_loss': abs(sum(losses) / max(len(losses), 1)) or 0.05,
        }
