"""
Sentiment Database - Persistent storage for stock sentiment analysis.
Migrated to SQLite backend for concurrent-safe storage and better performance.
"""
from typing import List, Dict
from utils.database import Database
from config import MEMORY_DIR

class SentimentDB:
    def __init__(self):
        self.db = Database(db_path=str(MEMORY_DIR / "smart_trader.db"))

    def update_ticker(self, ticker: str, score: float, headlines: List[str], reason: str = "", snippets: List[str] = None):
        """Update or add a ticker's sentiment data in SQLite."""
        self.db.update_sentiment(ticker, score, headlines, snippets, reason)

    def get_ticker_data(self, ticker: str) -> Dict:
        """Fetch ticker sentiment data."""
        # This method is simplified; in reality, we'd fetch from SQLite
        all_sent = self.db.get_all_active_sentiment(threshold=-2.0) # Get all
        for s in all_sent:
            if s['ticker'] == ticker:
                return s
        return {}

    def get_all_active_signals(self, threshold: float = 0.1) -> List[Dict]:
        """Return all tickers with significant sentiment from SQLite."""
        return self.db.get_all_active_sentiment(threshold)
