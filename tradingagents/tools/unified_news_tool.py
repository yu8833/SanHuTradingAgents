"""兼容层: 统一新闻工具占位"""
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


def get_stock_news(
    symbol: str,
    days_back: int = 7,
    max_news: int = 20,
) -> List[Dict[str, Any]]:
    """获取股票新闻 - 占位实现"""
    logger.debug(f"📰 [unified_news_tool] get_stock_news {symbol}")
    return []


def get_market_news(symbol: Optional[str] = None, **kwargs) -> List[Dict[str, Any]]:
    """获取市场新闻 - 占位实现"""
    logger.debug(f"📰 [unified_news_tool] get_market_news {symbol}")
    return []


def search_news(query: str, **kwargs) -> List[Dict[str, Any]]:
    """搜索新闻 - 占位实现"""
    logger.debug(f"📰 [unified_news_tool] search_news {query}")
    return []
