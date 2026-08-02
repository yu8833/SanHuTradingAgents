"""
数据获取模块

为速览分析提供股票数据获取功能
"""

from .stock_data_fetcher import (
    StockDataFetcher,
    get_kline,
    get_realtime_quote,
    get_stock_data_fetcher,
)

__all__ = [
    'StockDataFetcher',
    'get_stock_data_fetcher',
    'get_kline',
    'get_realtime_quote',
]
