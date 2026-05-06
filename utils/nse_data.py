"""
NSE (National Stock Exchange) Data Fetcher
Fetches Nifty 50/500 tickers, F&O listings, and corporate actions
"""

import yfinance as yf
import pandas as pd
import requests
import pytz
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta, date
import json

# Nifty 50 tickers (Corrected and updated for 2026)
NIFTY_50_TICKERS = [
    "ADANIENT.NS", "ADANIPORTS.NS", "APOLLOHOSP.NS", "ASIANPAINT.NS", "AXISBANK.NS",
    "BAJAJ-AUTO.NS", "BAJAJFINSV.NS", "BAJFINANCE.NS", "BHARTIARTL.NS", "BPCL.NS",
    "BRITANNIA.NS", "CIPLA.NS", "COALINDIA.NS", "DIVISLAB.NS", "DRREDDY.NS",
    "EICHERMOT.NS", "GRASIM.NS", "HCLTECH.NS", "HDFCBANK.NS", "HDFCLIFE.NS",
    "HEROMOTOCO.NS", "HINDALCO.NS", "HINDUNILVR.NS", "ICICIBANK.NS", "INDUSINDBK.NS",
    "INFY.NS", "ITC.NS", "JSWSTEEL.NS", "KOTAKBANK.NS", "LT.NS", "LTIM.NS",
    "M&M.NS", "MARUTI.NS", "NESTLEIND.NS", "NTPC.NS", "ONGC.NS", "POWERGRID.NS",
    "RELIANCE.NS", "SBILIFE.NS", "SBIN.NS", "SHRIRAMFIN.NS", "SUNPHARMA.NS",
    "TATACONSUM.NS", "TATASTEEL.NS", "TCS.NS", "TECHM.NS", "TITAN.NS",
    "ULTRACEMCO.NS", "WIPRO.NS", "JIOFIN.NS"
]

# Nifty 500 - Expanded list for broader coverage
NIFTY_500_TICKERS = NIFTY_50_TICKERS + [
    "ABB.NS", "ACC.NS", "AUBANK.NS", "ABBOTINDIA.NS", "ADANIGREEN.NS", "ADANIENSOL.NS",
    "ALKEM.NS", "AMBUJACEM.NS", "ASTRAL.NS", "AUROPHARMA.NS", "AVANTIFEED.NS",
    "BANDHANBNK.NS", "BANKBARODA.NS", "BANKINDIA.NS", "BATAINDIA.NS", "BEL.NS",
    "BERGEPAINT.NS", "BHARATFORG.NS", "BHEL.NS", "BIOCON.NS", "BOSCHLTD.NS",
    "CANBK.NS", "CGPOWER.NS", "CHOLAFIN.NS", "COFORGE.NS", "COLPAL.NS",
    "CONCOR.NS", "COROMANDEL.NS", "CROMPTON.NS", "CUMMINSIND.NS", "DALMIABHA.NS",
    "DEEPAKNTR.NS", "DELTACORP.NS", "DIXON.NS", "DLF.NS", "ESCORTS.NS",
    "EXIDEIND.NS", "FEDERALBNK.NS", "FORTIS.NS", "GAIL.NS", "GLENMARK.NS",
    "GODREJCP.NS", "GODREJPROP.NS", "GUJGASLTD.NS", "HAL.NS", "HAVELLS.NS",
    "HDFCAMC.NS", "HINDPETRO.NS", "HONAUT.NS", "HUDCO.NS", "ICICIGI.NS",
    "ICICIPRULI.NS", "IDFCFIRSTB.NS", "IEX.NS", "IGL.NS", "INDIANB.NS",
    "INDIGO.NS", "INDUSTOWER.NS", "IPCALAB.NS", "IRCTC.NS", "IRFC.NS",
    "JINDALSTEL.NS", "JKCEMENT.NS", "KAYNES.NS", "KEI.NS", "KPITTECH.NS",
    "LALPATHLAB.NS", "LAURUSLABS.NS", "LICHSGFIN.NS", "LUPIN.NS", "MANAPPURAM.NS",
    "MARICO.NS", "MAXHEALTH.NS", "MAZDOCK.NS", "METROPOLIS.NS", "MPHASIS.NS",
    "MRF.NS", "MUTHOOTFIN.NS", "NATCOPHARM.NS", "NAVINFLUOR.NS", "NMDC.NS",
    "OBEROIRLTY.NS", "OFSS.NS", "PAGEIND.NS", "PEL.NS", "PERSISTENT.NS",
    "PETRONET.NS", "PFC.NS", "PIDILITIND.NS", "PIIND.NS", "PNB.NS",
    "POLYCAB.NS", "POONAWALLA.NS", "PRESTIGE.NS", "RECLTD.NS", "RVNL.NS",
    "SAIL.NS", "SJVN.NS", "SKFINDIA.NS", "SOLARINDS.NS", "SONACOMS.NS",
    "SRF.NS", "STARHEALTH.NS", "SUPREMEIND.NS", "SYNGENE.NS", "TATACOMM.NS",
    "TATAPOWER.NS", "TATAELXSI.NS", "TRENT.NS", "TRIDENT.NS", "TVSMOTOR.NS",
    "UBL.NS", "UNIONBANK.NS", "UNITDSPR.NS", "VBL.NS", "VEDL.NS", "VOLTAS.NS",
    "WHIRLPOOL.NS", "YESBANK.NS", "ZEEL.NS", "ZOMATO.NS"
]

