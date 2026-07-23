"""兼容层: MongoDB 缓存适配器占位"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class _DummyMongoCache:
    def get_historical_data(self, *args, **kwargs):
        return None

    def get_stock_basic_info(self, *args, **kwargs):
        return None

    def get_financial_data(self, *args, **kwargs):
        return None

    def get_news(self, *args, **kwargs):
        return []


def get_mongodb_cache_adapter(*args, **kwargs) -> _DummyMongoCache:
    """获取 MongoDB 缓存适配器（占位）"""
    return _DummyMongoCache()
