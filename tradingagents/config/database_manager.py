"""兼容层: 数据库管理器占位"""
import os
from typing import Optional


class DatabaseManager:
    """数据库管理器（占位实现）"""

    def __init__(self, *args, **kwargs):
        self.mongo_url = os.getenv("TRADINGAGENTS_MONGODB_URL", "mongodb://mongodb:27017")
        self.mongo_db = os.getenv("TRADINGAGENTS_MONGODB_DB", "tradingagents")
        self.redis_url = os.getenv("TRADINGAGENTS_REDIS_URL", "redis://redis:6379/0")

    def get_mongo_client(self):
        try:
            from pymongo import MongoClient
            return MongoClient(self.mongo_url)
        except Exception:
            return None

    def get_mongo_db(self):
        client = self.get_mongo_client()
        if client is None:
            return None
        return client[self.mongo_db]

    def get_redis_client(self):
        try:
            import redis
            return redis.from_url(self.redis_url)
        except Exception:
            return None


_default_manager: Optional[DatabaseManager] = None


def get_database_manager() -> DatabaseManager:
    """获取数据库管理器单例"""
    global _default_manager
    if _default_manager is None:
        _default_manager = DatabaseManager()
    return _default_manager
