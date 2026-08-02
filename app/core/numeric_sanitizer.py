"""
数值清洗 / 异常值拒绝工具（修复 #B5）。

所有写入 MongoDB 的数值字段（price/volume/amount/pe/pb/roe/pct_chg 等）应在写入前
先通过 sanitize_numeric(value, ...) 跑一遍，保证入库数据在合理范围内，
避免脏数据（负 PE 展示为 -2300、AKShare 返回 "--"、除权未复权导致 ±1000% 的 pct_chg 等）
污染筛选/回测/排序。

用法示例：
    from app.core.numeric_sanitizer import sanitize_numeric, sanitize_price, sanitize_pct_chg
    close = sanitize_price(q.get("close"))
    pct = sanitize_pct_chg(q.get("pct_chg"))
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd  # 用于 pd.isna（服务层已全局依赖 pandas，复用即可）


# ---------- 基础清洗 ----------
def _coerce_raw(value: Any) -> tuple[bool, float | None]:
    """把输入尽可能转换成 float；返回 (是否成功, 数值)。

    规则：
    - None / 空字符串 / NaN / NaT -> (False, None)
    - 字符串 "-", "--", "null", "None", "N/A" 视为空
    - 数字字符串带千分位 "1,234.56" 自动去逗号
    - bool 视为无效（防止 True/1.0 意外混入股价）
    """
    if value is None:
        return False, None
    if isinstance(value, bool):
        return False, None
    if isinstance(value, (int, float)):
        # NaN / Inf 视为无效
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return False, None
        return True, float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "" or s.lower() in {"-", "--", "null", "none", "n/a", "na", "nan", "inf", "-inf"}:
            return False, None
        s = s.replace(",", "")
        try:
            v = float(s)
        except ValueError:
            return False, None
        if math.isnan(v) or math.isinf(v):
            return False, None
        return True, v
    # pandas 类型：NaT / pd.NA
    try:
        if pd.isna(value) or pd.isnull(value):
            return False, None
    except Exception:
        pass
    try:
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return False, None
        return True, v
    except Exception:
        return False, None


def sanitize_numeric(
    value: Any,
    *,
    min_value: float | None = None,
    max_value: float | None = None,
    allow_negative: bool = True,
    reject_zero: bool = False,
    default: float | None = None,
    round_digits: int | None = None,
) -> float | None:
    """通用数值清洗 + 范围校验。

    Args:
        value: 原始输入（任意类型）
        min_value: 最小值下界（含）。None 表示不限制。
        max_value: 最大值上界（含）。None 表示不限制。
        allow_negative: 是否允许负数。例如 PE 为负通常表示亏损股，可以设 True；
            但 volume/amount 等绝对非负字段应设 False。
        reject_zero: 是否把 0.0 视为非法。例如 pre_close/close 对实际交易股票通常 >= 0.01。
        default: 当输入无效 / 超出范围时返回的默认值（默认 None，调用方通常不会写入该字段）。
        round_digits: 如提供，则 round 到该小数位。例如百分比 round 到 4 位。
    """
    ok, num = _coerce_raw(value)
    if not ok:
        return default

    if not allow_negative and num < 0:
        return default
    if reject_zero and num == 0:
        return default
    if min_value is not None and num < min_value:
        return default
    if max_value is not None and num > max_value:
        return default

    if round_digits is not None:
        num = round(num, round_digits)
    return num


# ---------- 常用语义化封装（调用方用这些，保证口径一致）----------

# A股主板/创业板/科创板日涨跌停：±10% / ±20%；ST ±5%；北交所±30%。
# 日K pct_chg 给 ±35% 的容忍范围（除权除息当日若未复权也不会超过此值），
# 把脏数据如 -90% / +1000% 直接拒掉。
def sanitize_pct_chg(value: Any, *, max_abs_pct: float = 35.0, round_digits: int = 4) -> float | None:
    return sanitize_numeric(
        value,
        min_value=-max_abs_pct,
        max_value=max_abs_pct,
        round_digits=round_digits,
    )


def sanitize_price(value: Any, *, round_digits: int = 4) -> float | None:
    """股价类（close/open/high/low/pre_close）。非负，且合理上界 10 万元（A 股历史未见超过茅台 3000，但要兼容港股/美股后复权价百万级，给 1e6 上限）。"""
    return sanitize_numeric(
        value,
        min_value=0.0,
        max_value=1_000_000.0,
        allow_negative=False,
        round_digits=round_digits,
    )


def sanitize_amount(value: Any, *, round_digits: int = 2) -> float | None:
    """成交额 / 流通市值（元或万元，看写入口径，但单位转换在外部，这里只管数值本身）。"""
    return sanitize_numeric(
        value,
        min_value=0.0,
        max_value=1e16,
        allow_negative=False,
        round_digits=round_digits,
    )


def sanitize_volume(value: Any) -> float | None:
    """成交量：非负整数域，但允许 float；绝对非负。"""
    return sanitize_numeric(value, min_value=0.0, max_value=1e14, allow_negative=False)


def sanitize_turnover_rate(value: Any, *, round_digits: int = 4) -> float | None:
    """换手率 %：0 ~ 100 之间。"""
    return sanitize_numeric(
        value,
        min_value=0.0,
        max_value=100.0,
        allow_negative=False,
        round_digits=round_digits,
    )


def sanitize_pe(value: Any, *, round_digits: int = 2) -> float | None:
    """市盈率：允许负值（亏损股），但绝对数值限制在 [-1e4, 1e4]。
    负值的"含义"由前端/下游决定（很多展示会标为 None），这里只过滤离谱脏数据。
    """
    return sanitize_numeric(
        value,
        min_value=-10_000.0,
        max_value=10_000.0,
        round_digits=round_digits,
    )


def sanitize_pb(value: Any, *, round_digits: int = 2) -> float | None:
    """市净率：一般非负（资不抵债可以 <0），给 [-100, 1000] 容忍范围。"""
    return sanitize_numeric(
        value,
        min_value=-100.0,
        max_value=1_000.0,
        round_digits=round_digits,
    )


def sanitize_roe(value: Any, *, round_digits: int = 2) -> float | None:
    """ROE（%）。[-100, 100] 以外一般是脏数据。"""
    return sanitize_numeric(
        value,
        min_value=-100.0,
        max_value=100.0,
        round_digits=round_digits,
    )
