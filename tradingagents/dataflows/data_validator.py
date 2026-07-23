"""
股票数据验证与约束模块

系统性地对单股分析中的各项数据进行合理性约束，
避免"离谱"数据影响分析结果和用户体验。

约束原则：
1. 物理/业务不可能值 → 置为 None 并记录警告
2. 极端但可能的值 → 保留但标注警告
3. 缺失值 → 保持 None，由上层处理

指标分类及约束范围：
- 估值指标：PE, PB, PS, PEG
- 市值指标：总市值, 流通市值
- 盈利能力：ROE, ROA, 毛利率, 净利率
- 交易指标：换手率, 量比, 振幅, 涨跌幅
- 成长指标：营收增长率, 利润增长率
- 偿债能力：资产负债率, 流动比率, 速动比率
"""
import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ============================================================================
# 约束配置（可根据业务需要调整）
# ============================================================================

# 估值指标约束
VALUATION_CONSTRAINTS = {
    "pe": {
        "min": -500,       # 最小PE（极度亏损企业）
        "max": 1000,       # 最大PE（微利企业）
        "description": "市盈率"
    },
    "pe_ttm": {
        "min": -500,
        "max": 1000,
        "description": "滚动市盈率"
    },
    "pb": {
        "min": -100,       # 最小PB（资不抵债，通常不应超过-10）
        "max": 100,        # 最大PB（轻资产/高成长公司）
        "description": "市净率"
    },
    "pb_mrq": {
        "min": -100,
        "max": 100,
        "description": "最近季度市净率"
    },
    "ps": {
        "min": -100,
        "max": 500,
        "description": "市销率"
    },
    "ps_ttm": {
        "min": -100,
        "max": 500,
        "description": "滚动市销率"
    },
    "peg": {
        "min": -10,
        "max": 50,
        "description": "市盈率相对盈利增长比率"
    },
}

# 市值指标约束（单位：亿元）
MARKET_CAP_CONSTRAINTS = {
    "total_mv": {
        "min": 0.1,        # 最小总市值（1000万，退市股可能更低）
        "max": 200000,     # 最大总市值（20万亿，茅台/工行级别）
        "description": "总市值",
        "unit": "亿元"
    },
    "circ_mv": {
        "min": 0.05,       # 最小流通市值
        "max": 200000,
        "description": "流通市值",
        "unit": "亿元"
    },
}

# 盈利能力指标约束（单位：%）
PROFITABILITY_CONSTRAINTS = {
    "roe": {
        "min": -100,       # 最小ROE（严重亏损）
        "max": 100,        # 最大ROE（极高盈利）
        "description": "净资产收益率",
        "unit": "%"
    },
    "roa": {
        "min": -50,
        "max": 50,
        "description": "总资产收益率",
        "unit": "%"
    },
    "gross_margin": {
        "min": -50,
        "max": 100,
        "description": "毛利率",
        "unit": "%"
    },
    "net_margin": {
        "min": -200,
        "max": 100,
        "description": "净利率",
        "unit": "%"
    },
}

# 交易指标约束
TRADING_CONSTRAINTS = {
    "turnover_rate": {
        "min": 0,
        "max": 80,         # 最大换手率（新股首日可能更高，但日常不应超过80%）
        "description": "换手率",
        "unit": "%"
    },
    "volume_ratio": {
        "min": 0,
        "max": 50,         # 最大量比（极端放量）
        "description": "量比"
    },
    "amplitude": {
        "min": 0,
        "max": 60,         # 最大振幅（创业板/科创板20%涨跌停，极端情况约40%）
        "description": "振幅",
        "unit": "%"
    },
    "change_percent": {
        "min": -30,        # 最大跌幅（科创板/创业板20%，北交所30%）
        "max": 30,         # 最大涨幅
        "description": "涨跌幅",
        "unit": "%"
    },
    "pct_chg": {
        "min": -30,
        "max": 30,
        "description": "涨跌幅",
        "unit": "%"
    },
}

# 成长指标约束（单位：%）
GROWTH_CONSTRAINTS = {
    "revenue_yoy": {
        "min": -100,
        "max": 500,        # 最大营收增长率（5倍）
        "description": "营收同比增长率",
        "unit": "%"
    },
    "net_profit_yoy": {
        "min": -500,
        "max": 1000,       # 最大利润增长率（10倍，基数低时可能更高）
        "description": "净利润同比增长率",
        "unit": "%"
    },
}

