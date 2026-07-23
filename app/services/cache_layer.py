"""
统一缓存层：Redis + 内存二级缓存，支持分级TTL和优雅降级。

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

# TTL 分级（秒）
TTL = {
    "realtime": {"trading": 30, "non_trading": 300},
    "market": {"trading": 180, "non_trading": 1800},
    "news": {"trading": 300, "non_trading": 3600},
    "financial": {"trading": 43200, "non_trading": 86400},
    "default": {"trading": 300, "non_trading": 1800},
}


def _is_trading_hours() -> bool:
    """判断当前是否为A股交易时段（9:30-11:30, 13:00-15:00）。"""
    now = datetime.now(BEIJING)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 30 <= t <= 11 * 60 + 30) or (13 * 60 <= t <= 15 * 60)


def get_ttl(category: str) -> int:
    """根据数据类别和当前时段获取TTL（秒）。"""
    cat = TTL.get(category, TTL["default"])
    return cat["trading"] if _is_trading_hours() else cat["non_trading"]


# 内存二级缓存（Redis不可用时的兜底）
_memory_cache: dict[str, tuple[float, Any]] = {}
_MEMORY_MAX = 500


def _memory_get(key: str) -> Optional[Any]:
    hit = _memory_cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > 60:
        _memory_cache.pop(key, None)
        return None
    return val


def _memory_set(key: str, value: Any, ttl: int = 60):
    if len(_memory_cache) >= _MEMORY_MAX:
        for k in list(_memory_cache.keys())[:_MEMORY_MAX // 2]:
            _memory_cache.pop(k, None)
    _memory_cache[key] = (time.time() + ttl, value)


async def _ensure_redis_available() -> bool:
    """确保Redis可用，如果不可用则尝试重新初始化。"""
    try:
        from app.core.database import redis_client, db_manager
        if redis_client is not None and db_manager._redis_healthy:
            try:
                await redis_client.ping()
                return True
            except Exception:
                pass
        
        await db_manager.init_redis()
        from app.core.database import init_database
        await init_database()
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger("webapi")
        logger.warning(f"Redis重新初始化失败: {e}")
        return False


async def get_cache(key: str) -> Optional[Any]:
    """从缓存获取数据（优先Redis，兜底内存）。"""
    # 1. 尝试Redis
    if await _ensure_redis_available():
        try:
            from app.core.database import redis_client
            raw = await redis_client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"Redis读取失败，降级到内存缓存: {e}")

    # 2. 内存缓存兜底
    return _memory_get(key)


async def set_cache(key: str, value: Any, ttl: Optional[int] = None, category: str = "default"):
    """写入缓存（同时写Redis和内存）。"""
    if ttl is None:
        ttl = get_ttl(category)

    # 1. 写Redis
    if await _ensure_redis_available():
        try:
            from app.core.database import redis_client
            await redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Redis写入失败，仅写内存缓存: {e}")

    # 2. 写内存缓存（TTL较短，最多60s）
    _memory_set(key, value, min(ttl, 60))


async def cached(key: str, build_fn: Callable, category: str = "default",
                 valid: Callable[[Any], bool] = bool) -> Any:
    """
    带缓存的数据获取：命中则返回，未命中则调用 build_fn 构建并缓存。
    valid 返回 False 的结果不缓存，下次直接重试。
    """
    hit = await get_cache(key)
    if hit is not None:
        return hit

    value = build_fn()

    if valid(value):
        await set_cache(key, value, category=category)
    else:
        logger.warning(f"缓存跳过（校验失败）: {key}")

    return value
