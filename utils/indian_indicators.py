"""
Indian-Specific Technical Indicators
Critical indicators used by Indian traders for NSE/BSE markets

VWAP is now calculated on intraday (5m/15m) bars with daily reset — the only
correct way to compute VWAP for Indian intraday trading.
"""

import logging
import pandas as pd
import numpy as np
import pytz
import yfinance as yf
logger = logging.getLogger(__name__)
try:
    import vectorbt as vbt
    VBT_AVAILABLE = True
except ImportError:
    VBT_AVAILABLE = False
    logger.info("vectorbt not installed — using manual indicator calculation")
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date


def get_intraday_data(ticker: str, interval: str = '5m', days: int = 5) -> pd.DataFrame:
    """
    Fetch intraday OHLCV data needed for real VWAP computation.
    yfinance supports '1m','2m','5m','15m','30m','60m','90m' intervals.
    """
    try:
        df = yf.download(ticker, period=f'{days}d', interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            logger.warning(f"No intraday data for {ticker} at {interval}")
        return df
    except Exception as e:
        logger.error(f"Intraday fetch error for {ticker}: {e}")
        return pd.DataFrame()


from utils.cache import indicators_cache, cached

@cached(indicators_cache)
def calculate_vwap(df: pd.DataFrame, anchor: str = 'day') -> pd.Series:
    """
    Calculate VWAP correctly — resets at the start of each trading day.

    For daily OHLCV data (one row per day), returns a volume-weighted
    moving average of the typical price — useful as a trend filter but
    NOT the same as intraday VWAP.

    For intraday data (5m/15m bars), returns a true session VWAP that
    resets at 9:15 AM IST each morning — this is what Indian traders use.

    Parameters:
    -----------
    df : pd.DataFrame — must have High, Low, Close, Volume columns
    anchor : 'day' resets VWAP each calendar day; 'session' treats all rows as one session

    Returns:
    --------
    pd.Series of VWAP values, same index as df
    """
    if df.empty or not all(col in df.columns for col in ['High', 'Low', 'Close', 'Volume']):
        return pd.Series(index=df.index, dtype=float)

    typical_price = (df['High'] + df['Low'] + df['Close']) / 3

    # Detect intraday vs daily data
    is_intraday = False
    if hasattr(df.index, 'freq') and df.index.freq is not None:
        is_intraday = df.index.freq.n < 60 * 24  # Less than 1-day frequency
    elif len(df) > 1:
        delta = (df.index[1] - df.index[0]).total_seconds()
        is_intraday = delta < 86400  # Less than 1 day between rows

    if is_intraday and anchor == 'day':
        # True intraday VWAP: reset cumulative sums at each new calendar day
        try:
            ist = pytz.timezone('Asia/Kolkata')
            if df.index.tz is None:
                idx_ist = df.index.tz_localize('UTC').tz_convert(ist)
            else:
                idx_ist = df.index.tz_convert(ist)
            dates = pd.Series(idx_ist.date, index=df.index)
        except Exception:
            dates = pd.Series([i.date() if hasattr(i, 'date') else i for i in df.index],
                               index=df.index)

        vwap = pd.Series(index=df.index, dtype=float)
        for day, group_idx in df.groupby(dates.values).groups.items():
            grp = df.loc[group_idx]
            tp = (grp['High'] + grp['Low'] + grp['Close']) / 3
            cum_tpvol = (tp * grp['Volume']).cumsum()
            cum_vol = grp['Volume'].cumsum().replace(0, np.nan)
            vwap.loc[group_idx] = cum_tpvol / cum_vol
        return vwap
    else:
        # Daily data: rolling volume-weighted average (useful as trend filter)
        cum_tpvol = (typical_price * df['Volume']).cumsum()
        cum_vol = df['Volume'].cumsum().replace(0, np.nan)
        return cum_tpvol / cum_vol


@cached(indicators_cache)
def calculate_pivot_points(df: pd.DataFrame, method: str = 'classic') -> Dict[str, float]:
    """
    Calculate Pivot Points using previous day's completed candle (iloc[-2]).
    Methods: 'classic', 'fibonacci', 'camarilla'
    """
    if df.empty or not all(col in df.columns for col in ['High', 'Low', 'Close']):
        return {}
    if len(df) < 2:
        logger.warning("Need at least 2 rows for pivot points")
        return {}

    # Correct: use previous completed day (iloc[-2]), not today (iloc[-1])
    prev_high  = df['High'].iloc[-2]
    prev_low   = df['Low'].iloc[-2]
    prev_close = df['Close'].iloc[-2]

    pivot = (prev_high + prev_low + prev_close) / 3
    result = {'pivot': pivot, 'high': prev_high, 'low': prev_low, 'close': prev_close}

    if method == 'classic':
        r1 = (2 * pivot) - prev_low
        r2 = pivot + (prev_high - prev_low)
        r3 = r1 + (prev_high - prev_low)
        s1 = (2 * pivot) - prev_high
        s2 = pivot - (prev_high - prev_low)
        s3 = s1 - (prev_high - prev_low)
        result.update({'r1': r1, 'r2': r2, 'r3': r3, 's1': s1, 's2': s2, 's3': s3})

    elif method == 'fibonacci':
        diff = prev_high - prev_low
        result.update({
            'r1': pivot + 0.382 * diff, 'r2': pivot + 0.618 * diff, 'r3': pivot + diff,
            's1': pivot - 0.382 * diff, 's2': pivot - 0.618 * diff, 's3': pivot - diff,
        })

    elif method == 'camarilla':
        diff = prev_high - prev_low
        result.update({
            'r1': prev_close + diff * 1.1 / 12, 'r2': prev_close + diff * 1.1 / 6,
            'r3': prev_close + diff * 1.1 / 4,  'r4': prev_close + diff * 1.1 / 2,
            's1': prev_close - diff * 1.1 / 12, 's2': prev_close - diff * 1.1 / 6,
            's3': prev_close - diff * 1.1 / 4,  's4': prev_close - diff * 1.1 / 2,
        })

    return result


@cached(indicators_cache)
def calculate_cpr(df: pd.DataFrame) -> Dict[str, float]:
    """
    Central Pivot Range (CPR) — uses previous day's data (iloc[-2]).
    """
    if df.empty or not all(col in df.columns for col in ['High', 'Low', 'Close']):
        return {}
    if len(df) < 2:
        logger.warning("Need at least 2 rows for CPR")
        return {}

    prev_high  = df['High'].iloc[-2]
    prev_low   = df['Low'].iloc[-2]
    prev_close = df['Close'].iloc[-2]

    pivot = (prev_high + prev_low + prev_close) / 3
    bc    = (prev_high + prev_low) / 2
    tc    = (pivot + bc) / 2
    cpr_width = abs(tc - bc)

    return {
        'pivot': pivot, 'tc': tc, 'bc': bc,
        'cpr_width': cpr_width,
        'cpr_narrow': cpr_width < (prev_high - prev_low) * 0.2
    }


@cached(indicators_cache)
def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range"""
    if df.empty or not all(col in df.columns for col in ['High', 'Low', 'Close']):
        return pd.Series(index=df.index, dtype=float)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low']  - df['Close'].shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


@cached(indicators_cache)
def calculate_supertrend(df: pd.DataFrame, period: int = 10,
                          multiplier: float = 3.0) -> pd.DataFrame:
    """
    Supertrend Indicator
    Returns DataFrame with 'supertrend', 'direction', 'upper_band', 'lower_band' columns
    """
    if df.empty or not all(col in df.columns for col in ['High', 'Low', 'Close']):
        return df.copy()

    result_df = df.copy()
    atr = calculate_atr(df, period)

    # Basic bands
    basic_upper = (df['High'] + df['Low']) / 2 + multiplier * atr
    basic_lower = (df['High'] + df['Low']) / 2 - multiplier * atr

    # Initialize with scalar values (use .values to avoid Series assignment issues)
    n = len(df)
    final_upper = [None] * n
    final_lower = [None] * n
    direction = [0] * n
    supertrend = [None] * n

    for i in range(period, n):
        hi = float(df['High'].iloc[i])
        lo = float(df['Low'].iloc[i])
        cl = float(df['Close'].iloc[i])
        cl_prev = float(df['Close'].iloc[i-1])

        if i == period:
            final_upper[i] = float(basic_upper.iloc[i])
            final_lower[i] = float(basic_lower.iloc[i])
            direction[i] = 1 if cl > final_upper[i] else -1
        else:
            # Upper band
            if cl_prev <= final_upper[i-1]:
                final_upper[i] = min(float(basic_upper.iloc[i]), final_upper[i-1])
            else:
                final_upper[i] = float(basic_upper.iloc[i])

            # Lower band
            if cl_prev >= final_lower[i-1]:
                final_lower[i] = max(float(basic_lower.iloc[i]), final_lower[i-1])
            else:
                final_lower[i] = float(basic_lower.iloc[i])

            # Direction
            if cl <= final_upper[i-1]:
                direction[i] = -1
            elif cl >= final_lower[i-1]:
                direction[i] = 1
            else:
                direction[i] = direction[i-1]

        # Supertrend value
        supertrend[i] = final_lower[i] if direction[i] == 1 else final_upper[i]

    result_df['supertrend'] = supertrend
    result_df['direction'] = direction
    result_df['upper_band'] = final_upper
    result_df['lower_band'] = final_lower
    return result_df


@cached(indicators_cache)
def calculate_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI using vectorbt if available, else manual calculation"""
    if df.empty or 'Close' not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    if VBT_AVAILABLE:
        rsi = vbt.RSI.run(df['Close'], window=period)
        return rsi.rsi
    # Manual RSI calculation
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.inf)
    return 100 - (100 / (1 + rs))


