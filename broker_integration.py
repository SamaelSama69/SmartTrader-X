"""
Broker Integration for Indian Markets
Supports Zerodha (Kite Connect)
One-click auto-trading with easy setup
"""

import os
import requests
import json
from typing import Dict, List, Optional
from datetime import datetime
import time

# config import removed (uses os.getenv directly)


class ZerodhaBroker:
    """
    Zerodha Kite Connect API Integration
    Docs: https://kite.trade/docs/connect/v3/
    """

    def __init__(self, api_key: str = None, api_secret: str = None):
        self.api_key = api_key or os.getenv('ZERODHA_API_KEY', '')
        self.api_secret = api_secret or os.getenv('ZERODHA_API_SECRET', '')
        self.access_token = os.getenv('ZERODHA_ACCESS_TOKEN', '')
        self.base_url = 'https://api.kite.trade'
        self.session = requests.Session()

    def login_url(self) -> str:
        """Get login URL for Zerodha"""
        return f"https://kite.trade/connect/login?api_key={self.api_key}&v=3"

    def generate_session(self, request_token: str) -> Dict:
        """Generate session after user authorizes"""
        try:
            url = f"{self.base_url}/session/token"
            data = {
                'api_key': self.api_key,
                'request_token': request_token,
                'checksum': self._generate_checksum(request_token)
            }

            response = self.session.post(url, data=data)
            if response.status_code == 200:
                result = response.json()
                self.access_token = result['access_token']
                return {'success': True, 'access_token': self.access_token}
            return {'success': False, 'error': response.text}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _generate_checksum(self, request_token: str) -> str:
        """Generate checksum for API authentication"""
        import hashlib
        data = f"{self.api_key}{request_token}{self.api_secret}"
        return hashlib.sha256(data.encode()).hexdigest()

    def place_order(self, ticker: str, transaction_type: str,
                   quantity: int, order_type: str = 'MARKET',
                   price: float = None) -> Dict:
        """
        Place an order on Zerodha
        ticker: NSE/BSE symbol (e.g., 'RELIANCE', 'TCS')
        transaction_type: 'BUY' or 'SELL'
        """
        try:
            headers = {
                'Authorization': f"token {self.api_key}:{self.access_token}",
                'Content-Type': 'application/x-www-form-urlencoded'
            }

            data = {
                'tradingsymbol': ticker,
                'exchange': 'NSE',
                'transaction_type': transaction_type,
                'quantity': quantity,
                'order_type': order_type,
                'product': 'CNC',  # Cash and Carry (delivery)
                'validity': 'DAY'
            }

            if order_type == 'LIMIT' and price:
                data['price'] = price

            url = f"{self.base_url}/orders/regular"
            response = self.session.post(url, data=data, headers=headers)

            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'order_id': result.get('data', {}).get('order_id'),
                    'message': 'Order placed successfully'
                }
            return {'success': False, 'error': response.text}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_positions(self) -> List[Dict]:
        """Get current positions"""
        try:
            headers = {'Authorization': f"token {self.api_key}:{self.access_token}"}
            url = f"{self.base_url}/portfolio/positions"
            response = self.session.get(url, headers=headers)

            if response.status_code == 200:
                return response.json().get('data', [])
            return []
        except Exception as e:
            logger.warning(f"get_positions failed: {e}")
            return []

    def get_holdings(self) -> List[Dict]:
        """Get holdings"""
        try:
            headers = {'Authorization': f"token {self.api_key}:{self.access_token}"}
            url = f"{self.base_url}/portfolio/holdings"
            response = self.session.get(url, headers=headers)

            if response.status_code == 200:
                return response.json().get('data', [])
            return []
        except Exception as e:
            logger.warning(f"get_holdings failed: {e}")
            return []




class BrokerManager:
    """
    Unified broker management
    One-click setup and trading
    """

    def __init__(self):
        self.brokers = {}
        self.active_broker = None

    def setup_zerodha(self, api_key: str, api_secret: str) -> Dict:
        """Setup Zerodha broker"""
        broker = ZerodhaBroker(api_key, api_secret)
        self.brokers['zerodha'] = broker
        self.active_broker = 'zerodha'
        return {'success': True, 'message': 'Zerodha configured', 'login_url': broker.login_url()}

    def place_auto_order(self, ticker: str, signal: str,
                        capital: float = 100000.0,
                        risk_pct: float = 0.02) -> Dict:
        """
        One-click auto order placement
        signal: 'BUY' or 'SELL'
        """
        if not self.active_broker:
            return {'success': False, 'error': 'No broker configured'}

        broker = self.brokers.get(self.active_broker)
        if not broker:
            return {'success': False, 'error': 'Active broker not found'}

        # Get current price
        try:
            import yfinance as yf
            # For Indian stocks, append .NS for NSE
            yf_ticker = ticker if '.NS' in ticker else f"{ticker}.NS"
            hist = yf.Ticker(yf_ticker).history(period='1d')
            if hist.empty:
                return {'success': False, 'error': 'Could not get price'}

            current_price = hist['Close'].iloc[-1]

            # Calculate quantity based on risk
            risk_amount = capital * risk_pct
            quantity = int(risk_amount / current_price)
            quantity = max(quantity, 1)

            # Place order
            if hasattr(broker, 'place_order'):
                result = broker.place_order(
                    ticker=ticker,
                    transaction_type=signal,
                    quantity=quantity,
                    order_type='MARKET'
                )
                return result

            return {'success': False, 'error': 'Broker does not support order placement'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_portfolio_summary(self) -> Dict:
        """Get portfolio across all brokers"""
        summary = {'total_value': 0, 'positions': [], 'brokers': []}

        for name, broker in self.brokers.items():
            if hasattr(broker, 'get_positions'):
                positions = broker.get_positions()
                summary['positions'].extend(positions)
                summary['brokers'].append(name)

        return summary


def quick_setup_zerodha():
    """
    One-click Zerodha setup helper
    Returns instructions and login URL
    """
    print("\n" + "="*60)
    print("  ZERODHA ONE-CLICK SETUP")
    print("="*60)
    print("\n1. Go to: https://developers.kite.trade/")
    print("2. Create an app with redirect URL: http://127.0.0.1:5000/callback")
    print("3. Copy your API Key and API Secret")
    print("\nThen run:")
    print("  python -c \"from broker_integration import *; \\")
    print("    mgr = BrokerManager(); \\")
    print("    print(mgr.setup_zerodha('YOUR_API_KEY', 'YOUR_SECRET'))\"")
    print("\n4. Visit the login_url returned")
    print("5. Authorize and copy the request_token")
    print("6. Use the request_token to generate session")
    print("\n" + "="*60)

    return "Setup instructions printed above"
