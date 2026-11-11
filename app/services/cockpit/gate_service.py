"""环境闸门服务（交易驾驶舱 · 区块 01）

把「8 类大盘画像 × 短线情绪周期阶段」推导为一个明确的操作闸门：
- 绿灯 green：可进攻
- 黄灯 yellow：轻仓试错（退潮期降级为"只做临近触发，不追新"）
- 红灯 red：空仓等待

闸门矩阵是本判定的唯一事实源（情绪周期阶段规则移植自前端
Emotion.vue 的 cycleStageInfo，后续前端情绪页可切换复用本服务口径）。
"""

import logging

from app.services.market_overview import get_emotion_history, get_short_term_emotion
from app.strategy_system.market_portrait import PORTRAIT_ADVICE
from app.strategy_system.market_state import build_market_state

logger = logging.getLogger(__name__)

# 情绪周期阶段（与 Emotion.vue cycleStageInfo 保持一致）
PHASE_LABELS = ("冰点期", "退潮期", "分歧期", "修复期", "启动期", "发酵期", "高潮期")

_STRONG_PORTRAITS = {"牛市普涨", "牛市强趋势"}
_WEAK_PORTRAITS = {"熊市阴跌", "熊市恐慌"}


def _pick(d: dict | None, *keys: str, default=None):
    """兼容 snake_case / camelCase 字段取值。"""
    if not d:
        return default
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def derive_emotion_phase(today: dict | None, prev: dict | None) -> dict:
    """由今日/昨日情绪数据推导周期阶段（移植自 Emotion.vue cycleStageInfo）。

    today/prev 字段：zt, dt, zb, max_boards, seal_rate, break_rate。
    返回 {"label", "tone", "desc"}；数据不足时 label 为 None。
    """
    if not today:
        return {"label": None, "tone": "muted", "desc": "情绪数据缺失"}

    zt = float(_pick(today, "zt", default=0) or 0)
    dt = float(_pick(today, "dt", default=0) or 0)
    zb = float(_pick(today, "zb", default=0) or 0)
    boards = float(_pick(today, "max_boards", "maxBoards", default=0) or 0)
    total = zt + zb
    break_rate = _pick(today, "break_rate", "breakRate")
    if break_rate is None:
        break_rate = (zb / total) if total > 0 else 0.0
    break_rate = float(break_rate or 0)
    seal_rate = _pick(today, "seal_rate", "sealRate")
    if seal_rate is None:
        seal_rate = (zt / total) if total > 0 else 0.0
    seal_rate = float(seal_rate or 0)

    prev_zt = float(_pick(prev, "zt", default=0) or 0)
    delta = zt - prev_zt if prev else 0.0

    if zt < 30 and dt >= zt:
        return {
            "label": "冰点期",
            "tone": "down",
            "desc": "涨停稀少且跌停不弱于涨停，赚钱效应跌至谷底，等否极泰来",
        }
    if prev and zt < prev_zt * 0.7 and (break_rate >= 0.3 or dt >= 10):
        return {
            "label": "退潮期",
            "tone": "down",
            "desc": "涨停快速萎缩、炸板或跌停抬头，短线情绪进入收缩阶段",
        }
    if break_rate >= 0.35 or (prev and zt < prev_zt * 0.85):
        return {
            "label": "分歧期",
            "tone": "flat",
            "desc": "炸板率偏高或涨停开始减少，资金对高标产生分歧",
        }
    if zt >= 100 or boards >= 6:
        return {
            "label": "高潮期",
            "tone": "up",
            "desc": "涨停过百或连板高度突破 6 板，情绪亢奋，注意兑现风险",
        }
    if zt >= 60 and seal_rate >= 0.65:
        return {
            "label": "发酵期",
            "tone": "up",
            "desc": "涨停充足且封板率健康，赚钱效应正在扩散",
        }
    if delta > 0 or zt >= 40:
        return {
            "label": "修复期",
            "tone": "up",
            "desc": "涨停家数环比回升，情绪正在修复",
        }
    return {
        "label": "启动期",
        "tone": "flat",
        "desc": "情绪温和，关注新题材与首板方向",
    }