@cached(indicators_cache)
def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD using vectorbt if available, else manual calculation"""
    if df.empty or 'Close' not in df.columns:
        return pd.DataFrame(index=df.index)
    if VBT_AVAILABLE:
        macd = vbt.MACD.run(df['Close'], fast_window=fast, slow_window=slow, signal_window=signal)
        return pd.DataFrame({
            'macd': macd.macd,
            'signal': macd.signal,
            'histogram': macd.histogram
        }, index=df.index)
    # Manual MACD calculation
    ema_fast = df['Close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['Close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({
        'macd': macd_line,
        'signal': signal_line,
        'histogram': histogram
    }, index=df.index)


@cached(indicators_cache)
def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average Directional Index — measures trend strength, not direction.
    ADX > 25: strong trend (use trend-following strategies)
    ADX < 20: ranging market (use mean-reversion strategies)
    """
    if df.empty or len(df) < period * 2:
        return pd.Series(index=df.index, dtype=float)

    high, low, close = df['High'], df['Low'], df['Close']

    plus_dm  = high.diff()
    minus_dm = low.diff().abs()
    plus_dm  = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr_n     = tr.rolling(period).mean()
    plus_di   = 100 * (plus_dm.rolling(period).mean()  / atr_n)
    minus_di  = 100 * (minus_dm.rolling(period).mean() / atr_n)
    dx        = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx       = dx.rolling(period).mean()
    return adx.round(2)


