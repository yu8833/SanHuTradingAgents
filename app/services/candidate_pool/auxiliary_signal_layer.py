"""辅助信号层（对齐教材第三章「辅助信号系统」）

对候选池内每只票计算辅助信号，作为三买三卖主信号的「质量确认器」：
辅助信号不独立产生买卖，只对主信号做 确认 / 降权 / 预警，并合成综合分 aux_score(0-100)。

复用三买三卖 `_precompute_indicators` 产出的指标 dict（MA5/8/13/55/60、BIAS、VOL、
MACD、volume_ratio、short_convergence、stock_trend 等），避免重复计算。
已有雏形（抄底 / MACD 背离 / 量价背离）在三买三卖服务中已实现，本层基于同一套 ind
以独立纯函数重写等价逻辑，保持模块解耦、可单测。

输出：
    compute_auxiliary(ind, market_trend) -> {
        "details": { qty_verification, macd, bottom_fishing, washout, dense_break,
                     regime_quadrant },   # 每个子信号: {triggered, level, label, detail}
        "warnings": ["量价背离…", ...],     # 附录B 预警（只预警，不触发买卖）
        "score": 0-100                    # 综合辅助分 aux_score
    }
"""

from __future__ import annotations

from typing import Any

import numpy as np

# 各子信号 level 取值
CONFIRM = "confirm"   # 确认 → 加分
WARN = "warn"         # 预警 → 降权
NEUTRAL = "neutral"   # 中性


def _latest(ind: dict[str, Any], key: str, idx: int, default: float = 0.0):
    """取指标数组中 idx 处的原始值；越界/缺失返回 default。

    多数指标为数值（float 比较），个别为字符串（如 stock_trend），故不强制转 float。
    """
    arr = ind.get(key)
    if arr is None or idx < 0 or idx >= len(arr):
        return default
    return arr[idx]


# ==================== 3.1 量价关系 ====================

def _qty_quadrant(ind: dict[str, Any], idx: int) -> str:
    """量价四象限：价涨量涨 / 价涨量跌 / 价跌量涨 / 价跌量跌。"""
    if idx < 6:
        return "unknown"
    closes = ind["closes"]
    price_up = closes[idx] > closes[idx - 5]
    vol_up = _latest(ind, "volume_ratio", idx, 0.0) >= 1.0
    if price_up and vol_up:
        return "价涨量涨"
    if price_up and not vol_up:
        return "价涨量跌"
    if not price_up and vol_up:
        return "价跌量涨"
    return "价跌量跌"


def _qty_verification(ind: dict[str, Any], idx: int) -> tuple[dict[str, Any], list[str]]:
    """量价关系：确认健康（价涨量涨）或预警（价涨量跌量价背离）。"""
    q = _qty_quadrant(ind, idx)
    warnings: list[str] = []
    # 量价背离：价涨量跌 + 价在 MA60 上方（教材 3.1，警惕减仓）
    diverged = False
    if idx >= 25 and _latest(ind, "closes", idx) > _latest(ind, "ma60", idx):
        closes = ind["closes"]
        volumes = ind["volumes"]
        if closes[idx] > closes[idx - 5]:
            vol_recent = float(np.mean(volumes[idx - 4: idx + 1]))
            vol_earlier = float(np.mean(volumes[idx - 9: idx - 4]))
            if vol_recent < vol_earlier * 0.9:
                diverged = True
                warnings.append("量价背离（价涨量跌 + MA60 上方，警惕减仓）")

    if diverged:
        sig = {"triggered": True, "level": WARN, "label": "量价背离",
               "detail": "价涨量跌且位于 MA60 上方，主力出货嫌疑，主信号降权"}
    elif q == "价涨量涨":
        sig = {"triggered": True, "level": CONFIRM, "label": "量价齐升",
               "detail": "价涨量涨，上涨健康，确认主买入信号"}
    elif q == "价跌量跌":
        sig = {"triggered": True, "level": NEUTRAL, "label": "缩量回调",
               "detail": "价跌量跌，缩量回调，趋势未破坏"}
    else:
        sig = {"triggered": False, "level": NEUTRAL, "label": q,
               "detail": "量价未形成有效确认"}
    return sig, warnings


