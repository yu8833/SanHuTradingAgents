"""兼容层: 港股数据源占位"""
import logging

logger = logging.getLogger(__name__)


class HKStockProvider:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [HKStockProvider] 占位类，未实现")

    def get_stock_basic(self, *args, **kwargs):
        return []

    def get_daily(self, *args, **kwargs):
        return []