def calculate_bollinger_bands(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> dict:
    """Return upper, mid, lower bands and bandwidth."""
    if df.empty:
        return {'upper': pd.Series(dtype=float), 'mid': pd.Series(dtype=float),
                'lower': pd.Series(dtype=float), 'bandwidth': pd.Series(dtype=float),
                'pct_b': pd.Series(dtype=float)}

    mid   = df['Close'].rolling(period).mean()
    sigma = df['Close'].rolling(period).std()
    return {
        'upper':     (mid + std * sigma).round(2),
        'mid':       mid.round(2),
        'lower':     (mid - std * sigma).round(2),
        'bandwidth': ((std * 2 * sigma) / mid * 100).round(2),
        'pct_b':     ((df['Close'] - (mid - std * sigma)) / (std * 2 * sigma)).round(3),
    }


def get_india_pcr(index: str = 'NIFTY') -> float:
    """
    Fetch current Put-Call Ratio from NSE.
    PCR > 1.3: overly bearish (contrarian BUY signal)
    PCR < 0.7: overly bullish (contrarian SELL signal)
    PCR 0.7-1.3: neutral
    """
    try:
        url = f"https://www.nseindia.com/api/option-chain-indices?symbol={index}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'application/json',
            'Referer': 'https://www.nseindia.com'
        }
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        total_pe_oi = sum(r.get('PE', {}).get('openInterest', 0) for r in data['records']['data'] if 'PE' in r)
        total_ce_oi = sum(r.get('CE', {}).get('openInterest', 0) for r in data['records']['data'] if 'CE' in r)
        if total_ce_oi > 0:
            return round(total_pe_oi / total_ce_oi, 2)
    except Exception as e:
        logger.debug(f"PCR fetch failed: {e}")
    return 1.0


