"""
Portfolio Backtester - Realistic multi-asset simulation with capital constraints.
Replays AutonomousBot logic over a basket of stocks simultaneously.
"""
import pandas as pd
import numpy as np
import logging
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
from utils.risk_manager import RiskManager
from indian_config import POPULAR_INDIAN_STOCKS

logger = logging.getLogger(__name__)

class PortfolioBacktester:
    """Simulates a multi-stock portfolio with finite capital and risk limits."""

    def __init__(self, initial_capital: float = 1000000.0, max_positions: int = 10):
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.risk_mgr = RiskManager(initial_capital=initial_capital)
        self.risk_mgr.max_open_positions = max_positions
        
    def run_backtest(self, algorithm, tickers: List[str], start_date: str, end_date: str) -> Dict:
        """
        Runs a comprehensive portfolio backtest.
        Handles daily rebalancing and signal processing for all tickers in parallel.
        """
        logger.info(f"Starting Portfolio Backtest for {len(tickers)} tickers from {start_date} to {end_date}")
        
        # 1. Download all data in one go (with extra history for warmup)
        target_start = pd.to_datetime(start_date)
        fetch_start = (target_start - timedelta(days=400)).strftime('%Y-%m-%d')
        
        data = yf.download(tickers, start=fetch_start, end=end_date, group_by='ticker', auto_adjust=True, progress=False)
        bench = yf.download('^NSEI', start=fetch_start, end=end_date, auto_adjust=True, progress=False)
        
        if data.empty:
            return {"error": "No data found for the given tickers/dates."}

        # Align all dates but only iterate from target_start
        all_dates = sorted(data.index.unique())
        test_dates = [d for d in all_dates if d >= target_start]
        
        # State tracking
        portfolio_cash = self.initial_capital
        open_trades = {} # ticker -> {shares, entry_price, sl, tp, sector}
        capital_curve = []
        trade_log = []
        
        # 2. Daily Simulation Loop
        for current_date in test_dates:
            date_str = str(current_date)[:10]
            
            # --- A. Update Mark-to-Market ---
            invested_value = 0
            for ticker, trade in open_trades.items():
                try:
                    price = data[ticker]['Close'].loc[current_date]
                    if pd.isna(price): continue
                    invested_value += trade['shares'] * price
                except: continue
            
            current_total_value = portfolio_cash + invested_value
            capital_curve.append({"date": date_str, "value": current_total_value})
            self.risk_mgr.current_capital = current_total_value

            # --- B. Manage Exits (SL/TP) ---
            to_close = []
            for ticker, trade in open_trades.items():
                try:
                    price = data[ticker]['Close'].loc[current_date]
                    if pd.isna(price): continue
                    
                    # Logic matches PaperTradeManager
                    is_sl = (trade['sl'] and price <= trade['sl'])
                    is_tp = (trade['tp'] and price >= trade['tp'])
                    
                    if is_sl or is_tp:
                        to_close.append((ticker, price, "SL" if is_sl else "TP"))
                except: continue
            
            for ticker, price, reason in to_close:
                trade = open_trades.pop(ticker)
                val = trade['shares'] * price
                # Simplified cost calculation
                cost = val * 0.001 
                portfolio_cash += (val - cost)
                pnl = (price - trade['entry_price']) * trade['shares']
                trade_log.append({
                    "ticker": ticker, "action": "EXIT", "date": date_str, 
                    "price": price, "shares": trade['shares'], "reason": reason, "pnl": pnl
                })
                self.risk_mgr.record_trade(ticker, trade['shares'], price, 'SELL')

            # --- C. Process New Signals ---
            if len(open_trades) < self.max_positions:
                # Rank available tickers by confidence (simulating Bot scan)
                signals = []
                for ticker in tickers:
                    if ticker in open_trades: continue
                    try:
                        # Extract window up to today (max 400 days for MAs)
                        window = data[ticker].loc[:current_date].tail(400)
                        if len(window) < 50: continue
                        
                        # Note: backtest doesn't have live sentiment, usually mocked or neutral
                        result = algorithm.analyze(ticker, window)
                        if result['signal'] == 'BUY' and result['confidence'] > 0.5:
                            signals.append({"ticker": ticker, "result": result})
                    except: continue
                
                # Sort signals by confidence
                signals = sorted(signals, key=lambda x: x['result']['confidence'], reverse=True)
                
                for sig in signals:
                    if len(open_trades) >= self.max_positions: break
                    ticker = sig['ticker']
                    res = sig['result']
                    
                    # FIX: Use the window's last price as the current simulation price
                    # to avoid KeyError if the strategy doesn't return it.
                    price = res.get('current_price')
                    if price is None:
                        try:
                            price = float(data[ticker]['Close'].loc[:current_date].iloc[-1])
                        except:
                            continue # Skip if price data is missing
                    
                    # Risk Check
                    shares = self.risk_mgr.size_position_kelly(price, res['confidence'])
                    check = self.risk_mgr.check_trade(ticker, shares, price)
                    
                    if check['allowed'] and check['adjusted_shares'] > 0:
                        final_shares = check['adjusted_shares']
                        cost = final_shares * price * 1.001
                        if cost <= portfolio_cash:
                            portfolio_cash -= cost
                            open_trades[ticker] = {
                                "shares": final_shares, "entry_price": price,
                                "sl": res['stop_loss'], "tp": res['price_target'],
                                "sector": "UNKNOWN" # Mapping could be added
                            }
                            trade_log.append({
                                "ticker": ticker, "action": "ENTRY", "date": date_str,
                                "price": price, "shares": final_shares, "reason": "SIGNAL"
                            })
                            self.risk_mgr.record_trade(ticker, final_shares, price, 'BUY')

        # 3. Finalize Metrics
        df_curve = pd.DataFrame(capital_curve)
        df_curve['returns'] = df_curve['value'].pct_change()
        
        total_return = (df_curve['value'].iloc[-1] / self.initial_capital - 1) * 100
        sharpe = (df_curve['returns'].mean() / df_curve['returns'].std()) * np.sqrt(252) if df_curve['returns'].std() > 0 else 0
        
        return {
            "summary": {
                "initial": self.initial_capital,
                "final": float(df_curve['value'].iloc[-1]),
                "return_pct": total_return,
                "sharpe": sharpe,
                "total_trades": len(trade_log)
            },
            "capital_curve": capital_curve,
            "trade_log": trade_log
        }
