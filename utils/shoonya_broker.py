"""
Shoonya (Finvasia) Broker Integration
The best 'Free' API for Indian markets (Zero Brokerage, Zero API Charges)
Supports Equity, F&O, and Commodities
"""
import os
import logging
import json
from typing import Dict, List, Optional
from pathlib import Path
import pyotp

try:
    from NorenRestApiPy.NorenApi import NorenApi
except ImportError:
    NorenApi = None

logger = logging.getLogger(__name__)

class ShoonyaBroker(NorenApi if NorenApi else object):
    def __init__(self):
        if NorenApi:
            super(ShoonyaBroker, self).__init__(host='https://api.shoonya.com/NorenWSTP/', 
                                               websocket='wss://api.shoonya.com/NorenWSTP/')
        self.user_id = os.getenv('SHOONYA_USER_ID')
        self.password = os.getenv('SHOONYA_PASSWORD')
        self.totp_key = os.getenv('SHOONYA_TOTP_KEY')
        self.vendor_code = os.getenv('SHOONYA_VENDOR_CODE')
        self.api_key = os.getenv('SHOONYA_API_KEY')
        self.imei = os.getenv('SHOONYA_IMEI', 'abc1234')
        self.is_logged_in = False
        
        self.token_cache_path = Path("data/shoonya_tokens.json")
        self.token_cache: Dict[str, str] = self._load_token_cache()

    def _load_token_cache(self) -> Dict[str, str]:
        """Load instrument tokens from disk cache."""
        try:
            if self.token_cache_path.exists():
                with open(self.token_cache_path, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load Shoonya token cache: {e}")
        return {}

    def _save_token_cache(self):
        """Save instrument tokens to disk cache."""
        try:
            self.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_cache_path, 'w') as f:
                json.dump(self.token_cache, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save Shoonya token cache: {e}")

    def login(self) -> bool:
        """Perform login using user credentials and TOTP."""
        if not NorenApi:
            logger.error("NorenRestApiPy not installed. Run: pip install NorenRestApiPy")
            return False
        
        if not all([self.user_id, self.password, self.totp_key, self.vendor_code, self.api_key]):
            logger.error("Missing Shoonya credentials in .env")
            return False

        try:
            # Generate TOTP
            totp = pyotp.TOTP(self.totp_key).now()
            
            # Login
            ret = self.authorize(
                userid=self.user_id,
                password=self.password,
                twoFA=totp,
                vendor_code=self.vendor_code,
                api_secret=self.api_key,
                imei=self.imei
            )
            
            if ret and ret.get('stat') == 'Ok':
                logger.info(f"Shoonya Login Successful: {ret.get('uname')}")
                self.is_logged_in = True
                return True
            else:
                logger.error(f"Shoonya Login Failed: {ret}")
                return False
                
        except Exception as e:
            logger.error(f"Shoonya Login Exception: {e}")
            return False

    def get_live_price(self, ticker: str, exchange: str = 'NSE') -> Optional[float]:
        """Get last traded price (LTP)."""
        if not self.is_logged_in: return None
        try:
            # Note: ticker should be tradingsymbol (e.g. RELIANCE-EQ)
            if not ticker.endswith('-EQ') and exchange == 'NSE':
                ticker = f"{ticker}-EQ"
            
            quote = self.get_quotes(exchange=exchange, token=self._get_token(ticker, exchange))
            if quote and quote.get('lp'):
                return float(quote['lp'])
        except Exception as e:
            logger.error(f"Shoonya price error for {ticker}: {e}")
        return None

    def place_order(self, ticker: str, side: str, quantity: int, 
                    order_type: str = 'MKT', product: str = 'C') -> Dict:
        """
        Place an order.
        side: 'B' or 'S'
        order_type: 'MKT', 'LMT'
        product: 'C' (CNC/Delivery), 'I' (Intraday), 'M' (Margin)
        """
        if not self.is_logged_in: 
            return {'success': False, 'error': 'Not logged in'}

        try:
            # Standardize ticker for NSE
            if not ticker.endswith('-EQ'):
                tradingsymbol = f"{ticker}-EQ"
            else:
                tradingsymbol = ticker

            ret = super().place_order(
                buy_or_sell=side,
                product_type=product,
                exchange='NSE',
                tradingsymbol=tradingsymbol,
                quantity=quantity,
                discloseqty=0,
                price_type=order_type,
                price=0,
                trigger_price=0,
                retention='DAY',
                remarks='SmartTrader_Auto'
            )
            
            if ret and ret.get('stat') == 'Ok':
                return {'success': True, 'order_id': ret.get('norenordno')}
            return {'success': False, 'error': ret}
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_positions_summary(self) -> List[Dict]:
        """Get net positions."""
        if not self.is_logged_in: return []
        try:
            positions = self.get_positions()
            if positions and isinstance(positions, list):
                return positions
            return []
        except Exception:
            return []

    def _get_token(self, ticker: str, exchange: str) -> str:
        """Helper to find instrument token from symbol using cache."""
        cache_key = f"{exchange}:{ticker}"
        if cache_key in self.token_cache:
            return self.token_cache[cache_key]

        try:
            search = self.search_scrip(exchange=exchange, searchtext=ticker)
            if search and search.get('stat') == 'Ok' and search.get('values'):
                token = search['values'][0]['token']
                self.token_cache[cache_key] = token
                self._save_token_cache()
                return token
        except Exception as e:
            logger.error(f"Error fetching token for {ticker}: {e}")
        return ""
