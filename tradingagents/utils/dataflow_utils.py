"""数据流工具兼容层"""
from datetime import datetime, timedelta
from typing import Tuple


def get_trading_date_range(
    analysis_date: str,
    lookback_days: int = 10,
) -> Tuple[str, str]:
    """获取交易日范围

    Args:
        analysis_date: 分析日期 (YYYY-MM-DD)
        lookback_days: 回溯天数

    Returns:
        (start_date, end_date)
    """
    try:
        end = datetime.strptime(analysis_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        end = datetime.now()

    start = end - timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
