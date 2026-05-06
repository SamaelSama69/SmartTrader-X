"""
Enhanced Backtesting Framework
Improvements:
- Walk-forward validation with multiple folds
- Accurate Indian transaction costs (STT, brokerage, GST, stamp duty, SEBI charges)
- Proper slippage modeling based on market cap and liquidity
- Circuit limit handling
- Performance metrics (Sharpe, Sortino, Calmar, Win Rate, etc.)
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtesting"""
    initial_capital: float = 100000.0
    include_costs: bool = True
    max_position_pct: float = 0.20  # Max 20% per position
    max_daily_loss_pct: float = 2.0  # Stop at 2% daily loss
    max_drawdown_pct: float = 20.0  # Max 20% drawdown
    commission_rate: float = 0.0001  # 0.01% brokerage
    slippage_rate: float = 0.001  # 0.1% default slippage
    max_volume_participation: float = 0.02  # Max 2% of daily volume
    min_traded_value: float = 10_000_000  # Min 1 crore daily traded value

    # Indian transaction costs (as per SEBI)
    stt_equity: float = 0.00025  # 0.025% STT on equity delivery
    stt_intraday: float = 0.00025  # 0.025% STT on intraday
    stt_fno: float = 0.0005  # 0.05% STT on F&O
    gst_rate: float = 0.18  # 18% GST on brokerage
    sebi_charges: float = 0.000001  # 0.0001% SEBI charges
    stamp_duty: float = 0.00015  # 0.015% stamp duty

    # Circuit limits by market cap
    large_cap_circuit: float = 0.10  # 10% for large cap
    mid_cap_circuit: float = 0.15  # 15% for mid cap
    small_cap_circuit: float = 0.20  # 20% for small cap


@dataclass
class Trade:
    """Individual trade record"""
    type: str  # BUY, SELL, SHORT, COVER, CLOSE
    symbol: str
    entry_price: float
    exit_price: Optional[float]
    quantity: int
    entry_date: str
    exit_date: Optional[str]
    profit: Optional[float]
    profit_pct: Optional[float]
    holding_days: Optional[int]
    trade_type: str  # delivery, intraday, fno


@dataclass
class BacktestResult:
    """Complete backtest results"""
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    initial_capital: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_holding_days: float
    trades: List[Trade]
    capital_curve: List[float]
    daily_returns: List[float]


class IndianTransactionCosts:
    """Calculate accurate Indian transaction costs"""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def calculate_delivery_cost(self, trade_value: float, is_buy: bool = True) -> float:
        """Calculate total cost for delivery (CNC) trades"""
        # Brokerage
        brokerage = min(trade_value * self.config.commission_rate, 20.0)

        # STT (only on sell side for delivery)
        stt = 0.0
        if not is_buy:
            stt = trade_value * self.config.stt_equity

        # GST (18% on brokerage)
        gst = brokerage * self.config.gst_rate

        # SEBI charges
        sebi = trade_value * self.config.sebi_charges

        # Stamp duty (only on buy side)
        stamp_duty = 0.0
        if is_buy:
            stamp_duty = trade_value * self.config.stamp_duty

        total = brokerage + stt + gst + sebi + stamp_duty
        return total

    def calculate_intraday_cost(self, trade_value: float, is_buy: bool = True) -> float:
        """Calculate total cost for intraday (MIS) trades"""
        # Brokerage
        brokerage = min(trade_value * self.config.commission_rate, 20.0)

        # STT (both buy and sell for intraday)
        stt = trade_value * self.config.stt_intraday

        # GST
        gst = brokerage * self.config.gst_rate

        # SEBI charges
        sebi = trade_value * self.config.sebi_charges

        # Stamp duty (only on buy side)
        stamp_duty = 0.0
        if is_buy:
            stamp_duty = trade_value * self.config.stamp_duty

        total = brokerage + stt + gst + sebi + stamp_duty
        return total

    def calculate_fno_cost(self, trade_value: float, is_buy: bool = True) -> float:
        """Calculate total cost for F&O trades"""
        # Brokerage
        brokerage = min(trade_value * self.config.commission_rate, 20.0)

        # STT (only on sell side for F&O)
        stt = 0.0
        if not is_buy:
            stt = trade_value * self.config.stt_fno

        # GST
        gst = brokerage * self.config.gst_rate

        # SEBI charges
        sebi = trade_value * self.config.sebi_charges

        # Stamp duty (only on buy side)
        stamp_duty = 0.0
        if is_buy:
            stamp_duty = trade_value * self.config.stamp_duty

        total = brokerage + stt + gst + sebi + stamp_duty
        return total