# 偿债能力指标约束
SOLVENCY_CONSTRAINTS = {
    "debt_ratio": {
        "min": 0,
        "max": 150,        # 最大资产负债率（正常不超过100%，资不抵债可能更高）
        "description": "资产负债率",
        "unit": "%"
    },
    "debt_to_assets": {
        "min": 0,
        "max": 150,
        "description": "资产负债率",
        "unit": "%"
    },
    "current_ratio": {
        "min": 0,
        "max": 50,         # 最大流动比率
        "description": "流动比率"
    },
    "quick_ratio": {
        "min": 0,
        "max": 50,
        "description": "速动比率"
    },
}

# 价格约束
PRICE_CONSTRAINTS = {
    "price": {
        "min": 0.01,
        "max": 10000,      # 最大股价（A股最高茅台约2000）
        "description": "股价",
        "unit": "元"
    },
    "close": {
        "min": 0.01,
        "max": 10000,
        "description": "收盘价",
        "unit": "元"
    },
    "open": {
        "min": 0.01,
        "max": 10000,
        "description": "开盘价",
        "unit": "元"
    },
    "high": {
        "min": 0.01,
        "max": 10000,
        "description": "最高价",
        "unit": "元"
    },
    "low": {
        "min": 0.01,
        "max": 10000,
        "description": "最低价",
        "unit": "元"
    },
}

# 合并所有约束
ALL_CONSTRAINTS = {}
ALL_CONSTRAINTS.update(VALUATION_CONSTRAINTS)
ALL_CONSTRAINTS.update(MARKET_CAP_CONSTRAINTS)
ALL_CONSTRAINTS.update(PROFITABILITY_CONSTRAINTS)
ALL_CONSTRAINTS.update(TRADING_CONSTRAINTS)
ALL_CONSTRAINTS.update(GROWTH_CONSTRAINTS)
ALL_CONSTRAINTS.update(SOLVENCY_CONSTRAINTS)
ALL_CONSTRAINTS.update(PRICE_CONSTRAINTS)


# ============================================================================
# 核心验证函数
# ============================================================================

def validate_value(
    value: Any,
    field_name: str,
    constraints: Dict[str, Any] = None
) -> Tuple[Optional[float], Optional[str]]:
    """
    验证单个数值是否在合理范围内

    Args:
        value: 待验证的值
        field_name: 字段名（用于查找约束配置）
        constraints: 自定义约束（可选，覆盖默认配置）

    Returns:
        (清理后的值, 警告信息)
        - 如果值正常，返回 (原值, None)
        - 如果值超出范围，返回 (None, 警告信息)
        - 如果值为 None/NaN 等无效值，返回 (None, None)
    """
    if value is None:
        return None, None

    # 尝试转换为数值
    try:
        num = float(value)
    except (ValueError, TypeError):
        return None, f"{field_name}: 无法转换为数值 ({value})"

    # 检查 NaN 和 Inf
    import math
    if math.isnan(num) or math.isinf(num):
        return None, f"{field_name}: 值为 NaN/Inf"

    # 获取约束配置
    constraint = constraints or ALL_CONSTRAINTS.get(field_name)

    if constraint is None:
        return num, None

    min_val = constraint.get("min")
    max_val = constraint.get("max")
    desc = constraint.get("description", field_name)

    # 检查最小值
    if min_val is not None and num < min_val:
        logger.warning(f"⚠️ 数据约束: {desc}({field_name})={num} 低于最小值 {min_val}")
        return None, f"{desc}: {num} 低于合理范围 [{min_val}, {max_val}]"

    # 检查最大值
    if max_val is not None and num > max_val:
        logger.warning(f"⚠️ 数据约束: {desc}({field_name})={num} 高于最大值 {max_val}")
        return None, f"{desc}: {num} 高于合理范围 [{min_val}, {max_val}]"

    return num, None


def validate_stock_data(
    data: Dict[str, Any],
    symbol: str = "unknown"
) -> Dict[str, Any]:
    """
    验证股票数据字典中的所有字段，返回清理后的数据和警告

    Args:
        data: 股票数据字典
        symbol: 股票代码（用于日志）

    Returns:
        {
            "clean_data": {...},      # 清理后的数据
            "warnings": [...],        # 警告列表
            "sanitized_count": N,     # 被清理的字段数量
            "total_fields": N         # 总字段数量
        }
    """
    if not data or not isinstance(data, dict):
        return {
            "clean_data": data or {},
            "warnings": ["输入数据为空或格式错误"],
            "sanitized_count": 0,
            "total_fields": 0
        }

    clean_data = {}
    warnings = []
    sanitized_count = 0
    total_fields = 0

    for field_name, value in data.items():
        total_fields += 1

        # 非数值字段直接保留（包括 datetime, date, dict, list, str, bool, None）
        if value is None or isinstance(value, (dict, list, str, bool, datetime, date)):
            clean_data[field_name] = value
            continue

        # 验证数值字段
        cleaned, warning = validate_value(value, field_name)

        if warning:
            warnings.append(warning)
            sanitized_count += 1
            clean_data[field_name] = None
        else:
            clean_data[field_name] = cleaned

    if warnings:
        logger.warning(
            f"⚠️ 股票 {symbol} 数据验证: {sanitized_count}/{total_fields} 个字段被清理 - "
            + "; ".join(warnings[:5])
            + ("..." if len(warnings) > 5 else "")
        )

    return {
        "clean_data": clean_data,
        "warnings": warnings,
        "sanitized_count": sanitized_count,
        "total_fields": total_fields
    }