# Nifty Next 50
NIFTY_NEXT_50 = [
    "ADANIGREEN.NS", "ADANIENSOL.NS", "AMBUJACEM.NS", "AUROPHARMA.NS", "BANDHANBNK.NS", "BANKBARODA.NS",
    "BERGEPAINT.NS", "BIOCON.NS", "BOSCHLTD.NS", "CHOLAFIN.NS", "COLPAL.NS", "CONCOR.NS", "CUMMINSIND.NS",
    "DABUR.NS", "DLF.NS", "GAIL.NS", "GODREJCP.NS", "HAVELLS.NS", "HINDPETRO.NS", "ICICIPRULI.NS",
    "ICICIGI.NS", "INDUSTOWER.NS", "IRCTC.NS", "JKCEMENT.NS", "JKPAPER.NS", "JUSTDIAL.NS", "KALYANKJIL.NS",
    "KANSAINER.NS", "KPITTECH.NS", "LALPATHLAB.NS", "LAURUSLABS.NS", "LEMONTREE.NS", "LICHSGFIN.NS",
    "MANAPPURAM.NS", "MPHASIS.NS", "NATCOPHARM.NS", "NAVINFLUOR.NS", "COFORGE.NS", "OFSS.NS",
    "OLECTRA.NS", "RITES.NS", "ROUTE.NS", "RVNL.NS", "SJVN.NS", "SUPREMEIND.NS",
    "SYNGENE.NS", "TANLA.NS", "THERMAX.NS", "TIINDIA.NS", "TTKPRESTIG.NS", "VAIBHAVGBL.NS",
]

