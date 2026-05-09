"""
SQLite database for persistent, concurrent-safe storage
Replaces JSON files for better querying and multi-process access
"""
import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime
import threading


class Database:
    """SQLite-backed storage for SmartTrader"""

    def __init__(self, db_path: str = "smart_trader.db"):
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self):
        """Get a thread-local connection"""
        return sqlite3.connect(str(self.db_path), check_same_thread=False)

    def _init_db(self):
        """Initialize database tables"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Predictions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS predictions (
                    id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    prediction TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    outcome_recorded INTEGER DEFAULT 0,
                    outcome_data TEXT
                )
            ''')

            # Migration: add outcome_data column to existing DBs
            try:
                cursor.execute("ALTER TABLE predictions ADD COLUMN outcome_data TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Outcomes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    correct INTEGER,
                    timestamp TEXT NOT NULL
                )
            ''')

            # Trade logs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trade_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    side TEXT NOT NULL,
                    shares INTEGER,
                    price REAL,
                    timestamp TEXT NOT NULL,
                    pnl REAL
                )
            ''')

            # Sentiment table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sentiment (
                    ticker TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    headlines TEXT NOT NULL,
                    snippets TEXT,
                    reason TEXT,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Market context table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS market_context (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                )
            ''')

            # Strategy performance table (replaces JSON file)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    algorithm TEXT NOT NULL,
                    signal TEXT NOT NULL,
                    pnl_pct REAL NOT NULL,
                    outcome TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            ''')

            conn.commit()
            conn.close()

    def save_prediction(self, pred: Dict):
        """Save a prediction to database"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO predictions (id, ticker, prediction, timestamp, outcome_recorded) VALUES (?, ?, ?, ?, ?)",
                (
                    pred['id'],
                    pred['ticker'],
                    json.dumps(pred['prediction']),
                    pred['timestamp'],
                    1 if pred.get('outcome_recorded') else 0
                )
            )
            conn.commit()
            conn.close()

    def get_predictions(self, ticker: Optional[str] = None) -> List[Dict]:
        """Get predictions, optionally filtered by ticker"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()

            if ticker:
                cursor.execute("SELECT * FROM predictions WHERE ticker = ?", (ticker,))
            else:
                cursor.execute("SELECT * FROM predictions")

            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    'id': row[0],
                    'ticker': row[1],
                    'prediction': json.loads(row[2]),
                    'timestamp': row[3],
                    'outcome_recorded': bool(row[4])
                }
                for row in rows
            ]

    def log_trade(self, ticker: str, side: str, shares: int, price: float, pnl: float = 0):
        """Log a trade to database"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO trade_logs (ticker, side, shares, price, timestamp, pnl) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticker, side, shares, price,
                    datetime.now().isoformat(),
                    pnl
                )
            )
            conn.commit()
            conn.close()

    def update_sentiment(self, ticker: str, score: float, headlines: List[str], snippets: List[str] = None, reason: str = ""):
        """Update ticker sentiment in database"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO sentiment (ticker, score, headlines, snippets, reason, last_updated) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    ticker, score, json.dumps(headlines),
                    json.dumps(snippets or []), reason,
                    datetime.now().isoformat()
                )
            )
            conn.commit()
            conn.close()

    def get_all_active_sentiment(self, threshold: float = 0.1) -> List[Dict]:
        """Get all tickers with sentiment above threshold"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sentiment WHERE abs(score) >= ?", (threshold,))
            rows = cursor.fetchall()
            conn.close()

            return [
                {
                    'ticker': r[0],
                    'current_score': r[1],
                    'current_headlines': json.loads(r[2]),
                    'current_snippets': json.loads(r[3]),
                    'reason': r[4],
                    'last_updated': r[5]
                }
                for r in rows
            ]

    def update_market_context(self, key: str, value: Any):
        """Update market context value"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO market_context (key, value, last_updated) VALUES (?, ?, ?)",
                (key, json.dumps(value), datetime.now().isoformat())
            )
            conn.commit()
            conn.close()

    def get_market_context(self, key: str) -> Optional[Dict]:
        """Get market context value"""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value, last_updated FROM market_context WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    'value': json.loads(row[0]),
                    'last_updated': row[1]
                }
            return None

    # ── Prediction Outcome Recording ─────────────────────────────────────

    def record_outcome(self, prediction_id: str, outcome: Dict):
        """Record the actual outcome of a prediction via targeted UPDATE."""
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                """UPDATE predictions
                   SET outcome_recorded = 1,
                       outcome_data = ?
                   WHERE id = ?""",
                (json.dumps(outcome), prediction_id)
            )
            conn.commit()
            conn.close()

    # ── Strategy Performance (SQLite backend) ────────────────────────────

    def record_strategy_trade(self, algorithm: str, signal: str,
                               pnl_pct: float, outcome: str):
        """Record a single strategy trade outcome."""
        with self._lock:
            conn = self._get_connection()
            conn.execute(
                "INSERT INTO strategy_performance "
                "(algorithm, signal, pnl_pct, outcome, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (algorithm, signal, pnl_pct, outcome,
                 datetime.now().isoformat())
            )
            conn.commit()
            conn.close()

    def get_strategy_signals(self, algorithm: str,
                              limit: int = 100) -> List[Dict]:
        """Get recent trade signals for a strategy."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT algorithm, signal, pnl_pct, outcome, timestamp "
                "FROM strategy_performance "
                "WHERE algorithm = ? "
                "ORDER BY id DESC LIMIT ?",
                (algorithm, limit)
            )
            rows = cursor.fetchall()
            conn.close()
            return [
                {
                    'algorithm': r[0], 'signal': r[1],
                    'pnl_pct': r[2], 'outcome': r[3],
                    'timestamp': r[4]
                }
                for r in rows
            ]

    def get_all_strategy_signals(self, limit: int = 100) -> Dict[str, List[Dict]]:
        """Get recent trade signals grouped by algorithm."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT algorithm, signal, pnl_pct, outcome, timestamp "
                "FROM strategy_performance "
                "ORDER BY id DESC LIMIT ?",
                (limit * 10,)  # Fetch more, then group
            )
            rows = cursor.fetchall()
            conn.close()

            grouped: Dict[str, List[Dict]] = {}
            for r in rows:
                algo = r[0]
                if algo not in grouped:
                    grouped[algo] = []
                if len(grouped[algo]) < limit:
                    grouped[algo].append({
                        'algorithm': r[0], 'signal': r[1],
                        'pnl_pct': r[2], 'outcome': r[3],
                        'timestamp': r[4]
                    })
            return grouped
