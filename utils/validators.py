"""
Input validation utilities for SmartTrader
Validates ticker symbols, configuration values, and other inputs
"""

import re
import logging
from typing import List, Optional, Dict, Any

# Set up logger
logger = logging.getLogger(__name__)

# Valid ticker symbol pattern (letters, numbers, dots, hyphens - 1 to 10 chars)
TICKER_PATTERN = re.compile(r'^[A-Z0-9.\-]{1,10}$')

# Common invalid ticker patterns
INVALID_PATTERNS = [
    re.compile(r'^\d+$'),  # Only numbers
    re.compile(r'^[\.\-]+$'),  # Only dots or hyphens
]


def validate_ticker(ticker: str, market: str = 'US') -> Dict[str, Any]:
    """
    Validate a ticker symbol

    Args:
        ticker: The ticker symbol to validate
        market: 'US' for US markets, 'IN' for Indian markets

    Returns:
        Dict with 'valid' (bool), 'ticker' (normalized), 'error' (optional)
    """
    if not ticker or not isinstance(ticker, str):
        return {
            'valid': False,
            'ticker': ticker,
            'error': 'Ticker must be a non-empty string'
        }

    # Normalize ticker
    normalized = ticker.strip().upper()

    # Check length (allow up to 12 chars for Indian tickers with .NS/.BO suffix)
    max_length = 12 if market.upper() == 'IN' else 10
    if len(normalized) < 1 or len(normalized) > max_length:
        return {
            'valid': False,
            'ticker': normalized,
            'error': f'Ticker length must be between 1 and {max_length} characters, got {len(normalized)}'
        }

    # Check format based on market
    if market.upper() == 'US':
        # US tickers: letters, numbers, dots (for BRK.B), max 5 chars typically
        if not re.match(r'^[A-Z][A-Z0-9.]{0,9}$', normalized):
            return {
                'valid': False,
                'ticker': normalized,
                'error': f'Invalid US ticker format: {normalized}. Use format like AAPL, BRK.B'
            }
    elif market.upper() == 'IN':
        # Indian tickers: can have .NS (NSE) or .BO (BSE) suffix
        # Pattern: 1-9 alphanumeric chars, optionally followed by .NS or .BO
        if not re.match(r'^[A-Z0-9]{1,9}(\.NS|\.BO)?$', normalized):
            return {
                'valid': False,
                'ticker': normalized,
                'error': f'Invalid Indian ticker format: {normalized}. Use format like RELIANCE, TCS.NS'
            }

    # Check for invalid patterns
    for pattern in INVALID_PATTERNS:
        if pattern.match(normalized):
            return {
                'valid': False,
                'ticker': normalized,
                'error': f'Ticker has invalid format: {normalized}'
            }

    return {
        'valid': True,
        'ticker': normalized,
        'error': None
    }


def validate_tickers(tickers: List[str], market: str = 'US') -> Dict[str, Any]:
    """
    Validate a list of ticker symbols

    Returns:
        Dict with 'valid' (list of valid tickers), 'invalid' (list of validation results)
    """
    valid = []
    invalid = []

    for ticker in tickers:
        result = validate_ticker(ticker, market)
        if result['valid']:
            valid.append(result['ticker'])
        else:
            invalid.append(result)
            logger.warning(f"Invalid ticker: {result['error']}")

    return {
        'valid': valid,
        'invalid': invalid
    }


def validate_numeric_range(value: Any, min_val: Optional[float] = None,
                         max_val: Optional[float] = None, name: str = 'value') -> Dict[str, Any]:
    """
    Validate that a numeric value is within range

    Returns:
        Dict with 'valid' (bool), 'value' (the input), 'error' (optional)
    """
    try:
        num_value = float(value)
    except (ValueError, TypeError):
        return {
            'valid': False,
            'value': value,
            'error': f'{name} must be a number, got {value}'
        }

    if min_val is not None and num_value < min_val:
        return {
            'valid': False,
            'value': num_value,
            'error': f'{name} must be >= {min_val}, got {num_value}'
        }

    if max_val is not None and num_value > max_val:
        return {
            'valid': False,
            'value': num_value,
            'error': f'{name} must be <= {max_val}, got {num_value}'
        }

    return {
        'valid': True,
        'value': num_value,
        'error': None
    }


def validate_percentage(value: Any, name: str = 'percentage') -> Dict[str, Any]:
    """
    Validate that a value is a valid percentage (0 to 100)
    """
    return validate_numeric_range(value, min_val=0, max_val=100, name=name)


def validate_probability(value: Any, name: str = 'probability') -> Dict[str, Any]:
    """
    Validate that a value is a valid probability (0 to 1)
    """
    return validate_numeric_range(value, min_val=0, max_val=1, name=name)


def validate_positive_number(value: Any, name: str = 'value') -> Dict[str, Any]:
    """
    Validate that a value is a positive number
    """
    return validate_numeric_range(value, min_val=0, max_val=None, name=name)


def validate_api_key(key: str, key_name: str = 'API key') -> Dict[str, Any]:
    """
    Validate an API key format

    Returns:
        Dict with 'valid' (bool), 'error' (optional)
    """
    if not key or not isinstance(key, str):
        return {
            'valid': False,
            'error': f'{key_name} must be a non-empty string'
        }

    key = key.strip()

    if len(key) < 10:
        return {
            'valid': False,
            'error': f'{key_name} appears too short (less than 10 characters)'
        }

    return {
        'valid': True,
        'error': None
    }


def validate_file_path(path: str, must_exist: bool = False) -> Dict[str, Any]:
    """
    Validate a file path

    Args:
        path: The path to validate
        must_exist: If True, path must exist

    Returns:
        Dict with 'valid' (bool), 'path' (normalized), 'error' (optional)
    """
    import os
    from pathlib import Path

    if not path or not isinstance(path, str):
        return {
            'valid': False,
            'path': path,
            'error': 'Path must be a non-empty string'
        }

    try:
        normalized = str(Path(path).resolve())
    except Exception as e:
        return {
            'valid': False,
            'path': path,
            'error': f'Invalid path: {e}'
        }

    if must_exist and not os.path.exists(normalized):
        return {
            'valid': False,
            'path': normalized,
            'error': f'Path does not exist: {normalized}'
        }

    return {
        'valid': True,
        'path': normalized,
        'error': None
    }


# Example usage
if __name__ == '__main__':
    # Test ticker validation
    test_tickers = ['AAPL', 'brk.b', '123', '', 'TCS.NS', 'INVALID@TICKER']

    print("Testing ticker validation:")
    for ticker in test_tickers:
        result = validate_ticker(ticker)
        status = 'VALID' if result['valid'] else 'INVALID'
        print(f"  {ticker}: {status} {result['error'] or ''}")

    # Test numeric validation
    print("\nTesting numeric validation:")
    print(f"  validate_probability(0.5): {validate_probability(0.5)}")
    print(f"  validate_probability(1.5): {validate_probability(1.5)}")
    print(f"  validate_positive_number(100): {validate_positive_number(100)}")
    print(f"  validate_positive_number(-5): {validate_positive_number(-5)}")
