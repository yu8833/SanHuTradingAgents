"""兼容层: 港股数据源占位"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class HKStockProvider:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [HKStockProvider] 占位类，未实现")

    def get_stock_basic(self, *args, **kwargs):
        return []

    def get_daily(self, *args, **kwargs):
        return []


class ImprovedHKStockProvider:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [ImprovedHKStockProvider] 占位类，未实现")

    def get_stock_basic(self, *args, **kwargs):
        return []

    def get_daily(self, *args, **kwargs):
        return []


def get_hk_company_name_improved(*args, **kwargs) -> Optional[str]:
    """占位 - 返回 None"""
    return None


def get_hk_stock_info_akshare(*args, **kwargs):
    """占位"""
    return None


def get_improved_hk_provider(*args, **kwargs):
    """占位"""
    return ImprovedHKStockProvider()
