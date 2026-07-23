"""兼容层: 美股数据源占位"""
import logging

logger = logging.getLogger(__name__)


class OptimizedUSDataProvider:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [OptimizedUSDataProvider] 占位类，未实现")

    def get_stock_info(self, *args, **kwargs):
        return {}

    def get_historical_data(self, *args, **kwargs):
        return []
