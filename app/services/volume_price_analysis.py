"""单股量价分析服务 — 五步分析法。

从量和价两个维度对单只股票进行逐步分析：
1. 位置判断：依据 60 日高低点定位 高位/中位/低位
2. 趋势判断：收盘价相对 MA5/MA20/MA60 的位置判断多头/空头/震荡，并用 OBV 能量潮辅助验证（OBV 背离提示趋势反转）
3. 量能活跃度：量比/5日均量 vs 10日均量 等成交活跃度
4. 量价象限：近 5 日量价关系归类到四象限（价涨量增/价涨量缩/价跌量增/价跌量缩）
5. 关键位量能分析：在 60 日高低点、MA20 等关键位置的成交量表现

计算量极小（单股 ~90 行），复用 indicators.compute_all 计算指标，不依赖全市场面板。
"""
from __future__ import annotations
from app.utils.timezone import now_tz

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from app.strategy_system import data_adapter
from app.strategy_system.indicators import compute_all

logger = logging.getLogger(__name__)

# 加载历史天数：需覆盖 MA60 + 量比5日 + OBV warmup
_LOOKBACK_DAYS = 90


async def analyze_volume_price(db, symbol: str) -> dict[str, Any]:
    """对单只股票执行五步量价分析（异步包装，内部走 to_thread）。

    Args:
        db: MongoDB 数据库对象（同步 PyMongo Database）
        symbol: 6 位股票代码（如 "000001"）

    Returns:
        包含六个步骤分析结果和最新行情摘要的字典。
    """
    import asyncio
    return await asyncio.to_thread(_analyze_volume_price_sync, db, symbol)


def _analyze_volume_price_sync(db, symbol: str) -> dict[str, Any]:
    """量价分析同步实现。"""
    today = now_tz()
    start_dt = (today - timedelta(days=_LOOKBACK_DAYS * 2)).strftime("%Y-%m-%d")
    end_dt = today.strftime("%Y-%m-%d")

    df = data_adapter.load_symbol_history(db, symbol, start_dt, end_dt)
    if df is None or df.empty:
        return {"success": False, "message": f"无 {symbol} 历史行情数据"}

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # 计算指标（含 OBV）
    df = compute_all(df)
    if df.empty or len(df) < 10:
        return {"success": False, "message": f"{symbol} 数据不足，无法分析"}

    latest = df.iloc[-1]
    latest_date = latest["date"]

    steps = [
        _step1_position(df, latest),
        _step2_trend(df, latest),
        _step3_volume(df, latest),
        _step4_quadrant(df),
        _step5_key_level_volume(df, latest),
    ]

    result: dict[str, Any] = {
        "success": True,
        "symbol": symbol,
        "date": latest_date.strftime("%Y-%m-%d") if hasattr(latest_date, "strftime") else str(latest_date)[:10],
        "close": _safe_float(latest["close"]),
        "steps": steps,
        "overall": _build_overall(steps, _safe_float(latest["close"])),
        "series": _build_series(df),
    }
    return result


def _build_series(df: pd.DataFrame, lookback: int = 60) -> list[dict[str, Any]]:
    """返回最近 lookback 个交易日的 OHLCV + 均线序列，用于前端绘制 K 线+成交量图。"""
    tail = df.tail(lookback)
    series: list[dict[str, Any]] = []
    for _, row in tail.iterrows():
        series.append({
            "date": str(row["date"])[:10],
            "open": _safe_float(row.get("open")),
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "close": _safe_float(row.get("close")),
            "volume": _safe_float(row.get("volume")),
            "ma5": _safe_float(row.get("ma5")),
            "ma20": _safe_float(row.get("ma20")),
            "ma60": _safe_float(row.get("ma60")),
            "vol_ratio_5d": _safe_float(row.get("vol_ratio_5d")),
        })
    return series