# Nifty Midcap 100 Sample
NIFTY_MIDCAP_100_SAMPLE = [
    "ABCAPITAL.NS", "AARTIIND.NS", "ALKEM.NS", "APLLTD.NS", "ASTRAL.NS", "ATGL.NS", "BSOFT.NS", "CAMS.NS",
    "CANFINHOME.NS", "CARBORUNIV.NS", "CESC.NS", "CLEAN.NS", "COFORGE.NS", "CROMPTON.NS", "DEEPAKNTR.NS",
    "DELTACORP.NS", "DIXON.NS", "ELGIEQUIP.NS", "EMAMILTD.NS", "ENGINERSIN.NS", "FINCABLES.NS",
    "FORTIS.NS", "GLENMARK.NS", "GNFC.NS", "GPPL.NS", "GUJGASLTD.NS", "HINDCOPPER.NS", "HOMEFIRST.NS",
    "IDFCFIRSTB.NS", "IEX.NS", "INDIANB.NS", "INDIAMART.NS", "JKCEMENT.NS", "JKPAPER.NS",
    "JUSTDIAL.NS", "KALYANKJIL.NS", "KANSAINER.NS", "KPITTECH.NS", "LALPATHLAB.NS", "LAURUSLABS.NS",
    "LEMONTREE.NS", "LICHSGFIN.NS", "MANAPPURAM.NS", "MPHASIS.NS", "NATCOPHARM.NS", "NAVINFLUOR.NS",
    "COFORGE.NS", "OFSS.NS", "OLECTRA.NS", "RITES.NS", "ROUTE.NS", "RVNL.NS", "SJVN.NS", "SUPREMEIND.NS",
    "SYNGENE.NS", "TANLA.NS", "THERMAX.NS", "TIINDIA.NS", "TITAGARH.NS", "TTKPRESTIG.NS", "VAIBHAVGBL.NS",
]

def get_nifty_universe():
    """Return full Nifty 500 universe with .NS suffix (deduplicated)"""
    all_tickers = NIFTY_500_TICKERS + NIFTY_NEXT_50 + NIFTY_MIDCAP_100_SAMPLE
    return sorted(list(set(all_tickers)))

def convert_to_nse_format(ticker: str) -> str:
    """Ensure ticker has .NS suffix for Yahoo Finance"""
    if not ticker.endswith('.NS') and not ticker.endswith('.BO') and '^' not in ticker:
        return f"{ticker.upper()}.NS"
    return ticker.upper()

def convert_from_nse_format(ticker: str) -> str:
    """Remove .NS or .BO suffix"""
    return ticker.replace('.NS', '').replace('.BO', '')

# Popular F&O Stocks (frequently traded in Futures & Options)
FNO_STOCKS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "HCLTECH.NS", "TITAN.NS",
    "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "DRREDDY.NS", "ADANIPORTS.NS",
    "BPCL.NS", "EICHERMOT.NS", "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS",
    "CIPLA.NS", "UPL.NS", "BAJAJ-AUTO.NS", "TECHM.NS", "INDUSINDBK.NS"
]

# Bank Nifty components
BANKNIFTY_TICKERS = [
    "HDFCBANK.NS", "ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS",
    "SBIN.NS", "INDUSINDBK.NS", "BANKBARODA.NS", "FEDERALBNK.NS",
    "IDFCFIRSTB.NS", "PNB.NS", "AUROPHARMA.NS", "CIPLA.NS"
]


class NSEDataFetcher:
    """Fetch NSE-specific data for Indian markets"""

    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def get_nifty_50_tickers(self) -> List[str]:
        """Return Nifty 50 ticker list"""
        return NIFTY_50_TICKERS

    def get_nifty_500_tickers(self) -> List[str]:
        """Return Nifty 500 ticker list"""
        return NIFTY_500_TICKERS

    def get_fno_stocks(self) -> List[str]:
        """Return F&O stock list"""
        return FNO_STOCKS

    def get_banknifty_tickers(self) -> List[str]:
        """Return Bank Nifty component tickers"""
        return BANKNIFTY_TICKERS

    def get_index_data(self, index: str = "NIFTY50") -> pd.DataFrame:
        """
        Fetch index data
        index: "NIFTY50", "BANKNIFTY", "NIFTY500"
        """
        index_map = {
            "NIFTY50": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "NIFTY500": "^CRSLDX"
        }

        symbol = index_map.get(index.upper())
        if not symbol:
            return pd.DataFrame()

        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="6mo")
            return df
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error fetching index data: {e}")
            return pd.DataFrame()

    def get_nifty_universe(self) -> List[str]:
        """Return expanded 200-stock universe"""
        return get_nifty_universe()
