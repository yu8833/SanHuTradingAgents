"""兼容层: 缓存占位"""
import logging

logger = logging.getLogger(__name__)


class _DummyCache:
    def get(self, *args, **kwargs):
        return None

    def set(self, *args, **kwargs):
        return False

    def delete(self, *args, **kwargs):
        return False

    def clear(self, *args, **kwargs):
        return False

    def get_cache_stats(self, *args, **kwargs):
        return {}

    def clear_old_cache(self, *args, **kwargs):
        return 0

    def get_cache_details(self, *args, **kwargs):
        return []

    def get_cache_backend_info(self, *args, **kwargs):
        return {}


_cache_instance = None


def get_cache(*args, **kwargs):
    """获取缓存实例（占位）"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = _DummyCache()
    return _cache_instance
