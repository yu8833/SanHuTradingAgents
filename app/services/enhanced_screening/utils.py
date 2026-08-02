"""
Utility helpers for EnhancedScreeningService to separate analysis and conversion logic.
"""
from __future__ import annotations

from typing import Any

from app.models.screening import BASIC_FIELDS_INFO, FieldType


def analyze_conditions(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = {
        "total_conditions": len(conditions),
        "database_supported_conditions": 0,
        "technical_conditions": 0,
        "fundamental_conditions": 0,
        "basic_conditions": 0,
        "can_use_database": True,
        "needs_technical_indicators": False,
        "unsupported_fields": [],
        "condition_types": [],
    }

    supported_fields = set(BASIC_FIELDS_INFO.keys())

    # 硬编码：数据库中没有数据的字段（尽管 BASIC_FIELDS_INFO 里有定义，
    # 但它们的数据需要从 API 实时计算，不在数据库视图中）
    # 必须走传统筛选路径才能正确计算
    _not_in_db_fields = {
        # 技术指标数值
        "rsi14", "kdj_k", "kdj_d", "kdj_j", "dif", "dea", "macd_hist",
        "boll_upper", "boll_mid", "boll_lower", "atr14",
        "ma5", "ma10", "ma20", "ma60",
        # 技术信号标志
        "macd_golden_fork", "kdj_golden_fork",
        "macd_golden_fork_n", "kdj_golden_fork_n",
        "ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross",
        # 复合信号
        "ma_bullish", "ma_bearish",
        # 布林带突破信号
        "boll_break_upper", "boll_break_lower",
        # 均线金叉信号
        "ma5_ma10_golden", "ma10_ma20_golden",
    }

    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        field = condition.get("field")

        if field in _not_in_db_fields:
            analysis["can_use_database"] = False
            analysis["needs_technical_indicators"] = True
            analysis["technical_conditions"] += 1
            analysis["condition_types"].append("technical")
            analysis["unsupported_fields"].append(field)
        elif field in supported_fields:
            field_info = BASIC_FIELDS_INFO[field]
            field_type = field_info.field_type

            if field_type == FieldType.BASIC:
                analysis["basic_conditions"] += 1
            elif field_type == FieldType.FUNDAMENTAL:
                analysis["fundamental_conditions"] += 1
            elif field_type == FieldType.TECHNICAL:
                analysis["technical_conditions"] += 1

            analysis["condition_types"].append(field_type.value)
            analysis["database_supported_conditions"] += 1
        else:
            analysis["can_use_database"] = False
            analysis["needs_technical_indicators"] = True
            analysis["unsupported_fields"].append(field)

    return analysis


def convert_conditions_to_traditional_format(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    把 [{field, operator, value}, ...] 列表转为后端可统一评估的
    {logic, children} 树结构。每个叶子是 {'field':..., 'op':..., 'value':...}。
    这样 eval_utils.evaluate_conditions 能一致地走"叶子节点"分支，正确处理
    'between'/'eq' 等运算符以及 macd_golden_fork/ma20_cross 等标志字段。
    """
    if not conditions:
        return {"logic": "AND", "children": []}

    children: list[dict[str, Any]] = []
    for c in conditions:
        if not isinstance(c, dict):
            continue
        # 规范化操作符
        op_raw = c.get("operator", "==")
        if isinstance(op_raw, str):
            op = op_raw.strip()
            if op in {"eq", "="}:
                op = "=="
            elif op in {"ne", "<>", "neq"}:
                op = "!="
            elif op in {"gte", "ge"}:
                op = ">="
            elif op in {"lte", "le"}:
                op = "<="
            elif op in {"gt"}:
                op = ">"
            elif op in {"lt"}:
                op = "<"
        else:
            op = str(op_raw) if op_raw is not None else "=="

        children.append({
            "field": c.get("field"),
            "op": op,
            "value": c.get("value"),
        })

    return {"logic": "AND", "children": children}

