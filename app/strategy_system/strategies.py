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


def _bottom_volume(df: pd.DataFrame, params: dict) -> pd.Series:
    """底部放量（管道A · 7策略新增）：长期下跌后首个放量收阳，潜在反转。

    依赖 enriched 面板列：momentum_20d（20日涨幅）、vol_ratio_5d（量比=当日量/前5日均量）、
    close/open/low。任一缺失时返回空（False），不崩溃。

    逻辑（对齐 LLM 模板要点）：
    1. 持续下跌确认：20日涨幅 < -max_drop（默认 15%）；
    2. 量能异动：vol_ratio_5d >= min_vol_ratio（默认 3，前期缩量后脉冲放量）；
    3. 价格企稳：收阳（close > open）且收在当日振幅上 1/3（长下影，买方承接）。
    反转类信号风险提示：仓位建议≤2-3成，止损严格设近期低点下方（见 buy_desc/卖点模板）。
    """
    max_drop = float(params.get("max_drop", 0.15))
    min_vol_ratio = float(params.get("min_vol_ratio", 3.0))
    mom = _num_col(df, "momentum_20d")
    vratio = _num_col(df, "vol_ratio_5d")
    m = mom < -max_drop
    m &= vratio >= min_vol_ratio
    m &= df["close"] > df["open"]
    # 长下影（收在当日振幅上 1/3）：(close-low) >= (high-low)/3
    rng = (df["high"] - df["low"]).replace(0, float("nan"))
    m &= (df["close"] - df["low"]) / rng >= float(params.get("min_lower_shadow", 1 / 3))
    return m.fillna(False)