def _build_overall(steps: list[dict[str, Any]], close: float | None) -> dict[str, Any]:
    """综合五步分析结果，给出偏多/偏空倾向与综合判断。

    综合判断由五步分析共同得出，并将「位置」与「量价关系」交叉综合，
    归纳出高位放量、低位放量、上涨中继放量、下跌中继放量等情景。

    为避免「偏空却显示量价平稳」这类自相矛盾，summary 重塑为连贯叙述：
    先说明当前状态，再给出情景信号解读（含企稳/见顶等关键信号）。
    不输出方向预判（direction）与操作建议（action）——买卖决策交由三买三卖系统单独给出。
    """
    s_pos, s_trend, s_vol, s_quad, s_key = steps[0], steps[1], steps[2], steps[3], steps[4]

    trend = s_trend.get("trend")
    dominant = s_quad.get("dominant")
    level = s_vol.get("level")
    # OBV 已并入趋势判断步骤，作为辅助验证
    divergence = s_trend.get("divergence")
    near_levels = [lv for lv in s_key.get("levels", []) if lv.get("nearby")]

    signals: list[dict[str, str]] = []
    if trend == "多头排列":
        signals.append({"name": "均线多头排列", "bias": "多"})
    elif trend == "空头排列":
        signals.append({"name": "均线空头排列", "bias": "空"})
    else:
        signals.append({"name": "均线震荡整理", "bias": "中性"})

    quadrant_bias = {
        "价涨量增": "多", "价涨量缩": "空", "价跌量增": "空", "价跌量缩": "多",
    }
    if dominant:
        signals.append({"name": f"近5日以{dominant}为主", "bias": quadrant_bias.get(dominant, "中性")})

    if level == "显著放量":
        signals.append({"name": "显著放量", "bias": "中性"})
    elif level == "缩量":
        signals.append({"name": "缩量观望", "bias": "中性"})

    if divergence == "底背离":
        signals.append({"name": "OBV底背离", "bias": "多"})
    elif divergence == "顶背离":
        signals.append({"name": "OBV顶背离", "bias": "空"})

    if near_levels:
        signals.append({"name": f"贴近{'、'.join(lv['name'] for lv in near_levels)}", "bias": "中性"})

    # —— 位置 × 量价关系 交叉综合 ——
    position = s_pos.get("position") or _compute_position(s_key, close)
    volume_state = _compute_volume_state(s_vol)
    scenario, scenario_meaning, scenario_bias = _synthesize_scenario(
        position, trend, volume_state
    )
    if scenario:
        signals.append({"name": scenario, "bias": scenario_bias})

    # 综合倾向：多数信号倾向
    bias_count = {
        "多": sum(1 for s in signals if s["bias"] == "多"),
        "空": sum(1 for s in signals if s["bias"] == "空"),
    }
    if bias_count["多"] > bias_count["空"]:
        bias = "偏多"
    elif bias_count["空"] > bias_count["多"]:
        bias = "偏空"
    else:
        bias = "中性"

    # 结构化片段：当前量价状态 + 情景关键信号（供前端分模块展示，避免长段落阅读负担）
    parts = _build_summary_parts(position, volume_state, trend, dominant, divergence, scenario)

    # 连贯叙述（保留兼容，供需整段文本的场景使用）
    summary = f"{parts['current_state']}。{parts['signal_note']}"

    return {
        "bias": bias,
        "signals": signals,
        # 判断依据（信号名列表），供前端悬浮提示展示「为什么这样判断」
        "bias_basis": [s["name"] for s in signals],
        "summary": summary,
        # 结构化呈现字段：当前量价状态 / 情景关键信号，前端据此分模块展示
        "current_state": parts["current_state"],
        "signal_note": parts["signal_note"],
        "position": position,
        "volume_state": volume_state,
        "scenario": scenario,
        "scenario_meaning": scenario_meaning,
    }


def _build_summary_parts(
    position: str,
    volume_state: str,
    trend: str,
    dominant: str,
    divergence: str,
    scenario: str,
) -> dict[str, str]:
    """将综合判断拆分为「当前量价状态」与「情景关键信号」两个可独立阅读的片段。

    结构：①当前量价状态（位置/量能/均线走势/量价象限/OBV背离）
    → ②情景关键信号（含企稳/见顶等可落地的关注点）。
    """
    state_parts = [f"当前股价处于{position}"]
    if volume_state == "放量":
        state_parts.append("呈放量状态")
    elif volume_state == "缩量":
        state_parts.append("成交缩量")
    else:
        state_parts.append("量能平稳")

    if trend == "多头排列":
        state_parts.append("均线多头排列、处于上升趋势")
    elif trend == "空头排列":
        state_parts.append("均线空头排列、处于下降趋势")
    else:
        state_parts.append("均线交织、方向未明")

    if dominant:
        state_parts.append(f"近5日以「{dominant}」为主")

    if divergence == "底背离":
        state_parts.append("且OBV底背离、资金低位吸筹")
    elif divergence == "顶背离":
        state_parts.append("且OBV顶背离、上涨动能不足")

    return {
        "current_state": "，".join(state_parts),
        "signal_note": _scenario_signal_note(scenario),
    }