def derive_gate(portrait: str | None, phase_label: str | None, data_quality: str = "ok") -> dict:
    """闸门矩阵：画像 × 情绪阶段 → green/yellow/red。

    返回 {"gate", "label", "hint", "position_hint", "degraded", "degrade_note"}。
    """
    degraded = False
    degrade_note = ""

    if not portrait:
        # 画像缺失：保守降级为黄灯
        degraded = True
        degrade_note = "画像数据缺失，闸门降级为黄灯"
        return {
            "gate": "yellow",
            "label": "轻仓试错",
            "hint": degrade_note,
            "position_hint": "0~3 成（数据缺失，保守试错）",
            "degraded": degraded,
            "degrade_note": degrade_note,
        }

    if not phase_label:
        degraded = True
        degrade_note = "情绪数据缺失，按画像单独判定"

    gate = "yellow"
    hint = ""

    if portrait in _WEAK_PORTRAITS or phase_label == "冰点期":
        gate = "red"
        hint = "熊市画像或情绪冰点：空仓等待，只观察不动手"
    elif portrait in _STRONG_PORTRAITS and phase_label in ("发酵期", "高潮期", "启动期", "修复期"):
        gate = "green"
        hint = "趋势与情绪共振，可按信号正常进攻"
    elif phase_label == "退潮期":
        gate = "yellow"
        hint = "退潮期：只做临近触发的标的，不追新、不接力"
    elif portrait == "高波动市":
        gate = "yellow"
        hint = "高波动市：轻仓快进快出，不恋战"
    else:
        gate = "yellow"
        hint = "环境一般：轻仓试错，严格按触发价与量比执行"

    if degraded:
        hint = f"{degrade_note}；{hint}"

    # PORTRAIT_ADVICE 值为一句话文本（str），非 dict
    base_hint = PORTRAIT_ADVICE.get(portrait) or ""
    if gate == "red":
        position_hint = "0~2 成（观察仓）"
    elif gate == "green":
        position_hint = base_hint or "按画像建议"
    else:
        position_hint = f"轻仓（{base_hint}）" if base_hint else "轻仓试错"

    return {
        "gate": gate,
        "label": {"green": "可进攻", "yellow": "轻仓试错", "red": "空仓等待"}[gate],
        "hint": hint,
        "position_hint": position_hint,
        "degraded": degraded,
        "degrade_note": degrade_note,
    }


async def build_gate(db) -> dict:
    """构建区块 01 环境闸门的完整数据。"""
    portrait = None
    advice: dict = {}
    dims: dict = {}
    reasons: list[str] = []
    metrics: dict = {}
    data_quality = "ok"
    missing: list[str] = []
    as_of_portrait = None

    try:
        state = await build_market_state(db)
        portrait = state.get("portrait")
        advice = state.get("advice") or {}
        dims = state.get("dims") or {}
        reasons = state.get("reasons") or []
        metrics = state.get("metrics") or {}
        data_quality = state.get("data_quality", "ok")
        missing = state.get("missing") or []
        as_of_portrait = state.get("as_of")
    except Exception as exc:
        logger.error(f"获取大盘画像失败: {exc}", exc_info=True)

    today_emotion: dict | None = None
    prev_emotion: dict | None = None
    as_of_emotion = None
    emotion_raw: dict = {}
    try:
        raw_emotion = await get_short_term_emotion()
        hist = await get_emotion_history(2)
        series = (hist or {}).get("series") or []
        if len(series) >= 2:
            prev_emotion = series[-2]
        as_of_emotion = (raw_emotion or {}).get("date")
        # 标准化字段名（emotion 接口用 *_count，history series 用 zt/zb/dt）
        if raw_emotion:
            today_emotion = {
                "zt": _pick(raw_emotion, "zt_count", "zt", default=0),
                "dt": _pick(raw_emotion, "dt_count", "dt", default=0),
                "zb": _pick(raw_emotion, "zb_count", "zb", default=0),
                "max_boards": _pick(raw_emotion, "max_boards", default=0),
                "seal_rate": _pick(raw_emotion, "seal_rate", default=None),
                "break_rate": _pick(raw_emotion, "break_rate", default=None),
            }
            emotion_raw = {
                "zt": today_emotion["zt"],
                "dt": today_emotion["dt"],
                "zb": today_emotion["zb"],
                "max_boards": today_emotion["max_boards"],
                "seal_rate": today_emotion["seal_rate"],
                "lianban": _pick(raw_emotion, "lianban_count", default=None),
            }
    except Exception as exc:
        logger.error(f"获取短线情绪失败: {exc}", exc_info=True)

    phase = derive_emotion_phase(today_emotion, prev_emotion)
    gate = derive_gate(portrait, phase.get("label"), data_quality)

    return {
        **gate,
        "portrait": portrait,
        "advice": advice,
        "dims": dims,
        "reasons": reasons,
        "metrics": metrics,
        "emotion_phase": phase,
        "emotion": emotion_raw,
        "data_quality": data_quality,
        "missing": missing,
        "as_of_portrait": as_of_portrait,
        "as_of_emotion": as_of_emotion,
    }
