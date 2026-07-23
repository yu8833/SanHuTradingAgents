"""兼容层: 数据源管理器占位"""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


def get_data_source_manager(*args, **kwargs):
    """返回数据源管理器（占位）

    Returns:
        一个具有基础方法的占位对象
    """
    class _DummyDataSourceManager:
        def get_stock_basic_info(self, code: str) -> Optional[dict]:
            try:
                from tradingagents.dataflows.a_stock import resolve_ticker
                return resolve_ticker(code)
            except Exception as e:
                logger.warning(f"⚠️ [data_source_manager] 获取 {code} 基础信息失败: {e}")
                return None

        def get_financial_data(self, code: str, *args, **kwargs) -> Any:
            try:
                from tradingagents.dataflows.a_stock import get_fundamentals
                return get_fundamentals(code)
            except Exception as e:
                logger.warning(f"⚠️ [data_source_manager] 获取 {code} 财务数据失败: {e}")
                return None

        def __getattr__(self, name):
            def _stub(*a, **k):
                logger.debug(f"🔧 [data_source_manager.{name}] 未实现，返回 None")
                return None
            return _stub

    return _DummyDataSourceManager()
