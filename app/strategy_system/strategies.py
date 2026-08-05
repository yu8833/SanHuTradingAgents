"""内置策略定义 — 移植自 tickflow-stock-panel 的 strategy/builtin。

每个策略是一个 dict，包含元信息、参数、评分权重，以及一个 filter(df, params) 函数。
filter 接收目标日期的 enriched 行 DataFrame（含全部指标与信号列），返回布尔 Series。
"""
from __future__ import annotations

import pandas as pd


def _gt(df: pd.DataFrame, col: str, val: float) -> pd.Series:
    return df[col] > val


def _lt(df: pd.DataFrame, col: str, val: float) -> pd.Series:
    return df[col] < val


def _ge(df: pd.DataFrame, col: str, val: float) -> pd.Series:
    return df[col] >= val


def _signal(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name].fillna(False).astype(bool)


# ──────────────────────────────────────────────────────────────
# 策略定义
# ──────────────────────────────────────────────────────────────

def _ma_golden_cross(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_ma_golden_5_20")
    if params.get("use_volume_filter", True):
        m &= _ge(df, "vol_ratio_5d", float(params.get("vol_ratio_min", 1.2)))
    if params.get("require_above_ma60", True):
        m &= _gt(df, "close", df["ma60"])
    return m


def _macd_golden(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_macd_golden")
    if params.get("require_above_ma20", True):
        m &= _gt(df, "close", df["ma20"])
    return m


def _n_day_high_breakout(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_n_day_high")
    if params.get("use_volume_filter", True):
        m &= _ge(df, "vol_ratio_5d", float(params.get("vol_ratio_min", 1.2)))
    return m


def _n_day_low_reversal(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_n_day_low")
    m &= df["close"] > df["open"]  # 收阳
    if params.get("require_rsi_low", True):
        m &= _lt(df, "rsi_14", float(params.get("rsi_max", 35)))
    return m


def _oversold_bounce(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _lt(df, "rsi_14", float(params.get("rsi_max", 30)))
    m &= _signal(df, "signal_ma5_breakout")
    return m


def _trend_breakout(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_n_day_high")
    m &= _gt(df, "close", df["ma20"])
    m &= df["ma20"] > df["ma60"]
    return m


def _boll_breakout(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _signal(df, "signal_boll_breakout_upper")
    m &= _gt(df, "change_pct", 0)  # 收涨
    return m


def _volume_price_surge(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _gt(df, "change_pct", float(params.get("min_pct", 0.05)))
    m &= _ge(df, "vol_ratio_5d", float(params.get("min_vol_ratio", 2.0)))
    return m


def _pullback_ma20_bounce(df: pd.DataFrame, params: dict) -> pd.Series:
    # 今日站上 MA20，且前一日收盘在 MA20 下方（回踩后反弹）
    prev_close = df["close"].shift(1)
    prev_ma20 = df["ma20"].shift(1)
    m = (df["close"] > df["ma20"]) & (prev_close <= prev_ma20)
    m &= df["ma20"] > df["ma60"]
    return m


def _strong_open(df: pd.DataFrame, params: dict) -> pd.Series:
    m = df["open"] > df["prev_close"] * float(params.get("min_gap_pct", 1.02))
    m &= df["close"] > df["open"]
    if params.get("use_volume_filter", True):
        m &= _ge(df, "vol_ratio_5d", float(params.get("vol_ratio_min", 1.5)))
    return m


def _low_volatility_leader(df: pd.DataFrame, params: dict) -> pd.Series:
    m = _lt(df, "annual_vol_20d", float(params.get("max_vol", 0.35)))
    m &= _gt(df, "momentum_20d", float(params.get("min_momentum", 0.05)))
    m &= _gt(df, "close", df["ma60"])
    return m


def _def(id_, name, description, tags, params, scoring, filter_fn,
         entry_signals, exit_signals, order_by="score", descending=True, limit=100):
    return {
        "id": id_,
        "name": name,
        "description": description,
        "tags": tags,
        "params": params,
        "scoring": scoring,
        "filter": filter_fn,
        "entry_signals": entry_signals,
        "exit_signals": exit_signals,
        "order_by": order_by,
        "descending": descending,
        "limit": limit,
        "source": "builtin",
        "asset_types": ["stock", "etf"],
    }


BUILTIN_STRATEGIES: list[dict] = [
    _def(
        "ma_golden_cross", "MA金叉", "MA5上穿MA20当日触发，量能配合",
        ["均线", "金叉"],
        [
            {"id": "require_ma_golden", "label": "要求MA5上穿MA20", "type": "bool", "default": True},
            {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
            {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "step": 0.1},
            {"id": "require_above_ma60", "label": "要求收盘价在MA60上方", "type": "bool", "default": True},
        ],
        {"momentum_20d": 0.5, "vol_ratio_5d": 0.3, "change_pct": 0.2},
        _ma_golden_cross,
        ["signal_ma_golden_5_20"], ["signal_ma_dead_5_20"],
    ),
    _def(
        "macd_golden", "MACD金叉", "MACD零轴上方金叉，趋势延续",
        ["MACD", "金叉"],
        [
            {"id": "require_above_ma20", "label": "要求收盘价在MA20上方", "type": "bool", "default": True},
        ],
        {"momentum_20d": 0.5, "macd_hist": 0.3, "change_pct": 0.2},
        _macd_golden,
        ["signal_macd_golden"], ["signal_macd_dead"],
    ),
    _def(
        "n_day_high_breakout", "创60日新高", "收盘创60日新高且放量突破",
        ["突破", "新高"],
        [
            {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
            {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.2, "min": 0.5, "max": 5.0, "step": 0.1},
        ],
        {"momentum_20d": 0.5, "change_pct": 0.3, "vol_ratio_5d": 0.2},
        _n_day_high_breakout,
        ["signal_n_day_high"], [],
    ),
    _def(
        "n_day_low_reversal", "N日低点反转", "创60日新低后收阳企稳",
        ["反转", "超跌"],
        [
            {"id": "require_rsi_low", "label": "要求RSI处于低位", "type": "bool", "default": True},
            {"id": "rsi_max", "label": "RSI14上限", "type": "float", "default": 35, "min": 10, "max": 50, "step": 1},
        ],
        {"rsi_14": 0.5, "momentum_5d": 0.3, "change_pct": 0.2},
        _n_day_low_reversal,
        ["signal_n_day_low"], [],
    ),
    _def(
        "oversold_bounce", "超跌反弹", "RSI超卖后MA5金叉反弹",
        ["超跌", "反弹"],
        [
            {"id": "rsi_max", "label": "RSI14上限", "type": "float", "default": 30, "min": 10, "max": 50, "step": 1},
        ],
        {"rsi_14": 0.5, "momentum_5d": 0.3, "change_pct": 0.2},
        _oversold_bounce,
        ["signal_ma5_breakout"], ["signal_ma5_breakdown"],
    ),
    _def(
        "trend_breakout", "趋势突破", "创60日新高且站上多均线，多头趋势",
        ["趋势", "突破"],
        [],
        {"momentum_20d": 0.5, "momentum_60d": 0.3, "change_pct": 0.2},
        _trend_breakout,
        ["signal_n_day_high"], [],
    ),
    _def(
        "boll_breakout", "布林突破", "收盘突破布林上轨且收涨",
        ["布林", "突破"],
        [],
        {"momentum_20d": 0.5, "change_pct": 0.3, "vol_ratio_5d": 0.2},
        _boll_breakout,
        ["signal_boll_breakout_upper"], [],
    ),
    _def(
        "volume_price_surge", "量价齐升", "放量上涨，量比不低于2倍",
        ["量价", "放量"],
        [
            {"id": "min_pct", "label": "最低涨幅", "type": "float", "default": 0.05, "min": 0.01, "max": 0.1, "step": 0.01},
            {"id": "min_vol_ratio", "label": "最低量比", "type": "float", "default": 2.0, "min": 1.0, "max": 5.0, "step": 0.1},
        ],
        {"change_pct": 0.5, "vol_ratio_5d": 0.3, "momentum_5d": 0.2},
        _volume_price_surge,
        [], [],
    ),
    _def(
        "pullback_ma20_bounce", "回踩MA20反弹", "回踩MA20后重新站上，多头延续",
        ["均线", "回踩"],
        [],
        {"momentum_5d": 0.5, "momentum_20d": 0.3, "change_pct": 0.2},
        _pullback_ma20_bounce,
        ["signal_ma20_breakout"], ["signal_ma20_breakdown"],
    ),
    _def(
        "strong_open", "强势高开", "高开2%以上且收阳、放量",
        ["高开", "强势"],
        [
            {"id": "min_gap_pct", "label": "最低高开幅度", "type": "float", "default": 1.02, "min": 1.01, "max": 1.05, "step": 0.01},
            {"id": "use_volume_filter", "label": "启用量比过滤", "type": "bool", "default": True},
            {"id": "vol_ratio_min", "label": "最低量比", "type": "float", "default": 1.5, "min": 1.0, "max": 5.0, "step": 0.1},
        ],
        {"change_pct": 0.5, "vol_ratio_5d": 0.3, "momentum_5d": 0.2},
        _strong_open,
        [], [],
    ),
    _def(
        "low_volatility_leader", "低波动龙头", "低波动且持续走强，强势股",
        ["低波动", "强势"],
        [
            {"id": "max_vol", "label": "最大年化波动", "type": "float", "default": 0.35, "min": 0.1, "max": 0.6, "step": 0.05},
            {"id": "min_momentum", "label": "最低20日动量", "type": "float", "default": 0.05, "min": 0.0, "max": 0.2, "step": 0.01},
        ],
        {"momentum_20d": 0.5, "momentum_60d": 0.3, "annual_vol_20d": 0.2},
        _low_volatility_leader,
        [], [],
    ),
]

_STRATEGY_MAP: dict[str, dict] = {s["id"]: s for s in BUILTIN_STRATEGIES}


def get_strategies() -> list[dict]:
    """返回策略元信息（不含 filter 函数，供 API 序列化）。"""
    out = []
    for s in BUILTIN_STRATEGIES:
        item = dict(s)
        item.pop("filter", None)
        out.append(item)
    return out


def get_strategy(strategy_id: str) -> dict | None:
    return _STRATEGY_MAP.get(strategy_id)


def run_strategy_filter(strategy_id: str, df: pd.DataFrame, params: dict | None = None) -> pd.Series:
    """对目标日期行 DataFrame 执行策略过滤，返回布尔 Series。"""
    s = _STRATEGY_MAP.get(strategy_id)
    if s is None:
        raise ValueError(f"未知策略: {strategy_id}")
    params = params or {}
    return s["filter"](df, params)