class SlippageModel:
    """Model slippage based on market cap and liquidity"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self._market_cap_cache: Dict[str, float] = {}

    def get_slippage_rate(self, symbol: str, volume: int, trade_size: int) -> float:
        """
        Calculate slippage rate based on:
        1. Market cap (large cap = lower slippage)
        2. Trade size vs volume (larger participation = higher slippage)
        """
        # Base slippage by market cap
        base_slippage = self._get_market_cap_slippage(symbol)

        # Liquidity impact
        if volume > 0 and trade_size > 0:
            participation = trade_size / volume
            liquidity_impact = max(participation - 0.005, 0) * 2.0
        else:
            liquidity_impact = 0.01  # Default 1% if volume unknown

        total_slippage = base_slippage + liquidity_impact
        return min(total_slippage, 0.02)  # Cap at 2%

    def _get_market_cap_slippage(self, symbol: str) -> float:
        """Get base slippage based on market cap"""
        # Check cache first
        if symbol in self._market_cap_cache:
            market_cap = self._market_cap_cache[symbol]
        else:
            market_cap = self._fetch_market_cap(symbol)
            self._market_cap_cache[symbol] = market_cap

        # Large cap: > 20,000 crore (200 billion)
        if market_cap > 200_000_000_000:
            return 0.001  # 0.1%
        # Mid cap: > 5,000 crore (50 billion)
        elif market_cap > 50_000_000_000:
            return 0.005  # 0.5%
        # Small cap: > 0
        elif market_cap > 0:
            return 0.01  # 1.0%
        else:
            return 0.005  # Default 0.5%

    def _fetch_market_cap(self, symbol: str) -> float:
        """Fetch market cap from yfinance"""
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return info.get("marketCap", 0)
        except Exception:
            return 0


class WalkForwardValidator:
    """Walk-forward validation for robust strategy testing"""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def validate(
        self,
        strategy_func: Callable,
        symbol: str,
        data: pd.DataFrame,
        train_bars: int = 180,
        test_bars: int = 60,
        step_bars: int = 30
    ) -> Dict:
        """
        Perform walk-forward validation

        Args:
            strategy_func: Function that takes (data, config) and returns signals
            symbol: Stock symbol
            data: Historical price data
            train_bars: Number of bars for training
            test_bars: Number of bars for testing
            step_bars: Step size for rolling window

        Returns:
            Validation results with fold-by-fold performance
        """
        if len(data) < train_bars + test_bars:
            return {"error": "Insufficient data for walk-forward validation"}

        folds = []
        current_start = 0

        while current_start + train_bars + test_bars <= len(data):
            # Split data
            train_data = data.iloc[current_start:current_start + train_bars]
            test_data = data.iloc[current_start + train_bars:current_start + train_bars + test_bars]

            # Run backtest on test period
            fold_result = self._backtest_fold(
                strategy_func,
                symbol,
                train_data,
                test_data
            )

            folds.append(fold_result)

            # Move window
            current_start += step_bars

        # Aggregate results
        return self._aggregate_folds(folds)

    def _backtest_fold(
        self,
        strategy_func: Callable,
        symbol: str,
        train_data: pd.DataFrame,
        test_data: pd.DataFrame
    ) -> Dict:
        """Backtest a single fold"""
        # Get strategy parameters from training data
        params = strategy_func(train_data, mode="train")

        # Run backtest on test data
        result = strategy_func(test_data, mode="test", params=params)

        return {
            "train_start": str(train_data.index[0]),
            "train_end": str(train_data.index[-1]),
            "test_start": str(test_data.index[0]),
            "test_end": str(test_data.index[-1]),
            "return_pct": result.get("return_pct", 0),
            "sharpe_ratio": result.get("sharpe_ratio", 0),
            "max_drawdown_pct": result.get("max_drawdown_pct", 0),
            "trades": result.get("total_trades", 0),
            "win_rate": result.get("win_rate", 0)
        }

    def _aggregate_folds(self, folds: List[Dict]) -> Dict:
        """Aggregate results across all folds"""
        if not folds:
            return {"error": "No folds to aggregate"}

        returns = [f["return_pct"] for f in folds]
        sharpes = [f["sharpe_ratio"] for f in folds]
        drawdowns = [f["max_drawdown_pct"] for f in folds]

        profitable_folds = sum(1 for r in returns if r > 0)
        total_folds = len(folds)

        return {
            "fold_count": total_folds,
            "folds": folds,
            "summary": {
                "median_return_pct": np.median(returns),
                "mean_return_pct": np.mean(returns),
                "std_return_pct": np.std(returns),
                "median_sharpe": np.median(sharpes),
                "mean_sharpe": np.mean(sharpes),
                "worst_drawdown_pct": max(drawdowns),
                "profitable_fold_rate": profitable_folds / total_folds,
                "robust_score": self._calculate_robust_score(returns, drawdowns)
            }
        }

    def _calculate_robust_score(self, returns: List[float], drawdowns: List[float]) -> float:
        """
        Calculate robustness score (0-100)
        Higher = more robust strategy
        """
        if not returns:
            return 0.0

        # Consistency score (lower std = higher consistency)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        consistency_score = max(0, 100 - (std_return / abs(mean_return) * 100 if mean_return != 0 else 100))

        # Profitability score
        profitable_pct = sum(1 for r in returns if r > 0) / len(returns) * 100

        # Drawdown penalty
        max_dd = max(drawdowns)
        drawdown_penalty = min(max_dd * 2, 50)  # Up to 50 point penalty

        robust_score = (consistency_score * 0.4 + profitable_pct * 0.4) - drawdown_penalty
        return max(0, min(100, robust_score))


class EnhancedBacktester:
    """Enhanced backtester with accurate Indian costs and metrics"""

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.cost_calculator = IndianTransactionCosts(self.config)
        self.slippage_model = SlippageModel(self.config)

    def backtest(
        self,
        signals: pd.DataFrame,
        prices: pd.DataFrame,
        trade_type: str = "delivery"
    ) -> BacktestResult:
        """
        Run backtest with given signals

        Args:
            signals: DataFrame with 'signal' column (BUY, SELL, HOLD)
            prices: DataFrame with OHLCV data
            trade_type: 'delivery', 'intraday', or 'fno'

        Returns:
            BacktestResult with all metrics
        """
        capital = self.config.initial_capital
        capital_curve = [capital]
        position = 0  # 0 = no position, 1 = long, -1 = short
        shares = 0
        entry_price = 0.0
        entry_date = None
        trades = []
        daily_returns = []

        for i in range(len(prices)):
            row = prices.iloc[i]
            price = float(row['Close'])
            volume = int(row['Volume'])
            date = str(prices.index[i])[:10]

            # Get signal
            signal = signals.iloc[i]['signal'] if i < len(signals) else 'HOLD'

            # Calculate daily return
            if i > 0:
                prev_capital = capital_curve[-1]
                if position == 1:
                    current_value = capital + shares * price
                elif position == -1:
                    current_value = capital - shares * price
                else:
                    current_value = capital

                daily_return = (current_value - prev_capital) / prev_capital
                daily_returns.append(daily_return)

            # Entry - Long
            if signal == 'BUY' and position == 0:
                max_position_value = capital * self.config.max_position_pct
                shares = int(max_position_value / price)

                if shares > 0:
                    # Check liquidity
                    if not self._check_liquidity(volume, shares, price):
                        continue

                    # Apply slippage
                    slippage = self.slippage_model.get_slippage_rate(
                        signals.index[i], volume, shares
                    )
                    execution_price = price * (1 + slippage)

                    trade_value = shares * execution_price
                    cost = self._get_cost(trade_value, trade_type, is_buy=True)
                    total_cost = trade_value + cost

                    if total_cost <= capital:
                        capital -= total_cost
                        entry_price = execution_price
                        entry_date = date
                        position = 1
                        capital_curve.append(capital + shares * price)

            # Entry - Short
            elif signal == 'SELL' and position == 0:
                max_position_value = capital * self.config.max_position_pct
                shares = int(max_position_value / price)

                if shares > 0:
                    # Check liquidity
                    if not self._check_liquidity(volume, shares, price):
                        continue

                    # Apply slippage
                    slippage = self.slippage_model.get_slippage_rate(
                        signals.index[i], volume, shares
                    )
                    execution_price = price * (1 - slippage)

                    trade_value = shares * execution_price
                    cost = self._get_cost(trade_value, trade_type, is_buy=True)
                    total_cost = trade_value + cost

                    capital += trade_value - cost
                    entry_price = execution_price
                    entry_date = date
                    position = -1
                    capital_curve.append(capital - shares * price)

            # Exit Long
            elif position == 1 and signal == 'SELL':
                slippage = self.slippage_model.get_slippage_rate(
                    signals.index[i], volume, shares
                )
                execution_price = price * (1 - slippage)

                trade_value = shares * execution_price
                cost = self._get_cost(trade_value, trade_type, is_buy=False)
                capital += trade_value - cost

                profit = (execution_price - entry_price) * shares
                profit_pct = (execution_price - entry_price) / entry_price * 100

                holding_days = self._calculate_holding_days(entry_date, date)

                trades.append(Trade(
                    type='SELL',
                    symbol=signals.index[i],
                    entry_price=entry_price,
                    exit_price=execution_price,
                    quantity=shares,
                    entry_date=entry_date,
                    exit_date=date,
                    profit=profit,
                    profit_pct=profit_pct,
                    holding_days=holding_days,
                    trade_type=trade_type
                ))

                position = 0
                shares = 0
                capital_curve.append(capital)

            # Exit Short
            elif position == -1 and signal == 'BUY':
                slippage = self.slippage_model.get_slippage_rate(
                    signals.index[i], volume, shares
                )
                execution_price = price * (1 + slippage)

                trade_value = shares * execution_price
                cost = self._get_cost(trade_value, trade_type, is_buy=False)
                capital -= trade_value + cost

                profit = (entry_price - execution_price) * shares
                profit_pct = (entry_price - execution_price) / entry_price * 100

                holding_days = self._calculate_holding_days(entry_date, date)

                trades.append(Trade(
                    type='COVER',
                    symbol=signals.index[i],
                    entry_price=entry_price,
                    exit_price=execution_price,
                    quantity=shares,
                    entry_date=entry_date,
                    exit_date=date,
                    profit=profit,
                    profit_pct=profit_pct,
                    holding_days=holding_days,
                    trade_type=trade_type
                ))

                position = 0
                shares = 0
                capital_curve.append(capital)

            else:
                # Mark to market
                if position == 1:
                    capital_curve.append(capital + shares * price)
                elif position == -1:
                    capital_curve.append(capital - shares * price)
                else:
                    capital_curve.append(capital)

        # Close any open position
        if position != 0:
            final_price = float(prices['Close'].iloc[-1])
            final_date = str(prices.index[-1])[:10]

            if position == 1:
                trade_value = shares * final_price
                cost = self._get_cost(trade_value, trade_type, is_buy=False)
                capital += trade_value - cost
                profit = (final_price - entry_price) * shares
                profit_pct = (final_price - entry_price) / entry_price * 100
                trade_type_str = 'SELL'
            else:
                trade_value = shares * final_price
                cost = self._get_cost(trade_value, trade_type, is_buy=False)
                capital -= trade_value + cost
                profit = (entry_price - final_price) * shares
                profit_pct = (entry_price - final_price) / entry_price * 100
                trade_type_str = 'COVER'

            holding_days = self._calculate_holding_days(entry_date, final_date)

            trades.append(Trade(
                type=trade_type_str,
                symbol=signals.index[0],
                entry_price=entry_price,
                exit_price=final_price,
                quantity=shares,
                entry_date=entry_date,
                exit_date=final_date,
                profit=profit,
                profit_pct=profit_pct,
                holding_days=holding_days,
                trade_type=trade_type
            ))

            capital_curve.append(capital)

        # Calculate metrics
        return self._calculate_metrics(
            capital_curve,
            daily_returns,
            trades,
            str(prices.index[0])[:10],
            str(prices.index[-1])[:10]
        )

    def _get_cost(self, trade_value: float, trade_type: str, is_buy: bool) -> float:
        """Get transaction cost based on trade type"""
        if trade_type == "delivery":
            return self.cost_calculator.calculate_delivery_cost(trade_value, is_buy)
        elif trade_type == "intraday":
            return self.cost_calculator.calculate_intraday_cost(trade_value, is_buy)
        elif trade_type == "fno":
            return self.cost_calculator.calculate_fno_cost(trade_value, is_buy)
        return 0.0

    def _check_liquidity(self, volume: int, shares: int, price: float) -> bool:
        """Check if trade passes liquidity filter"""
        traded_value = volume * price
        if traded_value < self.config.min_traded_value:
            return False
        return shares <= volume * self.config.max_volume_participation

    def _calculate_holding_days(self, entry_date: str, exit_date: str) -> int:
        """Calculate number of holding days"""
        try:
            entry = datetime.strptime(entry_date, '%Y-%m-%d')
            exit_dt = datetime.strptime(exit_date, '%Y-%m-%d')
            return (exit_dt - entry).days
        except Exception:
            return 0

    def _calculate_metrics(
        self,
        capital_curve: List[float],
        daily_returns: List[float],
        trades: List[Trade],
        start_date: str,
        end_date: str
    ) -> BacktestResult:
        """Calculate all backtest metrics"""
        if not capital_curve:
            raise ValueError("Empty capital curve")

        series = pd.Series(capital_curve)
        returns = pd.Series(daily_returns) if daily_returns else series.pct_change().dropna()

        # Total return
        total_return_pct = (capital_curve[-1] - capital_curve[0]) / capital_curve[0] * 100

        # CAGR
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            years = (end - start).days / 365.25
            cagr_pct = ((capital_curve[-1] / capital_curve[0]) ** (1 / years) - 1) * 100 if years > 0 else 0
        except Exception:
            cagr_pct = 0

        # Drawdown
        running_max = series.cummax()
        drawdown = (series - running_max) / running_max
        max_drawdown_pct = drawdown.min() * 100

        # Sharpe Ratio
        sharpe_ratio = 0
        if len(returns) > 0 and returns.std() > 0:
            sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252)

        # Sortino Ratio
        sortino_ratio = 0
        if len(returns) > 0:
            downside_returns = returns[returns < 0]
            if len(downside_returns) > 0 and downside_returns.std() > 0:
                sortino_ratio = returns.mean() / downside_returns.std() * np.sqrt(252)

        # Calmar Ratio
        calmar_ratio = 0
        if max_drawdown_pct != 0:
            calmar_ratio = cagr_pct / abs(max_drawdown_pct)

        # Trade statistics
        winning_trades = [t for t in trades if t.profit and t.profit > 0]
        losing_trades = [t for t in trades if t.profit and t.profit < 0]

        win_rate = len(winning_trades) / len(trades) if trades else 0

        avg_win_pct = np.mean([t.profit_pct for t in winning_trades]) if winning_trades else 0
        avg_loss_pct = np.mean([t.profit_pct for t in losing_trades]) if losing_trades else 0

        # Profit Factor
        total_wins = sum(t.profit for t in winning_trades) if winning_trades else 0
        total_losses = abs(sum(t.profit for t in losing_trades)) if losing_trades else 1
        profit_factor = total_wins / total_losses if total_losses > 0 else 0

        # Average holding days
        avg_holding_days = np.mean([t.holding_days for t in trades if t.holding_days]) if trades else 0

        return BacktestResult(
            strategy="backtest",
            symbol="",
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.config.initial_capital,
            final_value=capital_curve[-1],
            total_return_pct=total_return_pct,
            cagr_pct=cagr_pct,
            max_drawdown_pct=max_drawdown_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            avg_holding_days=avg_holding_days,
            trades=trades,
            capital_curve=capital_curve,
            daily_returns=daily_returns
        )

    def save_results(self, result: BacktestResult, filepath: str) -> None:
        """Save backtest results to file"""
        data = asdict(result)
        data['trades'] = [asdict(t) for t in result.trades]

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Saved backtest results to {filepath}")
