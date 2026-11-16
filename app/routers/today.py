"""今日待办聚合接口

三层分工，AI 只做方向、规则层负责执行：
- L1 方向：大盘研判「今日结论」的结构化主攻/回避行业；
- L2 候选：全市场 B2 + 观察池，经主攻/回避行业过滤；
- L3 执行：纯规则计算仓位/止损/组合约束（decision.rules.decide）。

接口本身只做「鉴权 → 构建快照 → 调用纯函数 → 组装页面数据」，不再内联买卖判定。
"""

import logging

from fastapi import APIRouter, Depends

from app.core.database import get_mongo_db
from app.core.response import fail, ok
from app.routers.auth_db import get_current_user
from app.services.decision import decide
from app.services.decision.snapshot import build_snapshot

logger = logging.getLogger(__name__)
router = APIRouter()

_GATE_CN = {"green": "绿灯", "yellow": "黄灯", "red": "红灯"}
_PHASE_TONE = {
    "冰点期": "down", "退潮期": "down", "分歧期": "flat",
    "修复期": "up", "启动期": "flat", "发酵期": "up", "高潮期": "warn",
}


def _build_environment(gate: dict, trade_date: str) -> dict:
    """把环境闸门展开成「三层结论 + 详尽说明 + 该怎么做」。"""
    gate_key = gate.get("gate") or "yellow"
    gate_label = gate.get("label") or "轻仓试错"
    portrait = gate.get("portrait") or "画像未知"
    phase = gate.get("emotion_phase") or {}
    phase_label = phase.get("label") or "情绪未知"
    position_hint = gate.get("position_hint") or "—"
    advice = gate.get("advice")
    if not isinstance(advice, str) or not advice:
        advice = "顺势控制仓位"
    dims = gate.get("dims") or {}
    emotion = gate.get("emotion") or {}

    portrait_points: list[str] = []
    dim_line = " · ".join(
        f"{k}{v}"
        for k, v in (
            ("趋势", dims.get("trend")),
            ("波动", dims.get("vol")),
            ("宽度", dims.get("breadth")),
            ("情绪", dims.get("sentiment")),
        )
        if v
    )
    if dim_line:
        portrait_points.append(f"四维判定：{dim_line}")
    portrait_points.extend(list(gate.get("reasons") or [])[:4])
    if not portrait_points:
        portrait_points.append("画像依据暂缺，按保守口径处理")

    phase_points: list[str] = []
    if emotion.get("zt") is not None:
        phase_points.append(
            f"涨停 {emotion.get('zt')} 家 · 跌停 {emotion.get('dt')} 家 · 炸板 {emotion.get('zb')} 家"
        )
    if emotion.get("max_boards") is not None:
        phase_points.append(f"最高连板 {emotion.get('max_boards')} 板")
    if emotion.get("seal_rate") is not None:
        phase_points.append(f"封板率 {float(emotion['seal_rate']):.0%}")
    if phase_label == "高潮期":
        phase_points.append(
            "高潮期只说明短线情绪亢奋，不代表中期趋势转多：次日高开低走、炸板概率抬升，属于兑现区而不是加仓区"
        )
    elif phase_label in ("冰点期", "退潮期"):
        phase_points.append("情绪收缩期：等冰点/退潮走完、出现修复信号再谈进攻")
    phase_points.append(f"阶段判定：{phase.get('desc') or '情绪数据不足'}")

    position_points = [f"闸门判定 {gate_label}（{_GATE_CN.get(gate_key, '')}）→ 仓位上限 {position_hint}"]
    if gate_key == "red":
        position_points.extend(
            [
                "弱市画像时闸门一票否决：情绪再热也不加仓，避免在反弹末端接盘",
                "观察仓只用于跟踪临近触发与已持仓标的，不主动开新仓",
                "等画像脱离弱市、或情绪回到修复期，再考虑把仓位提回 3 成以上",
            ]
        )
    elif gate_key == "yellow":
        position_points.extend(
            [
                "轻仓试错：单票不超过总资金 15%，持仓不超过 3 只，只做临近触发的标的",
                "不追高、不接力，触发失败立即退出",
                f"画像建议：{advice}",
            ]
        )
    else:
        position_points.extend(
            [
                "趋势与情绪共振，可按 B2 信号正常执行",
                f"画像建议：{advice}",
            ]
        )

    if gate_key == "red":
        actions = [
            {
                "side": "买",
                "tone": "down",
                "title": "不新开仓，信号只记录不下单",
                "text": "买块里即使出现 B2 已触发，也按环境红灯暂停执行；把代码、触发价、止损记下来，等闸门转黄/绿再做第一笔。",
            },
            {
                "side": "盯",
                "tone": "flat",
                "title": "只盯 2% 临近区，不提前埋伏",
                "text": "高潮期的强势股次日容易分歧、炸板；只把距触发最近、且仍在积累区的标的放进明天清单，没到触发价一律不动手。",
            },
            {
                "side": "卖",
                "tone": "up",
                "title": "优先兑现，收紧止损",
                "text": "持仓冲高先兑现浮盈，跌破 MA5 或止损无条件离场；到 30 日时间止损的直接释放资金，不摊薄、不补仓。",
            },
        ]
    elif gate_key == "yellow":
        actions = [
            {
                "side": "买",
                "tone": "down",
                "title": "只做临近触发，单票 ≤15%",
                "text": "只执行已触发、且处于今日结论主攻方向的 B2；环境一般时风险预算减半、最多持有 3 只。",
            },
            {
                "side": "盯",
                "tone": "flat",
                "title": "盯临近触发 + 主攻方向",
                "text": "优先看距触发 2% 以内、且行业在今日主攻方向的标的；退潮期不接力高位股。",
            },
            {
                "side": "卖",
                "tone": "up",
                "title": "盈利分批止盈，亏损按线走",
                "text": "+15% 先卖一半，剩余仓位跌破 MA5 离场；亏损触及 -8% 或计划止损立即执行，不扛单。",
            },
        ]
    else:
        actions = [
            {
                "side": "买",
                "tone": "up",
                "title": "按 B2 信号正常进攻",
                "text": "已触发且属于主攻方向的 B2 可按规则仓位执行，单票不超过总资产 15%，首笔不满仓。",
            },
            {
                "side": "盯",
                "tone": "flat",
                "title": "提前排好次日触发清单",
                "text": "把积累区里距触发最近的标的按行业分组，开盘先看主攻方向是否延续，再等触发确认。",
            },
            {
                "side": "卖",
                "tone": "up",
                "title": "让利润奔跑，但守纪律",
                "text": "盈利仓位用 MA5 跟踪，跌破再走；只有触及止盈目标才主动减半，避免过早卖飞。",
            },
        ]

    return {
        "gate": gate_key,
        "verdict": gate_label,
        "headline": f"{portrait} · {phase_label} · {position_hint}",
        "portrait": {
            "value": portrait,
            "tone": "down" if "熊" in portrait else ("up" if "牛" in portrait else "flat"),
            "desc": advice,
            "points": portrait_points,
        },
        "phase": {
            "value": phase_label,
            "tone": _PHASE_TONE.get(phase_label, "flat"),
            "desc": phase.get("desc") or "情绪数据不足",
            "points": phase_points,
        },
        "position": {
            "value": position_hint,
            "tone": "down" if gate_key == "red" else ("up" if gate_key == "green" else "warn"),
            "desc": gate.get("hint") or "",
            "points": position_points,
        },
        "actions": actions,
        "footnote": (
            f"判定于 {trade_date} · 画像日期 {gate.get('as_of_portrait') or '—'} · "
            f"情绪日期 {gate.get('as_of_emotion') or '—'} · 数据质量 {gate.get('data_quality') or 'ok'}"
        ),
        "degraded": bool(gate.get("degraded")),
        "degrade_note": gate.get("degrade_note") or "",
    }


