"""
同步统一缓存层：Redis + 内存二级缓存，支持分级TTL和优雅降级。
用于同步代码（如unified_quotes、quotes_service等）。

分级TTL策略（交易时段/非交易时段自动切换）：
- 实时行情类：30s / 5min
- 大盘/板块类：3min / 30min
- 新闻资讯类：5min / 1h
- 财务/基础数据：12h / 24h
"""

from __future__ import annotations

import time
import json
import logging
from typing import Any, Callable, Optional
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))

TTL = {
    "realtime": {"trading": 30, "non_trading": 300},
    "market": {"trading": 180, "non_trading": 1800},
    "news": {"trading": 300, "non_trading": 3600},
    "financial": {"trading": 43200, "non_trading": 86400},
    "default": {"trading": 300, "non_trading": 1800},
}


def _is_trading_hours() -> bool:
    now = datetime.now(BEIJING)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60)


def get_ttl(category: str) -> int:
    cat = TTL.get(category, TTL["default"])
    return cat["trading"] if _is_trading_hours() else cat["non_trading"]


_memory_cache: dict[str, tuple[float, Any]] = {}
_MEMORY_MAX = 500


def _memory_get(key: str) -> Optional[Any]:
    hit = _memory_cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() > ts:
        _memory_cache.pop(key, None)
        return None
    return val


def _memory_set(key: str, value: Any, ttl: int = 60):
    if len(_memory_cache) >= _MEMORY_MAX:
        for k in list(_memory_cache.keys())[:_MEMORY_MAX // 2]:
            _memory_cache.pop(k, None)
    _memory_cache[key] = (time.time() + ttl, value)


def _redis_available() -> bool:
    try:
        from app.core.sync_redis import get_sync_redis
        return get_sync_redis() is not None
    except Exception:
        return False


def get_cache_sync(key: str) -> Optional[Any]:
    if _redis_available():
        try:
            from app.core.sync_redis import get_sync_redis
            redis = get_sync_redis()
            if redis:
                raw = redis.get(key)
                if raw:
                    return json.loads(raw)
        except Exception as e:
            logger.warning(f"Redis读取失败，降级到内存缓存: {e}")

    return _memory_get(key)


def set_cache_sync(key: str, value: Any, ttl: Optional[int] = None, category: str = "default"):
    if ttl is None:
        ttl = get_ttl(category)

    if _redis_available():
        try:
            from app.core.sync_redis import get_sync_redis
            redis = get_sync_redis()
            if redis:
                redis.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Redis写入失败，仅写内存缓存: {e}")

    _memory_set(key, value, min(ttl, 60))


def cached_sync(key: str, build_fn: Callable, category: str = "default",
                valid: Callable[[Any], bool] = bool) -> Any:
    hit = get_cache_sync(key)
    if hit is not None:
        return hit

    value = build_fn()

    if valid(value):
        set_cache_sync(key, value, category=category)
    else:
        logger.warning(f"缓存跳过（校验失败）: {key}")

    return value
