"""
Indian Market Configuration
All settings specific to NSE/BSE Indian markets
"""

from datetime import time
from typing import Dict, List
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent
INDIAN_DATA_DIR = BASE_DIR / "data" / "indian"
INDIAN_OUTPUT_DIR = BASE_DIR / "output" / "indian"

# Create directories
INDIAN_DATA_DIR.mkdir(parents=True, exist_ok=True)
INDIAN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Minimum confidence to execute a trade
MIN_CONFIDENCE_SWING = 0.65    # aligned with backtest-validated threshold
MIN_CONFIDENCE_INTRADAY = 0.65  # For intraday/ORB trades

# =============================================================================
# INDIAN MARKET TRADING HOURS
# =============================================================================
# NSE/BSE Trading Hours: 9:15 AM - 3:30 PM IST (Monday to Friday)
MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)
PRE_OPEN_TIME = time(9, 0)
POST_CLOSE_TIME = time(15, 40)

# Expiry Day: Thursday for NIFTY weekly options and current index monthly options
EXPIRY_DAY = 3  # 3 = Thursday (Python weekday convention)
EXPIRY_DAY_NAME = "Thursday"

# Current NSE weekly index options schedule.
# Since November 20, 2024, NSE weekly index options are available only on NIFTY.
WEEKLY_EXPIRY_DAYS = {
    "NIFTY": 3,
}

INDEX_DERIVATIVE_CONTRACT_SPECS = {
    "NIFTY": {
        "weekly_options_enabled": True,
        "weekly_expiry_day": 3,
        "monthly_expiry_day": 3,
        "lot_size": 65,
        "lot_size_effective_from": "2025-12-30",
        "source": "NSE/FAOP/70616",
    },
    "BANKNIFTY": {
        "weekly_options_enabled": False,
        "last_weekly_expiry": "2024-11-13",
        "monthly_expiry_day": 3,
        "lot_size": 30,
        "lot_size_effective_from": "2025-12-30",
        "source": "NSE/FAOP/64506, NSE/FAOP/65336, NSE/FAOP/70616",
    },
    "FINNIFTY": {
        "weekly_options_enabled": False,
        "last_weekly_expiry": "2024-11-19",
        "monthly_expiry_day": 3,
        "lot_size": 60,
        "lot_size_effective_from": "2025-12-30",
        "source": "NSE/FAOP/64506, NSE/FAOP/65336, NSE/FAOP/70616",
    },
    "MIDCPNIFTY": {
        "weekly_options_enabled": False,
        "last_weekly_expiry": "2024-11-18",
        "monthly_expiry_day": 3,
        "lot_size": 120,
        "lot_size_effective_from": "2025-12-30",
        "source": "NSE/FAOP/64506, NSE/FAOP/65336, NSE/FAOP/70616",
    },
    "NIFTYNXT50": {
        "weekly_options_enabled": False,
        "monthly_expiry_day": 3,
        "lot_size": 25,
        "source": "NSE contract file",
    },
}

