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
    # 今日站上 MA20，且前一日收盘在 MA20 下方（回踩后反弹）。
    # 必须按 symbol 分组 shift：筛选模式传入的是"目标日单行/每股"的 DataFrame，
    # 若直接 shift(1) 会取到上一行（另一只股票）的 close/ma20，造成跨股票数据污染；
    # 回测模式在每股首行也会泄漏到上一只股票的末行。
    prev_close = df.groupby("symbol")["close"].shift(1)
    prev_ma20 = df.groupby("symbol")["ma20"].shift(1)
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


def _num_col(df: pd.DataFrame, col: str) -> pd.Series:
    """安全读取数值列：缺失列返回与 df 对齐索引的 NaN Series，而非标量。

    避免 pd.to_numeric(None) 返回 numpy.float64 标量导致后续 .fillna/.notna 崩溃。
    """
    if col not in df.columns:
        return pd.Series(float("nan"), index=df.index)
    return pd.to_numeric(df[col], errors="coerce")


def _low_pe_high_dividend_leader(df: pd.DataFrame, params: dict) -> pd.Series:
    """低估值、高股息、能长期稳定分红的行业龙头。

    依赖 screener._enrich_target 注入的列：pe_ttm, pb, total_mv, industry,
    div_yield, div_paying_years。回测面板若无这些列（技术指标面板），
    则返回全 False（无信号），不崩溃。

    分两阶段：
    1. 基础过滤：PE>0且≤max_pe、PB>0且≤max_pb（低估值）、股息率≥min_div_yield（高股息）、
       近5年分红年数≥min_div_years（长期稳定分红）、市值有效。
    2. 行业龙头：在通过基础过滤的股票中，按行业内市值降序取 top N。
    """
    max_pe = float(params.get("max_pe", 15))
    max_pb = float(params.get("max_pb", 3.0))
    min_div_yield = float(params.get("min_div_yield", 0.03))
    min_div_years = int(params.get("min_div_years", 4))
    top_n = int(params.get("top_n", 3))

    pe = _num_col(df, "pe_ttm")
    pb = _num_col(df, "pb")
    dy = _num_col(df, "div_yield")
    div_years = _num_col(df, "div_paying_years")
    mv = _num_col(df, "total_mv")
    industry = df.get("industry", pd.Series("", index=df.index)).fillna("")

    m = (pe > 0) & (pe <= max_pe)
    m &= (pb > 0) & (pb <= max_pb)
    m &= (dy.fillna(0) >= min_div_yield)
    m &= (div_years.fillna(0) >= min_div_years)
    m &= mv.notna()

    didx = df.index[m.fillna(False)]
    leader = pd.Series(False, index=df.index)
    if len(didx) > 0:
        symbol = df.loc[didx, "symbol"].astype(str)
        sub = pd.DataFrame({
            "symbol": symbol.values,
            "industry": industry.loc[didx].values,
            "mv": mv.loc[didx].values,
        }, index=didx)
        # 先按 symbol 去重（回测面板含多日行，市值/行业为每股快照逐日广播），
        # 再按行业取市值 TopN 只股票，避免 head(top_n) 误取同一只股票的多行
        sub = sub.sort_values(["mv", "symbol"], ascending=[False, True])
        sub = sub.groupby("symbol", sort=False).head(1)
        selected: set[str] = set()
        for _ind, grp in sub.groupby("industry", sort=False):
            selected.update(grp["symbol"].head(top_n).tolist())
        leader = df["symbol"].isin(selected)
        # 关键：选中的行业龙头必须叠加"每日"基础过滤（PE/PB/股息/分红年数）。
        # 否则龙头在回测期被 broadcast 到所有日期，即使当日 PE/PB 已突破阈值
        # 仍会产生买入信号，导致"次日卖出→再次买入"的每日循环（bug-020）。
        return leader & m.fillna(False)
    return leader


