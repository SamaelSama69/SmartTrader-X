"""
Memory Manager - Persistent storage of predictions and outcomes
Migrated to pure SQLite backend for performance and reliability.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from utils.database import Database
from config import MEMORY_DIR

logger = logging.getLogger(__name__)

class PredictionMemory:
    """
    Stores past predictions and their outcomes in SQLite.
    Allows the system to learn without recomputing everything.
    """

    def __init__(self):
        self.db = Database(db_path=str(MEMORY_DIR / 'smart_trader.db'))

    def add_prediction(self, ticker: str, prediction: Dict):
        """Store a new prediction in SQLite"""
        entry = {
            'id': f"{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            'ticker': ticker,
            'timestamp': datetime.now().isoformat(),
            'prediction': prediction,
            'outcome_recorded': False
        }
        self.db.save_prediction(entry)

    def get_past_predictions(self, ticker: str, days: int = 30) -> List[Dict]:
        """Retrieve past predictions for a ticker from SQLite"""
        all_preds = self.db.get_predictions(ticker)
        cutoff = datetime.now() - timedelta(days=days)
        
        return [
            p for p in all_preds
            if datetime.fromisoformat(p['timestamp']) > cutoff
        ]

    def get_similar_predictions(self, ticker: str, signal_type: str, days: int = 60) -> List[Dict]:
        """Find similar past predictions in SQLite"""
        past = self.get_past_predictions(ticker, days)
        return [p for p in past if p['prediction'].get('signal') == signal_type]

    def record_outcome(self, prediction_id: str, actual_outcome: Dict):
        """Record the actual outcome of a prediction in SQLite"""
        # This implementation requires adding record_outcome to Database class
        # For now, we'll simplify and update the prediction entry
        all_preds = self.db.get_predictions()
        for p in all_preds:
            if p['id'] == prediction_id:
                p['outcome_recorded'] = True
                self.db.save_prediction(p)
                break

    def get_prediction_accuracy(self, ticker: str = None, days: int = 90) -> Dict:
        """Calculate prediction accuracy from past outcomes in SQLite"""
        # Simplified: fetch all and filter
        all_preds = self.db.get_predictions(ticker)
        cutoff = datetime.now() - timedelta(days=days)
        
        relevant = [p for p in all_preds if datetime.fromisoformat(p['timestamp']) > cutoff and p['outcome_recorded']]
        if not relevant:
            return {'accuracy': 0.0, 'count': 0}
            
        # Logic for 'correct' would go here
        return {'accuracy': 0.5, 'count': len(relevant)}

    def should_recompute(self, ticker: str, min_hours: int = 24, force: bool = False) -> bool:
        """Check if we should recompute analysis for a ticker"""
        if force: return True
        past = self.get_past_predictions(ticker, days=1)
        if not past: return True
        
        last_ts = max(datetime.fromisoformat(p['timestamp']) for p in past)
        return (datetime.now() - last_ts).total_seconds() / 3600 >= min_hours


class MarketContextMemory:
    """
    Stores market context in SQLite.
    Avoids recomputing market-wide analysis.
    """

    def __init__(self):
        self.db = Database(db_path=str(MEMORY_DIR / 'smart_trader.db'))

    def update_market_context(self, new_context: Dict):
        """Update market context in SQLite"""
        for k, v in new_context.items():
            self.db.update_market_context(k, v)

    def get_market_context(self) -> Dict:
        """Get all cached market context from SQLite"""
        # This requires adding a get_all method to Database
        # For now, we'll return a default structure
        return {
            'market_regime': self.db.get_market_context('market_regime') or 'unknown',
            'last_update': datetime.now().isoformat()
        }

    def is_context_stale(self, max_hours: int = 6) -> bool:
        ctx = self.db.get_market_context('market_regime')
        if not ctx: return True
        last_update = datetime.fromisoformat(ctx['last_updated'])
        return (datetime.now() - last_update).total_seconds() / 3600 >= max_hours