def _scenario_signal_note(scenario: str) -> str:
    """针对具体情景给出可落地的关键信号与下一步关注点（如低位缩量的企稳信号）。"""
    notes = {
        "低位缩量": (
            "股价处于相对低位且缩量，抛压减轻，或接近阶段性底部。企稳信号可关注："
            "①连续缩量且不再创新低；②缩量走平后出现放量阳线；③OBV由降转升；④MA5走平上翘。"
        ),
        "低位放量": (
            "股价处于相对低位且明显放量，可能是资金低位吸筹或底部启动信号。"
            "关注放量能否持续，若放量站稳并突破MA20/60日高点则确认启动。"
        ),
        "高位放量": (
            "股价处于相对高位且明显放量，警惕主力出货或见顶回落。"
            "关注放量后是否滞涨或出现长上影，若跌破MA20则确认见顶。"
        ),
        "上涨中继放量": "上升趋势中持续放量，量价配合良好。只要不放量跌破MA20，趋势有望延续；若放量滞涨则需防回调。",
        "下跌中继放量": "下降趋势中仍持续放量，抛压较重。反弹至关键均线不破需警惕再度下杀，暂以观望为主。",
        "高位缩量": "股价处于相对高位但缩量，上涨动能不足。若跌破MA20则确认回落，警惕滞涨见顶。",
        "中位放量": "股价处于中位且放量，多为方向选择在即。放量方向即为选择方向：突破60日高点看多，跌破60日低点看空。",
        "中位缩量": "股价处于中位且缩量，市场观望情绪浓。缩量盘整，等待放量方向选择。",
        "量价平稳": "当前量价关系总体平稳、多空分歧有限，方向待量能变化确认。",
    }
    return notes.get(scenario, "")


def _compute_position(s5: dict[str, Any], close: float | None) -> str:
    """依据 60 日高低点将当前股价定位为高位/中位/低位。"""
    high = low = None
    for lv in s5.get("levels", []):
        if lv["name"] == "60日高点":
            high = lv["value"]
        elif lv["name"] == "60日低点":
            low = lv["value"]
    if high and low and close is not None and high > low:
        ratio = (close - low) / (high - low)
        if ratio >= 0.7:
            return "高位"
        if ratio <= 0.3:
            return "低位"
    return "中位"


def _compute_volume_state(s3: dict[str, Any]) -> str:
    """将量能活跃度归一化为放量/缩量/量能平稳。"""
    level = s3.get("level")
    if level in ("显著放量", "温和放量"):
        return "放量"
    if level == "缩量":
        return "缩量"
    return "量能平稳"


def _synthesize_scenario(
    position: str, trend: str, volume_state: str
) -> tuple[str, str, str]:
    """综合位置与量价关系，输出情景名称、含义与倾向。

    覆盖高位放量、低位放量、上涨中继放量、下跌中继放量等典型情景。
    """
    up = trend == "多头排列"
    down = trend == "空头排列"

    # 上涨/下跌中继放量的特殊情景优先
    if up and volume_state == "放量":
        return (
            "上涨中继放量",
            "上升趋势中持续放量，量价配合良好，上涨趋势有望延续，可顺势持有。",
            "多",
        )
    if down and volume_state == "放量":
        return (
            "下跌中继放量",
            "下降趋势中仍持续放量，抛压较重，下跌趋势或延续，需防范进一步回落。",
            "空",
        )

    scenarios = {
        ("高位", "放量"): ("高位放量", "股价处于相对高位且明显放量，警惕主力出货或见顶回落风险，追高需谨慎。", "空"),
        ("低位", "放量"): ("低位放量", "股价处于相对低位且明显放量，可能是资金低位吸筹或底部启动信号，关注能否持续放量上攻。", "多"),
        ("中位", "放量"): ("中位放量", "股价处于中位且放量，多空分歧加大，方向选择在即，需结合趋势进一步判断。", "中性"),
        ("高位", "缩量"): ("高位缩量", "股价处于相对高位但缩量，上涨动能不足，警惕滞涨或见顶信号。", "空"),
        ("低位", "缩量"): ("低位缩量", "股价处于相对低位且缩量，抛压减轻，或接近阶段性底部，关注企稳信号。", "多"),
        ("中位", "缩量"): ("中位缩量", "股价处于中位且缩量，市场观望情绪浓，等待方向选择。", "中性"),
    }
    return scenarios.get(
        (position, volume_state), ("量价平稳", "当前量价关系平稳，无明显异常信号。", "中性")
    )


