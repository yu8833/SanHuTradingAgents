"""兼容层: app 数据适配器占位"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AppDataAdapter:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [AppDataAdapter] 占位类，未实现")

    def get_stock_basic_info(self, *args, **kwargs):
        return None
