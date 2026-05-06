"""
Full Lifecycle Prediction Manager
Predicts both entry AND exit for complete trades
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import uuid

from config import MEMORY_DIR


class LifecyclePrediction:
    """
    Full trade lifecycle prediction
    Includes: Entry signal, Exit signal, Stop loss, Target, Reason
    """

    def __init__(self):
        self.memory_file = MEMORY_DIR / "lifecycle_predictions.json"
        self.predictions = self._load_predictions()

    def _load_predictions(self) -> Dict:
        """Load predictions from memory file"""
        if self.memory_file.exists():
            try:
                with open(self.memory_file, 'r') as f:
                    return json.load(f)
            except:
                return {'predictions': {}, 'metadata': {'total': 0, 'active': 0, 'closed': 0}}
        return {'predictions': {}, 'metadata': {'total': 0, 'active': 0, 'closed': 0}}

    def _save_predictions(self):
        """Atomically save predictions to memory file"""
        self.predictions['metadata']['total'] = len(self.predictions['predictions'])
        self.predictions['metadata']['active'] = sum(
            1 for p in self.predictions['predictions'].values() if p['status'] == 'ACTIVE'
        )
        self.predictions['metadata']['closed'] = sum(
            1 for p in self.predictions['predictions'].values() if p['status'] in ['CLOSED', 'STOPPED']
        )

        import shutil
        import tempfile

        # Write to temp file first
        temp_file = self.memory_file.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(self.predictions, f, indent=2, default=str)
            # Atomic replace
            shutil.move(str(temp_file), str(self.memory_file))

            # Remove old backup if exists
            if self.memory_file.with_suffix('.bak').exists():
                self.memory_file.with_suffix('.bak').unlink()
        except Exception as e:
            print(f"Error saving predictions: {e}")
            if temp_file.exists():
                temp_file.unlink()

    def create_prediction(self, ticker: str, entry_signal: str,
                         entry_price: float, analysis: Dict) -> Dict:
        """
        Create a full lifecycle prediction when BUY signal is generated

        Returns:
        {
            'id': 'unique_id',
            'ticker': ticker,
            'entry': {...},
            'exit_plan': {...},
            'updates': [],
            'exit': None,
            'status': 'ACTIVE'
        }
        """
        prediction_id = str(uuid.uuid4())[:8]

        # Calculate exit plan based on analysis
        factors = analysis.get('factors', {})
        technical = factors.get('technical', {})

        # Use price target from analysis or calculate default (+10%)
        target_price = analysis.get('price_target', entry_price * 1.10)
        stop_loss = analysis.get('stop_loss', entry_price * 0.95)

        # Calculate expected exit date (default: 30 days from entry)
        expected_hold_days = 30
        target_date = (datetime.now() + timedelta(days=expected_hold_days)).strftime('%Y-%m-%d')

        # Build reasons for exit plan
        reasons = []

        # Take profit reason
        profit_pct = ((target_price - entry_price) / entry_price) * 100
        risk_pct = ((entry_price - stop_loss) / entry_price) * 100
        rr_ratio = abs(profit_pct / risk_pct) if risk_pct != 0 else 0
        reasons.append(f'Take profit at ${target_price:.2f} (+{profit_pct:.1f}%) - {rr_ratio:.1f}:1 reward:risk')

        # Stop loss reason
        reasons.append(f'Stop loss at ${stop_loss:.2f} (-{risk_pct:.1f}%)')

        # Trailing stop after partial profit
        trailing_trigger = entry_price * 1.05
        reasons.append(f'Trailing stop activates after +5% (${trailing_trigger:.2f})')

        # Technical-based exits
        rsi = technical.get('rsi', 50)
        if rsi < 30:
            reasons.append(f'Entry reason: RSI oversold ({rsi:.1f}) - exit if RSI > 70')
        elif rsi > 70:
            reasons.append(f'Caution: RSI overbought ({rsi:.1f}) - consider quick exit')

        # MACD based
        macd_signal = technical.get('macd_signal', '')
        if 'bullish' in macd_signal.lower():
            reasons.append(f'Entry: {macd_signal} - exit on bearish crossover')

        # Build entry reason
        entry_reasons = []
        sentiment = factors.get('sentiment', {})
        agg_sentiment = sentiment.get('aggregate_sentiment', 0)

        if agg_sentiment > 0.3:
            entry_reasons.append(f'Bullish sentiment ({agg_sentiment:.2f})')
        elif agg_sentiment < -0.3:
            entry_reasons.append(f'Warning: Negative sentiment ({agg_sentiment:.2f})')

        if rsi < 40:
            entry_reasons.append(f'RSI oversold ({rsi:.1f})')
        if 'bullish' in macd_signal.lower():
            entry_reasons.append(f'MACD {macd_signal}')

        entry_reason = ', '.join(entry_reasons) if entry_reasons else 'Technical setup'

        prediction = {
            'id': prediction_id,
            'ticker': ticker.upper(),
            'entry': {
                'signal': entry_signal,
                'price': float(entry_price),
                'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'reason': entry_reason,
                'confidence': float(analysis.get('confidence', 0.5))
            },
            'exit_plan': {
                'target_price': float(target_price),
                'stop_loss': float(stop_loss),
                'target_date': target_date,
                'reasons': reasons
            },
            'updates': [],
            'exit': None,
            'status': 'ACTIVE',
            'created_at': datetime.now().isoformat()
        }

        self.predictions['predictions'][prediction_id] = prediction
        self._save_predictions()

        return prediction

    def update_prediction(self, prediction_id: str, current_price: float) -> Dict:
        """
        Update an active prediction with current market data
        Check if exit conditions are met

        Returns updated prediction + action needed
        """
        if prediction_id not in self.predictions['predictions']:
            return {'error': 'Prediction not found'}

        pred = self.predictions['predictions'][prediction_id]

        if pred['status'] != 'ACTIVE':
            return {'error': 'Prediction is not active'}

        entry_price = pred['entry']['price']
        target_price = pred['exit_plan']['target_price']
        stop_loss = pred['exit_plan']['stop_loss']

        # Calculate current P&L
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        pnl_dollars = current_price - entry_price

        # Add update
        update = {
            'timestamp': datetime.now().isoformat(),
            'price': float(current_price),
            'pnl_pct': float(pnl_pct),
            'pnl_dollars': float(pnl_dollars)
        }
        # Calculate max price BEFORE appending current update
        historical_prices = [u['price'] for u in pred['updates']]
        pred['updates'].append(update)

        # Check exit conditions
        action_needed = None

        # 1. Target price reached (with 0.5% buffer)
        if current_price >= target_price * 0.995:
            action_needed = {
                'action': 'SELL',
                'reason': f'Target price reached: ${current_price:.2f} (target: ${target_price:.2f})',
                'confidence': 0.95,
                'pnl_pct': pnl_pct
            }

        # 2. Stop loss hit
        elif current_price <= stop_loss * 1.005:
            action_needed = {
                'action': 'SELL',
                'reason': f'Stop loss triggered: ${current_price:.2f} (stop: ${stop_loss:.2f})',
                'confidence': 0.99,
                'pnl_pct': pnl_pct
            }

        # 3. Trailing stop check (if up 5%, sell if drops 3% from high)
        if pnl_pct > 5:
            # Get highest price seen (excluding current update)
            max_price = max([entry_price] + historical_prices)
            trailing_stop = max_price * 0.97  # 3% below high
            if current_price <= trailing_stop:
                action_needed = {
                    'action': 'SELL',
                    'reason': f'Trailing stop triggered: ${current_price:.2f} (high: ${max_price:.2f})',
                    'confidence': 0.90,
                    'pnl_pct': pnl_pct
                }

        self._save_predictions()

        return {
            'prediction': pred,
            'current_price': current_price,
            'pnl_pct': pnl_pct,
            'pnl_dollars': pnl_dollars,
            'action_needed': action_needed
        }

    def generate_exit_signal(self, ticker: str, current_price: float,
                            hist: pd.DataFrame = None) -> Dict:
        """
        Generate SELL signal based on:
        1. Target price reached
        2. Stop loss hit
        3. Technical indicators signal sell
        4. Sentiment turned negative
        5. Time-based exit (held too long)
        """
        # Get active prediction for this ticker
        active = self.get_active_for_ticker(ticker)

        if not active:
            return {'sell': False, 'reason': 'No active prediction for ticker'}

        pred = active[0]  # Get the first active prediction
        entry_price = pred['entry']['price']
        target_price = pred['exit_plan']['target_price']
        stop_loss = pred['exit_plan']['stop_loss']

        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Check exit conditions in priority order

        # 1. Stop loss (highest priority)
        if current_price <= stop_loss:
            return {
                'sell': True,
                'reason': f'Stop loss hit: ${current_price:.2f} (loss: {pnl_pct:.1f}%)',
                'confidence': 0.98,
                'prediction_id': pred['id']
            }

        # 2. Target price reached
        if current_price >= target_price:
            return {
                'sell': True,
                'reason': f'Target price reached: ${current_price:.2f} (profit: {pnl_pct:.1f}%)',
                'confidence': 0.95,
                'prediction_id': pred['id']
            }

        # 3. Technical indicators (if hist provided)
        if hist is not None and len(hist) > 1:
            # RSI check (pandas implementation, no talib dependency)
            try:
                delta = hist['Close'].diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = (100 - (100 / (1 + rs))).iloc[-1]
                if rsi > 75:
                    return {
                        'sell': True,
                        'reason': f'RSI overbought: {rsi:.1f}',
                        'confidence': 0.80,
                        'prediction_id': pred['id']
                    }
            except Exception as e:
                pass

        # 4. Time-based exit (held > 45 days)
        entry_date = datetime.fromisoformat(pred['created_at'])
        days_held = (datetime.now() - entry_date).days
        if days_held > 45:
            return {
                'sell': True,
                'reason': f'Time-based exit: held for {days_held} days',
                'confidence': 0.70,
                'prediction_id': pred['id']
            }

        return {'sell': False, 'reason': 'Hold position', 'confidence': 0.5, 'pnl_pct': pnl_pct}

    def close_prediction(self, prediction_id: str, exit_price: float,
                         exit_reason: str) -> Dict:
        """
        Close a prediction when exit signal executes
        Record actual profit/loss
        """
        if prediction_id not in self.predictions['predictions']:
            return {'error': 'Prediction not found'}

        pred = self.predictions['predictions'][prediction_id]

        if pred['status'] != 'ACTIVE':
            return {'error': f'Prediction already {pred["status"]}'}

        entry_price = pred['entry']['price']
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        pnl_dollars = exit_price - entry_price

        pred['exit'] = {
            'price': float(exit_price),
            'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'reason': exit_reason,
            'pnl_pct': float(pnl_pct),
            'pnl_dollars': float(pnl_dollars)
        }

        # Determine final status
        if 'stop loss' in exit_reason.lower():
            pred['status'] = 'STOPPED'
        else:
            pred['status'] = 'CLOSED'

        pred['closed_at'] = datetime.now().isoformat()

        self._save_predictions()

        return {
            'prediction': pred,
            'pnl_pct': pnl_pct,
            'pnl_dollars': pnl_dollars,
            'status': pred['status']
        }

    def get_active_predictions(self) -> List[Dict]:
        """Get all active predictions"""
        return [
            p for p in self.predictions['predictions'].values()
            if p['status'] == 'ACTIVE'
        ]

    def get_active_for_ticker(self, ticker: str) -> List[Dict]:
        """Get active predictions for a specific ticker"""
        return [
            p for p in self.predictions['predictions'].values()
            if p['status'] == 'ACTIVE' and p['ticker'] == ticker.upper()
        ]

    def get_prediction_history(self, ticker: str = None) -> List[Dict]:
        """Get past predictions with outcomes"""
        predictions = list(self.predictions['predictions'].values())

        if ticker:
            predictions = [p for p in predictions if p['ticker'] == ticker.upper()]

        # Sort by created_at descending
        predictions.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return predictions

    def should_sell_now(self, ticker: str) -> Dict:
        """
        Check if we should sell based on active predictions
        Returns: {'sell': True/False, 'reason': '...', 'confidence': 0.9}
        """
        active = self.get_active_for_ticker(ticker)

        if not active:
            return {
                'sell': False,
                'reason': 'No active prediction found for ' + ticker,
                'confidence': 0.0
            }

        # Use the first active prediction
        pred = active[0]

        try:
            # Get current price
            ticker_obj = yf.Ticker(ticker)
            hist = ticker_obj.history(period='1d')
            if hist.empty:
                return {'sell': False, 'reason': 'Unable to fetch price', 'confidence': 0.0}

            current_price = hist['Close'].iloc[-1]

            # Generate exit signal
            return self.generate_exit_signal(ticker, current_price)

        except Exception as e:
            return {'sell': False, 'reason': f'Error checking: {str(e)}', 'confidence': 0.0}

    def get_prediction_summary(self, prediction_id: str) -> Optional[Dict]:
        """Get a summary of a specific prediction"""
        return self.predictions['predictions'].get(prediction_id)

    def cleanup_old_predictions(self, max_age_days: int = 90):
        """
        Remove predictions older than max_age_days to prevent memory bloat
        Closes any active predictions that have been open too long
        """
        cutoff = datetime.now() - timedelta(days=max_age_days)
        to_remove = []

        for pred_id, pred in self.predictions['predictions'].items():
            # Get creation time
            pred_time_str = pred.get('created_at', pred.get('entry', {}).get('date', '2000-01-01'))
            pred_time = datetime.fromisoformat(pred_time_str) if 'T' in pred_time_str else datetime.strptime(pred_time_str, '%Y-%m-%d %H:%M:%S')

            # Remove if older than cutoff
            if pred_time < cutoff:
                # If still active, close it first
                if pred['status'] == 'ACTIVE':
                    pred['status'] = 'CLOSED'
                    # Fetch real current price instead of using 0.0
                    entry_price = pred['entry']['price']
                    try:
                        current_hist = yf.Ticker(pred['ticker']).history(period='1d')
                        exit_price = float(current_hist['Close'].iloc[-1]) if not current_hist.empty else entry_price
                    except Exception:
                        exit_price = entry_price
                    real_pnl_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price else 0.0
                    real_pnl_dollars = exit_price - entry_price
                    pred['exit'] = {
                        'price': exit_price,
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'reason': 'Automatic cleanup - prediction too old',
                        'pnl_pct': round(real_pnl_pct, 2),
                        'pnl_dollars': round(real_pnl_dollars, 2)
                    }
                    pred['closed_at'] = datetime.now().isoformat()
                to_remove.append(pred_id)

        # Remove old predictions
        for pred_id in to_remove:
            del self.predictions['predictions'][pred_id]

        if to_remove:
            self._save_predictions()
            print(f"Cleaned up {len(to_remove)} old predictions")

        return len(to_remove)


def test_lifecycle_manager():
    """Test function for lifecycle manager"""
    print("Testing Lifecycle Prediction Manager...")
    print("=" * 60)

    manager = LifecyclePrediction()

    # Test creating a prediction
    test_analysis = {
        'signal': 'BUY',
        'confidence': 0.85,
        'price_target': 110.0,
        'stop_loss': 95.0,
        'factors': {
            'technical': {
                'rsi': 32.5,
                'macd_signal': 'Bullish crossover'
            },
            'sentiment': {
                'aggregate_sentiment': 0.45
            }
        }
    }

    print("\n1. Creating prediction...")
    pred = manager.create_prediction('AAPL', 'BUY', 100.0, test_analysis)
    print(f"   Created prediction ID: {pred['id']}")
    print(f"   Entry: ${pred['entry']['price']} on {pred['entry']['date']}")
    print(f"   Target: ${pred['exit_plan']['target_price']}")
    print(f"   Stop: ${pred['exit_plan']['stop_loss']}")

    # Test updating
    print("\n2. Updating prediction (price goes to $105)...")
    update = manager.update_prediction(pred['id'], 105.0)
    if 'error' not in update:
        print(f"   P&L: {update['pnl_pct']:.1f}%")
        if update['action_needed']:
            print(f"   Action: {update['action_needed']['action']} - {update['action_needed']['reason']}")

    # Test should_sell
    print("\n3. Checking if should sell...")
    sell_check = manager.should_sell_now('AAPL')
    print(f"   Sell: {sell_check['sell']}")
    print(f"   Reason: {sell_check['reason']}")

    # Test closing
    print("\n4. Closing prediction...")
    closed = manager.close_prediction(pred['id'], 108.0, 'Target price reached')
    print(f"   Status: {closed['status']}")
    print(f"   P&L: {closed['pnl_pct']:.1f}% (${closed['pnl_dollars']:.2f})")

    # Test history
    print("\n5. Getting prediction history...")
    history = manager.get_prediction_history()
    print(f"   Total predictions: {len(history)}")

    print("\n" + "=" * 60)
    print("Test completed!")

    return manager


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    test_lifecycle_manager()