# ──────────────────────────────────────────────────────────────
# 第一步：位置判断
# ──────────────────────────────────────────────────────────────
def _step1_position(df: pd.DataFrame, latest: pd.Series) -> dict[str, Any]:
    """依据 60 日高低点将当前股价定位为高位/中位/低位。"""
    close = _safe_float(latest["close"])
    high_60d = _safe_float(latest.get("high_60d"))
    low_60d = _safe_float(latest.get("low_60d"))

    levels: list[dict[str, Any]] = []
    if high_60d and not pd.isna(high_60d):
        near = abs(close - high_60d) / high_60d < 0.02 if high_60d > 0 else False
        levels.append({"name": "60日高点", "value": high_60d, "nearby": near})
    if low_60d and not pd.isna(low_60d):
        near = abs(close - low_60d) / low_60d < 0.02 if low_60d > 0 else False
        levels.append({"name": "60日低点", "value": low_60d, "nearby": near})

    position = _compute_position({"levels": levels}, close)

    if high_60d and low_60d and high_60d > low_60d:
        pct = (close - low_60d) / (high_60d - low_60d) * 100
        conclusion = f"当前股价 {close:.2f} 位于60日区间的 {pct:.0f}% 分位，处于{position}。"
    else:
        conclusion = f"当前股价 {close:.2f}，位置数据不足，判定为{position}。"

    return {
        "step": 1,
        "title": "位置判断",
        "meaning": "依据60日高低点将当前股价定位为高位/中位/低位，反映股价所处历史区间：越接近60日高点越处于高位，越接近60日低点越处于低位。",
        "position": position,
        "close": close,
        "high_60d": high_60d,
        "low_60d": low_60d,
        "levels": levels,
        "conclusion": conclusion,
    }


# ──────────────────────────────────────────────────────────────
# 第二步：趋势判断（均线定方向，OBV 辅助验证）
# ──────────────────────────────────────────────────────────────
def _step2_trend(df: pd.DataFrame, latest: pd.Series) -> dict[str, Any]:
    """收盘价相对 MA5/MA20/MA60 的位置判断趋势方向，并用 OBV 辅助验证。

    OBV（能量潮）反映成交量所推动的累计方向，仅作为趋势的辅助确认：
    趋势同向且 OBV 同步则趋势可信度高，OBV 背离则提示趋势可能反转。
    因此 OBV 并入趋势判断，不再单独成步。
    """
    close = _safe_float(latest["close"])
    ma5 = _safe_float(latest.get("ma5"))
    ma20 = _safe_float(latest.get("ma20"))
    ma60 = _safe_float(latest.get("ma60"))

    above: list[str] = []
    below: list[str] = []
    for name, val in [("MA5", ma5), ("MA20", ma20), ("MA60", ma60)]:
        if val is None or pd.isna(val):
            continue
        if close > val:
            above.append(name)
        else:
            below.append(name)

    # 趋势判定
    if ma20 and ma60 and not pd.isna(ma20) and not pd.isna(ma60):
        if close > ma20 > ma60:
            trend = "多头排列"
            conclusion = f"收盘价 {close:.2f} 站在 MA20({ma20:.2f}) 和 MA60({ma60:.2f}) 上方，均线多头排列，处于上升趋势中。"
        elif close < ma20 < ma60:
            trend = "空头排列"
            conclusion = f"收盘价 {close:.2f} 在 MA20({ma20:.2f}) 和 MA60({ma60:.2f}) 下方，均线空头排列，处于下降趋势中。"
        else:
            trend = "震荡"
            conclusion = f"收盘价 {close:.2f} 在均线间反复，MA20={ma20:.2f}、MA60={ma60:.2f}，处于震荡整理阶段。"
    else:
        trend = "数据不足"
        conclusion = "均线数据不足，无法判断趋势。"

    # —— OBV 辅助验证 ——
    obv = _compute_obv_aux(df)
    divergence = obv["divergence"]
    if divergence == "底背离":
        conclusion += " OBV近5日上升而价格下跌，呈现底背离，资金低位吸筹，关注企稳回升。"
    elif divergence == "顶背离":
        conclusion += " OBV近5日下降而价格上涨，呈现顶背离，上涨缺乏量能，警惕回调风险。"
    elif trend == "多头排列":
        conclusion += " OBV同步抬升，量能配合良好，上升趋势可信度较高。"
    elif trend == "空头排列":
        conclusion += " OBV同步走低，抛压持续，下降趋势可信度较高。"
    else:
        conclusion += " OBV与价格方向一致，量价关系正常。"

    return {
        "step": 2,
        "title": "趋势判断",
        "meaning": "以收盘价相对 MA5/MA20/MA60 的位置判断趋势方向（多头/空头/震荡），并用 OBV 能量潮辅助验证：OBV 与趋势同向则趋势可信度更高，OBV 背离则提示趋势可能反转。",
        "trend": trend,
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
        "ma60": ma60,
        "above": above,
        "below": below,
        # OBV 辅助信息（并入趋势判断）
        "obv": obv["obv"],
        "obv_direction": obv["obv_direction"],
        "price_direction": obv["price_direction"],
        "divergence": divergence,
        "conclusion": conclusion,
    }


