"""
SmartTrader Configuration
All settings for the trading analysis system
"""

# Force HuggingFace to cache locally — prevents re-download every run
import os
from pathlib import Path
import logging
from dotenv import load_dotenv

hf_cache_dir = Path(__file__).resolve().parent / 'models' / 'hf'
os.environ['TRANSFORMERS_CACHE'] = str(hf_cache_dir)
os.environ['HF_HOME'] = str(hf_cache_dir)

# If the model is already downloaded (directory > 100MB), force offline mode 
# to completely eliminate the HTTP HEAD metadata checks on startup for zero latency.
if hf_cache_dir.exists() and sum(f.stat().st_size for f in hf_cache_dir.rglob('*') if f.is_file()) > 100_000_000:
    os.environ['HF_HUB_OFFLINE'] = '1'

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
MEMORY_DIR = BASE_DIR / "memory"
STRATEGIES_DIR = BASE_DIR / "strategies"
UTILS_DIR = BASE_DIR / "utils"

# Create directories
for d in [DATA_DIR, MODELS_DIR, OUTPUT_DIR, LOGS_DIR, MEMORY_DIR, STRATEGIES_DIR, UTILS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Configure logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = LOGS_DIR / "smart_trader.log"

def setup_logging():
    """Configure logging with rotating files and console output"""
    import logging.handlers
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, LOG_LEVEL, logging.INFO)

    # Create logs directory if it doesn't exist
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Root formatter
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Handler 1: Daily Rotating File
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE, when="midnight", interval=1, backupCount=7, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    # Handler 2: Console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers to avoid duplicates
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Create logger for this module
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized at level {LOG_LEVEL} (Rotating: 7 days)")
    return logger


