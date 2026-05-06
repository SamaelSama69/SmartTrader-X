"""
Backtesting Engine - Test strategies against historical data
Uses free yfinance data for backtesting
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from pathlib import Path
import yfinance as yf
from config import *
from utils.risk_manager import RiskManager as _RM
from utils.options_pricer import simulate_options_write
from indian_config import get_lot_size, TAX_CONFIG, POPULAR_INDIAN_STOCKS

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    vbt = None
    HAS_VBT = False

try:
    _yf_cache = Path(__file__).resolve().parents[1] / "data" / "yfinance_cache"
    _yf_cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(_yf_cache))
except Exception:
    pass


class Backtester:
    """Backtest trading strategies on historical data"""

    def __init__(self, initial_capital: float = BACKTEST_INITIAL_CAPITAL,
                 include_costs: bool = True, benchmark: str = '^NSEI'):
        self.initial_capital = initial_capital
        self.include_costs = include_costs
        self.benchmark = benchmark
        self.commission_rate = BACKTEST_COMMISSION_RATE
        self.slippage = BACKTEST_SLIPPAGE
        self.max_volume_participation = 0.02
        self.min_traded_value = 10_000_000

    def _flatten_df(self, df):
        """Flatten MultiIndex columns from yf.download()"""
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        return df

    def _calculate_transaction_costs(self, trade_value: float,
                                 trade_type: str = 'delivery', is_buy: bool = True) -> float:
        """Calculate total transaction costs (brokerage, GST, STT, slippage)"""
        if not self.include_costs:
            return 0.0
        brokerage = trade_value * BROKERAGE_RATE
        if brokerage > BROKERAGE_CAP:
            brokerage = BROKERAGE_CAP
        gst = brokerage * GST_RATE
        if trade_type == 'delivery':
            stt = trade_value * STT_DELIVERY
        elif trade_type == 'intraday':
            stt = trade_value * STT_INTRADAY
        else:
            stt = 0.0
        slippage = trade_value * SLIPPAGE_RATE
        return brokerage + gst + stt + slippage

    def _passes_liquidity_filter(self, row, shares: int, price: float) -> bool:
        """Reject trades that are too large for the day's reported liquidity."""
        volume = float(row.get('Volume', 0) or 0)
        if volume <= 0 or shares <= 0:
            return False
        traded_value = volume * price
        if traded_value < self.min_traded_value:
            return False
        return shares <= volume * self.max_volume_participation

    def _estimate_slippage_rate(self, row, shares: int) -> float:
        """Increase slippage when our trade is a meaningful share of volume."""
        volume = float(row.get('Volume', 0) or 0)
        if volume <= 0 or shares <= 0:
            return SLIPPAGE_RATE * 3
        participation = shares / volume
        impact = max(participation - 0.005, 0) * 2.0
        return min(SLIPPAGE_RATE + impact, 0.02)

    def _liquidity_adjusted_price(self, row, shares: int, side: str, ticker: str = None) -> float:
        """Apply market-impact and market-cap based slippage to execution prices."""
        price = float(row['Close'])
        total_slip = 0.0
        if self.include_costs:
            # Market-cap based slippage
            if ticker:
                total_slip += self._get_slippage_rate(ticker)
            # Liquidity impact slippage
            total_slip += self._estimate_slippage_rate(row, shares)
        if side.upper() in {'BUY', 'COVER'}:
            return price * (1 + total_slip)
        return price * (1 - total_slip)

    def _calculate_indian_costs(self, trade_value: float, trade_type: str = 'equity') -> float:
        """Calculate total Indian transaction costs for a trade.

        Args:
            trade_value: Total value of the trade in INR.
            trade_type: 'equity' (delivery), 'intraday', or 'fno'.

        Returns:
            Total transaction cost in INR.
        """
        if not self.include_costs:
            return 0.0

        # STT based on trade type
        stt_rate = 0.0
        if trade_type == 'equity':
            stt_rate = TAX_CONFIG["stt_equity"]
        elif trade_type == 'intraday':
            stt_rate = TAX_CONFIG["stt_intraday"]
        elif trade_type == 'fno':
            stt_rate = TAX_CONFIG["stt_fno"]
        stt = trade_value * stt_rate

        # Brokerage based on trade type
        brokerage_rate = 0.0
        if trade_type in ('equity', 'intraday'):
            brokerage_rate = TAX_CONFIG["brokerage_eq"]
        elif trade_type == 'fno':
            brokerage_rate = TAX_CONFIG["brokerage_fno"]
        brokerage = trade_value * brokerage_rate

        # GST: 18% on brokerage
        gst = brokerage * TAX_CONFIG["gst"]

        # SEBI charges: 0.0001% of trade value
        sebi = trade_value * TAX_CONFIG["sebi_charges"]

        # Stamp duty: 0.015% of trade value
        stamp_duty = trade_value * TAX_CONFIG["stamp_duty"]

        total = stt + brokerage + gst + sebi + stamp_duty
        return total

    def _get_slippage_rate(self, ticker: str) -> float:
        """Get slippage rate based on market cap of ticker.

        Args:
            ticker: Stock ticker (e.g., 'RELIANCE.NS').

        Returns:
            Slippage rate as a decimal (e.g., 0.001 for 0.1%).
        """
        ticker_clean = ticker.replace(".NS", "").replace(".BO", "").upper()

        # Check predefined lists first
        if ticker_clean in POPULAR_INDIAN_STOCKS.get("large_cap", []):
            return 0.001  # 0.1% for large cap
        elif ticker_clean in POPULAR_INDIAN_STOCKS.get("mid_cap", []):
            return 0.005  # 0.5% for mid cap
        elif ticker_clean in POPULAR_INDIAN_STOCKS.get("small_cap", []):
            return 0.01   # 1.0% for small cap

        # Fallback: try yfinance for market cap
        try:
            import yfinance as yf
            ticker_obj = yf.Ticker(ticker)
            info = ticker_obj.info
            market_cap = info.get("marketCap", 0)

            if market_cap > 200_000_000_000:  # > 20,000 crore INR (200 billion)
                return 0.001
            elif market_cap > 50_000_000_000:  # > 5,000 crore (50 billion)
                return 0.005
            elif market_cap > 0:
                return 0.01
            else:
                return 0.005  # Default to 0.5% if market cap unknown
        except Exception:
            return 0.005  # Default to 0.5% on error

    def _check_circuit_limit(self, ticker: str, date, price: float) -> Optional[float]:
        """Check if stock hit circuit limit, return circuit price or None.

        Args:
            ticker: Stock ticker.
            date: Current date (string or datetime object).
            price: Current price of the stock.

        Returns:
            Circuit price if hit, else None.
        """
        from datetime import datetime, timedelta

        # Determine circuit percentage based on market cap
        ticker_clean = ticker.replace(".NS", "").replace(".BO", "").upper()
        if ticker_clean in POPULAR_INDIAN_STOCKS.get("large_cap", []):
            circuit_pct = 0.10  # 10% for large cap
        elif ticker_clean in POPULAR_INDIAN_STOCKS.get("mid_cap", []):
            circuit_pct = 0.15  # 15% for mid cap
        elif ticker_clean in POPULAR_INDIAN_STOCKS.get("small_cap", []):
            circuit_pct = 0.20  # 20% for small cap
        else:
            circuit_pct = 0.15  # Default to 15% if unknown

        # Get previous close price
        try:
            if isinstance(date, str):
                dt = datetime.strptime(date, '%Y-%m-%d')
            else:
                dt = date

            # Get previous trading day's close
            import yfinance as yf
            # Fetch data for the past week to get previous close
            start_date = dt - timedelta(days=7)
            end_date = dt + timedelta(days=1)
            data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)

            if data.empty:
                return None

            # Flatten MultiIndex if present
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.droplevel(1)

            # Get all close prices before or on the current date
            close_data = data[data.index <= dt]
            if close_data.empty:
                return None

            # Previous close is the last close before current date
            prev_close = float(close_data['Close'].iloc[-1])

            # Calculate circuit prices
            upper_circuit = prev_close * (1 + circuit_pct)
            lower_circuit = prev_close * (1 - circuit_pct)

            # Check if current price hit any circuit
            if price >= upper_circuit:
                return upper_circuit
            elif price <= lower_circuit:
                return lower_circuit
            else:
                return None
        except Exception:
            return None

    def _compute_metrics(self, capital_curve: list, trades: list,
                        start_date=None, end_date=None) -> Dict:
        """Compute common backtest metrics from capital curve and trades"""
        if not capital_curve:
            return {}
        series = pd.Series(capital_curve)
        returns = series.pct_change().dropna()
        running_max = series.cummax()
        drawdown = (series - running_max) / running_max
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        closed_trades = [
            t for t in trades
            if t.get('type') in {'SELL', 'CLOSE', 'COVER', 'OPTIONS_EXPIRE'}
            and 'profit' in t
        ]
        wins = sum(1 for t in closed_trades if t.get('profit', 0) > 0)
        metrics = {
            'max_drawdown_pct': round(drawdown.min() * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'win_rate': round(wins / max(len(closed_trades), 1), 2),
            'total_trades': len(trades)
        }
        # Compute CAGR if dates provided
        if start_date and end_date:
            try:
                s = datetime.strptime(start_date, '%Y-%m-%d')
                e = datetime.strptime(end_date, '%Y-%m-%d')
                years = (e - s).days / 365.25
                if years > 0 and capital_curve[0] > 0:
                    cagr = (capital_curve[-1] / capital_curve[0]) ** (1 / years) - 1
                    metrics['cagr_pct'] = round(cagr * 100, 2)
            except Exception:
                pass
        return metrics

    def buy_and_hold(self, ticker: str, start_date: str, end_date: str = None) -> Dict:
        """Benchmark: Simple buy and hold strategy with daily capital curve"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        data = self._flatten_df(data)

        if data.empty:
            return {'error': 'No data available'}

        initial_price = float(data['Close'].iloc[0])
        final_price = float(data['Close'].iloc[-1])
        shares = int(self.initial_capital / initial_price)
        remaining_cash = self.initial_capital - shares * initial_price

        final_value = shares * final_price + remaining_cash
        total_return = (final_value - self.initial_capital) / self.initial_capital * 100

        # Build real daily capital curve
        capital_curve = [
            float(data['Close'].iloc[i]) * shares + remaining_cash
            for i in range(len(data))
        ]
        # Proper trades list for metrics
        trades = [
            {'type': 'BUY',  'price': initial_price, 'date': str(data.index[0])[:10], 'profit': 0},
            {'type': 'SELL', 'price': final_price,   'date': str(data.index[-1])[:10],
             'profit': (final_price - initial_price) * shares}
        ]
        metrics = self._compute_metrics(capital_curve, trades=trades, start_date=start_date, end_date=end_date)

        return {
            'strategy': 'buy_and_hold',
            'ticker': ticker,
            'initial_capital': self.initial_capital,
            'final_value': round(final_value, 2),
            'return_pct': round(total_return, 2),
            'shares_held': shares,
            'start_date': start_date,
            'end_date': end_date,
            **metrics
        }

    def moving_average_crossover(self, ticker: str, start_date: str,
                                 fast_window: int = 20, slow_window: int = 50,
                                 end_date: str = None) -> Dict:
        """Moving Average Crossover Strategy"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        data = self._flatten_df(data)

        if data.empty or len(data) < slow_window:
            return {'error': 'Insufficient data'}

        # Calculate moving averages
        data['Fast_MA'] = data['Close'].rolling(fast_window).mean()
        data['Slow_MA'] = data['Close'].rolling(slow_window).mean()

        # Backtest
        capital = self.initial_capital
        capital_curve = [capital]
        position = 0
        shares = 0
        entry_price = 0
        trades = []

        for i in range(slow_window, len(data)):
            price = float(data['Close'].iloc[i])

            # Buy signal
            if data['Fast_MA'].iloc[i] > data['Slow_MA'].iloc[i] and position == 0:
                shares = int(capital * MAX_POSITION_PCT / price)
                if shares > 0:
                    trade_value = shares * price
                    if self.include_costs:
                        trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
                    if trade_value <= capital:
                        capital -= trade_value
                        entry_price = price
                        position = 1
                        capital_curve.append(capital + shares * price)
                        trades.append({'type': 'BUY', 'price': price,
                                       'shares': shares, 'date': str(data.index[i])[:10], 'profit': 0})

            # Sell signal
            elif data['Fast_MA'].iloc[i] < data['Slow_MA'].iloc[i] and position == 1:
                trade_value = shares * price
                if self.include_costs:
                    trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
                capital += trade_value
                profit = (price - entry_price) * shares
                if self.include_costs:
                    profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                position = 0
                capital_curve.append(capital)
                trades.append({'type': 'SELL', 'price': price,
                               'shares': shares, 'date': str(data.index[i])[:10],
                               'profit': round(profit, 2)})
                shares = 0

        # Close any open position
        if position == 1:
            final_price = float(data['Close'].iloc[-1])
            trade_value = shares * final_price
            if self.include_costs:
                trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
            capital += trade_value
            profit = (final_price - entry_price) * shares
            capital_curve.append(capital)
            trades.append({'type': 'CLOSE', 'price': final_price,
                           'shares': shares, 'date': str(data.index[-1])[:10],
                           'profit': round(profit, 2)})

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        metrics = self._compute_metrics(capital_curve, trades, start_date=start_date, end_date=end_date)
        return {
            'strategy': 'ma_crossover',
            'ticker': ticker,
            'initial_capital': self.initial_capital,
            'final_value': round(capital, 2),
            'return_pct': round(total_return, 2),
            'start_date': start_date,
            'end_date': end_date,
            **metrics,
            'trades': trades[:10]
        }

    def rsi_strategy(self, ticker: str, start_date: str,
                     oversold: int = 30, overbought: int = 70,
                     end_date: str = None) -> Dict:
        """RSI Mean Reversion Strategy"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        data = yf.download(ticker, start=start_date, end=end_date, progress=False, auto_adjust=True)
        data = self._flatten_df(data)

        if data.empty or len(data) < 20:
            return {'error': 'Insufficient data'}

        # Calculate RSI
        delta = data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        data['RSI'] = 100 - (100 / (1 + rs))

        # Backtest
        capital = self.initial_capital
        capital_curve = [capital]
        position = 0
        shares = 0
        entry_price = 0
        trades = []

        for i in range(14, len(data)):
            rsi = pd.to_numeric(data['RSI'].iloc[i], errors='coerce')
            price = float(data['Close'].iloc[i])

            # Buy when RSI oversold
            if rsi < float(oversold) and position == 0:
                shares = int(capital * MAX_POSITION_PCT / price)
                if shares > 0:
                    trade_value = shares * price
                    if self.include_costs:
                        trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
                    if trade_value <= capital:
                        capital -= trade_value
                        entry_price = price
                        position = 1
                        capital_curve.append(capital + shares * price)
                        trades.append({'type': 'BUY', 'price': price, 'rsi': rsi,
                                       'date': str(data.index[i])[:10], 'profit': 0})

            # Sell when RSI overbought
            elif rsi > float(overbought) and position == 1:
                trade_value = shares * price
                if self.include_costs:
                    trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
                capital += trade_value
                profit = (price - entry_price) * shares
                if self.include_costs:
                    profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                position = 0
                capital_curve.append(capital)
                trades.append({'type': 'SELL', 'price': price, 'rsi': rsi,
                               'date': str(data.index[i])[:10], 'profit': round(profit, 2)})
                shares = 0

        # Close open position
        if position == 1:
            final_price = float(data['Close'].iloc[-1])
            trade_value = shares * final_price
            if self.include_costs:
                trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
            capital += trade_value
            profit = (final_price - entry_price) * shares
            capital_curve.append(capital)
            trades.append({'type': 'CLOSE', 'price': final_price, 'rsi': rsi,
                           'date': str(data.index[-1])[:10], 'profit': round(profit, 2)})

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        metrics = self._compute_metrics(capital_curve, trades, start_date=start_date, end_date=end_date)
        return {
            'strategy': 'rsi_mean_reversion',
            'ticker': ticker,
            'initial_capital': self.initial_capital,
            'final_value': round(capital, 2),
            'return_pct': round(total_return, 2),
            'start_date': start_date,
            'end_date': end_date,
            **metrics,
            'trades': trades[:10]
        }

    def backtest_algorithm(self, algorithm, ticker: str,
                          start_date: str, end_date: str = None) -> Dict:
        """
        Walk-forward backtest of a production algorithm (e.g. IndianMomentumAlgorithm).
        Replays the algorithm day-by-day over historical data — no lookahead bias.
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        full_hist = yf.download(ticker, start=start_date, end=end_date,
                                progress=False, auto_adjust=True)
        full_hist = self._flatten_df(full_hist)

        if full_hist.empty or len(full_hist) < 60:
            return {'error': 'Insufficient historical data'}

        # Pre-download India VIX for the entire backtest period
        _vix_series = pd.Series(dtype=float)
        try:
            _vix_raw = yf.download('^INDIAVIX', start=start_date, end=end_date,
                                   progress=False, auto_adjust=True)
            _vix_raw = self._flatten_df(_vix_raw)
            if not _vix_raw.empty:
                _vix_series = _vix_raw['Close'].ffill()
        except Exception:
            pass  # Fallback to default VIX if download fails

        def _get_vix_for_date(dt) -> float:
            """Get VIX value for a given date, using latest available value (ffill)."""
            if _vix_series.empty:
                return 16.0  # Default fallback
            candidates = _vix_series[_vix_series.index <= dt]
            return float(candidates.iloc[-1]) if not candidates.empty else 16.0

        capital       = self.initial_capital
        capital_curve = [capital]
        position      = 0  # 0=none, 1=long, -1=short
        shares        = 0
        entry_price   = 0.0
        trades        = []
        position_values = []
        algo_name     = getattr(algorithm, 'name', algorithm.__class__.__name__)

        def mark_to_market(mark_price: float) -> float:
            if position == 1:
                return capital + shares * mark_price
            if position == -1:
                return capital - shares * mark_price
            return capital

        # Walk forward: give algorithm a growing window of history each day
        warmup = 60  # Minimum rows needed for indicators
        sig_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}

        # Initialize risk manager for Kelly sizing
        if not hasattr(self, '_risk_mgr'):
            self._risk_mgr = _RM(initial_capital=self.initial_capital)

        # ATR-based exit multipliers by regime
        STOP_MULT = {
            'BULL_TREND': 1.5, 'BULL_VOLATILE': 2.0, 'BEAR_TREND': 1.5,
            'BEAR_VOLATILE': 1.0, 'SIDEWAYS_LOW_VOL': 1.5, 'SIDEWAYS_HIGH_VOL': 1.0,
            'CRISIS': 1.0, None: 1.5
        }
        TARGET_MULT = {
            'BULL_TREND': 3.5, 'BULL_VOLATILE': 2.5, 'BEAR_TREND': 2.0,
            'BEAR_VOLATILE': 2.0, 'SIDEWAYS_LOW_VOL': 2.0, 'SIDEWAYS_HIGH_VOL': 1.5,
            'CRISIS': 1.5, None: 2.5
        }

        for i in range(warmup, len(full_hist)):
            window    = full_hist.iloc[:i+1]      # Include current day for expiry checks
            row       = full_hist.iloc[i]
            price     = float(row['Close'])
            date_str  = str(full_hist.index[i])[:10]
            current_date = full_hist.index[i]
            curve_len_before = len(capital_curve)

            # Check circuit limit
            circuit_price = self._check_circuit_limit(ticker, current_date, price)
            if circuit_price is not None:
                if position == 1:
                    exit_price = circuit_price
                    trade_value = shares * exit_price
                    if self.include_costs:
                        trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
                    capital += trade_value
                    profit = (exit_price - entry_price) * shares
                    if self.include_costs:
                        profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                    position = 0
                    capital_curve.append(capital)
                    trades.append({'type': 'CIRCUIT_CLOSE', 'price': exit_price,
                                   'shares': shares, 'date': date_str,
                                   'profit': round(profit, 2)})
                    self._risk_mgr.record_trade_history(
                        ticker=ticker,
                        side='SELL',
                        pnl=profit
                    )
                    shares = 0
                    continue
                elif position == -1:
                    exit_price = circuit_price
                    trade_value = shares * exit_price
                    if self.include_costs:
                        trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
                    capital -= trade_value
                    profit = (entry_price - exit_price) * shares
                    if self.include_costs:
                        profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                    position = 0
                    capital_curve.append(capital)
                    trades.append({'type': 'CIRCUIT_CLOSE', 'price': exit_price,
                                   'shares': shares, 'date': date_str,
                                   'profit': round(profit, 2)})
                    self._risk_mgr.record_trade_history(
                        ticker=ticker,
                        side='BUY',
                        pnl=profit
                    )
                    shares = 0
                    continue

            try:
                result = algorithm.analyze(ticker, window)
            except Exception as e:
                if i % 100 == 0:
                    logger.error(f"Analysis crash at {date_str}: {e}")
                capital_curve.append(mark_to_market(price))
                continue

            if 'error' in result:
                capital_curve.append(mark_to_market(price))
                continue

            sig  = result.get('signal', 'HOLD')
            conf = result.get('confidence', 0.5)
            sig_counts[sig] = sig_counts.get(sig, 0) + 1
            
            # Use strategy's suggested stops/targets if provided
            suggested_sl = result.get('stop_loss')
            suggested_tp = result.get('price_target')

            # Entry - Long
            if sig == 'BUY' and position == 0 and conf >= 0.50:
                # Check circuit breaker before every entry
                if self._risk_mgr.check_consecutive_losses(max_consecutive=3):
                    continue

                shares = self._risk_mgr.size_position_kelly(
                    price=price,
                    confidence=conf,
                    win_rate=getattr(algorithm, '_win_rate', 0.52),
                    avg_win=getattr(algorithm, '_avg_win', 0.08),
                    avg_loss=getattr(algorithm, '_avg_loss', 0.04),
                )
                if shares <= 0:
                    continue
                if shares > 0:
                    if not self._passes_liquidity_filter(row, shares, price):
                        continue
                    price = self._liquidity_adjusted_price(row, shares, 'BUY', ticker)
                    trade_value = shares * price
                    if self.include_costs:
                        trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
                    if trade_value <= capital:
                        capital    -= trade_value
                        entry_price = price
                        position    = 1
                        # Lock in SL/TP at entry
                        active_sl = suggested_sl
                        active_tp = suggested_tp
                        position_values.append(trade_value)
                        capital_curve.append(capital + shares * price)
                        trades.append({'type': 'BUY', 'price': price,
                                       'shares': shares, 'date': date_str, 'profit': 0})

            # Entry - Short (for SELL signals / options selling)
            elif sig == 'SELL' and position == 0 and conf >= 0.50:
                # ... (options writer logic remains same)
                if 'Options Writer' in algo_name or 'options_writer' in algo_name.lower():
                    # Simulate options writing - collect premium
                    try:
                        india_vix = _get_vix_for_date(full_hist.index[i])  # Dynamic VIX from historical data
                        lot_size = get_lot_size(ticker) or 1
                        options_result = simulate_options_write(
                            price, india_vix, days_to_expiry=1, lot_size=lot_size
                        )
                        premium = options_result['total_premium']
                        call_strike = options_result['call_strike']
                        put_strike = options_result['put_strike']
                        call_breakeven = options_result['call_breakeven']
                        put_breakeven = options_result['put_breakeven']

                        # Book premium as immediate income
                        capital += premium
                        position = -2  # Special marker for options position
                        entry_price = price
                        capital_curve.append(capital)
                        trades.append({
                            'type': 'OPTIONS_WRITE',
                            'price': price,
                            'premium': premium,
                            'point_premium': options_result.get('point_premium', premium),
                            'lot_size': lot_size,
                            'call_strike': call_strike,
                            'put_strike': put_strike,
                            'call_breakeven': call_breakeven,
                            'put_breakeven': put_breakeven,
                            'date': date_str,
                            'profit': premium
                        })
                        continue
                    except Exception:
                        # Fallback to regular short if options pricer fails
                        pass

                # Regular short position for non-options algorithms
                # Check circuit breaker before every entry
                if self._risk_mgr.check_consecutive_losses(max_consecutive=3):
                    continue

                shares = self._risk_mgr.size_position_kelly(
                    price=price,
                    confidence=conf,
                    win_rate=getattr(algorithm, '_win_rate', 0.52),
                    avg_win=getattr(algorithm, '_avg_win', 0.08),
                    avg_loss=getattr(algorithm, '_avg_loss', 0.04),
                )
                if shares <= 0:
                    continue
                if shares > 0:
                    if not self._passes_liquidity_filter(row, shares, price):
                        continue
                    price = self._liquidity_adjusted_price(row, shares, 'SELL', ticker)
                    trade_value = shares * price
                    if self.include_costs:
                        trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
                    capital += trade_value  # Credit from short sale
                    entry_price = price
                    position    = -1
                    # Lock in SL/TP at entry
                    active_sl = suggested_sl
                    active_tp = suggested_tp
                    position_values.append(trade_value)
                    capital_curve.append(capital - shares * price)
                    trades.append({'type': 'SHORT', 'price': price,
                                       'shares': shares, 'date': date_str, 'profit': 0})

            # Exit Long
            elif position == 1:
                profit_pct = (price - entry_price) / entry_price * 100
                
                # Dynamic Exit Conditions
                is_sl = (active_sl is not None and price <= active_sl) or profit_pct <= -10.0
                is_tp = (active_tp is not None and price >= active_tp) or profit_pct >= 20.0
                
                if sig == 'SELL' or is_sl or is_tp:
                    exit_price = self._liquidity_adjusted_price(row, shares, 'SELL', ticker)
                    trade_value = shares * exit_price
                    if self.include_costs:
                        trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
                    capital += trade_value
                    profit = (exit_price - entry_price) * shares
                    if self.include_costs:
                        profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                    position = 0
                    capital_curve.append(capital)
                    reason = "SIGNAL" if sig == 'SELL' else "SL" if is_sl else "TP"
                    trades.append({'type': 'SELL', 'price': exit_price,
                                   'shares': shares, 'date': date_str,
                                   'profit': round(profit, 2), 'reason': reason})
                    # Record outcome for Kelly evolution
                    self._risk_mgr.record_trade_history(
                        ticker=ticker,
                        side='SELL',
                        pnl=profit
                    )
                    shares = 0

            # Exit Short
            elif position == -1:
                profit_pct = (entry_price - price) / entry_price * 100
                
                # Dynamic Exit Conditions
                is_sl = (active_sl is not None and price >= active_sl) or profit_pct <= -10.0
                is_tp = (active_tp is not None and price <= active_tp) or profit_pct >= 20.0
                
                if sig == 'BUY' or is_sl or is_tp:
                    # Buy back to close short
                    exit_price = self._liquidity_adjusted_price(row, shares, 'COVER', ticker)
                    trade_value = shares * exit_price
                    if self.include_costs:
                        trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
                    capital -= trade_value
                    profit = (entry_price - exit_price) * shares
                    if self.include_costs:
                        profit -= self._calculate_indian_costs(shares * entry_price, trade_type='equity')
                    position = 0
                    capital_curve.append(capital)
                    reason = "SIGNAL" if sig == 'BUY' else "SL" if is_sl else "TP"
                    trades.append({'type': 'COVER', 'price': exit_price,
                                   'shares': shares, 'date': date_str,
                                   'profit': round(profit, 2), 'reason': reason})
                    self._risk_mgr.record_trade_history(
                        ticker=ticker,
                        side='BUY',
                        pnl=profit
                    )
                    shares = 0

            # Exit Options Position (end of day - check if spot moved past breakeven)
            elif position == -2:
                # Get breakeven levels from the last trade
                if trades and trades[-1].get('type') == 'OPTIONS_WRITE':
                    call_breakeven = trades[-1].get('call_breakeven', entry_price * 1.05)
                    put_breakeven = trades[-1].get('put_breakeven', entry_price * 0.95)
                    premium = trades[-1].get('premium', 0)
                    lot_size = trades[-1].get('lot_size', 1)

                    # Check if spot moved past breakeven (options expired ITM)
                    if price > call_breakeven:
                        # Call expired ITM - point loss scaled by lot size
                        loss = (price - call_breakeven) * lot_size
                        capital -= loss
                        profit = premium - loss
                    elif price < put_breakeven:
                        # Put expired ITM - point loss scaled by lot size
                        loss = (put_breakeven - price) * lot_size
                        capital -= loss
                        profit = premium - loss
                    else:
                        # Both expired OTM - keep full premium
                        profit = premium

                    position = 0
                    capital_curve.append(capital)
                    trades.append({'type': 'OPTIONS_EXPIRE', 'price': price,
                                   'date': date_str, 'profit': round(profit, 2)})
                    # Record outcome for Kelly evolution
                    self._risk_mgr.record_trade_history(
                        ticker=ticker,
                        side='SELL',
                        pnl=profit
                    )

            else:
                # Mark-to-market the open position
                if position == 1:
                    capital_curve.append(capital + shares * price)
                elif position == -1:
                    capital_curve.append(capital - shares * price)
                elif position == -2:
                    # Options position - premium already booked, show capital as is
                    capital_curve.append(capital)
                else:
                    capital_curve.append(capital)

            if len(capital_curve) == curve_len_before:
                capital_curve.append(mark_to_market(price))

        print(f"  Signal counts: {sig_counts}")
        print(f"  Total trades: {len(trades)}")

        # Close any remaining position
        if position == 1:
            final_price = float(full_hist['Close'].iloc[-1])
            trade_value = shares * final_price
            if self.include_costs:
                trade_value -= self._calculate_indian_costs(trade_value, trade_type='equity')
            capital += trade_value
            profit = (final_price - entry_price) * shares
            capital_curve.append(capital)
            trades.append({'type': 'CLOSE', 'price': final_price,
                           'shares': shares, 'date': str(full_hist.index[-1])[:10],
                           'profit': round(profit, 2)})
        elif position == -1:
            final_price = float(full_hist['Close'].iloc[-1])
            trade_value = shares * final_price
            if self.include_costs:
                trade_value += self._calculate_indian_costs(trade_value, trade_type='equity')
            capital -= trade_value
            profit = (entry_price - final_price) * shares
            capital_curve.append(capital)
            trades.append({'type': 'CLOSE', 'price': final_price,
                           'shares': shares, 'date': str(full_hist.index[-1])[:10],
                           'profit': round(profit, 2)})
        elif position == -2 and trades and trades[-1].get('type') == 'OPTIONS_WRITE':
            final_price = float(full_hist['Close'].iloc[-1])
            call_breakeven = trades[-1].get('call_breakeven', entry_price * 1.05)
            put_breakeven = trades[-1].get('put_breakeven', entry_price * 0.95)
            premium = trades[-1].get('premium', 0)
            lot_size = trades[-1].get('lot_size', 1)
            if final_price > call_breakeven:
                loss = (final_price - call_breakeven) * lot_size
                capital -= loss
                profit = premium - loss
            elif final_price < put_breakeven:
                loss = (put_breakeven - final_price) * lot_size
                capital -= loss
                profit = premium - loss
            else:
                profit = premium
            capital_curve.append(capital)
            trades.append({'type': 'OPTIONS_EXPIRE', 'price': final_price,
                           'date': str(full_hist.index[-1])[:10],
                           'profit': round(profit, 2)})

        total_return = (capital - self.initial_capital) / self.initial_capital * 100
        metrics = self._compute_metrics(capital_curve, trades, start_date=start_date, end_date=end_date)
        return {
            'strategy': algo_name,
            'ticker': ticker,
            'initial_capital': self.initial_capital,
            'final_value': round(capital, 2),
            'return_pct': round(total_return, 2),
            'start_date': start_date,
            'end_date': end_date,
            **metrics,
            'avg_position_pct': round(
                float(np.mean(position_values) / self.initial_capital) if position_values else 0.0,
                4
            ),
            'trades': trades
        }

    def compare_strategies(self, ticker: str, start_date: str, end_date: str = None) -> Dict:
        """Compare multiple strategies on the same ticker"""
        results = {}

        # Buy and Hold
        results['buy_hold'] = self.buy_and_hold(ticker, start_date, end_date)

        # MA Crossover
        results['ma_crossover'] = self.moving_average_crossover(ticker, start_date, end_date)

        # RSI Strategy
        results['rsi'] = self.rsi_strategy(ticker, start_date, end_date)

        # Find best strategy
        best_strategy = max(results.items(), key=lambda x: x[1].get('return_pct', -999))

        return {
            'ticker': ticker,
            'strategies': results,
            'best_strategy': best_strategy[0],
            'best_return': best_strategy[1].get('return_pct', 0)
        }