# =============================================================================
# POPULAR INDIAN STOCKS
# =============================================================================
POPULAR_INDIAN_STOCKS = {
    # Large Cap
    "large_cap": [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
        "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
        "LT", "AXISBANK", "BAJFINANCE", "HCLTECH", "TITAN"
    ],

    # Mid Cap
    "mid_cap": [
        "IDFCFIRSTB", "FEDERALBNK", "BANKBARODA", "PNB", "INDIANB",
        "RVNL", "IRFC", "TATAPOWER", "ADANIPORTS", "BALRAMCHIN",
        "CHOLAFIN", "MFSL", "CANBK", "JINDALSTEL", "SAIL"
    ],

    # Small Cap (High Risk)
    "small_cap": [
        "TRIDENT", "YESBANK", "SOUTHBANK", "RPOWER", "ALOKTEXT",
        "UCOBANK", "CENTURYTEX", "JPASSOCIAT", "SUZLON", "IVRCLINFRA"
    ],

    # Sector-wise
    "sectors": {
        "it": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
        "banking": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK"],
        "pharma": ["SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "BIOCON"],
        "auto": ["MARUTI", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
        "fmcg": ["HINDUNILVR", "ITC", "BRITANNIA", "DABUR", "GODREJCP"],
        "metal": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "NATIONALUM", "VEDL"],
        "oil_gas": ["RELIANCE", "ONGC", "BPCL", "HPCL", "GAIL"],
        "telecom": ["BHARTIARTL", "IDEA", "RCOM"],
        "cement": ["ULTRACEMCO", "AMBUJACEM", "ACC", "SHREECEM", "DALMIABHA"],
    }
}

# =============================================================================
# F&O LOT SIZES (Updated periodically by SEBI)
# =============================================================================
FNO_LOT_SIZES = {
    # Indices
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "MIDCAPNIFTY": 120,
    "NIFTYNXT50": 25,

    # Stocks
    "RELIANCE": 250,
    "TCS": 175,
    "HDFCBANK": 500,
    "INFY": 600,
    "ICICIBANK": 1375,
    "HINDUNILVR": 200,
    "ITC": 3200,
    "SBIN": 1500,
    "BHARTIARTL": 2200,
    "KOTAKBANK": 625,
    "LT": 375,
    "AXISBANK": 975,
    "BAJFINANCE": 125,
    "HCLTECH": 350,
    "TITAN": 375,
    "MARUTI": 100,
    "TATAMOTORS": 3000,
    "SUNPHARMA": 750,
    "DRREDDY": 250,
    "ADANIPORTS": 1500,
    "BAJAJ-AUTO": 125,
    "WIPRO": 1500,
    "TECHM": 1200,
    "CIPLA": 750,
    "UPL": 1000,
    "ONGC": 4400,
    "NTPC": 3500,
    "POWERGRID": 4000,
    "ULTRACEMCO": 100,
    "JSWSTEEL": 1400,
    "HINDALCO": 1850,
    "GRASIM": 350,
    "DIVISLAB": 175,
    "BRITANNIA": 100,
    "EICHERMOT": 150,
    "HEROMOTOCO": 300,
    "INDUSINDBK": 750,
    "COALINDIA": 3000,
    "BPCL": 875,
    "TATASTEEL": 2300,
}

# =============================================================================
# MARGIN REQUIREMENTS (Approximate, check with broker)
# =============================================================================
MARGIN_REQUIREMENTS = {
    "NIFTY": {
        "span_margin": 5.0,    # 5% SPAN margin
        "exposure_margin": 3.0,  # 3% exposure margin
    },
    "BANKNIFTY": {
        "span_margin": 6.0,
        "exposure_margin": 4.0,
    },
    "STOCK_OPTIONS": {
        "span_margin": 8.0,
        "exposure_margin": 5.0,
    }
}

# =============================================================================
# OPTIONS WRITING SETTINGS
# =============================================================================
OPTIONS_WRITING_CONFIG = {
    "max_loss_percentage": 2.0,     # Max 2% loss per trade
    "target_profit_pct": 1.0,        # Close at 1% profit
    "stop_loss_pct": 2.0,            # Stop loss at 2% loss
    "prefer_thursday_expiry": True,  # Only trade on expiry day
    "min_premium_pct": 1.0,          # Min 1% premium
    "max_otm_strikes": 2,            # Sell max 2 strikes OTM
    "avoid_earnings_week": True,     # Avoid options during earnings
}

# =============================================================================
# BUDGET DAY TRADING SETTINGS
# =============================================================================
BUDGET_DAY_CONFIG = {
    "date": (2, 1),  # February 1st (month, day)
    "avoid_heavy_positions": True,
    "reduce_position_size_pct": 50,  # Reduce to 50% position size
    "close_before_budget": True,     # Close positions before budget presentation
    "volatile_stocks_to_avoid": [
        "RELIANCE", "ONGC", "BPCL", "HPCL",  # Oil & Gas sensitive
        "SBI", "HDFCBANK", "ICICIBANK",       # Banking sensitive
        "L&T", "ULTRACEMCO", "NTPC"           # Infrastructure sensitive
    ],
}

# =============================================================================
# INTRADAY SETTINGS
# =============================================================================
INTRADAY_CONFIG = {
    "square_off_time": time(15, 15),   # Square off by 3:15 PM
    "force_square_off": True,            # Force square off before market close
    "max_positions": 5,                 # Max 5 concurrent positions
    "min_capital": 100000,              # Min 1 lakh INR for intraday
    "leverage_allowed": 5,              # 5x leverage for intraday (MIS)
    "vwap_confirmation": True,          # Use VWAP for entries
}

# =============================================================================
# SWING TRADING SETTINGS
# =============================================================================
SWING_TRADING_CONFIG = {
    "holding_period_days": (3, 15),    # Hold for 3-15 days
    "min_swing_pct": 3.0,              # Min 3% swing expected
    "stop_loss_pct": 5.0,              # 5% stop loss
    "target_profit_pct": 10.0,         # 10% target profit
    "use_supertrend": True,            # Use Supertrend for exit
}

# =============================================================================
# RISK MANAGEMENT (Indian Context)
# =============================================================================
INDIAN_RISK_CONFIG = {
    "max_position_size_pct": 10.0,     # Max 10% per position
    "max_sector_exposure_pct": 30.0,    # Max 30% in one sector
    "max_capital_per_trade": 500000,    # Max 5 lakhs per trade (INR)
    "daily_loss_limit_pct": 2.0,       # Stop trading if 2% daily loss
    "max_open_positions": 10,           # Max 10 open positions
    "margin_buffer_pct": 20.0,         # Keep 20% margin buffer
}

# =============================================================================
# POPULAR SCAN CRITERIA (Indian Traders)
# =============================================================================
INDIAN_SCAN_CRITERIA = {
    "breakout_stocks": {
        "volume_surge": 2.0,           # 2x average volume
        "price_above_200ma": True,
        "rsi_range": (55, 70),         # RSI 55-70
    },
    "momentum_stocks": {
        "price_change_5d": 3.0,        # 3% up in 5 days
        "rsi_min": 60,
        "adx_min": 25,                 # Strong trend
    },
    "value_stocks": {
        "pe_ratio_max": 20,
        "debt_to_equity_max": 1.0,
        "roe_min": 15,                 # 15% ROE
        "dividend_yield_min": 1.0,     # 1% dividend
    },
    "fno_breakout": {
        "oi_change_pct": 10.0,         # 10% OI change
        "price_change_pct": 2.0,
        "volume_vs_avg": 1.5,          # 1.5x average volume
    }
}

# =============================================================================
# BLACKOUT PERIODS (When to avoid trading)
# =============================================================================
BLACKOUT_PERIODS = [
    {"name": "Budget Week", "dates": ((2, 1), (2, 7))},  # Budget week
    {"name": "RBI Policy Week", "dates": None},  # Dynamic - check RBI website
    {"name": "F&O Expiry Day", "day": 3},  # Thursday (high volatility)
    {"name": "Quarterly Results Peak", "months": [1, 4, 7, 10]},  # Results season
]

# =============================================================================
# TAX SETTINGS (India)
# =============================================================================
TAX_CONFIG = {
    "stt_equity": 0.00025,        # 0.025% STT on equity delivery
    "stt_intraday": 0.00025,      # 0.025% STT on intraday
    "stt_fno": 0.0005,            # 0.05% STT on F&O
    "brokerage_eq": 0.0001,       # 0.01% brokerage (discount brokers)
    "brokerage_fno": 0.0001,      # 0.01% brokerage on F&O
    "gst": 0.18,                  # 18% GST on brokerage
    "sebi_charges": 0.000001,     # 0.0001% SEBI charges
    "stamp_duty": 0.00015,        # 0.015% stamp duty
    "lrs_tax": 0.30,              # 30% LRS tax on profitable trades > 1L
}

# =============================================================================
# HOLIDAYS (Trading Holidays - Update Yearly)
# =============================================================================
NSE_HOLIDAYS_2024 = [
    "2024-01-26",  # Republic Day
    "2024-03-08",  # Mahashivratri
    "2024-03-25",  # Holi
    "2024-03-29",  # Good Friday
    "2024-04-11",  # Id-Ul-Fitr
    "2024-04-17",  # Ram Navami
    "2024-05-01",  # Maharashtra Day
    "2024-06-17",  # Bakri Id
    "2024-07-17",  # Moharram
    "2024-08-15",  # Independence Day
    "2024-10-02",  # Gandhi Jayanti
    "2024-11-01",  # Diwali-Laxmi Pujan
    "2024-11-15",  # Gurunanak Jayanti
    "2024-12-25",  # Christmas
]

NSE_HOLIDAYS_2025 = [
    "2025-01-26",  # Republic Day
    "2025-03-14",  # Holi
    "2025-03-29",  # Good Friday
    "2025-04-01",  # Id-Ul-Fitr
    "2025-05-01",  # Maharashtra Day
    "2025-08-15",  # Independence Day
    "2025-10-02",  # Gandhi Jayanti
    "2025-10-21",  # Diwali
    "2025-12-25",  # Christmas
]

NSE_HOLIDAYS_2026 = [
    "2026-01-26",  # Republic Day
    "2026-03-04",  # Mahashivratri (tentative)
    "2026-03-20",  # Holi (tentative)
    "2026-04-03",  # Good Friday (tentative)
    "2026-04-15",  # Id-Ul-Fitr (tentative)
    "2026-05-01",  # Maharashtra Day
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Gandhi Jayanti
    "2026-11-08",  # Diwali (tentative)
    "2026-12-25",  # Christmas
]

NSE_HOLIDAYS_2027 = [
    "2027-01-26",  # Republic Day
    "2027-02-22",  # Mahashivratri (tentative)
    "2027-03-12",  # Holi (tentative)
    "2027-03-26",  # Good Friday (tentative)
    "2027-04-05",  # Id-Ul-Fitr (tentative)
    "2027-05-01",  # Maharashtra Day
    "2027-08-15",  # Independence Day
    "2027-10-02",  # Gandhi Jayanti
    "2027-10-28",  # Diwali (tentative)
    "2027-12-25",  # Christmas
]

def get_nse_holidays(year: int = None) -> list:
    """Get NSE holidays for a given year (dynamic)"""
    if year is None:
        from datetime import datetime
        year = datetime.now().year

    holiday_map = {
        2024: NSE_HOLIDAYS_2024,
        2025: NSE_HOLIDAYS_2025,
        2026: NSE_HOLIDAYS_2026,
        2027: NSE_HOLIDAYS_2027,
    }
    return holiday_map.get(year, [])

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def is_expiry_day(today=None) -> bool:
    """Check if today is expiry day (Thursday)"""
    if today is None:
        from datetime import datetime
        today = datetime.now()
    return today.weekday() == EXPIRY_DAY

def get_index_derivative_spec(symbol: str) -> dict:
    """Return current index derivative contract metadata for NSE symbols."""
    key = symbol.replace(".NS", "").replace(".BO", "").upper()
    return INDEX_DERIVATIVE_CONTRACT_SPECS.get(key, {})

def is_weekly_index_options_enabled(symbol: str) -> bool:
    """Return whether NSE still lists weekly options for this index."""
    return bool(get_index_derivative_spec(symbol).get("weekly_options_enabled", False))

def is_budget_day(today=None) -> bool:
    """Check if today is Budget day (Feb 1st)"""
    if today is None:
        from datetime import datetime
        today = datetime.now()
    return today.month == BUDGET_DAY_CONFIG["date"][0] and today.day == BUDGET_DAY_CONFIG["date"][1]

def is_earnings_season(today=None) -> bool:
    """Returns True during quarterly results peak months.

    Peak months: Jan, Apr, Jul, Oct (full month) plus the first week
    of the following month (Feb 1-7, May 1-7, Aug 1-7, Nov 1-7).
    During earnings season, position sizes should be reduced to
    account for surprise gap risk.
    """
    if today is None:
        from datetime import datetime
        today = datetime.now()
    if today.month in (1, 4, 7, 10):
        return True
    if today.month in (2, 5, 8, 11) and today.day <= 7:
        return True
    return False


def get_lot_size(ticker: str) -> int:
    """Get F&O lot size for a ticker"""
    ticker = ticker.replace(".NS", "").replace(".BO", "")
    return FNO_LOT_SIZES.get(ticker.upper(), 0)

def get_trading_hours() -> tuple:
    """Return market open and close times"""
    return (MARKET_OPEN_TIME, MARKET_CLOSE_TIME)
