"""
共享技术指标计算模块

提供 MA/EMA/MACD/BIAS/ATR/量比/均线粘合度/MA斜率/中阳线判定/慢组压缩度
所有指标均提供 numpy 向量化版本，支持高性能回测使用

参考:
- calc_ma_np: 简单移动平均线
- calc_ema_np: 指数移动平均线
- calc_macd_np: MACD (DIF/DEA/MACD 柱)
- calc_bias_np: 乖离率
- calc_atr_np: Wilder's ATR
- calc_volume_ratio_np: 量比
- calc_ma_slope_np: MA 斜率
- calc_ma_convergence_np: 均线粘合度
- is_zhongyang_np: 中阳线判定
- calc_slow_group_compression_np: GMMA 慢组压缩度
"""

import numpy as np
from typing import List, Optional, Tuple


def calc_ma_np(closes: np.ndarray, period: int) -> np.ndarray:
    """计算简单移动平均线（SMA）

    Args:
        closes: 收盘价数组，shape (n,)
        period: 均线周期

    Returns:
        MA 数组，shape (n,)，前 period-1 个为 0（无意义）
    """
    n = len(closes)
    if n < period:
        return np.zeros(n, dtype=np.float64)

    ma = np.zeros(n, dtype=np.float64)
    cumsum = np.cumsum(closes)
    ma[period - 1] = cumsum[period - 1] / period
    for i in range(period, n):
        ma[i] = ma[i - 1] + (closes[i] - closes[i - period]) / period
    return ma


def calc_ema_np(closes: np.ndarray, period: int) -> np.ndarray:
    """计算指数移动平均线（EMA）

    Args:
        closes: 收盘价数组，shape (n,)
        period: EMA 周期

    Returns:
        EMA 数组，shape (n,)
    """
    n = len(closes)
    if n == 0:
        return np.array([], dtype=np.float64)
    ema = np.zeros(n, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    ema[0] = closes[0]
    for i in range(1, n):
        ema[i] = closes[i] * alpha + ema[i - 1] * (1 - alpha)
    return ema


def calc_macd_np(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算 MACD 指标

    Args:
        closes: 收盘价数组
        fast: 快线周期，默认 12
        slow: 慢线周期，默认 26
        signal: 信号线周期，默认 9

    Returns:
        (dif, dea, hist) 三元组，均为 shape (n,)
        dif: 差离值
        dea: 讯号线
        hist: MACD 柱（dif - dea 的 2 倍，与通达信一致）
    """
    ema_fast = calc_ema_np(closes, fast)
    ema_slow = calc_ema_np(closes, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema_np(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


def calc_bias_np(closes: np.ndarray, ma_arr: np.ndarray) -> np.ndarray:
    """计算乖离率 BIAS = (close - MA) / MA * 100%

    Args:
        closes: 收盘价数组
        ma_arr: 均线数组（通常是 MA60）

    Returns:
        BIAS 数组（百分比形式，如 5.0 表示 +5%）
    """
    with np.errstate(divide='ignore', invalid='ignore'):
        bias = np.where(ma_arr > 0, (closes - ma_arr) / ma_arr * 100.0, 0.0)
    return bias


def calc_atr_np(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14
) -> np.ndarray:
    """计算 Wilder's ATR（平均真实波幅）

    Args:
        highs: 最高价数组
        lows: 最低价数组
        closes: 收盘价数组
        period: ATR 周期，默认 14

    Returns:
        ATR 数组
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=np.float64)

    tr = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )

    atr = np.zeros(n, dtype=np.float64)
    if n < period:
        return atr

    alpha = 1.0 / period
    atr[period - 1] = np.mean(tr[1:period])
    for i in range(period, n):
        atr[i] = atr[i - 1] * (1 - alpha) + tr[i] * alpha
    return atr


