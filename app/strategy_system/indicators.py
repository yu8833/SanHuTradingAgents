"""技术指标计算 — pandas 实现（移植自 tickflow-stock-panel 的 indicators/pipeline.py）。

输入 DataFrame 需包含列: symbol, date, open, high, low, close, volume（可选 amount）。
每只股票独立计算（groupby symbol），输出与参考实现语义一致的指标列与信号列。
"""
from __future__ import annotations

import logging

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


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """从 OHLCV 计算全套技术指标。输入含 symbol 列，按 symbol 分组计算。"""
    if df is None or df.empty:
        return df

    required = ["symbol", "date", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"缺少必要列: {missing}")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
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

    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
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

    return pd.concat([df, out], axis=1)


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """从指标列计算原子信号布尔列。保持原索引与既有列不变，仅追加信号列。"""
    if df is None or df.empty:
        return df

    df = df.copy()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    symbols = df["symbol"]

    def _shift(col):
        return col.groupby(symbols, sort=False).shift(1)

    s = pd.DataFrame(index=df.index)
    s["signal_ma_golden_5_20"] = (df["ma5"] > df["ma20"]) & (_shift(df["ma5"]) <= _shift(df["ma20"]))
    s["signal_ma_dead_5_20"] = (df["ma5"] < df["ma20"]) & (_shift(df["ma5"]) >= _shift(df["ma20"]))
    s["signal_ma_golden_20_60"] = (df["ma20"] > df["ma60"]) & (_shift(df["ma20"]) <= _shift(df["ma60"]))
    s["signal_macd_golden"] = (df["macd_dif"] > df["macd_dea"]) & (_shift(df["macd_dif"]) <= _shift(df["macd_dea"]))
    s["signal_macd_dead"] = (df["macd_dif"] < df["macd_dea"]) & (_shift(df["macd_dif"]) >= _shift(df["macd_dea"]))
    s["signal_ma20_breakout"] = (df["close"] > df["ma20"]) & (_shift(df["close"]) <= _shift(df["ma20"]))
    s["signal_ma20_breakdown"] = (df["close"] < df["ma20"]) & (_shift(df["close"]) >= _shift(df["ma20"]))
    s["signal_ma5_breakout"] = (df["close"] > df["ma5"]) & (_shift(df["close"]) <= _shift(df["ma5"]))
    s["signal_ma5_breakdown"] = (df["close"] < df["ma5"]) & (_shift(df["close"]) >= _shift(df["ma5"]))
    s["signal_ma10_breakout"] = (df["close"] > df["ma10"]) & (_shift(df["close"]) <= _shift(df["ma10"]))
    s["signal_ma10_breakdown"] = (df["close"] < df["ma10"]) & (_shift(df["close"]) >= _shift(df["ma10"]))
    s["signal_n_day_high"] = df["close"] >= df["high_60d"]
    s["signal_n_day_low"] = df["close"] <= df["low_60d"]
    s["signal_boll_breakout_upper"] = df["close"] > df["boll_upper"]
    s["signal_boll_breakdown_lower"] = df["close"] < df["boll_lower"]
    s["signal_volume_surge"] = df["vol_ratio_5d"] >= 2.0

    return pd.concat([df, s], axis=1)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """一站式计算：指标 + 信号。"""
    df = compute_indicators(df)
    df = compute_signals(df)
    return df