# ============================================================================
# 专用验证函数
# ============================================================================

def validate_pe_pb(pe: float = None, pb: float = None) -> bool:
    """
    验证PE/PB是否在合理范围内（兼容旧接口）

    Args:
        pe: 市盈率
        pb: 市净率

    Returns:
        True 表示数据正常，False 表示存在异常值
    """
    if pe is not None:
        cleaned_pe, _ = validate_value(pe, "pe")
        if cleaned_pe is None:
            return False

    if pb is not None:
        cleaned_pb, _ = validate_value(pb, "pb")
        if cleaned_pb is None:
            return False

    return True


def validate_market_cap(total_mv: float = None, circ_mv: float = None) -> bool:
    """验证市值数据合理性"""
    if total_mv is not None:
        cleaned, _ = validate_value(total_mv, "total_mv")
        if cleaned is None:
            return False

    if circ_mv is not None:
        cleaned, _ = validate_value(circ_mv, "circ_mv")
        if cleaned is None:
            return False

    return True


def validate_trading_metrics(
    turnover_rate: float = None,
    volume_ratio: float = None,
    amplitude: float = None,
    change_percent: float = None
) -> Dict[str, Any]:
    """验证交易指标合理性，返回清理后的数据"""
    result = {}
    warnings = []

    if turnover_rate is not None:
        val, warn = validate_value(turnover_rate, "turnover_rate")
        result["turnover_rate"] = val
        if warn:
            warnings.append(warn)

    if volume_ratio is not None:
        val, warn = validate_value(volume_ratio, "volume_ratio")
        result["volume_ratio"] = val
        if warn:
            warnings.append(warn)

    if amplitude is not None:
        val, warn = validate_value(amplitude, "amplitude")
        result["amplitude"] = val
        if warn:
            warnings.append(warn)

    if change_percent is not None:
        val, warn = validate_value(change_percent, "change_percent")
        result["change_percent"] = val
        if warn:
            warnings.append(warn)

    return {"cleaned": result, "warnings": warnings}


def validate_price(price: float, field_name: str = "price") -> Optional[float]:
    """验证股价合理性"""
    cleaned, _ = validate_value(price, field_name)
    return cleaned


def validate_fundamentals(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证基本面数据（财务指标）

    Args:
        data: 财务数据字典

    Returns:
        清理后的财务数据字典
    """
    return validate_stock_data(data)["clean_data"]


# ============================================================================
# 数据标注函数（给极端值打标签，不删除）
# ============================================================================

def annotate_extreme_values(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    为极端值添加标注，但保留原始值

    返回结构：
    {
        "value": 原始值,
        "is_extreme": True/False,
        "extreme_type": "too_high"/"too_low"/None,
        "suggested_range": [min, max]
    }
    """
    result = {}

    for field_name, value in data.items():
        constraint = ALL_CONSTRAINTS.get(field_name)
        if constraint is None or not isinstance(value, (int, float)):
            result[field_name] = {
                "value": value,
                "is_extreme": False,
                "extreme_type": None,
                "suggested_range": None
            }
            continue

        min_val = constraint.get("min")
        max_val = constraint.get("max")

        is_extreme = False
        extreme_type = None

        if min_val is not None and value < min_val:
            is_extreme = True
            extreme_type = "too_low"
        elif max_val is not None and value > max_val:
            is_extreme = True
            extreme_type = "too_high"

        result[field_name] = {
            "value": value,
            "is_extreme": is_extreme,
            "extreme_type": extreme_type,
            "suggested_range": [min_val, max_val] if min_val or max_val else None
        }

    return result


# ============================================================================
# 便捷函数：获取指标说明
# ============================================================================

def get_constraint_info(field_name: str) -> Optional[Dict[str, Any]]:
    """获取指定字段的约束信息"""
    return ALL_CONSTRAINTS.get(field_name)


def get_all_constraints() -> Dict[str, Any]:
    """获取所有约束配置"""
    return ALL_CONSTRAINTS.copy()


def list_supported_fields() -> List[str]:
    """列出所有支持验证的字段"""
    return sorted(ALL_CONSTRAINTS.keys())
