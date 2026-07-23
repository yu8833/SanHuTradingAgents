"""兼容层: BaoStock 数据源占位"""
import logging

logger = logging.getLogger(__name__)


class BaoStockProvider:
    """BaoStock 数据源占位（兼容层）"""

    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [BaoStockProvider] 已迁移到 a_stock.py，本占位类仅用于 import 兼容")

    def get_stock_basic(self, *args, **kwargs):
        return []

    def get_daily(self, *args, **kwargs):
        return []

    def get_financial(self, *args, **kwargs):
        return {}


_default_baostock = None


def get_baostock_provider(*args, **kwargs):
    """获取 BaoStockProvider 单例（占位）"""
    global _default_baostock
    if _default_baostock is None:
        _default_baostock = BaoStockProvider(*args, **kwargs)
    return _default_baostock
