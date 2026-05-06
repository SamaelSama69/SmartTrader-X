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
    asset_type TEXT DEFAULT 'EQUITY'
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
            
        self.conn.commit()

    def log_action(self, ticker, action_type, details, source="SYSTEM"):
        """Record an event in the Actions Hub."""
        self.conn.execute(
            "INSERT INTO action_logs (timestamp, ticker, action_type, details, source) VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), ticker, action_type, details, source)
        )
        self.conn.commit()

    def open_trade(self, ticker, signal, entry_price, shares, stop_loss, target, sector=None, asset_type='EQUITY', source='BOT'):
        trade_id = f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.conn.execute(
            "INSERT INTO paper_trades (id, ticker, signal, entry_price, shares, stop_loss, target, opened_at, status, sector, asset_type) VALUES (?,?,?,?,?,?,?,?,'OPEN',?,?)",
            (trade_id, ticker, signal, entry_price, shares, stop_loss, target,
             datetime.now().isoformat(), sector, asset_type)
        )
        self.conn.commit()
        
        # Log to Actions Hub
        self.log_action(ticker, f"OPEN_{signal}", f"Price: ₹{entry_price:.2f}, Qty: {shares}, SL: {stop_loss}, TP: {target}", source=source)
        return trade_id

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
        rows = cursor.fetchall()
        closed_trades_summary = []
        for row in rows:
            id_, ticker, signal, entry, shares, stop, target, opened, *_ = row
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
                    'reason': reason
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