@router.get("/api/today/actions")
async def get_today_actions(current_user: dict = Depends(get_current_user)):
    """今日待办：买 / 盯 / 卖 三块一次返回（L1 方向 + L2 候选 + L3 规则执行）。"""
    db = get_mongo_db()
    user_id = current_user.get("user_id") or current_user.get("id")

    snapshot, extras = await build_snapshot(db, user_id)
    decision = decide(snapshot)
    gate = extras.get("gate") or {}

    mainline_rows = [
        {"name": k, **v} for k, v in (extras.get("mainlines") or {}).items() if v.get("is_mainline")
    ]
    mainline_rows.sort(key=lambda x: (-x["streak"], -(x["net_3d"] or 0)))

    data = {
        "as_of": snapshot.as_of,
        "trade_date": snapshot.trade_date,
        "session": extras.get("session") or {},
        "gate": {
            "gate": gate.get("gate"),
            "label": gate.get("label"),
            "hint": gate.get("hint"),
            "position_hint": gate.get("position_hint"),
            "portrait": gate.get("portrait"),
            "emotion_phase": gate.get("emotion_phase"),
            "degraded": gate.get("degraded"),
        },
        "mainlines": mainline_rows[:5],
        "environment": _build_environment(gate, snapshot.trade_date),
        "account": extras.get("account") or {"cash_cny": 0.0, "equity": 0.0},
        "direction": decision["direction"],
        "buy": decision["buy"],
        "watch": decision["watch"],
        "sell": decision["sell"],
        "meta": decision["meta"],
    }
    return ok(data)


@router.post("/api/today/sync-daily-bars")
async def sync_daily_bars(
    trade_date: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """手动补齐当日（或指定日）日线。

    盘中：用实时快照合成临时日线；收盘后：一次全市场官方日线落库并校准行情快照。
    用于数据异常时无需等待定时任务，直接从「今日待办」触发补数。
    """
    try:
        from app.services.daily_bar_sync_service import run_daily_bar_sync

        result = await run_daily_bar_sync(trade_date=trade_date, force_official=True)
        return ok(result)
    except Exception as exc:
        logger.error(f"今日待办-日线补数失败: {exc}", exc_info=True)
        return fail(f"日线补数失败: {exc}")