def _turnaround(df: pd.DataFrame, params: dict) -> pd.Series:
    """困境反转：基本面（营收/净利增速）由负转正、估值修复，且价格企稳。

    依赖 _enrich_target 注入的列：revenue_yoy, net_profit_yoy, roe, pe_ttm, close。
    回测/技术面板若无这些列，则返回全 False（无信号），不崩溃。
    逻辑：
    1. 营收或净利同比>=0（增速转正/已转正），且非双降；
    2. 估值合理（PE>0 且 <= max_pe）；
    3. 价格企稳：收盘价至少站上 MA20 或 MA5>MA10（趋势初步修复）。
    """
    min_growth = float(params.get("min_growth", 0.0))
    max_pe = float(params.get("max_pe", 60))
    rev = _num_col(df, "revenue_yoy")
    npf = _num_col(df, "net_profit_yoy")
    pe = _num_col(df, "pe_ttm")

    # 基本面止跌：营收或净利同比 >= min_growth（允许一个为负，但至少一个转正）
    grow = (rev >= min_growth) | (npf >= min_growth)
    grow = grow.fillna(False)
    # 排除双降：营收与净利均 < 0
    both_neg = (rev.fillna(0) < 0) & (npf.fillna(0) < 0)
    m = grow & ~both_neg
    # 估值合理
    m &= (pe > 0) & (pe <= max_pe)
    # 价格企稳：close >= ma20（column 可选）
    if "ma20" in df.columns:
        m &= df["close"] >= df["ma20"]
    return m.fillna(False)


def _small_cap_value(df: pd.DataFrame, params: dict) -> pd.Series:
    """小盘价值：中小市值 + 低估值 + 盈利为正。

    依赖 _enrich_target 注入的列：total_mv, pe_ttm, pb, roe。
    回测/技术面板若无这些列（技术指标面板），则返回全 False（无信号），不崩溃。
    逻辑：
    1. 市值区间 [min_mv, max_mv]（亿元）；
    2. 低估值：PE>0 且 <= max_pe，PB>0 且 <= max_pb；
    3. 盈利为正：ROE>0。
    """
    min_mv = float(params.get("min_mv", 10))
    max_mv = float(params.get("max_mv", 50))
    max_pe = float(params.get("max_pe", 25))
    max_pb = float(params.get("max_pb", 3.0))

    mv = _num_col(df, "total_mv")
    pe = _num_col(df, "pe_ttm")
    pb = _num_col(df, "pb")
    roe = _num_col(df, "roe")

    m = (mv >= min_mv) & (mv <= max_mv)
    m &= (pe > 0) & (pe <= max_pe)
    m &= (pb > 0) & (pb <= max_pb)
    m &= (roe.fillna(0) > 0)
    return m.fillna(False)


