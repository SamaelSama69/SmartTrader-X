"""
Strategy Performance Attribution
Tracks P&L per algorithm so the system can dynamically weight winners.
This is what separates a signal generator from a self-improving system.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

PERF_FILE = Path(os.getenv('MEMORY_DIR', 'memory')) / 'strategy_performance.json'


class StrategyPerformanceTracker:
    """
    Records every signal per algorithm and its eventual outcome.
    Computes: win rate, avg return, Sharpe per algorithm.
    Used to dynamically weight algorithms in AlgorithmSelector.
    """

    ALGORITHMS = [
        'BuffettValue', 'DalioAllWeather', 'CathieWoodGrowth',
        'BullsAIMomentum', 'IndianMomentum', 'NiftyOptionsWriter',
        'MomentumBreakout', 'SectorRotation'
    ]

    def __init__(self):
        self.perf_file = PERF_FILE
        self.perf_file.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Dict:
        if self.perf_file.exists():
            try:
                with open(self.perf_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Performance file corrupted, resetting: {e}")
        return {algo: {'signals': [], 'stats': {}} for algo in self.ALGORITHMS}

    def _save(self):
        try:
            with open(self.perf_file, 'w') as f:
                json.dump(self.data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save performance data: {e}")

    def record_signal(self, algorithm: str, ticker: str, signal: str,
                      confidence: float, entry_price: float):
        """Record a new BUY/SELL signal from an algorithm."""
        if algorithm not in self.data:
            self.data[algorithm] = {'signals': [], 'stats': {}}

        record = {
            'id':          f"{algorithm}_{ticker}_{datetime.now():%Y%m%d_%H%M%S}",
            'ticker':      ticker,
            'signal':      signal,
            'confidence':  confidence,
            'entry_price': entry_price,
            'timestamp':   datetime.now().isoformat(),
            'outcome':     None,   # Filled in by record_outcome()
            'pnl_pct':     None,
        }
        self.data[algorithm]['signals'].append(record)
        # Keep last 500 signals per algorithm
        self.data[algorithm]['signals'] = self.data[algorithm]['signals'][-500:]
        self._save()
        logger.debug(f"[Perf] Recorded {algorithm} signal: {signal} {ticker} @ {entry_price:.2f}")

    def record_outcome(self, algorithm: str, ticker: str,
                       exit_price: float, entry_price: float):
        """Update the most recent open signal for this algo/ticker with its outcome."""
        if algorithm not in self.data:
            return
        for sig in reversed(self.data[algorithm]['signals']):
            if sig['ticker'] == ticker and sig['outcome'] is None:
                pnl_pct = (exit_price - sig['entry_price']) / sig['entry_price'] * 100
                if sig['signal'] == 'SELL':
                    pnl_pct = -pnl_pct
                sig['outcome']   = 'WIN' if pnl_pct > 0 else 'LOSS'
                sig['pnl_pct']   = round(pnl_pct, 3)
                sig['exit_price']   = exit_price
                sig['closed_at'] = datetime.now().isoformat()
                self._update_stats(algorithm)
                self._save()
                return

    def _update_stats(self, algorithm: str):
        """Recompute win rate, avg return, Sharpe for an algorithm."""
        signals = self.data[algorithm]['signals']
        closed  = [s for s in signals if s['outcome'] is not None]
        if len(closed) < 3:
            return

        returns  = [s['pnl_pct'] for s in closed]
        wins     = [r for r in returns if r > 0]
        losses   = [r for r in returns if r <= 0]
        avg_ret  = sum(returns) / len(returns)
        win_rate = len(wins) / len(returns)

        import numpy as np
        std_ret = float(np.std(returns)) if len(returns) > 1 else 1.0
        sharpe  = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0.0

        self.data[algorithm]['stats'] = {
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
        Algorithms with negative Sharpe get minimum weight (0.1).
        Used by AlgorithmSelector to weight consensus votes.
        """
        weights = {}
        for algo in self.ALGORITHMS:
            stats = self.data.get(algo, {}).get('stats', {})
            sharpe = stats.get('sharpe_ratio', 0.0)
            # Min weight 0.1, max weight 2.0; baseline 1.0 with no data
            if not stats:
                weights[algo] = 1.0   # Equal weight until we have data
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
            signals = self.data.get(algo, {}).get('signals', [])
            closed = [s for s in signals if s.get('outcome') is not None and s.get('pnl_pct') is not None]
            if len(closed) < min_closed:
                weights[algo] = 1.0
                continue

            weighted_returns = []
            weighted_wins = 0.0
            total_weight = 0.0
            weighted_profit = 0.0
            weighted_loss = 0.0

            for sig in closed:
                stamp = sig.get('closed_at') or sig.get('timestamp')
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

    def get_strategy_health(self, half_life_days: int = 60) -> Dict[str, Dict]:
        """Return recent performance diagnostics for dashboards and routers."""
        weights = self.get_decayed_algorithm_weights(half_life_days=half_life_days)
        health = {}
        for algo in self.ALGORITHMS:
            stats = self.data.get(algo, {}).get('stats', {})
            health[algo] = {
                'weight': weights.get(algo, 1.0),
                'total_signals': stats.get('total_signals', 0),
                'win_rate': stats.get('win_rate', None),
                'avg_return_pct': stats.get('avg_return_pct', None),
                'profit_factor': stats.get('profit_factor', None),
                'sharpe_ratio': stats.get('sharpe_ratio', None),
            }
        return health

    def print_leaderboard(self):
        """Print a formatted leaderboard of algorithm performance."""
        header = f"\n{'Algorithm':<22} {'Signals':>8} {'Win%':>7} {'AvgRet':>8} {'Sharpe':>8} {'PF':>6}"
        print(header)
        print('-' * len(header))
        rows = []
        for algo in self.ALGORITHMS:
            stats = self.data.get(algo, {}).get('stats', {})
            if not stats:
                rows.append((0, algo, '—', '—', '—', '—'))
            else:
                rows.append((
                    stats.get('sharpe_ratio', 0),
                    algo,
                    str(stats.get('total_signals', 0)),
                    f"{stats.get('win_rate', 0):.0%}",
                    f"{stats.get('avg_return_pct', 0):+.2f}%",
                    f"{stats.get('sharpe_ratio', 0):.2f}",
                    f"{stats.get('profit_factor', 0):.1f}",
                ))
        for row in sorted(rows, key=lambda x: x[0], reverse=True):
            if len(row) == 7:
                _, algo, sigs, wr, avgr, sharpe, pf = row
                print(f"{algo:<22} {sigs:>8} {wr:>7} {avgr:>8} {sharpe:>8} {pf:>6}")
            else:
                _, algo, *rest = row
                print(f"{algo:<22} {'No data':>8}")
        print()