def _compute_obv_aux(df: pd.DataFrame) -> dict[str, Any]:
    """计算 OBV 近 5 日方向及其与价格方向的背离，作为趋势判断的辅助确认。"""
    recent = df.tail(20)
    if recent.empty or "obv" not in recent.columns:
        return {
            "obv": None, "obv_direction": "走平", "price_direction": "走平", "divergence": "无背离",
        }

    obv_now = _safe_float(recent["obv"].iloc[-1])
    obv_5d_ago = _safe_float(recent["obv"].iloc[-6]) if len(recent) >= 6 else None

    obv_direction = "走平"
    if obv_5d_ago is not None and not pd.isna(obv_5d_ago) and not pd.isna(obv_now):
        if obv_now > obv_5d_ago:
            obv_direction = "上升"
        elif obv_now < obv_5d_ago:
            obv_direction = "下降"

    price_now = _safe_float(recent["close"].iloc[-1])
    price_5d_ago = _safe_float(recent["close"].iloc[-6]) if len(recent) >= 6 else None
    price_direction = "走平"
    if price_5d_ago is not None and not pd.isna(price_5d_ago):
        if price_now > price_5d_ago:
            price_direction = "上升"
        elif price_now < price_5d_ago:
            price_direction = "下降"

    divergence = "无背离"
    if obv_direction == "上升" and price_direction == "下降":
        divergence = "底背离"
    elif obv_direction == "下降" and price_direction == "上升":
        divergence = "顶背离"

    return {
        "obv": obv_now,
        "obv_direction": obv_direction,
        "price_direction": price_direction,
        "divergence": divergence,
    }