def validate_config():
    """Validate configuration values are in reasonable ranges"""
    logger = logging.getLogger(__name__)

    # Validate API keys
    if not FINNHUB_API_KEY and not NEWS_API_KEY:
        logger.warning("No news/sentiment API keys found. Sentiment analysis will be limited.")
    if not ZERODHA_API_KEY:
        logger.info("Zerodha API key not set. Live trading will be disabled.")

    errors = []
    warnings = []

    # Validate numeric ranges
    if not (0 < CONFIDENCE_THRESHOLD <= 1):
        errors.append(f"CONFIDENCE_THRESHOLD should be between 0 and 1, got {CONFIDENCE_THRESHOLD}")

    if INITIAL_CAPITAL <= 0:
        errors.append(f"INITIAL_CAPITAL should be positive, got {INITIAL_CAPITAL}")

    if not (0 < MAX_POSITION_PCT <= 1):
        errors.append(f"MAX_POSITION_PCT should be between 0 and 1, got {MAX_POSITION_PCT}")

    if TRANSACTION_COST_BPS < 0:
        errors.append(f"TRANSACTION_COST_BPS should be non-negative, got {TRANSACTION_COST_BPS}")

    if CACHE_DAYS < 0:
        errors.append(f"CACHE_DAYS should be non-negative, got {CACHE_DAYS}")

    if LOOKBACK_DAYS < 0:
        errors.append(f"LOOKBACK_DAYS should be non-negative, got {LOOKBACK_DAYS}")

    if NEWS_LOOKBACK_DAYS < 0:
        errors.append(f"NEWS_LOOKBACK_DAYS should be non-negative, got {NEWS_LOOKBACK_DAYS}")

    if NEWS_LIMIT_PER_SOURCE < 0:
        errors.append(f"NEWS_LIMIT_PER_SOURCE should be non-negative, got {NEWS_LIMIT_PER_SOURCE}")

    if MAX_TICKERS_TO_ANALYZE <= 0:
        errors.append(f"MAX_TICKERS_TO_ANALYZE should be positive, got {MAX_TICKERS_TO_ANALYZE}")

    if MAX_MEMORY_ENTRIES <= 0:
        errors.append(f"MAX_MEMORY_ENTRIES should be positive, got {MAX_MEMORY_ENTRIES}")

    if BACKTEST_INITIAL_CAPITAL <= 0:
        errors.append(f"BACKTEST_INITIAL_CAPITAL should be positive, got {BACKTEST_INITIAL_CAPITAL}")

    if not (0 <= BACKTEST_COMMISSION_RATE < 1):
        warnings.append(f"BACKTEST_COMMISSION_RATE seems out of range: {BACKTEST_COMMISSION_RATE}")

    if not (0 <= BACKTEST_SLIPPAGE < 1):
        warnings.append(f"BACKTEST_SLIPPAGE seems out of range: {BACKTEST_SLIPPAGE}")

    if OPTIONS_MIN_VOLUME < 0:
        errors.append(f"OPTIONS_MIN_VOLUME should be non-negative, got {OPTIONS_MIN_VOLUME}")

    if OPTIONS_MIN_OPEN_INTEREST < 0:
        errors.append(f"OPTIONS_MIN_OPEN_INTEREST should be non-negative, got {OPTIONS_MIN_OPEN_INTEREST}")

    if UNUSUAL_OPTIONS_VOLUME_MULTIPLIER <= 0:
        errors.append(f"UNUSUAL_OPTIONS_VOLUME_MULTIPLIER should be positive, got {UNUSUAL_OPTIONS_VOLUME_MULTIPLIER}")

    if not (0 < MAX_DRAWDOWN_PCT <= 1):
        errors.append(f"MAX_DRAWDOWN_PCT should be between 0 and 1, got {MAX_DRAWDOWN_PCT}")

    if STOP_LOSS_ATR_MULTIPLIER <= 0:
        errors.append(f"STOP_LOSS_ATR_MULTIPLIER should be positive, got {STOP_LOSS_ATR_MULTIPLIER}")

    if TAKE_PROFIT_RR_RATIO <= 0:
        errors.append(f"TAKE_PROFIT_RR_RATIO should be positive, got {TAKE_PROFIT_RR_RATIO}")

    # Validate Screener Criteria
    if SCREEN_CRITERIA["min_market_cap"] <= 0:
        errors.append(f"SCREEN_CRITERIA['min_market_cap'] should be positive")

    if SCREEN_CRITERIA["min_avg_volume"] <= 0:
        errors.append(f"SCREEN_CRITERIA['min_avg_volume'] should be positive")

    if not (0 <= SCREEN_CRITERIA["min_rsi"] <= 100):
        errors.append(f"SCREEN_CRITERIA['min_rsi'] should be between 0 and 100")

    if not (0 <= SCREEN_CRITERIA["max_rsi"] <= 100):
        errors.append(f"SCREEN_CRITERIA['max_rsi'] should be between 0 and 100")

    # Validate Strategy Screeners
    for strategy, criteria in STRATEGY_SCREENERS.items():
        if 'min_price_change_1m' in criteria and criteria['min_price_change_1m'] < -1:
            warnings.append(f"Strategy '{strategy}' has unusual min_price_change_1m")
        if 'min_rsi' in criteria and not (0 <= criteria['min_rsi'] <= 100):
            errors.append(f"Strategy '{strategy}' has invalid min_rsi")
        if 'volume_surge' in criteria and criteria['volume_surge'] <= 0:
            errors.append(f"Strategy '{strategy}' has invalid volume_surge")
        if 'max_pe_ratio' in criteria and criteria['max_pe_ratio'] <= 0:
            errors.append(f"Strategy '{strategy}' has invalid max_pe_ratio")

    # Check file paths exist or can be created
    for path_name, path in [("DATA_DIR", DATA_DIR), ("MODELS_DIR", MODELS_DIR),
                             ("OUTPUT_DIR", OUTPUT_DIR), ("LOGS_DIR", LOGS_DIR),
                             ("MEMORY_DIR", MEMORY_DIR)]:
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory: {path}")
            except Exception as e:
                errors.append(f"Cannot create {path_name} at {path}: {e}")

    # Log validation results
    for warning in warnings:
        logger.warning(f"Config validation warning: {warning}")

    for error in errors:
        logger.error(f"Config validation error: {error}")

    if errors:
        logger.error(f"Configuration validation failed with {len(errors)} error(s)")
        return False

    logger.info("Configuration validation passed")
    return True