def _def(id_, name, description, tags, params, scoring, filter_fn,
         entry_signals, exit_signals, buy_desc=None, sell_desc=None,
         order_by="score", descending=True, limit=100):
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
        # 人类可读的买入 / 卖出指导（信号栏位可能为空，此时作为买卖规则兜底）
        "buy_desc": buy_desc or [],
        "sell_desc": sell_desc or [],
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
        ["MA5 上穿 MA20（金叉）且量能配合"], ["MA5 下穿 MA20（死叉）离场"],
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
        ["MACD 零轴上方金叉（DIF 上穿 DEA）"], ["MACD 死叉（DIF 下穿 DEA）离场"],
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
        ["收盘创 60 日新高且放量突破"], ["跌破 20 日均线或冲高回落离场"],
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
        ["创 60 日新低后收阳企稳，RSI 低位"], ["跌破前低转弱离场"],
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
        ["RSI 超卖后 MA5 向上突破反弹"], ["MA5 下穿（反弹乏力）离场"],
    ),
    _def(
        "trend_breakout", "趋势突破", "创60日新高且站上多均线，多头趋势",
        ["趋势", "突破"],
        [],
        {"momentum_20d": 0.5, "momentum_60d": 0.3, "change_pct": 0.2},
        _trend_breakout,
        ["signal_n_day_high"], ["signal_ma20_breakdown"],
        ["创 60 日新高且站上多均线，多头趋势"], ["跌破 MA20，趋势转弱离场"],
    ),
    _def(
        "boll_breakout", "布林突破", "收盘突破布林上轨且收涨",
        ["布林", "突破"],
        [],
        {"momentum_20d": 0.5, "change_pct": 0.3, "vol_ratio_5d": 0.2},
        _boll_breakout,
        ["signal_boll_breakout_upper"], [],
        ["收盘突破布林上轨且收涨"], ["收盘跌破布林中轨（MA20）离场"],
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
        ["放量上涨，量比 ≥2 倍且收涨"], ["缩量滞涨或跌破 5 日均线离场"],
    ),
    _def(
        "pullback_ma20_bounce", "回踩MA20反弹", "回踩MA20后重新站上，多头延续",
        ["均线", "回踩"],
        [],
        {"momentum_5d": 0.5, "momentum_20d": 0.3, "change_pct": 0.2},
        _pullback_ma20_bounce,
        ["signal_ma20_breakout"], ["signal_ma20_breakdown"],
        ["回踩 MA20 后重新站上企稳"], ["跌破 MA20（回踩失败）离场"],
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
        ["高开 ≥2% 且收阳、放量走强"], ["冲高回落或跌破开盘价离场"],
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
        ["低波动（年化波动 ≤35%）、20 日动量走强"], ["放量下跌破位或动量转弱离场"],
    ),
    _def(
        "low_pe_high_div_leader", "低估值高股息龙头", "低估值(PE/PB)、高股息、近5年稳定分红且行业内市值Top3的行业龙头",
        ["价值", "高股息", "行业龙头"],
        [
            {"id": "max_pe", "label": "市盈率上限", "type": "float", "default": 15, "min": 5, "max": 50, "step": 1},
            {"id": "max_pb", "label": "市净率上限", "type": "float", "default": 3.0, "min": 0.5, "max": 10, "step": 0.1},
            {"id": "min_div_yield", "label": "最低股息率", "type": "float", "default": 0.03, "min": 0.01, "max": 0.10, "step": 0.005},
            {"id": "min_div_years", "label": "近5年分红年数", "type": "int", "default": 4, "min": 1, "max": 5, "step": 1},
            {"id": "top_n", "label": "行业龙头数", "type": "int", "default": 3, "min": 1, "max": 10, "step": 1},
        ],
        {"div_yield": 0.4, "total_mv": 0.3, "div_paying_years": 0.3},
        _low_pe_high_dividend_leader,
        [], [],
        ["低估值（PE≤15/PB≤3）、股息率≥3%、行业市值 Top3"], ["估值修复到位或盈利/分红恶化离场"],
    ),
    _def(
        "turnaround", "困境反转", "基本面(营收/净利增速)由负转正、估值合理且价格企稳",
        ["反转", "基本面", "困境"],
        [
            {"id": "min_growth", "label": "最低增速(营收/净利任一)", "type": "float", "default": 0.0, "min": -0.5, "max": 0.5, "step": 0.05},
            {"id": "max_pe", "label": "市盈率上限", "type": "float", "default": 60, "min": 10, "max": 200, "step": 5},
        ],
        {"revenue_yoy": 0.4, "net_profit_yoy": 0.4, "momentum_20d": 0.2},
        _turnaround,
        [], [],
        ["营收/净利增速由负转正、估值合理、价格企稳"], ["反转证伪（增速再转负）或跌破平台离场"],
    ),
    _def(
        "small_cap_value", "小盘价值", "中小市值(10~50亿) + 低估值(PE/PB) + 盈利为正",
        ["小盘", "价值"],
        [
            {"id": "min_mv", "label": "最小市值(亿)", "type": "float", "default": 10, "min": 5, "max": 100, "step": 5},
            {"id": "max_mv", "label": "最大市值(亿)", "type": "float", "default": 50, "min": 10, "max": 200, "step": 5},
            {"id": "max_pe", "label": "市盈率上限", "type": "float", "default": 25, "min": 5, "max": 100, "step": 5},
            {"id": "max_pb", "label": "市净率上限", "type": "float", "default": 3.0, "min": 0.5, "max": 10, "step": 0.1},
        ],
        {"total_mv": 0.3, "pe_ttm": 0.3, "pb": 0.2, "roe": 0.2},
        _small_cap_value,
        [], [],
        ["中小市值（10~50亿）、低估值（PE≤25/PB≤3）、盈利为正"], ["盈利转负或脱离价值区间离场"],
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