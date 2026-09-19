"""
统一缓存层：Redis + 内存二级缓存，支持分级TTL和优雅降级。

分级TTL策略（交易时段/非交易时段自动切换）：
- 实时行情类：30s / 5min
- 大盘/板块类：3min / 30min
- 新闻资讯类：5min / 1h
- 财务/基础数据：12h / 24h
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def json_default(obj: Any) -> Any:
    """Redis 缓存 JSON 序列化兜底：支持 datetime/date/set/tuple，
    避免含时间字段的结构写入 Redis 时整段失败（此前只写内存缓存）。"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (set, tuple)):
        return list(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# Redis 健康状态短缓存：避免每次缓存访问都 ping Redis
_redis_health_at: float = 0.0
_redis_health_ok: bool = False
_REDIS_HEALTH_TTL = 5.0

BEIJING = timezone(timedelta(hours=8))

# TTL 分级（秒）
TTL = {
    "realtime": {"trading": 30, "non_trading": 300},
    # 市场环境检测/大盘/情绪/概念：交易时段 10 分钟。
    # 冷启动重建需 5-30s（东财/同花顺外部源），60s 缓存期内容易被用户撞上冷启动；
    # 配合后台预热任务（market_data_prewarm）周期刷新，保证数据新鲜且多数请求命中缓存。
    "market": {"trading": 600, "non_trading": 1800},
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


def _memory_get(key: str) -> Any | None:
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
    """确保Redis可用，不可用则仅重建Redis连接（不重建MongoDB视图/索引）。"""
    global _redis_health_at, _redis_health_ok
    # 5s 内复用上次健康状态，避免每次缓存访问都 ping Redis
    if _redis_health_at and time.time() - _redis_health_at < _REDIS_HEALTH_TTL:
        return _redis_health_ok

    ok = False
    try:
        import app.core.database as db_mod
        client = db_mod.redis_client
        if client is not None and db_mod.db_manager._redis_healthy:
            try:
                await client.ping()
                ok = True
            except Exception:
                ok = False
        if not ok:
            # 仅重建 Redis 连接；不要调用 init_database()，
            # 否则会 drop/重建 MongoDB 视图与索引，造成性能雪崩
            await db_mod.db_manager.init_redis()
            db_mod.redis_client = db_mod.db_manager.redis_client
            db_mod.redis_pool = db_mod.db_manager.redis_pool
            ok = True
    except Exception as e:
        logger.warning(f"Redis重新初始化失败: {e}")
        ok = False

    _redis_health_at = time.time()
    _redis_health_ok = ok
    return ok


async def get_cache(key: str) -> Any | None:
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


async def set_cache(key: str, value: Any, ttl: int | None = None, category: str = "default"):
    """写入缓存（同时写Redis和内存）。"""
    if ttl is None:
        ttl = get_ttl(category)

    # 1. 写Redis
    if await _ensure_redis_available():
        try:
            from app.core.database import redis_client
            await redis_client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=json_default))
        except Exception as e:
            logger.warning(f"Redis写入失败，仅写内存缓存: {e}")

    # 2. 写内存缓存（TTL较短，最多60s）
    _memory_set(key, value, min(ttl, 60))


async def clear_cache(key: str):
    """清除指定 key 的缓存（Redis + 内存双清）。

    同时清除 SWR 备用旧值（key:stale）：只清正式 key 会让刷新后仍回退到
    旧的 stale 数据（如外围指数新增商品后 refresh 仍返回旧列表）。
    """
    keys = [key, f"{key}:stale"]
    if await _ensure_redis_available():
        try:
            from app.core.database import redis_client
            await redis_client.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis清除缓存失败: {e}")
    for k in keys:
        _memory_cache.pop(k, None)


# ---------------------------------------------------------------------------
# 缓存构建"单飞"：同一 key 任意时刻只允许一个构建任务（SWR 后台重建/冷启动
# 并发首建共用），其余请求合并等待同一任务结果，杜绝 N 个并发请求叠加重建。
# ---------------------------------------------------------------------------
_build_tasks: dict[str, asyncio.Task[Any]] = {}
_build_tasks_lock = asyncio.Lock()


def _execute_build(build_fn: Callable) -> Any:
    """执行构建函数：协程直接 await，同步函数放线程池避免阻塞事件循环。"""
    if asyncio.iscoroutinefunction(build_fn):
        return build_fn()
    return asyncio.to_thread(build_fn)


async def _build_and_cache(
    key: str, build_fn: Callable, category: str,
    valid: Callable[[Any], bool], ttl: int | None,
    stale_key: str | None, stale_ttl: int | None,
) -> Any:
    try:
        value = await _execute_build(build_fn)
        if valid(value):
            await set_cache(key, value, ttl=ttl, category=category)
            if stale_key:
                # 备用旧值：长 TTL（默认 3h），供 SWR 在正式 key 过期后回退
                await set_cache(stale_key, value, ttl=stale_ttl or 3 * 3600)
        else:
            logger.warning(f"缓存跳过（校验失败）: {key}")
        return value
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"缓存构建失败: {key} - {e}", exc_info=True)
        raise


async def _ensure_build_task(
    key: str, build_fn: Callable, category: str,
    valid: Callable[[Any], bool], ttl: int | None,
    stale_key: str | None, stale_ttl: int | None,
) -> asyncio.Task[Any]:
    """按原始 key 单飞去重；主缓存写入 key，备用旧值写入 stale_key。"""
    async with _build_tasks_lock:
        task = _build_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(
                _build_and_cache(key, build_fn, category, valid, ttl, stale_key, stale_ttl)
            )
            _build_tasks[key] = task

            def _cleanup(t: asyncio.Task) -> None:
                if _build_tasks.get(key) is t:
                    _build_tasks.pop(key, None)

            task.add_done_callback(_cleanup)
        return task


async def cached(key: str, build_fn: Callable, category: str = "default",
                 valid: Callable[[Any], bool] = bool, ttl: int | None = None,
                 swr: bool = False, stale_ttl: int | None = None) -> Any:
    """
    带缓存的数据获取：命中则返回，未命中则调用 build_fn 构建并缓存。
    valid 返回 False 的结果不缓存，下次直接重试。
    ttl 指定时覆盖分级 TTL（例如财经日历固定 1 天），否则按 category+时段自动分级。

    swr=True（stale-while-revalidate）：正式 key 过期但备用旧值仍有效时，
    立即返回旧值并在后台异步重建缓存，请求方无需等待；无旧值时才前台构建。
    所有构建（前台/后台）按 key 单飞合并，避免并发重建雪崩。
    """
    hit = await get_cache(key)
    if hit is not None:
        return hit

    stale_key = f"{key}:stale" if swr else None
    if stale_key:
        stale = await get_cache(stale_key)
        if stale is not None and valid(stale):
            # 后台异步重建，不阻塞本次请求；单飞防止重复重建
            await _ensure_build_task(key, build_fn, category, valid, ttl, stale_key, stale_ttl)
            return stale

    # 前台构建：单飞合并并发请求（同一 key 同时只构建一次，其余等待其结果）
    task = await _ensure_build_task(key, build_fn, category, valid, ttl, stale_key, stale_ttl)
    try:
        return await task
    finally:
        if _build_tasks.get(key) is task:
            async with _build_tasks_lock:
                if _build_tasks.get(key) is task:
                    _build_tasks.pop(key, None)
