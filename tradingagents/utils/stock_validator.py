"""股票验证兼容层 - 转发到新 tradingagents.dataflows.a_stock"""
import logging
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def validate_stock_code(symbol: str) -> Tuple[bool, str]:
    """验证股票代码是否有效

    Returns:
        (is_valid, error_message)
    """
    if not symbol:
        return False, "股票代码为空"

    s = str(symbol).strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break

    code = s.strip()
    if not code:
        return False, "股票代码为空"

    if code.isdigit() and 4 <= len(code) <= 6:
        return True, ""

    return False, f"无效的股票代码格式: {symbol}"


async def prepare_stock_data_async(
    stock_code: str,
    trade_date: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """异步准备股票数据

    Returns:
        Dict: {success, stock_code, stock_name, market_type, error}
    """
    is_valid, err = validate_stock_code(stock_code)
    if not is_valid:
        return {
            "success": False,
            "stock_code": stock_code,
            "error": err,
        }

    # 调用新数据源
    try:
        from tradingagents.dataflows.a_stock import resolve_ticker
        info = resolve_ticker(stock_code)
        return {
            "success": True,
            "stock_code": stock_code,
            "stock_name": info.get("name", "") if isinstance(info, dict) else "",
            "market_type": info.get("market", "china_a") if isinstance(info, dict) else "china_a",
            "data": info,
        }
    except Exception as e:
        logger.warning(f"⚠️ [prepare_stock_data_async] 调用 a_stock 失败: {e}")
        return {
            "success": True,  # 即使获取名称失败，也认为代码有效
            "stock_code": stock_code,
            "stock_name": "",
            "market_type": "china_a",
            "warning": str(e),
        }