# ==================== 3.2 MACD 确认 ====================

def _macd_confirm(ind: dict[str, Any], idx: int) -> tuple[dict[str, Any], list[str]]:
    """MACD 确认：金叉强化 B2 / 底背离配合抄底；顶背离提前预警。"""
    warnings: list[str] = []
    if idx < 30:
        return {"triggered": False, "level": NEUTRAL, "label": "数据不足",
                "detail": "MACD 数据不足"}, warnings

    dif = ind["dif"]
    dea = ind["dea"]
    closes = ind["closes"]

    # 金叉：近 3 日 DIF 上穿 DEA
    golden_cross = False
    for i in range(max(1, idx - 2), idx + 1):
        if dif[i] > dea[i] and dif[i - 1] <= dea[i - 1]:
            golden_cross = True
            break

    # 顶背离：价创 20 日新高而 DIF 未新高（常先于 S1 出现）
    def _divergence(window: int = 20) -> str:
        start = max(0, idx - window)
        wc = closes[start: idx + 1]
        wd = dif[start: idx + 1]
        if len(wc) < 10:
            return ""
        price_new_high = float(np.max(wc[-5:])) > float(np.max(wc[:-5]))
        price_new_low = float(np.min(wc[-5:])) < float(np.min(wc[:-5]))
        de_new_high = float(np.max(wd[-5:])) > float(np.max(wd[:-5]))
        de_new_low = float(np.min(wd[-5:])) < float(np.min(wd[:-5]))
        if price_new_high and not de_new_high:
            return "top"
        if price_new_low and not de_new_low:
            return "bottom"
        return ""

    div = _divergence()
    if div == "top":
        warnings.append("MACD 顶背离（价新高而 DIF 不新高，预警见顶）")
        sig = {"triggered": True, "level": WARN, "label": "MACD顶背离",
               "detail": "价格创新高但动能未跟上，S1 前提前预警，持仓降权"}
    elif div == "bottom":
        sig = {"triggered": True, "level": CONFIRM, "label": "MACD底背离",
               "detail": "价格创新低但动能未创新低，配合 B1/抄底确认底部"}
    elif golden_cross:
        sig = {"triggered": True, "level": CONFIRM, "label": "MACD金叉",
               "detail": "DIF 上穿 DEA，强化 B2 突破确认"}
    else:
        sig = {"triggered": False, "level": NEUTRAL, "label": "无明显信号",
               "detail": "MACD 无金叉/背离确认"}
    return sig, warnings


# ==================== 3.3 抄底信号 ====================

def _bottom_fishing(ind: dict[str, Any], idx: int) -> dict[str, Any]:
    """抄底信号：3 天不新低 + 短期均线组(MA5/8/13)粘合向上。"""
    if idx < 20:
        return {"triggered": False, "level": NEUTRAL, "label": "数据不足",
                "detail": "K线长度不足"}
    lows = ind["lows"]
    recent_lows = lows[max(0, idx - 2): idx + 1]
    earlier_lows = lows[max(0, idx - 13): max(0, idx - 2)]
    if len(recent_lows) < 3 or len(earlier_lows) < 5:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "无抄底信号"}
    if float(np.min(recent_lows)) <= float(np.min(earlier_lows)):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "仍在创新低，底部未确认"}
    sc = _latest(ind, "short_convergence", idx, 99.0)
    if sc > 2.0:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "短期均线未粘合"}
    ma5_rising = idx >= 3 and ind["ma5"][idx] > ind["ma5"][idx - 1]
    ma8_rising = idx >= 3 and ind["ma8"][idx] > ind["ma8"][idx - 1]
    if not (ma5_rising and ma8_rising):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "短期均线未向上拐头"}
    return {"triggered": True, "level": CONFIRM, "label": "抄底形态",
            "detail": "3 天不新低 + 短期均线粘合向上，配合 B1 左侧确认底部"}