def compute_all(df: pd.DataFrame) -> Dict:
    """
    Compute all indicators for a single stock (vectorized with vectorbt)
    Target: <1s per stock
    """
    if df.empty:
        return {}
    result = {}
    try:
        result['rsi'] = calculate_rsi(df)
        result['macd'] = calculate_macd(df)
        result['supertrend'] = calculate_supertrend(df)
        result['vwap'] = calculate_vwap(df)
        result['atr'] = calculate_atr(df)
        result['pivot'] = calculate_pivot_points(df)
        result['cpr'] = calculate_cpr(df)
    except Exception as e:
        logger.error(f"Error computing indicators: {e}")
    return result


def get_indian_intraday_signals(df: pd.DataFrame) -> Dict:
    """
    Generate composite signal from VWAP + CPR + Supertrend.
    Expects daily OHLCV data. For real intraday VWAP, pass intraday bars.
    """
    if df.empty:
        return {'signal': 'HOLD', 'confidence': 0.0, 'reasons': []}

    score   = 0
    reasons = []
    signals = []

    vwap          = calculate_vwap(df)
    current_price = df['Close'].iloc[-1]
    current_vwap  = vwap.iloc[-1]

    if not pd.isna(current_vwap):
        if current_price > current_vwap:
            score += 2
            reasons.append("Price above VWAP (Bullish)")
        else:
            score -= 2
            reasons.append("Price below VWAP (Bearish)")
        signals.append({'indicator': 'VWAP', 'value': round(float(current_vwap), 2)})

    cpr = calculate_cpr(df)
    if cpr:
        if current_price > cpr['tc']:
            score += 2
            reasons.append("Price above CPR Top (Strong Bullish)")
        elif current_price < cpr['bc']:
            score -= 2
            reasons.append("Price below CPR Bottom (Strong Bearish)")
        else:
            reasons.append("Price within CPR range (Neutral)")
        signals.append({'indicator': 'CPR', 'tc': round(cpr['tc'], 2), 'bc': round(cpr['bc'], 2)})

    df_with_st = calculate_supertrend(df)
    if 'direction' in df_with_st.columns:
        current_direction = df_with_st['direction'].iloc[-1]
        if current_direction == 1:
            score += 2
            reasons.append("Supertrend: Uptrend")
        elif current_direction == -1:
            score -= 2
            reasons.append("Supertrend: Downtrend")
        signals.append({'indicator': 'Supertrend',
                         'direction': 'UP' if current_direction == 1 else 'DOWN'})

    pivots = calculate_pivot_points(df, 'classic')
    signals.append({'indicator': 'Pivot', 'levels': pivots})

    confidence = min(abs(score) / 6.0, 1.0)
    signal = 'BUY' if score >= 3 else 'SELL' if score <= -3 else 'HOLD'

    return {
        'signal': signal, 'confidence': confidence,
        'score': score, 'reasons': reasons,
        'indicators': signals, 'current_price': current_price
    }


def is_expiry_day() -> bool:
    """Thursday = Nifty/BankNifty weekly expiry (IST-aware)"""
    ist   = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist)
    return today.weekday() == 3


def is_budget_day() -> bool:
    """February 1st = Union Budget Day (IST-aware)"""
    ist   = pytz.timezone('Asia/Kolkata')
    today = datetime.now(ist)
    return today.month == 2 and today.day == 1