def _one_yang_three_yin(df: pd.DataFrame, params: dict) -> pd.Series:
    """一阳夹三阴（管道A · 7策略新增）：1 大阳 + 3 小K整理（不破大阳开盘）+ 第5日突破。

    依赖 enriched 面板列（按 symbol 分组 shift，防跨股票污染）：open/high/low/close/volume，
    ma5/ma10/ma20。回测模式下每股首 4 行为 NaN → 自动 False。

    形态（对齐 LLM 模板要点）：
    1. 第1日（T-4）大阳：实体 (c-o)/o > min_entity_pct（默认 2%）；
    2. 第2~4日（T-3/T-2/T-1）三根小K：低点不破第1日开盘价、收盘落在第1日实体区间、
       三根量能相对第1日萎缩（合计 < 第1日量 × 3 × 缩量系数）；
    3. 第5日（T）收阳并突破第1日收盘价；
    4. 确认项（可选）：MA5 > MA10 > MA20。
    """
    min_entity_pct = float(params.get("min_entity_pct", 0.02))
    shrink = float(params.get("shrink_ratio", 0.9))
    g = df.groupby("symbol")
    o4 = g["open"].shift(4)
    c4 = g["close"].shift(4)
    v4 = g["volume"].shift(4)
    lows = [g["low"].shift(i) for i in (3, 2, 1)]
    closes = [g["close"].shift(i) for i in (3, 2, 1)]
    vols = [g["volume"].shift(i) for i in (3, 2, 1)]

    m = (c4 - o4) / o4.replace(0, float("nan")) > min_entity_pct  # 第1日大阳
    for lo, cl in zip(lows, closes, strict=False):
        m &= lo > o4                      # 三根低点不破第1日开盘价
        m &= cl >= o4                     # 收盘落在第1日实体区间内
        m &= cl <= c4
    m &= (vols[0] + vols[1] + vols[2]) <= (v4 * 3 * shrink)  # 三根量能相对第1日萎缩
    m &= df["close"] > df["open"]         # 第5日收阳
    m &= df["close"] > c4                 # 突破第1日收盘
    if params.get("require_ma_trend", True):
        m &= df["ma5"] > df["ma10"]
        m &= df["ma10"] > df["ma20"]
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
         order_by="score", descending=True, limit=100, market_regimes=None):
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
        "market_regimes": market_regimes or [],
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
        market_regimes=["牛市强趋势", "牛市普涨"],
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
        market_regimes=["牛市强趋势", "震荡蓄势"],
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
        market_regimes=["牛市强趋势", "牛市普涨"],
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
        market_regimes=["震荡蓄势", "震荡分化"],
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
        market_regimes=["熊市恐慌", "高波动市"],
    ),
    _def(
        "trend_breakout", "趋势突破", "创60日新高且站上多均线，多头趋势",
        ["趋势", "突破"],
        [],
        {"momentum_20d": 0.5, "momentum_60d": 0.3, "change_pct": 0.2},
        _trend_breakout,
        ["signal_n_day_high"], ["signal_ma20_breakdown"],
        ["创 60 日新高且站上多均线，多头趋势"], ["跌破 MA20，趋势转弱离场"],
        market_regimes=["牛市强趋势", "牛市普涨"],
    ),
    _def(
        "boll_breakout", "布林突破", "收盘突破布林上轨且收涨",
        ["布林", "突破"],
        [],
        {"momentum_20d": 0.5, "change_pct": 0.3, "vol_ratio_5d": 0.2},
        _boll_breakout,
        ["signal_boll_breakout_upper"], [],
        ["收盘突破布林上轨且收涨"], ["收盘跌破布林中轨（MA20）离场"],
        market_regimes=["震荡蓄势", "震荡分化"],
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
        market_regimes=["牛市普涨", "高波动市"],
    ),
    _def(
        "pullback_ma20_bounce", "回踩MA20反弹", "回踩MA20后重新站上，多头延续",
        ["均线", "回踩"],
        [],
        {"momentum_5d": 0.5, "momentum_20d": 0.3, "change_pct": 0.2},
        _pullback_ma20_bounce,
        ["signal_ma20_breakout"], ["signal_ma20_breakdown"],
        ["回踩 MA20 后重新站上企稳"], ["跌破 MA20（回踩失败）离场"],
        market_regimes=["牛市强趋势", "震荡蓄势"],
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
        market_regimes=["牛市普涨", "高波动市"],
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
        market_regimes=["牛市强趋势", "全面适用"],
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
        market_regimes=["熊市阴跌", "全面适用"],
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
        market_regimes=["熊市阴跌", "震荡蓄势", "震荡分化"],
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
        market_regimes=["牛市普涨", "震荡分化"],
    ),
    # ── 管道A · 7策略新增（底部放量 / 一阳夹三阴）──
    # 完整元数据（required_columns / market_regimes / frontend）由下方 @strategy
    # 装饰器注册进 registry；此处 _def 追加到 BUILTIN_STRATEGIES 供
    # get_strategies()/run_strategy_filter()/screener/backtest 直接使用。
    _def(
        "bottom_volume", "底部放量", "持续下跌后底部放量收阳（跌幅>15%、量比≥3、长下影），潜在反转",
        ["反转", "底部", "放量"],
        [
            {"id": "max_drop", "label": "最大20日跌幅", "type": "float", "default": 0.15, "min": 0.05, "max": 0.5, "step": 0.05},
            {"id": "min_vol_ratio", "label": "最低量比", "type": "float", "default": 3.0, "min": 1.5, "max": 6.0, "step": 0.5},
            {"id": "min_lower_shadow", "label": "最短下影线占比", "type": "float", "default": 0.33, "min": 0.1, "max": 0.5, "step": 0.05},
        ],
        {"momentum_20d": 0.4, "vol_ratio_5d": 0.4, "change_pct": 0.2},
        _bottom_volume,
        [], [],
        ["20日跌幅>15%，当日量比≥3、收阳带长下影（底部承接）"], ["反转证伪：跌破放量日低点 / 3日内不回补，止损离场"],
        market_regimes=["熊市恐慌", "震荡蓄势"],
    ),
    _def(
        "one_yang_three_yin", "一阳夹三阴", "1大阳+3小K整理（不破大阳开盘）+第5日放量突破，多方蓄势形态",
        ["K线", "形态", "突破"],
        [
            {"id": "min_entity_pct", "label": "第1日最低实体涨幅", "type": "float", "default": 0.02, "min": 0.01, "max": 0.08, "step": 0.01},
            {"id": "shrink_ratio", "label": "三根缩量系数", "type": "float", "default": 0.9, "min": 0.5, "max": 1.2, "step": 0.05},
            {"id": "require_ma_trend", "label": "要求多头均线排列", "type": "bool", "default": True},
        ],
        {"momentum_5d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
        _one_yang_three_yin,
        [], [],
        ["1大阳+3小K不破大阳开盘+第5日突破大阳收盘，MA5>MA10>MA20"], ["跌破第1日开盘价（形态破坏）离场止损"],
        market_regimes=["牛市强趋势", "震荡蓄势"],
    ),
]