# ==================== 3.4 上影洗筹模型 ====================

def _washout(ind: dict[str, Any], idx: int) -> dict[str, Any]:
    """上影洗筹：30 日内涨停 → 长上影(≥5%) → 横盘(日振幅<5% 持续≥5 日) →
    短期均线粘合(<2%)拐头 → 放量中阳突破。"""
    if idx < 40:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "K线长度不足"}
    closes = ind["closes"]
    opens = ind["opens"]
    highs = ind["highs"]
    lows = ind["lows"]
    pct = ind["pct_chgs"]

    start = max(0, idx - 30)
    # 1) 30 日内曾涨停（≥9.8%）
    if not bool(np.any(pct[start: idx + 1] >= 9.8)):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "30 日内无涨停，非强势股洗筹"}
    # 2) 30 日内曾出现长上影（上影 ≥ 5%）
    upper = (highs - np.maximum(opens, closes)) / np.maximum(closes, 1e-9)
    if not bool(np.any(upper[start: idx + 1] >= 0.05)):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "无长上影洗盘痕迹"}
    # 3) 近期横盘：近 5 日振幅 < 5%
    amp = (highs - lows) / np.maximum(closes, 1e-9)
    recent5 = amp[max(0, idx - 4): idx + 1]
    if len(recent5) < 3 or float(np.max(recent5)) >= 0.05:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "未见横盘蓄势"}
    # 4) 短期均线粘合(<2%) 且拐头向上
    sc = _latest(ind, "short_convergence", idx, 99.0)
    if sc > 2.0 or idx < 3:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "短期均线未粘合向上"}
    if ind["ma5"][idx] <= ind["ma5"][idx - 1]:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "MA5 未向上拐头"}
    # 5) 放量中阳突破：当日放量且阳线实体 ≥ 5%
    vol_up = _latest(ind, "volume_ratio", idx, 0.0) >= 1.5
    body = (closes[idx] - opens[idx]) / max(opens[idx], 1e-9)
    if not (vol_up and body >= 0.05):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "未见放量中阳突破"}
    return {"triggered": True, "level": CONFIRM, "label": "上影洗筹",
            "detail": "涨停后长上影洗盘，横盘蓄势后放量突破，为 B2/B3 增强确认"}


# ==================== 3.5 密集成交突破模型 ====================

def _dense_break(ind: dict[str, Any], idx: int) -> dict[str, Any]:
    """密集成交突破：30 日内巨量(60 日最高量)换手 → 窄幅震荡均线上移 → 放量中阳突破中期均线。"""
    if idx < 60:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "K线长度不足"}
    volumes = ind["volumes"]
    closes = ind["closes"]
    opens = ind["opens"]
    start30 = max(0, idx - 30)
    start60 = max(0, idx - 60)
    # 1) 30 日内出现接近 60 日最高量（巨量换手）
    max_vol_60 = float(np.max(volumes[start60: idx + 1]))
    if max_vol_60 <= 0:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "无量能数据"}
    peak_vol_30 = float(np.max(volumes[start30: idx + 1]))
    if peak_vol_30 < max_vol_60 * 0.9:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "30 日内无巨量换手"}
    # 2) 窄幅震荡：近 5 日振幅收敛
    highs = ind["highs"]
    lows = ind["lows"]
    amp = (highs - lows) / np.maximum(closes, 1e-9)
    recent5 = amp[max(0, idx - 4): idx + 1]
    if len(recent5) < 3 or float(np.max(recent5)) >= 0.06:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "未见窄幅震荡"}
    # 3) 中期均线（MA20）上行
    if idx < 20 or ind["ma20"][idx] < ind["ma20"][idx - 3]:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "中期均线未上行"}
    # 4) 放量中阳突破中期均线 MA20
    vol_up = _latest(ind, "volume_ratio", idx, 0.0) >= 1.5
    body = (closes[idx] - opens[idx]) / max(opens[idx], 1e-9)
    if closes[idx] <= ind["ma20"][idx]:
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "未站上 MA20"}
    if not (vol_up and body >= 0.03):
        return {"triggered": False, "level": NEUTRAL, "label": "无",
                "detail": "未见放量中阳突破"}
    return {"triggered": True, "level": CONFIRM, "label": "密集突破",
            "detail": "巨量换手后筹码充分交换，放量突破 MA20，二波启动，强化 B2 突破"}


