"""A 股数据接口层 — 多数据源路由 + Fallback 机制

支持按工具方法或分类配置数据源，主数据源失败时自动降级到备用数据源。

Available vendors:
- a_stock: 自建多源聚合（mootdx + 腾讯 + 东方财富 + 新浪 + 同花顺 + 财联社）
- akshare: 开源 A 股数据库（备用数据源）
"""
from typing import Optional, Any, List
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool categories (matching upstream convention)
# ---------------------------------------------------------------------------

TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": ["get_stock_data"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "Company fundamentals and financial statements",
        "tools": [
            "get_fundamentals",
            "get_balance_sheet",
            "get_cashflow",
            "get_income_statement",
        ],
    },
    "news_data": {
        "description": "News, global news, and insider transactions",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_transactions",
        ],
    },
    "signal_data": {
        "description": "A-stock signal layer (topic attribution, capital flow, consensus forecast)",
        "tools": [
            "get_profit_forecast",
            "get_hot_stocks",
            "get_northbound_flow",
            "get_concept_blocks",
            "get_fund_flow",
            "get_dragon_tiger_board",
            "get_lockup_expiry",
            "get_industry_comparison",
            "get_margin_trading",
            "get_shareholder_concentration",
            "get_risk_scan",
        ],
    },
}

ALL_TOOL_METHODS = [
    tool for cat_info in TOOLS_CATEGORIES.values() for tool in cat_info["tools"]
]

# ---------------------------------------------------------------------------
# Vendor list and method mapping
# ---------------------------------------------------------------------------

VENDOR_LIST = ["a_stock", "akshare"]

_VENDOR_MODULE_CACHE = {}


def _get_vendor_module(vendor: str):
    """Lazy-load a vendor module and cache it."""
    if vendor in _VENDOR_MODULE_CACHE:
        return _VENDOR_MODULE_CACHE[vendor]

    if vendor == "a_stock":
        import tradingagents.dataflows.a_stock as mod
        _VENDOR_MODULE_CACHE[vendor] = mod
        return mod
    elif vendor == "akshare":
        from tradingagents.dataflows import akshare_vendor as mod
        _VENDOR_MODULE_CACHE[vendor] = mod
        return mod
    else:
        raise ValueError(f"Unknown vendor: {vendor}")


def _get_vendor_method(vendor: str, method: str) -> Optional[Any]:
    """Get a specific method from a vendor module. Returns None if not implemented."""
    try:
        mod = _get_vendor_module(vendor)
    except Exception as e:
        logger.debug(f"Vendor {vendor} not available: {e}")
        return None

    func = getattr(mod, method, None)
    if func is None or not callable(func):
        return None
    return func


# ---------------------------------------------------------------------------
# Category / vendor resolution
# ---------------------------------------------------------------------------

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.

    Tool-level configuration takes precedence over category-level.
    Returns a comma-separated vendor chain (e.g. "a_stock,akshare").
    """
    from .config import get_config

    config = get_config()

    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    return config.get("data_vendors", {}).get(category, "a_stock")


def _build_fallback_chain(method: str) -> List[str]:
    """Build the fallback vendor chain for a method.

    Primary vendors come from config; remaining available vendors are appended
    as automatic fallbacks (so a single-vendor config still gets redundancy).
    """
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",") if v.strip()]

    all_available = list(VENDOR_LIST)
    chain = primary_vendors.copy()
    for v in all_available:
        if v not in chain:
            chain.append(v)

    return chain


# ---------------------------------------------------------------------------
# Main routing with fallback
# ---------------------------------------------------------------------------

def route_to_vendor(method: str, *args, **kwargs):
    """Route method call to appropriate vendor with fallback support.

    Tries vendors in the configured priority order. The first vendor that
    returns a non-empty / non-error result wins. If all fail, raises the
    last exception.

    返回前经过 DataIntegrityGuard 校验：
    - 日线过期 → 触发即时补数 → 补数失败则抛 DataStaleError 阻断分析
    - 无数据 → 标记 MISSING
    - 异常值 → 标记 ABNORMAL
    """
    if method not in ALL_TOOL_METHODS:
        logger.warning(f"⚠️ [route_to_vendor] 未知方法: {method}")
        raise ValueError(f"未知的数据源方法: {method}")

    chain = _build_fallback_chain(method)
    last_error = None
    tried = []

    for vendor in chain:
        func = _get_vendor_method(vendor, method)
        if func is None:
            logger.debug(f"[route_to_vendor] {method} 未在 {vendor} 实现，跳过")
            continue

        tried.append(vendor)
        try:
            result = func(*args, **kwargs)
            if result is None or (isinstance(result, str) and not result.strip()):
                logger.warning(f"[route_to_vendor] {vendor}.{method} 返回空结果，尝试 fallback")
                continue
            if len(tried) > 1:
                logger.info(f"✅ [route_to_vendor] {method} fallback 成功: {tried[0]} 失败 → {vendor} 成功")

            # 数据完整性校验拦截（日线过期+补数失败会抛 DataStaleError 阻断分析）
            from tradingagents.dataflows.integrity_guard import check_integrity
            result = check_integrity(result, method, args)
            return result
        except Exception as e:
            # DataStaleError 是"故意阻断"的异常，不 fallback，直接向上传播
            from tradingagents.dataflows.integrity_guard import DataStaleError
            if isinstance(e, DataStaleError):
                raise
            last_error = e
            logger.warning(f"[route_to_vendor] {vendor}.{method} 失败: {e}，尝试 fallback")
            continue

    if last_error:
        logger.error(f"❌ [route_to_vendor] {method} 所有数据源均失败 (tried: {tried}): {last_error}")
        raise last_error
    else:
        msg = f"[route_to_vendor] {method} 没有可用的数据源实现 (chain: {chain})"
        logger.error(msg)
        raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Legacy compatibility helpers
# ---------------------------------------------------------------------------

def get_china_stock_data_unified(
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    **kwargs,
) -> str:
    """统一获取 A 股数据 — 兼容层"""
    return route_to_vendor("get_stock_data", symbol, start_date, end_date, **kwargs)


def get_china_stock_info_unified(symbol: str) -> str:
    """获取 A 股股票信息 — 兼容层（用 fundamentals 作为近似）"""
    try:
        from tradingagents.dataflows.a_stock import resolve_ticker
        info = resolve_ticker(symbol)
        if isinstance(info, dict):
            return str(info)
        return str(info)
    except Exception as e:
        logger.error(f"❌ [get_china_stock_info_unified] {e}")
        return f"获取股票 {symbol} 信息失败: {e}"
