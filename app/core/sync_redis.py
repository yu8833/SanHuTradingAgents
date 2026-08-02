"""
同步Redis客户端 - 用于筛选服务等同步代码
"""
import json
import logging

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# 全局同步Redis连接池
_sync_redis_pool: redis.ConnectionPool | None = None
_sync_redis_client: redis.Redis | None = None


def init_sync_redis() -> redis.Redis:
    """初始化同步Redis连接（懒加载）"""
    global _sync_redis_pool, _sync_redis_client
    if _sync_redis_client is not None:
        return _sync_redis_client

    try:
        _sync_redis_pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
            socket_keepalive=True,
        )
        _sync_redis_client = redis.Redis(connection_pool=_sync_redis_pool)
        _sync_redis_client.ping()
        logger.info("✅ 同步Redis连接成功")
    except Exception as e:
        logger.warning(f"⚠️ 同步Redis连接失败: {e}，缓存将被禁用")
        _sync_redis_client = None
    return _sync_redis_client


def get_sync_redis() -> redis.Redis | None:
    """获取同步Redis客户端，连接失败返回None（不抛异常）"""
    global _sync_redis_client
    if _sync_redis_client is None:
        init_sync_redis()
    return _sync_redis_client


class KlineCache:
    """
    K线数据Redis缓存
    - key: kline:{code}:{period}:{limit}
    - TTL: 交易日当天5分钟，非交易日1小时
    """

    # 缓存前缀
    PREFIX = "kline"

    def __init__(self, ttl_trading: int = 300, ttl_holiday: int = 3600):
        """
        Args:
            ttl_trading: 交易日TTL（秒），默认5分钟
            ttl_holiday: 非交易日TTL（秒），默认1小时
        """
        self.ttl_trading = ttl_trading
        self.ttl_holiday = ttl_holiday

    def _make_key(self, code: str, period: str, limit: int, adj: str) -> str:
        """生成缓存key"""
        adj_suffix = f"_{adj}" if adj else ""
        return f"{self.PREFIX}:{code}:{period}:{limit}{adj_suffix}"

    def _get_ttl(self) -> int:
        """根据当前时间判断TTL（交易日vs非交易日）"""
        import datetime
        now = datetime.datetime.now()
        weekday = now.weekday()
        # 周六周日一定是非交易日
        if weekday >= 5:
            return self.ttl_holiday
        # 检查是否在交易时间内 (9:30-15:00)
        hour_min = now.hour * 100 + now.minute
        if 930 <= hour_min <= 1500:
            return self.ttl_trading  # 交易时段缓存5分钟
        return self.ttl_holiday  # 非交易时段缓存1小时

    def get(self, code: str, period: str, limit: int, adj: str = None) -> list[dict] | None:
        """从缓存获取K线数据"""
        client = get_sync_redis()
        if client is None:
            return None

        try:
            key = self._make_key(code, period, limit, adj)
            data = client.get(key)
            if data:
                logger.debug(f"📦 缓存命中: {key}")
                return json.loads(data)
        except Exception as e:
            logger.warning(f"⚠️ 缓存读取失败: {e}")
        return None

    def set(self, code: str, period: str, limit: int, adj: str, data: list[dict]):
        """写入缓存"""
        client = get_sync_redis()
        if client is None:
            return

        try:
            key = self._make_key(code, period, limit, adj)
            ttl = self._get_ttl()
            client.setex(key, ttl, json.dumps(data, ensure_ascii=False))
            logger.debug(f"💾 缓存写入: {key} (TTL={ttl}s)")
        except Exception as e:
            logger.warning(f"⚠️ 缓存写入失败: {e}")

    def delete(self, code: str, period: str, limit: int, adj: str = None):
        """删除缓存"""
        client = get_sync_redis()
        if client is None:
            return

        try:
            key = self._make_key(code, period, limit, adj)
            client.delete(key)
        except Exception as e:
            logger.warning(f"⚠️ 缓存删除失败: {e}")

    def clear_all(self):
        """清除所有K线缓存（用于数据更新时）"""
        client = get_sync_redis()
        if client is None:
            return

        try:
            keys = client.keys(f"{self.PREFIX}:*")
            if keys:
                client.delete(*keys)
                logger.info(f"🗑️ 清除 {len(keys)} 条K线缓存")
        except Exception as e:
            logger.warning(f"⚠️ 清除缓存失败: {e}")


# 全局实例
kline_cache = KlineCache()
