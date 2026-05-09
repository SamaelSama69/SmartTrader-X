"""
PaperTradeManager — tracks open/closed paper trades with real P&L.
Replaces the broken record_trade_history(ticker, signal, 0.0) calls.
"""
import sqlite3
from pathlib import Path
from datetime import datetime
import logging
import yfinance as yf

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[1] / 'memory' / 'paper_trades.db'

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    signal TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares INTEGER NOT NULL,
    stop_loss REAL,
    target REAL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    pnl_pct REAL,
    status TEXT DEFAULT 'OPEN',
    sector TEXT,
    asset_type TEXT DEFAULT 'EQUITY',
    prediction_id TEXT,
    strategy TEXT DEFAULT 'unknown',
    trade_mode TEXT DEFAULT 'SWING',
    is_manual BOOLEAN DEFAULT 0
)
"""

ACTIONS_SQL = """
CREATE TABLE IF NOT EXISTS action_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    ticker TEXT,
    action_type TEXT NOT NULL,
    details TEXT,
    source TEXT DEFAULT 'SYSTEM'
)
"""

class PaperTradeManager:
    def __init__(self):
        # Use check_same_thread=False for Streamlit multi-threading compatibility
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.execute(CREATE_SQL)
        self.conn.execute(ACTIONS_SQL)
        
        # Migrations
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN sector TEXT")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN asset_type TEXT DEFAULT 'EQUITY'")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN prediction_id TEXT")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN strategy TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN trade_mode TEXT DEFAULT 'SWING'")
        except sqlite3.OperationalError: pass
        try: self.conn.execute("ALTER TABLE paper_trades ADD COLUMN is_manual BOOLEAN DEFAULT 0")
        except sqlite3.OperationalError: pass
            
        self.conn.commit()

    def log_action(self, ticker, action_type, details, source="SYSTEM"):
        """Record an event in the Actions Hub."""
        self.conn.execute(
            "INSERT INTO action_logs (timestamp, ticker, action_type, details, source) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), ticker, action_type, details, source)
        )
        self.conn.commit()

    def open_trade(self, ticker, signal, entry_price, shares, stop_loss, target, sector=None, asset_type='EQUITY', source='BOT', prediction_id='', strategy='unknown', trade_mode='SWING', is_manual=False):
        trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        is_man_int = 1 if is_manual else 0
        self.conn.execute(
            "INSERT INTO paper_trades (id, ticker, signal, entry_price, shares, stop_loss, target, opened_at, status, sector, asset_type, prediction_id, strategy, trade_mode, is_manual) VALUES (?,?,?,?,?,?,?,?,'OPEN',?,?,?,?,?,?)",
            (trade_id, ticker, signal, entry_price, shares, stop_loss, target,
             datetime.now().isoformat(), sector, asset_type, prediction_id, strategy, trade_mode, is_man_int)
        )
        self.conn.commit()
        
        # Log to Actions Hub
        mode_str = "MANUAL " if is_manual else ""
        self.log_action(ticker, f"OPEN_{signal}", f"{mode_str}{trade_mode} | Price: ₹{entry_price:.2f}, Qty: {shares}, SL: {stop_loss}, TP: {target}", source=source)
        return trade_id

    def update_trade_mode(self, trade_id, new_mode, source='BOT'):
        """Update trade_mode (e.g., SWING -> INTRADAY)."""
        cursor = self.conn.execute("SELECT ticker, trade_mode FROM paper_trades WHERE id=?", (trade_id,))
        row = cursor.fetchone()
        if not row: return False
        ticker, old_mode = row

        self.conn.execute(
            "UPDATE paper_trades SET trade_mode=? WHERE id=?",
            (new_mode, trade_id)
        )
        self.conn.commit()
        self.log_action(ticker, "MODE_UPDATE", f"{old_mode} -> {new_mode}", source=source)
        return True

    def close_trade(self, trade_id, exit_price, reason="MANUAL", source='USER'):
        """Force close a specific trade with a given reason."""
        cursor = self.conn.execute("SELECT * FROM paper_trades WHERE id=?", (trade_id,))
        row = cursor.fetchone()
        if not row: return False
        
        # Unpack row
        id_, ticker, signal, entry, shares, stop, target, opened, *_ = row
        pnl_pct = 0.0
        if signal == 'BUY':
            pnl_pct = (exit_price - entry) / entry
        else:
            # Short P&L: (Entry - Exit) / Entry
            pnl_pct = (entry - exit_price) / entry
            
        self.conn.execute(
            "UPDATE paper_trades SET status='CLOSED', closed_at=?, exit_price=?, pnl_pct=? WHERE id=?",
            (datetime.now().isoformat(), exit_price, pnl_pct, trade_id)
        )
        self.conn.commit()
        
        # Log to Actions Hub
        self.log_action(ticker, f"CLOSE_{reason}", f"Exit: ₹{exit_price:.2f}, P&L: {pnl_pct:+.2%}", source=source)
        
        logger.info(f"[PAPER] {reason} EXIT {ticker}: P&L={pnl_pct:+.2%}")
        return True

    def update_trade_targets(self, trade_id, stop_loss, target, source='USER'):
        """Update SL and TP for an existing trade."""
        cursor = self.conn.execute("SELECT ticker FROM paper_trades WHERE id=?", (trade_id,))
        row = cursor.fetchone()
        ticker = row[0] if row else "Unknown"

        self.conn.execute(
            "UPDATE paper_trades SET stop_loss=?, target=? WHERE id=?",
            (stop_loss, target, trade_id)
        )
        self.conn.commit()
        
        # Log to Actions Hub
        self.log_action(ticker, "REPAIR_TARGETS", f"New SL: {stop_loss}, New TP: {target}", source=source)
        return True

    def close_positions(self, perf_tracker=None):
        """Check all open positions and close those that hit stop or target."""
        cursor = self.conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'")
        cols = [d[0] for d in cursor.description]
        rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        closed_trades_summary = []
        for pos in rows:
            id_ = pos['id']
            ticker = pos['ticker']
            signal = pos['signal']
            entry = pos['entry_price']
            shares = pos['shares']
            stop = pos.get('stop_loss')
            target = pos.get('target')
            try:
                yf_ticker = ticker if (ticker.endswith('.NS') or ticker.endswith('.BO')) else f"{ticker}.NS"
                current = float(yf.Ticker(yf_ticker).fast_info.get('lastPrice', 0) or 0)
            except Exception: continue
            if current <= 0: continue

            closed = False
            pnl_pct = 0.0
            reason = "TP"
            if signal == 'BUY':
                if stop and current <= stop:
                    pnl_pct = (current - entry) / entry
                    closed = True; reason = "SL"
                elif target and current >= target:
                    pnl_pct = (current - entry) / entry
                    closed = True; reason = "TP"
            elif signal in ('SHORT', 'SELL'):
                if stop and current >= stop:
                    pnl_pct = (entry - current) / entry
                    closed = True; reason = "SL"
                elif target and current <= target:
                    pnl_pct = (entry - current) / entry
                    closed = True; reason = "TP"

            if closed:
                self.conn.execute(
                    "UPDATE paper_trades SET status='CLOSED', closed_at=?, exit_price=?, pnl_pct=? WHERE id=?",
                    (datetime.now().isoformat(), current, pnl_pct, id_)
                )
                self.conn.commit()
                
                summary = {
                    'ticker': ticker,
                    'signal': signal,
                    'exit_price': current,
                    'pnl_pct': pnl_pct * 100,
                    'reason': reason,
                    'prediction_id': pos.get('prediction_id', ''),
                    'strategy': pos.get('strategy', 'unknown'),
                }
                closed_trades_summary.append(summary)
                
                # Log to Actions Hub
                self.log_action(ticker, f"AUTO_EXIT_{reason}", f"Exit: ₹{current:.2f}, P&L: {pnl_pct:+.2%}", source='BOT')
                
                logger.info(f"[PAPER] Closed {signal} {ticker}: P&L={pnl_pct:+.2%}")
                if perf_tracker:
                    perf_tracker.record_trade_history(ticker, signal, pnl_pct)
        return closed_trades_summary

    def get_open_positions(self):
        """Return list of current open paper positions."""
        cursor = self.conn.execute("SELECT * FROM paper_trades WHERE status='OPEN'")
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_portfolio_summary(self):
        """Calculate total P&L and metrics for paper trading portfolio."""
        cursor = self.conn.execute("SELECT * FROM paper_trades")
        cols = [d[0] for d in cursor.description]
        all_trades = [dict(zip(cols, row)) for row in cursor.fetchall()]
        open_trades = [t for t in all_trades if t['status'] == 'OPEN']
        closed_trades = [t for t in all_trades if t['status'] == 'CLOSED']
        realized_pnl = sum(t['pnl_pct'] for t in closed_trades if t['pnl_pct'] is not None)
        win_rate = len([t for t in closed_trades if (t['pnl_pct'] or 0) > 0]) / len(closed_trades) if closed_trades else 0
        return {
            'total_trades': len(all_trades), 'open_count': len(open_trades), 'closed_count': len(closed_trades),
            'realized_pnl_pct': realized_pnl * 100, 'win_rate': win_rate * 100, 'open_positions': open_trades
        }
    
    def get_action_logs(self, limit=100):
        """Return recent logs from the Actions Hub."""
        cursor = self.conn.execute("SELECT * FROM action_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def apply_trailing_stops(self, atr_trail: float = 2.0) -> list:
        """
        Update stop losses on open positions using a trailing ATR stop.
        Raises the stop loss on winning positions — never lowers it.
        Returns list of tickers with updated stops.
        """
        import yfinance as yf
        import pandas as pd
        updated = []
        positions = self.get_open_positions()
        for pos in positions:
            try:
                ticker = pos['ticker']
                yf_t = ticker if ticker.endswith('.NS') or ticker.endswith('.BO') else f"{ticker}.NS"
                hist = yf.Ticker(yf_t).history(period='1mo', auto_adjust=True)
                if hist.empty or len(hist) < 14:
                    continue

                # ATR(14)
                hl = hist['High'] - hist['Low']
                hc = (hist['High'] - hist['Close'].shift()).abs()
                lc = (hist['Low'] - hist['Close'].shift()).abs()
                tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
                atr = tr.rolling(14).mean().iloc[-1]
                current_price = float(hist['Close'].iloc[-1])

                if pos['signal'] == 'BUY':
                    new_stop = round(current_price - atr_trail * atr, 2)
                    old_stop = pos.get('stop_loss') or 0
                    if new_stop > old_stop:   # Only move stop UP, never down
                        self._update_stop(pos['id'], new_stop)
                        updated.append({'ticker': ticker, 'old_stop': old_stop, 'new_stop': new_stop})
                elif pos['signal'] in ('SELL', 'SHORT'):
                    new_stop = round(current_price + atr_trail * atr, 2)
                    old_stop = pos.get('stop_loss') or float('inf')
                    if new_stop < old_stop:   # Only move stop DOWN for shorts
                        self._update_stop(pos['id'], new_stop)
                        updated.append({'ticker': ticker, 'old_stop': old_stop, 'new_stop': new_stop})
            except Exception as e:
                logger.debug(f"Trailing stop error for {pos.get('ticker', '?')}: {e}")
        return updated

    def _update_stop(self, trade_id: str, new_stop: float):
        """Persist the updated stop loss for an open position."""
        self.conn.execute(
            "UPDATE paper_trades SET stop_loss = ? WHERE id = ? AND status = 'OPEN'",
            (new_stop, trade_id)
        )
        self.conn.commit()
