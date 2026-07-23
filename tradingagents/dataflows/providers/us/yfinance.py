"""兼容层: 美股数据源占位"""
import logging

logger = logging.getLogger(__name__)


class YFinanceUtils:
    """YFinance 工具类占位"""

    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [YFinanceUtils] 占位类，未实现")

    def get_stock_info(self, *args, **kwargs):
        return {}

    def get_historical_data(self, *args, **kwargs):
        return []
