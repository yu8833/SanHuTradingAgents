"""
Utility functions for screening evaluation and DSL parsing.
Extracted from ScreeningService to separate concerns while keeping API unchanged.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

# 标志字段集（技术信号类筛选）
FLAG_FIELDS = frozenset({
    "macd_golden_fork", "kdj_golden_fork",
    "macd_golden_fork_n", "kdj_golden_fork_n",  # 近N日金叉
    "ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross",
    # 均线多头/空头排列（复合信号）
    "ma_bullish", "ma_bearish",
    # 布林带突破信号
    "boll_break_upper", "boll_break_lower",
    # 均线金叉（MA5上穿MA10等）
    "ma5_ma10_golden", "ma10_ma20_golden",
})


def _normalize_op(op: Any) -> str:
    """归一化操作符：把 'eq'/'ne' 等常见别名统一成规范形式。"""
    if not isinstance(op, str):
        return ""
    o = op.strip().lower()
    if o in {"eq", "="}:
        return "=="
    if o in {"ne", "<>", "neq"}:
        return "!="
    if o in {"gte", "ge"}:
        return ">="
    if o in {"lte", "le"}:
        return "<="
    if o in {"gt"}:
        return ">"
    if o in {"lt"}:
        return "<"
    return o


def _is_group(node: dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("op") == "group":
        return True
    return bool("children" in node and isinstance(node.get("children"), (list, tuple)))


def collect_fields_from_conditions(node: dict[str, Any], allowed_fields: Iterable[str]) -> list[str]:
    if not node:
        return []

    allowed = set(allowed_fields)

    # group 节点：递归收集
    if _is_group(node):
        fields: list[str] = []
        for c in node.get("children", []) or []:
            fields.extend(collect_fields_from_conditions(c, allowed))
        return list(dict.fromkeys(fields))

    # 叶子节点：支持两种格式
    # (a) {"field": "macd_golden_fork", "op": "eq", "value": True
    # (b) {"macd_golden_fork": True, "total_mv": ...}
    if isinstance(node, dict) and "field" in node:
        f = node.get("field")
        out: list[str] = []
        if isinstance(f, str) and (f in allowed or f in FLAG_FIELDS):
            out.append(f)
        rf = node.get("right_field")
        if isinstance(rf, str) and (rf in allowed or rf in FLAG_FIELDS):
            out.append(rf)
        return out

    # 扁平字典
    if isinstance(node, dict):
        out2: list[str] = []
        for f in node:
            if not isinstance(f, str):
                continue
            if f in allowed or f in FLAG_FIELDS:
                out2.append(f)
        return out2

    return []


def evaluate_fund_conditions(snap: dict[str, Any], node: dict[str, Any], fund_fields: Iterable[str]) -> bool:
    if not node:
        return True
    # group
    if _is_group(node):
        logic = (node.get("logic") or "AND").upper()
        children = node.get("children", []) or []
        flags = [evaluate_fund_conditions(snap, c, fund_fields) for c in children]
        if logic == "OR":
            return any(flags)
        return all(flags)
    # leaf: {"field": ..., "op": ..., "value": ...}
    field = node.get("field") if isinstance(node, dict) and "field" in node else None
    if field is not None:
        op = _normalize_op(node.get("op"))
        if field not in set(fund_fields):
            return True  # 非基本面字段在纯基本面路径中跳过
        left = snap.get(field) if isinstance(snap, dict) else None
        if left is None or (isinstance(left, float) and np.isnan(left)):
            return False
        right = node.get("value")
        return _compare_values(left, op, right)

    # 扁平字典格式：键是字段名
    if isinstance(node, dict):
        for f, v in node.items():
            if f == "logic":
                continue
            if f not in set(fund_fields):
                    continue
            left = snap.get(f) if isinstance(snap, dict) else None
            if left is None or (isinstance(left, float) and np.isnan(left)):
                return False
            if not _compare_values(left, "==", v):
                return False
        return True
    return True


def _compare_values(left: Any, op: str, right: Any) -> bool:
    """统一的值比较（支持 between / == 等）。"""
    try:
        if op == "between":
            if not isinstance(right, (list, tuple)) or len(right) != 2:
                return False
            lo, hi = right
            if lo is None or hi is None:
                return False
            v = float(left)
            return float(lo) <= v <= float(hi)
        if op == "in":
            try:
                return left in right
            except Exception:
                return False
        if op == "not_in":
            try:
                return left not in right
            except Exception:
                return False
        if op == "contains":
            try:
                return str(right).lower() in str(left).lower()
            except Exception:
                return False
        # 数值比较
        if left is None or right is None:
            return False
        if isinstance(right, bool) or isinstance(left, bool):
            if op == "==":
                return bool(left) == bool(right)
            if op == "!=":
                return bool(left) != bool(right)
        lv = float(left)
        rv = float(right)
        if op == ">":
            return lv > rv
        if op == "<":
            return lv < rv
        if op == ">=":
            return lv >= rv
        if op == "<=":
            return lv <= rv
        if op == "==":
            return lv == rv
        if op == "!=":
            return lv != rv
    except Exception:
        return False
    return False


def evaluate_conditions(
    df: pd.DataFrame,
    node: dict[str, Any],
    allowed_fields: Iterable[str],
    allowed_ops: Iterable[str],
) -> bool:
    if df is None or (hasattr(df, "empty") and df.empty):
        return False
    if not node:
        return True

    allowed = set(allowed_fields)
    allowed_opset = set(allowed_ops) | {"eq", "ne", "==", "!=", ">", "<", ">=", "<=", "between", "in", "not_in", "contains", "cross_up", "cross_down"}

    # group 节点
    if _is_group(node):
        logic = (node.get("logic") or "AND").upper()
        children = node.get("children", []) or []
        flags = [evaluate_conditions(df, c, allowed, allowed_opset) for c in children]
        if logic == "OR":
            return any(flags)
        return all(flags)

    # 叶子：字段比较（{"field":..., "op":..., "value": ...}
    if isinstance(node, dict) and "field" in node:
        field = node.get("field")
        op = _normalize_op(node.get("op"))
        right = node.get("value")

        # 标志字段（macd_golden_fork 等）：独立处理
        if isinstance(field, str) and field in FLAG_FIELDS:
            return _evaluate_flag(df, field, op, right)

        # 普通字段：检查字段/操作符
        if field not in allowed:
            return False
        if op not in allowed_opset:
            return False

        # 最近一行用于普通数值比较
        if df is None or (hasattr(df, "empty") and df.empty):
            return False

        # 交叉（需要两行情）
        if op in {"cross_up", "cross_down"}:
            right_field = node.get("right_field")
            if right_field not in allowed:
                return False
            if len(df) < 2:
                return False
            t0 = df.iloc[-1]
            t1 = df.iloc[-2]
            a0 = t0.get(field)
            a1 = t1.get(field)
            b0 = t0.get(right_field)
            b1 = t1.get(right_field)
            try:
                a0, a1, b0, b1 = float(a0), float(a1), float(b0), float(b1)
            except Exception:
                return False
            if op == "cross_up":
                return (a1 <= b1) and (a0 > b0)
            return (a1 >= b1) and (a0 < b0)

        # 普通比较（最近一根）
        t0 = df.iloc[-1]
        left = t0.get(field)
        if left is None or (isinstance(left, float) and np.isnan(left)):
            return False
        if node.get("right_field"):
            rf = node.get("right_field")
            if rf not in allowed:
                return False
            right = t0.get(rf)
        else:
            right = node.get("value")
        return _compare_values(left, op, right)

    # 扁平字典格式（旧/传统格式）
    if isinstance(node, dict):
        for f, v in node.items():
            if f == "logic":
                continue
            if isinstance(f, str) and f in FLAG_FIELDS:
                if not _evaluate_flag(df, f, "==", v):
                    return False
            elif isinstance(f, str) and f in allowed:
                if not _evaluate_simple_field(df, f, v):
                    return False
            # 未知字段：不通过
            else:
                return False
        return True

    return True


def _evaluate_flag(df: pd.DataFrame, field: str, op: str, right: Any) -> bool:
    """评估标志字段（macd_golden_fork / kdj_golden_fork / maXX_cross）"""
    if df is None or (hasattr(df, "empty") and df.empty) or len(df) < 2:
        # 站上均线仅需 1 根 K 线；金叉至少 2 根
        if field in {"ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross"}:
            if df is None or (hasattr(df, "empty") and df.empty):
                return False
        else:
            return False

    want_true = (right is True or right == "true" or right == "True" or right == 1)

    # MACD 金叉：DIF 从下往上穿越 DEA
    if field == "macd_golden_fork":
        t0 = df.iloc[-1]
        t1 = df.iloc[-2] if len(df) >= 2 else t0
        try:
            dif0 = float(t0.get("dif")) if t0.get("dif") is not None else None
            dif1 = float(t1.get("dif")) if t1.get("dif") is not None else None
            dea0 = float(t0.get("dea")) if t0.get("dea") is not None else None
            dea1 = float(t1.get("dea")) if t1.get("dea") is not None else None
        except Exception:
            return False
        vals = (dif0, dif1, dea0, dea1)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            return False
        golden = (dif1 <= dea1) and (dif0 > dea0)
        return golden if want_true else not golden

    # KDJ 金叉：K 从下往上穿越 D
    if field == "kdj_golden_fork":
        t0 = df.iloc[-1]
        t1 = df.iloc[-2] if len(df) >= 2 else t0
        try:
            k0 = float(t0.get("kdj_k")) if t0.get("kdj_k") is not None else None
            k1 = float(t1.get("kdj_k")) if t1.get("kdj_k") is not None else None
            d0 = float(t0.get("kdj_d")) if t0.get("kdj_d") is not None else None
            d1 = float(t1.get("kdj_d")) if t1.get("kdj_d") is not None else None
        except Exception:
            return False
        vals_kdj = (k0, k1, d0, d1)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals_kdj):
            return False
        golden = (k1 <= d1) and (k0 > d0)
        return golden if want_true else not golden

    # 站上/跌破 N 日均线
    if field in {"ma5_cross", "ma10_cross", "ma20_cross", "ma60_cross"}:
        t0 = df.iloc[-1]
        try:
            close = float(t0.get("close")) if t0.get("close") is not None else None
            ma_key = field.replace("_cross", "")
            ma = float(t0.get(ma_key)) if t0.get(ma_key) is not None else None
        except Exception:
            return False
        if close is None or ma is None or (isinstance(close, float) and np.isnan(close)) or (isinstance(ma, float) and np.isnan(ma)):
            return False
        above = close > ma
        return above if want_true else not above

    # 均线多头排列：ma5 > ma10 > ma20 > ma60
    if field == "ma_bullish":
        t0 = df.iloc[-1]
        try:
            ma5 = float(t0.get("ma5")) if t0.get("ma5") is not None else None
            ma10 = float(t0.get("ma10")) if t0.get("ma10") is not None else None
            ma20 = float(t0.get("ma20")) if t0.get("ma20") is not None else None
            ma60 = float(t0.get("ma60")) if t0.get("ma60") is not None else None
        except Exception:
            return False
        vals = (ma5, ma10, ma20, ma60)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            return False
        bullish = (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60)
        return bullish if want_true else not bullish

    # 均线空头排列：ma5 < ma10 < ma20 < ma60
    if field == "ma_bearish":
        t0 = df.iloc[-1]
        try:
            ma5 = float(t0.get("ma5")) if t0.get("ma5") is not None else None
            ma10 = float(t0.get("ma10")) if t0.get("ma10") is not None else None
            ma20 = float(t0.get("ma20")) if t0.get("ma20") is not None else None
            ma60 = float(t0.get("ma60")) if t0.get("ma60") is not None else None
        except Exception:
            return False
        vals = (ma5, ma10, ma20, ma60)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            return False
        bearish = (ma5 < ma10) and (ma10 < ma20) and (ma20 < ma60)
        return bearish if want_true else not bearish

    # 布林带突破：收盘价突破上轨
    if field == "boll_break_upper":
        t0 = df.iloc[-1]
        try:
            close = float(t0.get("close")) if t0.get("close") is not None else None
            boll_upper = float(t0.get("boll_upper")) if t0.get("boll_upper") is not None else None
        except Exception:
            return False
        if close is None or boll_upper is None or np.isnan(close) or np.isnan(boll_upper):
            return False
        broken = close > boll_upper
        return broken if want_true else not broken

    # 布林带下轨跌破：收盘价跌破下轨
    if field == "boll_break_lower":
        t0 = df.iloc[-1]
        try:
            close = float(t0.get("close")) if t0.get("close") is not None else None
            boll_lower = float(t0.get("boll_lower")) if t0.get("boll_lower") is not None else None
        except Exception:
            return False
        if close is None or boll_lower is None or np.isnan(close) or np.isnan(boll_lower):
            return False
        broken = close < boll_lower
        return broken if want_true else not broken

    # MA5 上穿 MA10（均线金叉）
    if field == "ma5_ma10_golden":
        t0 = df.iloc[-1]
        t1 = df.iloc[-2] if len(df) >= 2 else t0
        try:
            ma5_0 = float(t0.get("ma5")) if t0.get("ma5") is not None else None
            ma5_1 = float(t1.get("ma5")) if t1.get("ma5") is not None else None
            ma10_0 = float(t0.get("ma10")) if t0.get("ma10") is not None else None
            ma10_1 = float(t1.get("ma10")) if t1.get("ma10") is not None else None
        except Exception:
            return False
        vals = (ma5_0, ma5_1, ma10_0, ma10_1)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            return False
        golden = (ma5_1 <= ma10_1) and (ma5_0 > ma10_0)
        return golden if want_true else not golden

    # MA10 上穿 MA20（均线金叉）
    if field == "ma10_ma20_golden":
        t0 = df.iloc[-1]
        t1 = df.iloc[-2] if len(df) >= 2 else t0
        try:
            ma10_0 = float(t0.get("ma10")) if t0.get("ma10") is not None else None
            ma10_1 = float(t1.get("ma10")) if t1.get("ma10") is not None else None
            ma20_0 = float(t0.get("ma20")) if t0.get("ma20") is not None else None
            ma20_1 = float(t1.get("ma20")) if t1.get("ma20") is not None else None
        except Exception:
            return False
        vals = (ma10_0, ma10_1, ma20_0, ma20_1)
        if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
            return False
        golden = (ma10_1 <= ma20_1) and (ma10_0 > ma20_0)
        return golden if want_true else not golden

    # 近N日金叉（value 为整数 N 表示近N日内）
    if field in {"macd_golden_fork_n", "kdj_golden_fork_n"}:
        # value 为 int 时表示近N日内（金叉当天+N-1天内出现过金叉）
        lookback = int(right) if isinstance(right, int) else 1
        lookback = max(1, min(lookback, 30))  # 限制范围 1-30
        base_field = field.replace("_fork_n", "_golden_fork")

        # 检查最近 N 根K线中是否有金叉（DIF从上穿越DEA）
        # i=1表示昨天，i=lookback表示lookback天前
        _golden_found = False
        for i in range(1, min(lookback + 1, len(df))):
            # t_i: i天前的K线（i=1为昨天）
            t_i = df.iloc[-i]
            # t_ip1: (i+1)天前的K线（i=1为前天）
            t_ip1 = df.iloc[-i - 1] if i < len(df) - 1 else t_i
            try:
                if base_field == "macd_golden_fork":
                    # 金叉：dif从下面穿越dea
                    # 条件：(i+1)天前 dif <= dea AND i天前 dif > dea
                    dif_i = float(t_i.get("dif")) if t_i.get("dif") is not None else None
                    dif_ip1 = float(t_ip1.get("dif")) if t_ip1.get("dif") is not None else None
                    dea_i = float(t_i.get("dea")) if t_i.get("dea") is not None else None
                    dea_ip1 = float(t_ip1.get("dea")) if t_ip1.get("dea") is not None else None
                    vals = (dif_i, dif_ip1, dea_i, dea_ip1)
                    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
                        continue
                    # 金叉：(i+1)天前 dif<=dea AND i天前 dif>dea
                    _golden_found = (dif_ip1 <= dea_ip1) and (dif_i > dea_i)
                elif base_field == "kdj_golden_fork":
                    # 金叉：kdj_k从下面穿越kdj_d
                    k_i = float(t_i.get("kdj_k")) if t_i.get("kdj_k") is not None else None
                    k_ip1 = float(t_ip1.get("kdj_k")) if t_ip1.get("kdj_k") is not None else None
                    d_i = float(t_i.get("kdj_d")) if t_i.get("kdj_d") is not None else None
                    d_ip1 = float(t_ip1.get("kdj_d")) if t_ip1.get("kdj_d") is not None else None
                    vals = (k_i, k_ip1, d_i, d_ip1)
                    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in vals):
                        continue
                    _golden_found = (k_ip1 <= d_ip1) and (k_i > d_i)
                else:
                    continue
                if _golden_found:
                    return bool(want_true)
            except Exception:
                continue
        return not want_true

    return False


def _evaluate_simple_field(df: pd.DataFrame, field: str, value: Any) -> bool:
    """评估简单字段条件（扁平字典格式）：支持 {">": x / 直接数值相等"""
    if df is None or (hasattr(df, "empty") and df.empty):
        return False
    t0 = df.iloc[-1]
    left = t0.get(field)
    if left is None or (isinstance(left, float) and np.isnan(left)):
        return False
    try:
        if isinstance(value, dict):
            if "$gt" in value:
                return float(left) > float(value["$gt"])
            if "$lt" in value:
                return float(left) < float(value["$lt"])
            if "$gte" in value:
                return float(left) >= float(value["$gte"])
            if "$lte" in value:
                return float(left) <= float(value["$lte"])
            if "$eq" in value:
                return float(left) == float(value["$eq"])
            if "$ne" in value:
                return float(left) != float(value["$ne"])
            return False
        return float(left) == float(value)
    except (ValueError, TypeError):
        return False


def safe_float(v: Any) -> float | None:
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return float(v)
    except Exception:
        return None