# API Keys (from environment)
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "SmartTrader/1.0")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "")

# Trading Settings
MAX_TICKERS_TO_ANALYZE = int(os.getenv("MAX_TICKERS_TO_ANALYZE", "50"))
CONFIDENCE_THRESHOLD = 0.70  # 70% confidence for signals
INITIAL_CAPITAL = 1000000.0  # Paper trading capital
MAX_POSITION_PCT = 0.10  # Max 10% per position
TRANSACTION_COST_BPS = 10  # 10 basis points per trade

# Data Settings
CACHE_DAYS = int(os.getenv("CACHE_DAYS", "30"))
LOOKBACK_DAYS = 252  # 1 year of trading data
NEWS_LOOKBACK_DAYS = 7  # Days to look back for news
NEWS_LIMIT_PER_SOURCE = 50

# Screener Settings - Indian Market Focus
SCREEN_CRITERIA = {
    "min_market_cap": 1e9,  # ₹1B minimum (large cap)
    "min_avg_volume": 50000,  # 50k daily volume (Phase1 illiquidity filter)
    "sectors": [  # Focus on NSE sectors
        "IT", "Banking", "Pharma", "Auto", "FMCG",
        "Metal", "Oil & Gas", "Telecom", "Cement"
    ],
    "min_rsi": 30,
    "max_rsi": 70,
}

# ML Model Settings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, lightweight
SENTIMENT_MODEL = "distilbert-base-uncased-finetuned-sst-2-english"  # Lightweight DistilBERT sentiment model (SST-2)

# Memory Settings
MEMORY_FILE = MEMORY_DIR / "prediction_memory.json"
OUTCOMES_FILE = MEMORY_DIR / "prediction_outcomes.json"
MAX_MEMORY_ENTRIES = 10000

# Backtesting Settings
BACKTEST_INITIAL_CAPITAL = 100000.0
BACKTEST_COMMISSION_RATE = 0.001  # Deprecated: use transaction cost model below
BACKTEST_SLIPPAGE = 0.0005  # 0.05% per trade (Phase1 update)
# Transaction Cost Model (Phase1)
BROKERAGE_RATE = 0.0005  # 0.05% of trade value
BROKERAGE_CAP = 20.0  # ₹20 per trade cap
STT_DELIVERY = 0.001  # 0.1% for delivery (sell side only)
STT_INTRADAY = 0.00025  # 0.025% for intraday (both sides)
GST_RATE = 0.18  # 18% on brokerage
SLIPPAGE_RATE = 0.0005  # 0.05% per trade

# Options Settings
OPTIONS_MIN_VOLUME = 100
OPTIONS_MIN_OPEN_INTEREST = 500
UNUSUAL_OPTIONS_VOLUME_MULTIPLIER = 3.0  # 3x average volume

# Watchlist - Indian stocks
DEFAULT_WATCHLIST = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK"
]

# Predefined screeners for Indian market strategies
STRATEGY_SCREENERS = {
    "momentum": {
        "min_price_change_1m": 0.05,  # 5% up in month
        "min_rsi": 50,
        "volume_surge": 1.5,  # 1.5x average volume
    },
    "value": {
        "max_pe_ratio": 20,
        "min_dividend_yield": 0.01,  # 1% dividend yield
        "min_roe": 0.15,
    },
    "swing": {
        "min_atr_pct": 0.02,  # 2% ATR
        "trending": True,
    },
    "breakout": {
        "volume_surge": 2.0,  # 2x average volume
        "price_above_200ma": True,
        "rsi_range": (55, 70),
    }
}

# Risk Management
MAX_DRAWDOWN_PCT = 0.20  # 20% max drawdown
STOP_LOSS_ATR_MULTIPLIER = 2.0
TAKE_PROFIT_RR_RATIO = 2.0  # 2:1 reward:risk

# Initialize logging
logger = setup_logging()

# Validate configuration
validate_config()
