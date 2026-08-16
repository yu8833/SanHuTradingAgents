"""技术指标计算 — pandas 实现（移植自 tickflow-stock-panel 的 indicators/pipeline.py）。

输入 DataFrame 需包含列: symbol, date, open, high, low, close, volume（可选 amount）。
每只股票独立计算（groupby symbol），输出与参考实现语义一致的指标列与信号列。
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 指标列（与参考 ENRICHED_COLUMNS 对齐）
INDICATOR_COLUMNS = [
    "prev_close", "change_pct", "change_amount", "amplitude",
    "ma5", "ma10", "ma20", "ma30", "ma60",
    "ema5", "ema10", "ema20", "ema30", "ema60",
    "macd_dif", "macd_dea", "macd_hist",
    "boll_upper", "boll_lower",
    "kdj_k", "kdj_d", "kdj_j",
    "atr_14",
    "vol_ma5", "vol_ma10", "vol_ratio_5d",
    "high_60d", "low_60d",
    "momentum_5d", "momentum_10d", "momentum_20d", "momentum_30d", "momentum_60d",
    "annual_vol_20d",
    "rsi_6", "rsi_14", "rsi_24",
    "obv", "obv_ma5",
]

SIGNAL_COLUMNS = [
    "signal_ma_golden_5_20", "signal_ma_dead_5_20", "signal_ma_golden_20_60",
    "signal_macd_golden", "signal_macd_dead",
    "signal_ma20_breakout", "signal_ma20_breakdown",
    "signal_ma5_breakout", "signal_ma5_breakdown",
    "signal_ma10_breakout", "signal_ma10_breakdown",
    "signal_n_day_high", "signal_n_day_low",
    "signal_boll_breakout_upper", "signal_boll_breakdown_lower",
    "signal_volume_surge",
]

# 信号 → 其依赖的指标列（用于回测"按需计算"：只保留策略所需信号对应的指标列）。
# close 为基础列，始终存在，故不列入。
SIGNAL_INDICATOR_DEPS: dict[str, set[str]] = {
    "signal_ma_golden_5_20": {"ma5", "ma20"},
    "signal_ma_dead_5_20": {"ma5", "ma20"},
    "signal_ma_golden_20_60": {"ma20", "ma60"},
    "signal_macd_golden": {"macd_dif", "macd_dea"},
    "signal_macd_dead": {"macd_dif", "macd_dea"},
    "signal_ma20_breakout": {"ma20"},
    "signal_ma20_breakdown": {"ma20"},
    "signal_ma5_breakout": {"ma5"},
    "signal_ma5_breakdown": {"ma5"},
    "signal_ma10_breakout": {"ma10"},
    "signal_ma10_breakdown": {"ma10"},
    "signal_n_day_high": {"high_60d"},
    "signal_n_day_low": {"low_60d"},
    "signal_boll_breakout_upper": {"boll_upper"},
    "signal_boll_breakdown_lower": {"boll_lower"},
    "signal_volume_surge": {"vol_ratio_5d"},
}


def _ema_alpha(span: int) -> float:
    return 2.0 / (span + 1)


def _compute_symbol_indicators(g: pd.DataFrame) -> pd.DataFrame:
    """对单只股票的时间序列计算全部指标。g 需按 date 升序。"""
    g = g.sort_values("date")

    close = g["close"]
    high = g["high"]
    low = g["low"]
    volume = g["volume"]

    prev_close = close.shift(1)

    out = pd.DataFrame(index=g.index)

    # 基础
    out["prev_close"] = prev_close
    out["change_pct"] = close / prev_close - 1
    out["change_amount"] = close - prev_close
    amp = (high - low) / prev_close
    out["amplitude"] = amp.where(prev_close > 0)

    # MA
    for n in (5, 10, 20, 30, 60):
        out[f"ma{n}"] = close.rolling(n).mean()

    # EMA
    for n in (5, 10, 20, 30, 60):
        out[f"ema{n}"] = close.ewm(alpha=_ema_alpha(n), adjust=False).mean()

    # MACD
    ema12 = close.ewm(alpha=_ema_alpha(12), adjust=False).mean()
    ema26 = close.ewm(alpha=_ema_alpha(26), adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(alpha=_ema_alpha(9), adjust=False).mean()
    out["macd_dif"] = dif
    out["macd_dea"] = dea
    out["macd_hist"] = (dif - dea) * 2

    # BOLL
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    out["boll_upper"] = ma20 + 2 * std20
    out["boll_lower"] = ma20 - 2 * std20

    # KDJ
    ln = low.rolling(9).min()
    hn = high.rolling(9).max()
    rsv = 100 * (close - ln) / (hn - ln).replace(0, np.nan)
    k = rsv.ewm(alpha=1.0 / 3, adjust=False).mean()
    d = k.ewm(alpha=1.0 / 3, adjust=False).mean()
    out["kdj_k"] = k
    out["kdj_d"] = d
    out["kdj_j"] = 3 * k - 2 * d

    # ATR
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["atr_14"] = tr.ewm(alpha=1.0 / 14, adjust=False).mean()

    # 量价
    out["vol_ma5"] = volume.rolling(5).mean()
    out["vol_ma10"] = volume.rolling(10).mean()
    prev_vol_ma5 = volume.shift(1).rolling(5).mean()
    out["vol_ratio_5d"] = volume / prev_vol_ma5

    # 极值
    out["high_60d"] = close.rolling(60).max()
    out["low_60d"] = close.rolling(60).min()

    # 动量
    for n in (5, 10, 20, 30, 60):
        out[f"momentum_{n}d"] = close / close.shift(n) - 1

    # 年化波动率
    daily_pct = close.pct_change()
    out["annual_vol_20d"] = daily_pct.rolling(20).std() * np.sqrt(252)

    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    for n in (6, 14, 24):
        avg_gain = gain.ewm(alpha=1.0 / n, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / n, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        out[f"rsi_{n}"] = 100 - 100 / (1 + rs)

    # OBV: 上涨日累加成交量，下跌日累减，平盘不变
    direction = np.sign(close.diff())
    obv = (direction * volume).cumsum()
    out["obv"] = obv
    out["obv_ma5"] = obv.rolling(5).mean()

    return out


def _group_rolling(col, symbols, window, agg: str, min_periods=None):
    """按 symbol 分组做滚动计算，返回与输入对齐的 Series。

    用 groupby.rolling 在 C 层面完成，避免逐股票 Python 循环。
    """
    group_rolling = col.groupby(symbols, sort=False).rolling(
        window, min_periods=min_periods
    )
    return getattr(group_rolling, agg)().reset_index(level=0, drop=True)


def _group_ewm(col, symbols, alpha):
    """按 symbol 分组做指数加权平均，返回与输入对齐的 Series。"""
    return (
        col.groupby(symbols, sort=False)
        .ewm(alpha=alpha, adjust=False)
        .mean()
        .reset_index(level=0, drop=True)
    )


def compute_indicators(
    df: pd.DataFrame,
    progress_cb: Callable[[float, str], None] | None = None,
    keep_columns: set[str] | None = None,
) -> pd.DataFrame:
    """从 OHLCV 计算技术指标。输入含 symbol 列，按 symbol 分组计算。

    内存优化：全市场面板（数千只股票 × 数百交易日）若一次性对整个面板做
    groupby 滚动/EWM，会产生大量与全面板等长的中间数组，峰值内存可达数 GB，
    在内存受限的容器中易触发 OOM。因此按股票分批计算，每批处理完即拼接并
    释放中间数组，把峰值内存限制在「单批规模」，与市场股票总数解耦。

    keep_columns（可选）：回测对单策略通常只用少数指标列，传此集合可让本函数
    只保留命中列（含全部基础列），丢掉其余指标列。这样分批累积的 out 只携带
    所需列，全市场长区间面板的内存占用大幅下降，避免 3 年期回测触发容器 OOM。
    默认 None 表示保留全部指标列（筛选/分析等场景不变）。

    progress_cb(p, msg) 可选：p 在 [0,1] 内按分批进度回调，供长时全市场回测
    上报进度，避免进度条长时间停留在 0% 造成"卡死"假象。
    """
    if df is None or df.empty:
        return df

    required = ["symbol", "date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必要列: {missing}")

    df = df.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)

    def _keep(result: pd.DataFrame) -> pd.DataFrame:
        if not keep_columns:
            return result
        base = [c for c in df.columns if c in result.columns]
        # 仅追加尚未在 base 中的命中列，避免 keep_columns 里同时含指标与其信号
        # 依赖（如 ma5 与 signal_ma5_breakout）时重复选中同一列，产生重复列
        keep = [c for c in keep_columns if c in result.columns and c not in base]
        return result[base + keep]

    symbols = df["symbol"]
    if len(symbols) <= _INDICATOR_CHUNK_SYMBOLS:
        return _keep(_concat_indicators(df))

    # 分批：按 symbol 编码切块，每块最多 _INDICATOR_CHUNK_SYMBOLS 只股票，
    # 每块独立计算后拼接，避免全量中间数组撑爆内存。
    # 注意：必须按“固定股票数”切块，而非按 symbol 变更处切块——若按 symbol 切，
    # 每只股票单独成为一块（数千块），每块都要重新做十余次 groupby 滚动/EWM，
    # 固定开销被放大数千倍，导致全市场计算从十几秒退化到数百秒（bug-023）。
    codes, _ = pd.factorize(symbols)
    chunk_id = codes // _INDICATOR_CHUNK_SYMBOLS
    rows_by_chunk = df.groupby(chunk_id, sort=False).indices
    n = len(rows_by_chunk)
    out = []
    for i, idx in enumerate(rows_by_chunk.values()):
        if progress_cb:
            progress_cb((i + 1) / n, f"正在计算技术指标（{i + 1}/{n} 批）…")
        out.append(_keep(_concat_indicators(df.iloc[idx])))
    return pd.concat(out, axis=0, ignore_index=True)


# 单批最多处理的股票数：控制中间数组的峰值内存（每批约 300 只 × 交易日）
_INDICATOR_CHUNK_SYMBOLS = 300


def _concat_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """对单批 DataFrame 计算全部技术指标并返回（分批计算的核心逻辑）。"""
    symbols = df["symbol"]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    prev_close = close.groupby(symbols, sort=False).shift(1)

    out = pd.DataFrame(index=df.index)
    out["prev_close"] = prev_close
    out["change_pct"] = close / prev_close - 1
    out["change_amount"] = close - prev_close
    amp = (high - low) / prev_close
    out["amplitude"] = amp.where(prev_close > 0)

    for n in (5, 10, 20, 30, 60):
        out[f"ma{n}"] = _group_rolling(close, symbols, n, "mean")
    for n in (5, 10, 20, 30, 60):
        out[f"ema{n}"] = _group_ewm(close, symbols, _ema_alpha(n))

    ema12 = _group_ewm(close, symbols, _ema_alpha(12))
    ema26 = _group_ewm(close, symbols, _ema_alpha(26))
    dif = ema12 - ema26
    dea = _group_ewm(dif, symbols, _ema_alpha(9))
    out["macd_dif"] = dif
    out["macd_dea"] = dea
    out["macd_hist"] = (dif - dea) * 2

    ma20 = _group_rolling(close, symbols, 20, "mean")
    std20 = _group_rolling(close, symbols, 20, "std")
    out["boll_upper"] = ma20 + 2 * std20
    out["boll_lower"] = ma20 - 2 * std20

    ln = _group_rolling(low, symbols, 9, "min")
    hn = _group_rolling(high, symbols, 9, "max")
    rsv = 100 * (close - ln) / (hn - ln).replace(0, np.nan)
    k = _group_ewm(rsv, symbols, 1.0 / 3)
    d = _group_ewm(k, symbols, 1.0 / 3)
    out["kdj_k"] = k
    out["kdj_d"] = d
    out["kdj_j"] = 3 * k - 2 * d

    tr = pd.Series(
        np.maximum.reduce(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()]
        ),
        index=df.index,
    )
    out["atr_14"] = _group_ewm(tr, symbols, 1.0 / 14)

    out["vol_ma5"] = _group_rolling(volume, symbols, 5, "mean")
    out["vol_ma10"] = _group_rolling(volume, symbols, 10, "mean")
    prev_vol_ma5 = _group_rolling(
        volume.groupby(symbols, sort=False).shift(1), symbols, 5, "mean"
    )
    out["vol_ratio_5d"] = volume / prev_vol_ma5

    out["high_60d"] = _group_rolling(close, symbols, 60, "max")
    out["low_60d"] = _group_rolling(close, symbols, 60, "min")

    for n in (5, 10, 20, 30, 60):
        out[f"momentum_{n}d"] = close / close.groupby(symbols, sort=False).shift(n) - 1

    daily_pct = close.groupby(symbols, sort=False).pct_change()
    out["annual_vol_20d"] = _group_rolling(daily_pct, symbols, 20, "std") * np.sqrt(252)

    delta = close.groupby(symbols, sort=False).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    for n in (6, 14, 24):
        avg_gain = _group_ewm(gain, symbols, 1.0 / n)
        avg_loss = _group_ewm(loss, symbols, 1.0 / n)
        rs = avg_gain / avg_loss.replace(0, np.nan)
        out[f"rsi_{n}"] = 100 - 100 / (1 + rs)

    # OBV: 上涨日累加成交量，下跌日累减，平盘不变
    direction = close.groupby(symbols, sort=False).diff()
    direction = np.sign(direction)
    obv = (direction * volume).groupby(symbols, sort=False).cumsum()
    out["obv"] = obv
    out["obv_ma5"] = _group_rolling(obv, symbols, 5, "mean")

    # 全市场 407 万行 × 60 列面板在 8GB 容器中会触发 OOM，将 float64 指标列
    # 统一降为 float32（精度对信号判定足够，内存减半）
    out = out.astype({c: "float32" for c in out.columns if out[c].dtype == "float64"})
    return pd.concat([df, out], axis=1)


def compute_signals(
    df: pd.DataFrame,
    progress_cb: Callable[[float, str], None] | None = None,
    keep_columns: set[str] | None = None,
) -> pd.DataFrame:
    """从指标列计算原子信号布尔列。保持原索引与既有列不变，仅追加信号列。

    内存优化：与 compute_indicators 一致，按股票分批计算以控制峰值内存。
    keep_columns（可选）：只保留命中的信号列（含全部既有列），丢弃其余信号列，
    与 compute_indicators 的 keep_columns 配合，压缩回测面板内存占用。
    progress_cb 同 compute_indicators，按分批上报进度。
    """
    if df is None or df.empty:
        return df

    df = df.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)

    def _keep(result: pd.DataFrame) -> pd.DataFrame:
        if not keep_columns:
            return result
        base = [c for c in df.columns if c in result.columns]
        # 仅追加尚未在 base 中的命中列（keep_columns 含指标列时避免重复选中）
        keep = [c for c in keep_columns if c in result.columns and c not in base]
        return result[base + keep]

    symbols = df["symbol"]
    if len(symbols) <= _INDICATOR_CHUNK_SYMBOLS:
        return _keep(_concat_signals(df))

    # 分批：按 symbol 编码切块，每块最多 _INDICATOR_CHUNK_SYMBOLS 只股票。
    # 必须按“固定股票数”切块而非按 symbol 变更处切块，否则每只股票单独成块，
    # 信号阶段十余次 groupby.shift 的固定开销被放大数千倍（bug-022）。
    codes, _ = pd.factorize(symbols)
    chunk_id = codes // _INDICATOR_CHUNK_SYMBOLS
    rows_by_chunk = df.groupby(chunk_id, sort=False).indices
    n = len(rows_by_chunk)
    out = []
    for i, idx in enumerate(rows_by_chunk.values()):
        if progress_cb:
            progress_cb((i + 1) / n, f"正在计算信号（{i + 1}/{n} 批）…")
        out.append(_keep(_concat_signals(df.iloc[idx])))
    return pd.concat(out, axis=0, ignore_index=True)


def _concat_signals(df: pd.DataFrame) -> pd.DataFrame:
    """对单批 DataFrame 计算原子信号布尔列（分批计算的核心逻辑）。

    仅计算依赖列均存在的信号：配合 compute_indicators 的 keep_columns 按需计算，
    某些信号依赖的指标列（如 ma20/ma60）未保留时自动跳过，避免 KeyError。
    """
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    symbols = df["symbol"]

    def _shift(col):
        return col.groupby(symbols, sort=False).shift(1)

    s = pd.DataFrame(index=df.index)
    # 信号 → 其实际访问的列；仅当这些列全部存在时才计算该信号
    _signal_deps = {
        "signal_ma_golden_5_20": {"ma5", "ma20"},
        "signal_ma_dead_5_20": {"ma5", "ma20"},
        "signal_ma_golden_20_60": {"ma20", "ma60"},
        "signal_macd_golden": {"macd_dif", "macd_dea"},
        "signal_macd_dead": {"macd_dif", "macd_dea"},
        "signal_ma20_breakout": {"close", "ma20"},
        "signal_ma20_breakdown": {"close", "ma20"},
        "signal_ma5_breakout": {"close", "ma5"},
        "signal_ma5_breakdown": {"close", "ma5"},
        "signal_ma10_breakout": {"close", "ma10"},
        "signal_ma10_breakdown": {"close", "ma10"},
        "signal_n_day_high": {"close", "high_60d"},
        "signal_n_day_low": {"close", "low_60d"},
        "signal_boll_breakout_upper": {"close", "boll_upper"},
        "signal_boll_breakdown_lower": {"close", "boll_lower"},
        "signal_volume_surge": {"vol_ratio_5d"},
    }
    available = set(df.columns)
    computable = {name for name, deps in _signal_deps.items() if deps <= available}

    if "signal_ma_golden_5_20" in computable:
        s["signal_ma_golden_5_20"] = (df["ma5"] > df["ma20"]) & (_shift(df["ma5"]) <= _shift(df["ma20"]))
    if "signal_ma_dead_5_20" in computable:
        s["signal_ma_dead_5_20"] = (df["ma5"] < df["ma20"]) & (_shift(df["ma5"]) >= _shift(df["ma20"]))
    if "signal_ma_golden_20_60" in computable:
        s["signal_ma_golden_20_60"] = (df["ma20"] > df["ma60"]) & (_shift(df["ma20"]) <= _shift(df["ma60"]))
    if "signal_macd_golden" in computable:
        s["signal_macd_golden"] = (df["macd_dif"] > df["macd_dea"]) & (_shift(df["macd_dif"]) <= _shift(df["macd_dea"]))
    if "signal_macd_dead" in computable:
        s["signal_macd_dead"] = (df["macd_dif"] < df["macd_dea"]) & (_shift(df["macd_dif"]) >= _shift(df["macd_dea"]))
    if "signal_ma20_breakout" in computable:
        s["signal_ma20_breakout"] = (df["close"] > df["ma20"]) & (_shift(df["close"]) <= _shift(df["ma20"]))
    if "signal_ma20_breakdown" in computable:
        s["signal_ma20_breakdown"] = (df["close"] < df["ma20"]) & (_shift(df["close"]) >= _shift(df["ma20"]))
    if "signal_ma5_breakout" in computable:
        s["signal_ma5_breakout"] = (df["close"] > df["ma5"]) & (_shift(df["close"]) <= _shift(df["ma5"]))
    if "signal_ma5_breakdown" in computable:
        s["signal_ma5_breakdown"] = (df["close"] < df["ma5"]) & (_shift(df["close"]) >= _shift(df["ma5"]))
    if "signal_ma10_breakout" in computable:
        s["signal_ma10_breakout"] = (df["close"] > df["ma10"]) & (_shift(df["close"]) <= _shift(df["ma10"]))
    if "signal_ma10_breakdown" in computable:
        s["signal_ma10_breakdown"] = (df["close"] < df["ma10"]) & (_shift(df["close"]) >= _shift(df["ma10"]))
    if "signal_n_day_high" in computable:
        s["signal_n_day_high"] = df["close"] >= df["high_60d"]
    if "signal_n_day_low" in computable:
        s["signal_n_day_low"] = df["close"] <= df["low_60d"]
    if "signal_boll_breakout_upper" in computable:
        s["signal_boll_breakout_upper"] = df["close"] > df["boll_upper"]
    if "signal_boll_breakdown_lower" in computable:
        s["signal_boll_breakdown_lower"] = df["close"] < df["boll_lower"]
    if "signal_volume_surge" in computable:
        s["signal_volume_surge"] = df["vol_ratio_5d"] >= 2.0

    return pd.concat([df, s], axis=1)


def compute_all(
    df: pd.DataFrame,
    progress_cb: Callable[[float, str], None] | None = None,
    keep_columns: set[str] | None = None,
) -> pd.DataFrame:
    """一站式计算：指标 + 信号。

    progress_cb(p, msg) 可选：p 在 [0,1] 内，指标阶段占 [0, 0.7]，信号阶段占
    [0.7, 1.0]，供回测/筛选在长时全市场计算时上报进度。
    keep_columns（可选）：只计算并保留命中的指标/信号列，压缩回测面板内存。
    """
    sub = progress_cb if progress_cb else None

    def _indic(p: float, msg: str) -> None:
        if sub:
            sub(0.0 + 0.7 * min(1.0, max(0.0, float(p))), msg)

    def _signal(p: float, msg: str) -> None:
        if sub:
            sub(0.7 + 0.3 * min(1.0, max(0.0, float(p))), msg)

    df = compute_indicators(df, progress_cb=_indic if sub else None, keep_columns=keep_columns)
    df = compute_signals(df, progress_cb=_signal if sub else None, keep_columns=keep_columns)
    return df