_STRATEGY_MAP: dict[str, dict] = {s["id"]: s for s in BUILTIN_STRATEGIES}

# ── 兼容 shim：把存量策略批量同步进注册表（registry.py），
#    新策略可用 @strategy 装饰器直接注册；get_strategies 等保持原实现零改动 ──
try:
    from app.strategy_system.registry import FrontendSpec, strategy
    from app.strategy_system.registry import registry as _registry

    # 管道A 两个新策略：装饰器注册（含 required_columns / market_regimes / frontend）。
    # required_columns 显式声明取代回测 AST 解析（AST 降级为 dev 校验兜底）。
    @strategy(
        id="bottom_volume", name="底部放量",
        description="持续下跌后底部放量收阳（跌幅>15%、量比≥3、长下影），潜在反转",
        tags=["反转", "底部", "放量"],
        params=[
            {"id": "max_drop", "label": "最大20日跌幅", "type": "float", "default": 0.15, "min": 0.05, "max": 0.5, "step": 0.05},
            {"id": "min_vol_ratio", "label": "最低量比", "type": "float", "default": 3.0, "min": 1.5, "max": 6.0, "step": 0.5},
            {"id": "min_lower_shadow", "label": "最短下影线占比", "type": "float", "default": 0.33, "min": 0.1, "max": 0.5, "step": 0.05},
        ],
        scoring={"momentum_20d": 0.4, "vol_ratio_5d": 0.4, "change_pct": 0.2},
        required_columns={"momentum_20d", "vol_ratio_5d", "change_pct"},
        needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["20日跌幅>15%，当日量比≥3、收阳带长下影（底部承接）"],
        sell_desc=["反转证伪：跌破放量日低点 / 3日内不回补，止损离场"],
        frontend=FrontendSpec(icon="🛑", color="#E6A23C", order=15),
        market_regimes=["熊市恐慌", "震荡蓄势"],
    )
    def bottom_volume_deco(df, params):
        return _bottom_volume(df, params)

    @strategy(
        id="one_yang_three_yin", name="一阳夹三阴",
        description="1大阳+3小K整理（不破大阳开盘）+第5日放量突破，多方蓄势形态",
        tags=["K线", "形态", "突破"],
        params=[
            {"id": "min_entity_pct", "label": "第1日最低实体涨幅", "type": "float", "default": 0.02, "min": 0.01, "max": 0.08, "step": 0.01},
            {"id": "shrink_ratio", "label": "三根缩量系数", "type": "float", "default": 0.9, "min": 0.5, "max": 1.2, "step": 0.05},
            {"id": "require_ma_trend", "label": "要求多头均线排列", "type": "bool", "default": True},
        ],
        scoring={"momentum_5d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
        required_columns={"momentum_5d", "vol_ratio_5d", "change_pct", "ma5", "ma10", "ma20"},
        needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["1大阳+3小K不破大阳开盘+第5日突破大阳收盘，MA5>MA10>MA20"],
        sell_desc=["跌破第1日开盘价（形态破坏）离场止损"],
        frontend=FrontendSpec(icon="📰", color="#67C23A", order=16),
        market_regimes=["牛市强趋势", "震荡蓄势"],
    )
    def one_yang_three_yin_deco(df, params):
        return _one_yang_three_yin(df, params)

    # 零售独有 2 策略：execution 走 retail 扫描服务（extreme_reversal_service /
    # convertible_arbitrage_service），此处仅注册元数据供前端适配矩阵 /
    # 对话策略下拉 / MarketRegime.is_strategy_allowed 统一使用（不参与 run_strategy_filter）。
    def _retail_noop(df, params):
        return pd.Series(False, index=df.index)

    @strategy(
        id="extreme_reversal", name="极端反转",
        description="恐慌超跌后的极端情绪反转机会（零售扫描器执行）",
        tags=["反转", "恐慌", "零售"],
        params=[],
        scoring={},
        required_columns=set(),
        needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["恐慌超跌后情绪极端反转，逆向入场"],
        sell_desc=["情绪修复兑现或跌破确认错位离场"],
        frontend=FrontendSpec(icon="🔻", color="#F56C6C", order=17),
        market_regimes=["熊市恐慌", "高波动市"],
        source="retail",
    )
    def extreme_reversal_deco(df, params):
        return _retail_noop(df, params)

    @strategy(
        id="convertible_arbitrage", name="转债套利",
        description="可转债债底保护下的下修/折价套利（零售扫描器执行）",
        tags=["转债", "套利", "零售"],
        params=[],
        scoring={},
        required_columns=set(),
        needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["债底保护 + 下修/折价套利，任何环境适用"],
        sell_desc=["溢价收敛或强赎风险触发离场"],
        frontend=FrontendSpec(icon="💠", color="#909399", order=18),
        market_regimes=["全面适用"],
        source="retail",
    )
    def convertible_arbitrage_deco(df, params):
        return _retail_noop(df, params)

    # 对话 LLM 类/辅助信号类 5 策略（管道B/C）：不进 BUILTIN_STRATEGIES（不自动过滤），
    # 仅注册元数据供前端适配矩阵 / 对话策略下拉展示（执行走对话模板或候选池辅助信号）。
    @strategy(
        id="chan_theory", name="缠论", description="通过分型→笔→线段→中枢定位买卖点（对话分析）",
        tags=["缠论", "结构", "背驰"],
        params=[], scoring={}, required_columns=set(), needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["中枢震荡抓背驰买卖点（一/二/三买）"], sell_desc=["背驰钝化或破中枢离场"],
        frontend=FrontendSpec(icon="🧺", color="#409EFF", order=19),
        market_regimes=["震荡蓄势", "高波动市"], source="template",
    )
    def chan_theory_deco(df, params):
        return _retail_noop(df, params)

    @strategy(
        id="wave_theory", name="波浪理论", description="以5推动+3调整定位浪型与斐波那契目标（对话分析）",
        tags=["波浪", "浪型", "斐波那契"],
        params=[], scoring={}, required_columns=set(), needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["第2浪/第4浪企稳买点，第3浪放量确认"], sell_desc=["浪型破坏或计数失效离场"],
        frontend=FrontendSpec(icon="🌊", color="#409EFF", order=20),
        market_regimes=["牛市强趋势", "高波动市"], source="template",
    )
    def wave_theory_deco(df, params):
        return _retail_noop(df, params)

    @strategy(
        id="event_driven", name="事件驱动", description="围绕业绩/政策/订单等事件判断兑现周期与反映度（辅助信号）",
        tags=["事件", "催化", "兑现"],
        params=[], scoring={}, required_columns=set(), needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["事件确认突破（放量站上MA20）"], sell_desc=["事件证伪或跌破支撑离场"],
        frontend=FrontendSpec(icon="📡", color="#E6A23C", order=21),
        market_regimes=["高波动市", "震荡分化"], source="template",
    )
    def event_driven_deco(df, params):
        return _retail_noop(df, params)

    @strategy(
        id="expectation_repricing", name="预期重估", description="识别硬/软信息预期差与估值重估方向（辅助信号）",
        tags=["预期", "重估", "预期差"],
        params=[], scoring={}, required_columns=set(), needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["20日动量由负转正站上MA20（预期修复）"], sell_desc=["利好不涨/观察点证伪离场"],
        frontend=FrontendSpec(icon="⚖️", color="#E6A23C", order=22),
        market_regimes=["震荡蓄势", "震荡分化"], source="template",
    )
    def expectation_repricing_deco(df, params):
        return _retail_noop(df, params)

    @strategy(
        id="emotion_cycle", name="情绪周期", description="以换手/量能识别情绪阶段（冷淡底→过热顶）（辅助信号）",
        tags=["情绪", "换手", "周期"],
        params=[], scoring={}, required_columns=set(), needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["情绪地量+均线粘合（潜伏）"], sell_desc=["情绪过热+退潮迹象离场"],
        frontend=FrontendSpec(icon="🎭", color="#F56C6C", order=23),
        market_regimes=["高波动市", "熊市恐慌"], source="template",
    )
    def emotion_cycle_deco(df, params):
        return _retail_noop(df, params)

    # 存量策略批量注册（装饰器已注册的 id 跳过，避免覆盖 required_columns 等显式元数据）
    for _s in BUILTIN_STRATEGIES:
        if _registry.get(_s["id"]) is None:
            _registry.register_dict(_s)
except Exception:  # pragma: no cover
    pass


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