def calc_volume_ratio_np(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """计算量比（当日成交量 / 前 period 日平均成交量）

    Args:
        volumes: 成交量数组
        period: 均量周期，默认 20

    Returns:
        量比数组，前 period 个为 0
    """
    n = len(volumes)
    if n < period + 1:
        return np.zeros(n, dtype=np.float64)

    vr = np.zeros(n, dtype=np.float64)
    ma_vol = calc_ma_np(volumes[:-1], period)
    for i in range(period, n):
        avg_vol = ma_vol[i - 1]
        if avg_vol > 0:
            vr[i] = volumes[i] / avg_vol
    return vr


def calc_ma_slope_np(ma_arr: np.ndarray, window: int = 5) -> np.ndarray:
    """计算 MA 斜率（单位周期内的变化率，百分比）

    Args:
        ma_arr: 均线数组
        window: 计算窗口，默认 5

    Returns:
        斜率数组（百分比形式，如 2.0 表示 5 日内上涨 2%）
    """
    n = len(ma_arr)
    slope = np.zeros(n, dtype=np.float64)
    if n <= window:
        return slope
    for i in range(window, n):
        if ma_arr[i - window] > 0:
            slope[i] = (ma_arr[i] - ma_arr[i - window]) / ma_arr[i - window] * 100.0
    return slope


def calc_ma_convergence_np(ma_list: List[np.ndarray]) -> np.ndarray:
    """计算均线粘合度（多条均线之间的最大间距百分比）

    Args:
        ma_list: 多条均线数组的列表，每条 shape 均为 (n,)

    Returns:
        粘合度数组，值越小越粘合，如 2.0 表示最大间距 2%
    """
    n = len(ma_list[0])
    if not ma_list:
        return np.zeros(n, dtype=np.float64)

    stacked = np.stack(ma_list, axis=0)
    max_ma = np.max(stacked, axis=0)
    min_ma = np.min(stacked, axis=0)

    with np.errstate(divide='ignore', invalid='ignore'):
        convergence = np.where(min_ma > 0, (max_ma - min_ma) / min_ma * 100.0, 0.0)
    return convergence


def is_zhongyang_np(
    closes: np.ndarray,
    opens: np.ndarray,
    threshold: float = 0.05
) -> np.ndarray:
    """判断中阳线（实体涨幅 >= 阈值）

    Args:
        closes: 收盘价数组
        opens: 开盘价数组
        threshold: 实体涨幅阈值，默认 0.05（5%）

    Returns:
        布尔数组，True 表示中阳线
    """
    with np.errstate(divide='ignore', invalid='ignore'):
        body_pct = np.where(opens > 0, (closes - opens) / opens, 0.0)
    return body_pct >= threshold


def calc_slow_group_compression_np(
    ema30: np.ndarray,
    ema60: np.ndarray,
    window: int = 60
) -> np.ndarray:
    """计算 GMMA 慢组压缩度（从 60 日高点回落的幅度）

    慢组压缩度 = 1 - (当前慢组带宽 / 60 日内慢组带宽最大值)
    超过 30% 以上则视为 S1 预警信号

    Args:
        ema30: EMA30 数组（慢组上沿近似）
        ema60: EMA60 数组（慢组下沿近似）
        window: 回溯窗口，默认 60

    Returns:
        压缩度数组（0-1，越大压缩越严重），超过 0.3 表示从高点回落 30%+
    """
    n = len(ema30)
    compression = np.zeros(n, dtype=np.float64)
    if n < window:
        return compression

    band_width = np.abs(ema30 - ema60)

    for i in range(window - 1, n):
        start = max(0, i - window + 1)
        max_bw = np.max(band_width[start:i + 1])
        if max_bw > 0:
            compression[i] = 1.0 - (band_width[i] / max_bw)
        else:
            compression[i] = 0.0
    return compression


def calc_fast_slow_separation_np(
    ma13: np.ndarray,
    ma55: np.ndarray
) -> np.ndarray:
    """计算 GMMA 快慢分离度

    快慢分离度 = (快组下沿 - 慢组上沿) / 慢组上沿 × 100%
    - 正值 = 多头结构，越大趋势越强
    - 3-8% = 正常健康区间
    - >15% = 过热，警惕均值回归
    - 转负 = 空头结构形成

    Args:
        ma13: MA13 数组（快组下沿）
        ma55: MA55 数组（慢组上沿）

    Returns:
        分离度百分比数组
    """
    separation = np.zeros_like(ma55, dtype=np.float64)
    valid = ma55 > 0
    separation[valid] = (ma13[valid] - ma55[valid]) / ma55[valid] * 100
    return separation


def calc_strong_bull_duration_np(
    ma5: np.ndarray,
    ma8: np.ndarray,
    ma13: np.ndarray,
    ma55: np.ndarray,
    ma60: np.ndarray,
    ma65: np.ndarray
) -> np.ndarray:
    """计算 GMMA 强多状态持续 K 线数

    强多状态三条件：
    1. 快组多头: MA5 > MA8 > MA13
    2. 慢组多头: MA55 > MA60 > MA65
    3. 快组在慢组上: MA13 > MA55

    每根K线如果是强多状态，持续天数+1；否则重置为0。

    Returns:
        持续天数数组（0表示非强多状态）
    """
    n = len(ma5)
    duration = np.zeros(n, dtype=np.int32)
    count = 0
    for i in range(65, n):
        fast_bull = ma5[i] > ma8[i] > ma13[i]
        slow_bull = ma55[i] > ma60[i] > ma65[i]
        fast_above = ma13[i] > ma55[i]
        if fast_bull and slow_bull and fast_above:
            count += 1
        else:
            count = 0
        duration[i] = count
    return duration


def classify_stock_type(
    market_cap: float, industry: str = "", name: str = "") -> str:
    """判断股票类型（用于 S1 乖离率阈值和风险预警）

    高辨识度龙头: 行业绝对龙头，市值 >= 2000 亿科技股或 >= 5000 亿任何行业
    科技龙头: 科技行业且市值 > 500 亿
    ST股票: 名称包含 ST、*ST、SST、S*ST
    普通股: 其余

    Args:
        market_cap: 总市值（亿元）
        industry: 行业名称
        name: 股票名称

    Returns:
        'leader' | 'tech_leader' | 'st' | 'normal'
    """
    tech_industries = [
        "半导体", "芯片", "电子", "计算机", "软件", "互联网",
        "通信", "5G", "人工智能", "AI", "新能源", "光伏", "锂电",
        "生物医药", "创新药", "医疗"
    ]

    name_upper = (name or "").upper()
    if "ST" in name_upper:
        return "st"

    is_tech = any(t in (industry or "") for t in tech_industries)

    if market_cap >= 2000 and is_tech:
        return "leader"
    if market_cap >= 5000:
        return "leader"
    if market_cap > 500 and is_tech:
        return "tech_leader"
    return "normal"


def get_s1_threshold(stock_type: str) -> float:
    """根据股票类型获取 S1 乖离率阈值（百分比）

    Args:
        stock_type: 'normal' | 'tech_leader' | 'leader' | 'st'

    Returns:
        S1 BIAS 阈值（%），如 30.0 表示 +30%
    """
    thresholds = {
        "normal": 30.0,
        "tech_leader": 65.0,
        "leader": 100.0,
        "st": 20.0
    }
    return thresholds.get(stock_type, 30.0)


def calc_market_trend(
    index_closes: np.ndarray, ma60: np.ndarray, ma20: np.ndarray) -> str:
    """判断大盘趋势（上升/下降/震荡）

    Args:
        index_closes: 指数收盘价数组
        ma60: MA60 数组
        ma20: MA20 数组

    Returns:
        'up' | 'down' | 'neutral'
    """
    if len(index_closes) < 60:
        return "neutral"

    price = index_closes[-1]
    ma60_val = ma60[-1]
    ma20_val = ma20[-1]
    ma60_slope = (ma60[-1] - ma60[-6]) / ma60[-6] * 100 if ma60[-6] > 0 else 0

    if price > ma60_val and ma20_val > ma60_val and ma60_slope > 0:
        return "up"
    elif price < ma60_val and ma20_val < ma60_val and ma60_slope < 0:
        return "down"
    else:
        return "neutral"
