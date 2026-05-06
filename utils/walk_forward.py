"""
Walk-forward validation for trading algorithms.
This tests whether a strategy survives repeated out-of-sample windows.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.backtester import Backtester


@dataclass
class WalkForwardConfig:
    initial_capital: float = 100_000
    train_bars: int = 180
    test_bars: int = 60
    min_confidence: float = 0.50
    stop_loss_pct: float = 4.0
    take_profit_pct: float = 8.0


class WalkForwardValidator:
    """Run expanding-window validation on already-fetched OHLCV data."""

    def __init__(self, config: Optional[WalkForwardConfig] = None):
        self.config = config or WalkForwardConfig()
        self.backtester = Backtester(
            initial_capital=self.config.initial_capital,
            include_costs=True,
        )

    def make_folds(self, data: pd.DataFrame) -> List[Dict]:
        """Create expanding train windows followed by fixed test windows."""
        if len(data) < self.config.train_bars + self.config.test_bars:
            return []

        folds = []
        start = self.config.train_bars
        fold_id = 1
        while start + self.config.test_bars <= len(data):
            train = data.iloc[:start]
            test = data.iloc[start:start + self.config.test_bars]
            folds.append({
                'fold': fold_id,
                'train_start': str(train.index[0])[:10],
                'train_end': str(train.index[-1])[:10],
                'test_start': str(test.index[0])[:10],
                'test_end': str(test.index[-1])[:10],
                'train_bars': len(train),
                'test_bars': len(test),
                '_train_end_pos': start,
                '_test_end_pos': start + self.config.test_bars,
            })
            start += self.config.test_bars
            fold_id += 1
        return folds

    def evaluate_algorithm(self, algorithm, ticker: str, data: pd.DataFrame) -> Dict:
        """
        Evaluate an algorithm on expanding walk-forward folds.
        The algorithm only receives history available up to each test bar.
        """
        required = {'Open', 'High', 'Low', 'Close', 'Volume'}
        missing = required.difference(data.columns)
        if missing:
            return {'error': f"Missing OHLCV columns: {sorted(missing)}"}

        data = data.dropna(subset=['Close']).copy()
        folds = self.make_folds(data)
        if not folds:
            return {'error': 'Insufficient data for walk-forward validation'}

        fold_results = []
        for fold in folds:
            result = self._run_fold(algorithm, ticker, data, fold)
            public_fold = {k: v for k, v in fold.items() if not k.startswith('_')}
            fold_results.append({**public_fold, **result})

        returns = [f['return_pct'] for f in fold_results]
        drawdowns = [f.get('max_drawdown_pct', 0) for f in fold_results]
        profitable = [r for r in returns if r > 0]
        robust_score = float(np.median(returns) - abs(min(drawdowns, default=0)) * 0.10)

        return {
            'ticker': ticker,
            'algorithm': getattr(algorithm, 'name', algorithm.__class__.__name__),
            'folds': fold_results,
            'summary': {
                'fold_count': len(fold_results),
                'avg_return_pct': round(float(np.mean(returns)), 2),
                'median_return_pct': round(float(np.median(returns)), 2),
                'profitable_fold_rate': round(len(profitable) / len(returns), 2),
                'worst_drawdown_pct': round(float(min(drawdowns, default=0)), 2),
                'robust_score': round(robust_score, 2),
            }
        }

    def _run_fold(self, algorithm, ticker: str, data: pd.DataFrame, fold: Dict) -> Dict:
        capital = self.config.initial_capital
        capital_curve = [capital]
        position = 0
        shares = 0
        entry_price = 0.0
        trades = []

        for i in range(fold['_train_end_pos'], fold['_test_end_pos']):
            window = data.iloc[:i + 1]
            row = data.iloc[i]
            price = float(row['Close'])
            date_str = str(data.index[i])[:10]

            try:
                signal = algorithm.analyze(ticker, window)
            except Exception as e:
                signal = {'signal': 'HOLD', 'confidence': 0.0, 'error': str(e)}

            sig = signal.get('signal', 'HOLD')
            conf = float(signal.get('confidence', 0.0) or 0.0)

            if position == 0 and sig == 'BUY' and conf >= self.config.min_confidence:
                shares = int((capital * 0.10 * conf) / price)
                if shares > 0 and self.backtester._passes_liquidity_filter(row, shares, price):
                    entry_price = self.backtester._liquidity_adjusted_price(row, shares, 'BUY')
                    trade_value = shares * entry_price
                    trade_value += self.backtester._calculate_transaction_costs(trade_value, 'delivery', True)
                    if trade_value <= capital:
                        capital -= trade_value
                        position = 1
                        trades.append({'type': 'BUY', 'date': date_str, 'price': entry_price, 'shares': shares})

            elif position == 1:
                pnl_pct = (price - entry_price) / entry_price * 100
                should_exit = (
                    sig == 'SELL'
                    or pnl_pct <= -self.config.stop_loss_pct
                    or pnl_pct >= self.config.take_profit_pct
                    or i == fold['_test_end_pos'] - 1
                )
                if should_exit:
                    exit_price = self.backtester._liquidity_adjusted_price(row, shares, 'SELL')
                    trade_value = shares * exit_price
                    trade_value -= self.backtester._calculate_transaction_costs(trade_value, 'delivery', False)
                    capital += trade_value
                    profit = (exit_price - entry_price) * shares
                    trades.append({
                        'type': 'SELL',
                        'date': date_str,
                        'price': exit_price,
                        'shares': shares,
                        'profit': round(profit, 2),
                    })
                    position = 0
                    shares = 0

            equity = capital + shares * price if position == 1 else capital
            capital_curve.append(equity)

        final_value = capital_curve[-1]
        metrics = self.backtester._compute_metrics(capital_curve, trades)
        return {
            'initial_capital': self.config.initial_capital,
            'final_value': round(final_value, 2),
            'return_pct': round((final_value - self.config.initial_capital) / self.config.initial_capital * 100, 2),
            'trades': len(trades),
            **metrics,
        }
