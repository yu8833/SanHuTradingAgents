"""
TradingAgentsGraph 实例缓存管理器
复用图实例，减少重复初始化开销
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GraphInstance:
    """图实例包装类"""
    graph: Any
    config: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    last_used: datetime = field(default_factory=datetime.now)
    use_count: int = 0

    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """检查实例是否过期"""
        age = (datetime.now() - self.created_at).total_seconds()
        return age > max_age_seconds

    def refresh(self):
        """刷新最后使用时间"""
        self.last_used = datetime.now()
        self.use_count += 1


class GraphCache:
    """
    TradingAgentsGraph 实例缓存管理器

    设计原则:
    - 根据配置（模型、分析师列表）缓存图实例
    - 实例有最大生命周期（默认1小时）
    - 最多缓存 N 个实例，超出时清理最久未使用的
    - 线程安全
    """

    def __init__(
        self,
        max_instances: int = 5,
        max_age_seconds: int = 3600,
        cleanup_interval_seconds: int = 300
    ):
        self._cache: dict[str, GraphInstance] = {}
        self._lock = threading.Lock()
        self._max_instances = max_instances
        self._max_age_seconds = max_age_seconds
        self._last_cleanup = time.time()

        logger.info(
            f"📊 [图缓存] 初始化完成: "
            f"max_instances={max_instances}, "
            f"max_age={max_age_seconds}s"
        )

    def _generate_key(self, config: dict[str, Any], selected_analysts: list[str]) -> str:
        """生成缓存键"""
        # 使用关键配置参数生成唯一键
        key_parts = [
            str(selected_analysts),
            config.get("llm_provider", ""),
            config.get("quick_think_llm", ""),
            config.get("deep_think_llm", ""),
        ]

        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()

    def get(self, config: dict[str, Any], selected_analysts: list[str]) -> Any | None:
        """
        获取缓存的图实例

        Args:
            config: 图配置
            selected_analysts: 分析师列表

        Returns:
            缓存的图实例，如果没有则返回 None
        """
        key = self._generate_key(config, selected_analysts)

        with self._lock:
            if key in self._cache:
                instance = self._cache[key]

                # 检查是否过期
                if instance.is_expired(self._max_age_seconds):
                    logger.info(f"📊 [图缓存] 实例已过期，移除: {key[:8]}...")
                    del self._cache[key]
                    return None

                # 刷新使用时间
                instance.refresh()
                logger.info(
                    f"📊 [图缓存] 命中: {key[:8]}..., "
                    f"使用次数: {instance.use_count}, "
                    f"创建时间: {instance.created_at.strftime('%H:%M:%S')}"
                )
                return instance.graph

        return None

    def put(self, config: dict[str, Any], selected_analysts: list[str], graph: Any) -> str:
        """
        缓存图实例

        Args:
            config: 图配置
            selected_analysts: 分析师列表
            graph: 图实例

        Returns:
            缓存键
        """
        key = self._generate_key(config, selected_analysts)

        with self._lock:
            # 检查是否需要清理
            self._maybe_cleanup()

            # 添加或更新实例
            if key in self._cache:
                self._cache[key].refresh()
                self._cache[key].graph = graph
                logger.info(f"📊 [图缓存] 更新实例: {key[:8]}...")
            else:
                self._cache[key] = GraphInstance(
                    graph=graph,
                    config=config.copy()
                )
                logger.info(f"📊 [图缓存] 新增实例: {key[:8]}..., 当前缓存数: {len(self._cache)}")

        return key

    def _maybe_cleanup(self):
        """检查并清理过期实例"""
        now = time.time()

        # 检查是否需要执行清理
        if now - self._last_cleanup < 300:  # 5分钟清理一次
            return

        # 清理过期实例
        expired_keys = [
            key for key, instance in self._cache.items()
            if instance.is_expired(self._max_age_seconds)
        ]

        for key in expired_keys:
            del self._cache[key]
            logger.info(f"📊 [图缓存] 清理过期实例: {key[:8]}...")

        # 如果实例数量超限，清理最久未使用的
        while len(self._cache) > self._max_instances:
            oldest_key = min(
                self._cache.keys(),
                key=lambda k: self._cache[k].last_used
            )
            del self._cache[oldest_key]
            logger.info(f"📊 [图缓存] 清理最久未使用实例: {oldest_key[:8]}..., 缓存数: {len(self._cache) + 1} -> {len(self._cache)}")

        self._last_cleanup = now

    def clear(self):
        """清空所有缓存"""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"📊 [图缓存] 清空缓存: {count} 个实例")

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            instances = list(self._cache.values())

            if not instances:
                return {
                    "count": 0,
                    "total_uses": 0,
                    "avg_age_seconds": 0,
                    "oldest_instance": None,
                }

            return {
                "count": len(instances),
                "total_uses": sum(i.use_count for i in instances),
                "avg_age_seconds": sum(
                    (datetime.now() - i.created_at).total_seconds()
                    for i in instances
                ) / len(instances),
                "oldest_instance": min(
                    i.created_at for i in instances
                ).isoformat(),
                "max_instances": self._max_instances,
                "max_age_seconds": self._max_age_seconds,
            }


# 全局缓存实例
_graph_cache: GraphCache | None = None
_cache_lock = threading.Lock()


def get_graph_cache() -> GraphCache:
    """获取全局图缓存实例"""
    global _graph_cache
    with _cache_lock:
        if _graph_cache is None:
            _graph_cache = GraphCache(
                max_instances=5,
                max_age_seconds=3600,
                cleanup_interval_seconds=300
            )
        return _graph_cache
