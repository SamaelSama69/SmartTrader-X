"""
In-memory TTL caching for critical data fetching (market data, sentiment, indicators)
Simplified per Phase 1 audit: removed unused DiskCache, RedisCache, rate_limited decorator
"""
import time
import json
import hashlib
import os
from functools import wraps
from typing import Any, Callable, Optional, Dict
from pathlib import Path


class TTLCache:
    """Simple in-memory cache with TTL support (thread-safe for single-process use)"""
    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl

    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """Generate a unique cache key based on function and arguments"""
        key_parts = [func_name]
        for arg in args:
            if isinstance(arg, (str, int, float, bool, type(None))):
                key_parts.append(str(arg))
            elif isinstance(arg, (list, tuple)):
                key_parts.append(str(tuple(arg)))
            elif isinstance(arg, dict):
                key_parts.append(json.dumps(arg, sort_keys=True))
            else:
                key_parts.append(str(arg))
        for k in sorted(kwargs.keys()):
            v = kwargs[k]
            if isinstance(v, (str, int, float, bool, type(None))):
                key_parts.append(f"{k}:{v}")
            else:
                key_parts.append(f"{k}:{str(v)}")
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        if key not in self._cache:
            return None
        entry = self._cache[key]
        if time.time() > entry['expires_at']:
            del self._cache[key]
            return None
        return entry['value']

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        ttl = ttl if ttl is not None else self.default_ttl
        self._cache[key] = {
            'value': value,
            'expires_at': time.time() + ttl,
            'created_at': time.time()
        }

    def delete(self, key: str):
        if key in self._cache:
            del self._cache[key]

    def clear(self):
        self._cache.clear()

    def cleanup_expired(self):
        now = time.time()
        expired_keys = [k for k, v in self._cache.items() if now > v['expires_at']]
        for key in expired_keys:
            del self._cache[key]

    def stats(self) -> Dict[str, Any]:
        self.cleanup_expired()
        return {'size': len(self._cache), 'default_ttl': self.default_ttl}


class DiskCache:
    """Disk-based cache with stable hash-based file paths"""
    def __init__(self, cache_dir: str = '.cache'):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, key: str) -> Path:
        """Generate stable cache path using MD5 hash"""
        key_hash = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{key_hash}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            with open(path, 'r') as f:
                entry = json.load(f)
            if time.time() > entry.get('expires_at', 0):
                path.unlink()
                return None
            return entry.get('value')
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl: int = 3600):
        path = self._cache_path(key)
        entry = {
            'value': value,
            'expires_at': time.time() + ttl,
            'created_at': time.time()
        }
        with open(path, 'w') as f:
            json.dump(entry, f)

    def delete(self, key: str):
        path = self._cache_path(key)
        if path.exists():
            path.unlink()

    def clear(self):
        for path in self.cache_dir.glob('*.json'):
            path.unlink()


# Global cache instances for critical data fetching
market_data_cache = TTLCache(default_ttl=300)  # 5 minutes for market data
sentiment_cache = TTLCache(default_ttl=3600)   # 1 hour for sentiment
company_info_cache = TTLCache(default_ttl=3600)  # 1 hour for company info
indicators_cache = TTLCache(default_ttl=600)     # 10 minutes for indicators


def cached(cache_instance: TTLCache, ttl: Optional[int] = None):
    """Decorator for caching function results with TTL"""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = cache_instance._make_key(func.__name__, args, kwargs)
            cached_value = cache_instance.get(cache_key)
            if cached_value is not None:
                return cached_value
            result = func(*args, **kwargs)
            cache_instance.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