# ──────────────────────────────────────────────────────────────
# 第三步：量能活跃度
# ──────────────────────────────────────────────────────────────
def _step3_volume(df: pd.DataFrame, latest: pd.Series) -> dict[str, Any]:
    """近期成交活跃度：量比、5日均量 vs 10日均量。"""
    vol_ratio = _safe_float(latest.get("vol_ratio_5d"))
    vol_ma5 = _safe_float(latest.get("vol_ma5"))
    vol_ma10 = _safe_float(latest.get("vol_ma10"))
    volume = _safe_float(latest.get("volume"))

    # 活跃度判定
    if vol_ratio is not None and not pd.isna(vol_ratio):
        if vol_ratio >= 2.0:
            level = "显著放量"
            meaning = "成交量远超近期均值，资金参与度极高，关注后续方向选择。"
        elif vol_ratio >= 1.5:
            level = "温和放量"
            meaning = "成交量高于近期均值，市场关注度提升。"
        elif vol_ratio >= 0.8:
            level = "量能平稳"
            meaning = "成交量与近期均值接近，市场交投正常。"
        else:
            level = "缩量"
            meaning = "成交量低于近期均值，市场关注度下降，观望情绪较浓。"
    else:
        level = "数据不足"
        meaning = "量比数据不足。"

    # 5日均量 vs 10日均量趋势
    vol_trend = "持平"
    if vol_ma5 and vol_ma10 and not pd.isna(vol_ma5) and not pd.isna(vol_ma10):
        if vol_ma5 > vol_ma10 * 1.1:
            vol_trend = "短期放量"
        elif vol_ma5 < vol_ma10 * 0.9:
            vol_trend = "短期缩量"

    conclusion = f"当日量比 {vol_ratio:.2f}（{level}）。{meaning} 5日均量{'高于' if vol_trend == '短期放量' else '低于' if vol_trend == '短期缩量' else '接近'}10日均量，{vol_trend}。"

    return {
        "step": 3,
        "title": "量能活跃度",
        "meaning": "用量比（当日量/近期均量）衡量当前成交活跃度：量比≥2为显著放量、1.5-2为温和放量、0.8-1.5为量能平稳、<0.8为缩量，反映市场对该股的关注度与资金参与度。",
        "volume": volume,
        "vol_ratio_5d": vol_ratio,
        "vol_ma5": vol_ma5,
        "vol_ma10": vol_ma10,
        "level": level,
        "vol_trend": vol_trend,
        "conclusion": conclusion,
    }


# ──────────────────────────────────────────────────────────────
# 第四步：量价象限
# ──────────────────────────────────────────────────────────────
def _step4_quadrant(df: pd.DataFrame) -> dict[str, Any]:
    """近 5 日量价关系归类到四象限。"""
    recent = df.tail(5).copy()
    if recent.empty:
        return {"step": 4, "title": "量价象限", "conclusion": "数据不足"}

    # 涨跌方向：change_pct > 0 为涨
    recent["is_up"] = recent["change_pct"] > 0
    # 量增减：vol_ratio_5d > 1 为放量
    recent["is_vol_up"] = recent["vol_ratio_5d"] > 1.0

    # 统计近 5 日四象限分布
    quad_count = {
        "价涨量增": int(((recent["is_up"]) & (recent["is_vol_up"])).sum()),
        "价涨量缩": int(((recent["is_up"]) & (~recent["is_vol_up"])).sum()),
        "价跌量增": int(((~recent["is_up"]) & (recent["is_vol_up"])).sum()),
        "价跌量缩": int(((~recent["is_up"]) & (~recent["is_vol_up"])).sum()),
    }

    # 主导象限
    dominant = max(quad_count, key=quad_count.get)
    quad_meaning = {
        "价涨量增": "健康上涨：资金积极买入，量价配合良好，趋势有望延续。",
        "价涨量缩": "量价背离：上涨缺乏量能支撑，需警惕后续动能不足。",
        "价跌量增": "放量下跌：抛压较重，可能是恐慌性抛售或主力出货。",
        "价跌量缩": "缩量下跌：卖盘减弱，可能接近阶段性底部。",
    }
    conclusion = f"近 5 日以「{dominant}」为主（{quad_count[dominant]}/5 日）。{quad_meaning[dominant]}"

    return {
        "step": 4,
        "title": "量价象限",
        "meaning": "统计近5日股价涨跌与量能增减的组合，归类到「价涨量增/价涨量缩/价跌量增/价跌量缩」四个象限，判断近期资金买卖意愿与量价配合是否健康。",
        "distribution": quad_count,
        "dominant": dominant,
        # 每个象限的意义，供前端鼠标停留展示
        "quadrant_meanings": quad_meaning,
        "days": [
            {
                "date": str(r["date"])[:10],
                "change_pct": _safe_float(r["change_pct"]),
                "vol_ratio": _safe_float(r["vol_ratio_5d"]),
                "quadrant": _classify_quadrant(r["change_pct"], r["vol_ratio_5d"]),
            }
            for _, r in recent.iterrows()
        ],
        "conclusion": conclusion,
    }