# ==================== 3.6 大盘-个股联动 ====================

def _regime_quadrant(market_trend: str, ind: dict[str, Any], idx: int) -> tuple[dict[str, Any], list[str]]:
    """大盘趋势 × 个股趋势 → 联动象限（影响建议仓位与信号确认）。"""
    warnings: list[str] = []
    stock_trend = str(_latest(ind, "stock_trend", idx, "neutral"))
    m = market_trend or "neutral"

    quadrant = f"{m}盘·{stock_trend}"
    if m == "up" and stock_trend == "up":
        level, label, detail = CONFIRM, "大盘↑个股↑", "顺风共振，主信号确认，仓位可至 80-100%"
    elif m == "down" and stock_trend == "down":
        level, label, detail = WARN, "大盘↓个股↓", "双杀逆风，主信号降权，仓位 0-30%"
        warnings.append("大盘个股双下跌，严格控制仓位")
    elif m == "down" and stock_trend == "up":
        level, label, detail = NEUTRAL, "大盘↓个股↑", "当弱不弱，个股或领涨，关注但不追高"
    elif m == "up" and stock_trend == "down":
        level, label, detail = WARN, "大盘↑个股↓", "当强不强，个股或有隐患，预警"
        warnings.append("当强不强（大盘涨个股跌），个股可能有隐患")
    elif m == "neutral" and stock_trend == "up":
        level, label, detail = CONFIRM, "大盘平·个股↑", "个股独立走强，可正常参与"
    elif m == "neutral" and stock_trend == "down":
        level, label, detail = WARN, "大盘平·个股↓", "个股弱势，主信号降权"
    else:
        level, label, detail = NEUTRAL, "震荡观望", "大盘与个股均无明确方向"
    return {"triggered": level != NEUTRAL, "level": level, "label": label,
            "detail": detail}, warnings


# ==================== 综合 ====================

def compute_auxiliary(ind: dict[str, Any], market_trend: str = "neutral",
                      idx: int | None = None) -> dict[str, Any]:
    """对单只股票计算教材第三章辅助信号，返回子信号明细 + 预警 + 综合分 aux_score。

    Args:
        ind: 三买三卖 `_precompute_indicators` 产出的指标 dict。
        market_trend: 大盘趋势，'up' / 'neutral' / 'down'。
        idx: 目标索引，默认取最新一根（ind['n']-1）。
    """
    if idx is None:
        idx = int(ind.get("n", 0)) - 1
    if idx < 0:
        idx = 0

    qty, warn1 = _qty_verification(ind, idx)
    macd, warn2 = _macd_confirm(ind, idx)
    bottom = _bottom_fishing(ind, idx)
    washout = _washout(ind, idx)
    dense = _dense_break(ind, idx)
    regime, warn3 = _regime_quadrant(market_trend, ind, idx)

    details = {
        "qty_verification": qty,
        "macd": macd,
        "bottom_fishing": bottom,
        "washout": washout,
        "dense_break": dense,
        "regime_quadrant": regime,
    }
    warnings = list(dict.fromkeys(warn1 + warn2 + warn3))

    # ---- 综合分 aux_score（0-100）：基准 50 + 确认加分 - 预警降权 ----
    score = 50.0
    for sig in details.values():
        if sig["level"] == CONFIRM:
            score += 10.0
        elif sig["level"] == WARN:
            score -= 12.0
    # 辅助确认里已含在大盘联动中，避免重复，仅做微调
    score = max(0.0, min(100.0, score))

    return {
        "details": details,
        "warnings": warnings,
        "score": round(score, 1),
    }