def _classify_quadrant(change_pct: float, vol_ratio: float) -> str:
    is_up = (change_pct or 0) > 0
    is_vol_up = (vol_ratio or 0) > 1.0
    if is_up and is_vol_up:
        return "价涨量增"
    if is_up and not is_vol_up:
        return "价涨量缩"
    if not is_up and is_vol_up:
        return "价跌量增"
    return "价跌量缩"


# ──────────────────────────────────────────────────────────────
# 第五步：关键位量能分析
# ──────────────────────────────────────────────────────────────
def _step5_key_level_volume(df: pd.DataFrame, latest: pd.Series) -> dict[str, Any]:
    """在 60 日高低点、MA20 等关键位置的成交量表现。

    判断「是否贴近关键位置」用百分比弹性区间（约 ±2%），而非要求价格
    精确等于关键价位——股价以两位小数报价，无法也不会精确触碰关键位。
    """
    close = _safe_float(latest["close"])
    high_60d = _safe_float(latest.get("high_60d"))
    low_60d = _safe_float(latest.get("low_60d"))
    ma20 = _safe_float(latest.get("ma20"))
    volume = _safe_float(latest.get("volume"))
    vol_ma5 = _safe_float(latest.get("vol_ma5"))

    # 「贴近」判定宽度：关键位 ±2% 范围内视为已到关键位置
    NEAR_BAND = 0.02

    levels: list[dict[str, Any]] = []

    # 60 日新高
    if high_60d and not pd.isna(high_60d):
        near_high = abs(close - high_60d) / high_60d < NEAR_BAND if high_60d > 0 else False
        levels.append({
            "name": "60日高点",
            "value": high_60d,
            "nearby": near_high,
            "note": "进入60日新高±2%区间，关注突破时的量能配合" if near_high else f"距60日高点 {((close / high_60d - 1) * 100):.1f}%",
        })

    # 60 日新低
    if low_60d and not pd.isna(low_60d):
        near_low = abs(close - low_60d) / low_60d < NEAR_BAND if low_60d > 0 else False
        levels.append({
            "name": "60日低点",
            "value": low_60d,
            "nearby": near_low,
            "note": "进入60日低点±2%区间，关注是否缩量企稳" if near_low else f"距60日低点 {((close / low_60d - 1) * 100):.1f}%",
        })

    # MA20
    if ma20 and not pd.isna(ma20):
        near_ma20 = abs(close - ma20) / ma20 < NEAR_BAND if ma20 > 0 else False
        above_ma20 = close > ma20
        levels.append({
            "name": "MA20",
            "value": ma20,
            "nearby": near_ma20,
            "note": ("站在MA20上方" if above_ma20 else "在MA20下方") + ("，贴近±2%均线，关注方向选择" if near_ma20 else ""),
        })

    # 量能是否放大
    is_volume_surge = vol_ma5 and volume and not pd.isna(vol_ma5) and vol_ma5 > 0 and volume > vol_ma5 * 1.5

    # 综合结论
    near_levels = [lv for lv in levels if lv.get("nearby")]
    if near_levels:
        level_names = "、".join(lv["name"] for lv in near_levels)
        if is_volume_surge:
            conclusion = f"股价已进入{level_names}±2%区间，且成交量显著放大（量比 > 1.5），关键位突破/支撑的有效性较高。"
        else:
            conclusion = f"股价已进入{level_names}±2%区间，但量能未明显放大，突破/支撑的有效性存疑，需等待放量确认。"
    else:
        if is_volume_surge:
            conclusion = "当前未处于关键位置±2%区间，但成交量显著放大，可能有异动，关注后续走势。"
        else:
            conclusion = "当前未处于关键位置，量能平稳，无明显信号。"

    return {
        "step": 5,
        "title": "关键位量能分析",
        "meaning": "判断股价是否进入关键支撑阻力位（60日高点/低点、MA20）的±2%弹性区间，并结合该位置的成交量表现判断突破/支撑的有效性：贴近关键位且放量则突破或企稳可信度高，缩量则有效性存疑。",
        "close": close,
        "levels": levels,
        "is_volume_surge": bool(is_volume_surge),
        "conclusion": conclusion,
    }


def _safe_float(val: Any) -> float | None:
    """安全转 float，NaN/None 返回 None。"""
    if val is None:
        return None
    try:
        f = float(val)
        if pd.isna(f):
            return None
        return f
    except (TypeError, ValueError):
        return None