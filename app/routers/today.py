"""今日待办聚合接口

把系统里分散的买卖结论收敛成「一个页面、三块待办」：
- 买：B2 突破买点已触发 → 代码 / 价格 / 仓位 / 止损（照做即可）
- 盯：积累区观察池里距触发最近的标的 → 明天重点看这几只
- 卖：持仓的统一离场结论 → 代码 / 原因 / 参考价

每一条都直接给结论，并把系统内已有的依据（B1/B2 信号、积累区四条件、
行业主线、环境闸门、统一离场原因）编排成可展开的「为什么」。
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from app.core.collections import Collections
from app.core.database import get_mongo_db
from app.core.response import fail, ok
from app.routers.auth_db import get_current_user
from app.services.cache_layer import cached
from app.services.cockpit import gate_service, position_service
from app.services.industry_dashboard import get_industry_period_flows
from app.services.intraday_guide_service import (
    _advice_for,
    _load_open_positions,
    evaluate_sell_signal,
)
from app.utils.timezone import now_tz
from app.utils.trading_time import is_trading_day

logger = logging.getLogger(__name__)
router = APIRouter()

# 三买三卖：单票最大仓位（占总资金），B2 position_pct=0.67 → 实际约 10%
MAX_SINGLE_POSITION_PCT = 0.15
# 环境闸门 → 仓位系数
_GATE_FACTOR = {"green": 1.0, "yellow": 0.5, "red": 0.0}


def _is_intraday(now: datetime) -> bool:
    if not is_trading_day(now.strftime("%Y%m%d")):
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 25) <= minutes <= (15 * 60 + 5)


def _fmt_trade_date(raw) -> str | None:
    if not raw:
        return None
    s = str(raw).replace("-", "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else str(raw)


def _holding_days(buy_date: str | None, trade_date: str) -> int:
    try:
        d0 = datetime.strptime(str(buy_date)[:10], "%Y-%m-%d")
        d1 = datetime.strptime(trade_date, "%Y-%m-%d")
        return max((d1 - d0).days, 0)
    except (ValueError, TypeError):
        return 0


async def _gate_cached(db) -> dict:
    async def _build() -> dict:
        return await gate_service.build_gate(db)

    return await cached("cockpit:gate", _build, category="market")


async def _current_prices(db, codes: list[str]) -> tuple[dict[str, float], str | None]:
    """批量取现价：盘中用实时行情，收盘后用当日收盘快照。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}, None
    now = now_tz()
    if _is_intraday(now):
        try:
            from app.services.quotes_service import get_quotes_service

            quotes = await get_quotes_service().get_quotes(codes)
            return {c: q["close"] for c, q in quotes.items() if q.get("close")}, None
        except Exception as exc:
            logger.warning(f"今日待办-实时价获取失败（回退收盘快照）: {exc}")
    try:
        latest = await db[Collections.market_quotes].find_one({}, {"trade_date": 1}, sort=[("trade_date", -1)])
        trade_date = (latest or {}).get("trade_date")
        if not trade_date:
            return {}, None
        rows = await db[Collections.market_quotes].find(
            {"trade_date": trade_date, "code": {"$in": codes}}, {"code": 1, "close": 1, "_id": 0}
        ).to_list(None)
        return {r["code"]: r["close"] for r in rows if r.get("close")}, _fmt_trade_date(trade_date)
    except Exception as exc:
        logger.warning(f"今日待办-收盘快照读取失败: {exc}")
        return {}, None


def _mainline_map(periods: dict) -> dict[str, dict]:
    """行业 → {streak, net_3d, pct_3d, is_mainline}（与 02 主线同口径）。"""
    net_by_name: dict[str, dict[str, float]] = {}
    pct_by_name: dict[str, float] = {}
    for key in ("3", "5", "10", "20"):
        for row in periods.get(key) or []:
            name = row.get("name")
            if not name:
                continue
            net_by_name.setdefault(name, {})[key] = row.get("net") or 0
            if key == "3":
                pct_by_name[name] = row.get("pct") or 0
    out: dict[str, dict] = {}
    for name, nets in net_by_name.items():
        streak = 0
        for key in ("3", "5", "10", "20"):
            if nets.get(key, 0) > 0:
                streak = int(key)
            else:
                break
        out[name] = {
            "streak": streak,
            "net_3d": nets.get("3", 0),
            "pct_3d": pct_by_name.get(name, 0),
            "is_mainline": streak >= 3,
        }
    return out


def _accum_reasons(doc: dict) -> list[dict]:
    """积累区四条件（池内文档真实数值）→ 可展开依据。"""
    reasons: list[dict] = []
    sideways = doc.get("sideways_days")
    volp = doc.get("volatility_pctile")
    conv = doc.get("converge_ratio")
    amount = doc.get("avg_amount_20d")
    if sideways is not None:
        reasons.append({"kind": "trend", "text": f"形态：横盘 {int(sideways)} 日未创新低（60 日低点之上，筹码在积累）"})
    if volp is not None:
        reasons.append({"kind": "trend", "text": f"波动收敛：20 日年化波动率处于自身 250 日的 {volp * 100:.0f}% 分位（阈值 <40%）"})
    if conv is not None:
        reasons.append({"kind": "trend", "text": f"振幅收敛：近 15 日均振幅 / 60 日均振幅 = {conv:.2f}（阈值 ≤0.9）"})
    if amount is not None:
        reasons.append({"kind": "liquidity", "text": f"流动性：20 日日均成交额 {amount / 1e8:.2f} 亿元（阈值 ≥1 亿）"})
    return reasons


def _industry_reason(industry: str, mainlines: dict[str, dict]) -> dict:
    info = mainlines.get(industry) or {}
    if info.get("is_mainline"):
        return {
            "kind": "mainline",
            "text": (
                f"主线共振：行业「{industry}」连续 {info['streak']} 日累计净流入为正，"
                f"3 日涨幅 {info['pct_3d']:+.2f}%、净流入 {info['net_3d']:.2f} 亿"
            ),
        }
    return {"kind": "flat", "text": f"行业「{industry or '—'}」当前不在资金持续净流入主线内（不享受主线溢价）"}


def _env_reason(gate: dict) -> dict:
    phase = (gate.get("emotion_phase") or {}).get("label") or "情绪数据缺失"
    portrait = gate.get("portrait") or "画像缺失"
    return {
        "kind": "env",
        "text": f"环境闸门：{gate.get('label')}（{portrait} · {phase}），仓位建议 {gate.get('position_hint')}",
    }


_GATE_CN = {"green": "绿灯", "yellow": "黄灯", "red": "红灯"}
_PHASE_TONE = {
    "冰点期": "down", "退潮期": "down", "分歧期": "flat",
    "修复期": "up", "启动期": "flat", "发酵期": "up", "高潮期": "warn",
}


def _build_environment(gate: dict, trade_date: str) -> dict:
    """把环境闸门展开成「三层结论 + 详尽说明 + 该怎么做」。

    三层结论：市场画像 · 情绪阶段 · 仓位纪律；每层给依据，再给买/盯/卖三条动作。
    """
    gate_key = gate.get("gate") or "yellow"
    gate_label = gate.get("label") or "轻仓试错"
    portrait = gate.get("portrait") or "画像未知"
    phase = gate.get("emotion_phase") or {}
    phase_label = phase.get("label") or "情绪未知"
    position_hint = gate.get("position_hint") or "—"
    dims = gate.get("dims") or {}
    emotion = gate.get("emotion") or {}

    # ① 画像：四维 + 判定依据
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

    # ② 情绪：当日涨停/跌停/炸板 + 阶段含义
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

    # ③ 仓位：闸门结论 + 为什么是这个仓位
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
                "轻仓试错：单票不超过总资金 10%，只做临近触发的标的",
                "不追高、不接力，触发失败立即退出",
                f"画像建议：{gate.get('advice') or '顺势控制仓位'}",
            ]
        )
    else:
        position_points.extend(
            [
                "趋势与情绪共振，可按 B2 信号正常执行",
                f"画像建议：{gate.get('advice') or '顺势持仓，让利润奔跑'}",
            ]
        )

    # ④ 三块动作：与页面买/盯/卖一一对应
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
                "title": "只做临近触发，单票 ≤10%",
                "text": "只执行已触发且处于主线行业的 B2，回踩不破触发价再下手；环境一般时不追第二根阳线。",
            },
            {
                "side": "盯",
                "tone": "flat",
                "title": "盯临近触发 + 主线方向",
                "text": "优先看距触发 2% 以内的标的，叠加行业资金连续净流入的再加一分；退潮期不接力高位股。",
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
                "text": "已触发且属于主线的 B2 可按建议仓位执行，单票不超过总资金 15%，首笔不满仓。",
            },
            {
                "side": "盯",
                "tone": "flat",
                "title": "提前排好次日触发清单",
                "text": "把积累区里距触发最近的标的按行业分组，开盘先看主线方向是否延续，再等触发确认。",
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
            "desc": gate.get("advice") or "顺势控制仓位，等待方向明确",
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



def _stop_line(price: float, plan_stop: float | None) -> float:
    """统一离场口径：计划止损价与成本 -8% 取更紧的一条。"""
    default_stop = price * 0.92
    if plan_stop and plan_stop > 0:
        return round(max(float(plan_stop), default_stop), 3)
    return round(default_stop, 3)


def _buy_item(doc: dict, price: float | None, gate: dict, mainlines: dict, cash_cny: float, held: bool) -> dict | None:
    close = price or doc.get("last_price") or doc.get("close")
    if not close:
        return None
    close = float(close)
    trigger = doc.get("b2_trigger_price") or doc.get("trigger_price")
    signal_pct = float(doc.get("position_pct") or 0.67)
    factor = _GATE_FACTOR.get(gate.get("gate"), 0.5)
    blocked = gate.get("gate") == "red"
    position_pct = round(MAX_SINGLE_POSITION_PCT * signal_pct * factor, 4)
    stop = _stop_line(close, doc.get("b1_stop_loss_price"))
    take = round(close * 1.15, 2)

    budget = max(cash_cny, 0.0) * position_pct
    suggest_qty = int(budget / close / 100) * 100 if close > 0 and budget > 0 else 0

    reasons: list[dict] = [
        {
            "kind": "signal",
            "text": (
                f"B2 突破买点已确认：盘中量比 {doc.get('b2_volume_ratio') or '—'}（阈值 ≥1.5）、"
                f"中阳站上 MA55 {doc.get('b2_ma55') or '—'} / MA60 {doc.get('b2_ma60') or '—'}，"
                f"触发价 {float(trigger):.2f}，现价 {close:.2f}"
            ),
        }
    ]
    if doc.get("bias60") is not None:
        reasons.append({"kind": "signal", "text": f"左侧 B1 仍在：BIAS60 {doc['bias60']:+.1f}%（未过热，右侧确认未透支）"})
    reasons.extend(_accum_reasons(doc))
    reasons.append(_industry_reason(doc.get("industry") or "", mainlines))
    reasons.append(_env_reason(gate))
    if blocked:
        reasons.append(
            {
                "kind": "risk",
                "text": "环境红灯（空仓等待）：B2 信号虽已触发，但闸门不允许开新仓，等转黄/绿再执行",
            }
        )
    reasons.append(
        {
            "kind": "risk",
            "text": (
                f"执行纪律：建议仓位 {position_pct * 100:.1f}%（约 {suggest_qty} 股 / {round(budget, 2)} 元），"
                f"止损 {stop:.2f}（成本 -8% 与计划止损取更紧），止盈 {take:.2f}（+15% 先卖一半）"
            ),
        }
    )
    reasons.append({"kind": "risk", "text": "A股 T+1：今日买入次日才能卖出；买入当日所有离场信号只作预警"})

    return {
        "code": doc["code"],
        "name": doc.get("name") or doc["code"],
        "industry": doc.get("industry") or "",
        "signal_label": "B2 突破买点",
        "trigger_date": doc.get("last_triggered_date") or _fmt_trade_date(doc.get("triggered_at")),
        "current_price": round(close, 2),
        "trigger_price": round(float(trigger), 2) if trigger else None,
        "stop_loss_price": stop,
        "take_profit_price": take,
        "position_pct": position_pct,
        "suggest_qty": suggest_qty,
        "suggest_amount": round(budget, 2),
        "held": held,
        "blocked": blocked,
        "action": "买入" if not blocked else "暂停",
        "summary": (
            "环境红灯 · 信号已触发但暂停买入"
            if blocked
            else f"B2 已确认 · 仓位 {position_pct * 100:.1f}% · 止损 {stop:.2f}"
        ),
        "reasons": reasons,
    }


def _watch_item(doc: dict, price: float | None, mainlines: dict) -> dict | None:
    close = price or doc.get("last_price") or doc.get("close")
    trigger = doc.get("trigger_price")
    if not close or not trigger:
        return None
    close, trigger = float(close), float(trigger)
    distance = close / trigger - 1
    to_trigger = -distance

    reasons: list[dict] = [
        {
            "kind": "signal",
            "text": (
                f"距突破触发价 {trigger:.2f} 还差 {to_trigger * 100:.2f}%（现价 {close:.2f}），"
                + ("已进入 2% 临近区，明天开盘重点盯住" if distance >= -0.02 else "仍在观察区，等靠近再盯")
            ),
        },
        {
            "kind": "signal",
            "text": "确认条件：放量（量比 ≥1.5）+ 中阳（实体 ≥5%）+ 收盘站上 MA55/MA60，缺一不买",
        },
    ]
    reasons.extend(_accum_reasons(doc))
    reasons.append(_industry_reason(doc.get("industry") or "", mainlines))

    return {
        "code": doc["code"],
        "name": doc.get("name") or doc["code"],
        "industry": doc.get("industry") or "",
        "status": doc.get("status"),
        "current_price": round(close, 2),
        "trigger_price": round(trigger, 2),
        "distance_to_trigger": round(distance, 4),
        "to_trigger_pct": round(to_trigger, 4),
        "action": "盯",
        "summary": f"距触发 {to_trigger * 100:.2f}% · 触发价 {trigger:.2f}",
        "reasons": reasons,
    }


def _sell_item_from_advice(
    advice: dict, state: str, source: str, trade_date: str, buy_date: str | None = None, position_id: str | None = None
) -> dict:
    reasons = list(advice.get("reasons") or [])
    cost = advice.get("avg_cost")
    price = advice.get("last_price")
    if cost and price:
        days = _holding_days(buy_date, trade_date)
        reasons.append(
            {
                "kind": "flat",
                "text": f"持仓：成本 {float(cost):.2f} → 现价 {float(price):.2f}（{advice.get('profit_loss_rate') or 0:+.2f}%），持有 {days} 天",
            }
        )
    return {
        "code": advice["code"],
        "name": advice.get("name") or advice["code"],
        "source": source,
        "position_id": position_id,
        "state": state,
        "quantity": advice.get("quantity"),
        "avg_cost": cost,
        "current_price": price,
        "pnl_pct": advice.get("profit_loss_rate"),
        "advice": advice.get("advice"),
        "advice_label": advice.get("advice_label"),
        "sell_pct": advice.get("sell_pct") or 0.0,
        "reference_price": advice.get("trigger_price") or price,
        "stop_loss_price": advice.get("stop_loss_price"),
        "reasons": reasons,
        "summary": f"{advice.get('advice_label') or ''} · {advice.get('advice') or ''}".strip(" ·"),
    }


@router.get("/api/today/actions")
async def get_today_actions(current_user: dict = Depends(get_current_user)):
    """今日待办：买 / 盯 / 卖 三块一次返回（每块独立容错，失败不拖垮其他块）。"""
    db = get_mongo_db()
    user_id = current_user.get("user_id") or current_user.get("id")
    now = now_tz()
    trade_date = now.strftime("%Y-%m-%d")

    # ── 环境闸门 + 行业主线（失败降级，不影响三块主体） ──
    try:
        gate = await _gate_cached(db)
    except Exception as exc:
        logger.error(f"今日待办-环境闸门失败: {exc}", exc_info=True)
        gate = {"gate": "yellow", "label": "轻仓试错", "position_hint": "轻仓试错", "portrait": None,
                "emotion_phase": {}, "hint": "环境数据缺失，按轻仓处理", "degraded": True}

    mainlines: dict[str, dict] = {}
    try:
        flows = await get_industry_period_flows()
        mainlines = _mainline_map((flows or {}).get("periods") or {})
    except Exception as exc:
        logger.warning(f"今日待办-行业主线失败: {exc}")

    # ── 持仓（两套账本合并去重） ──
    try:
        paper_positions = await _load_open_positions(user_id)
    except Exception as exc:
        logger.warning(f"今日待办-模拟持仓读取失败: {exc}")
        paper_positions = []
    try:
        cockpit_data = await position_service.list_positions(db, user_id)
    except Exception as exc:
        logger.warning(f"今日待办-纪律持仓读取失败: {exc}")
        cockpit_data = {"items": []}
    cockpit_open = [p for p in (cockpit_data.get("items") or []) if p.get("status") == "open"]
    held_codes = {p["code"] for p in paper_positions} | {p["code"] for p in cockpit_open}

    # ── 观察池（买 + 盯 同源） ──
    try:
        pool_docs = await db[Collections.cockpit_watch_pool].find(
            {"status": {"$in": ["triggered", "watching", "near"]}}, {"_id": 0}
        ).to_list(600)
    except Exception as exc:
        logger.error(f"今日待办-观察池读取失败: {exc}", exc_info=True)
        pool_docs = []

    codes = [d["code"] for d in pool_docs] + [p["code"] for p in paper_positions]
    prices, quote_as_of = await _current_prices(db, codes)

    # 模拟账户可用现金（用于把「建议仓位」换算成可直接下单的股数）
    cash_cny = 0.0
    try:
        acc = await db["paper_accounts"].find_one({"user_id": user_id}) or {}
        cash = acc.get("cash")
        if isinstance(cash, dict):
            cash_cny = float(cash.get("CNY") or 0)
        elif cash is not None:
            cash_cny = float(cash or 0)
    except Exception as exc:
        logger.warning(f"今日待办-账户读取失败: {exc}")

    # ── 买：当日 B2 已触发 ──
    triggered = [d for d in pool_docs if d.get("status") == "triggered"]
    triggered.sort(key=lambda d: str(d.get("last_triggered_date") or ""), reverse=True)
    buy_items = [
        item
        for d in triggered
        if (item := _buy_item(d, prices.get(d["code"]), gate, mainlines, cash_cny, d["code"] in held_codes))
    ]

    # ── 盯：watching / near，距触发最近在前 ──
    watch_items = []
    for d in pool_docs:
        if d.get("status") not in ("watching", "near"):
            continue
        item = _watch_item(d, prices.get(d["code"]), mainlines)
        if item:
            watch_items.append(item)
    watch_items.sort(key=lambda x: x["distance_to_trigger"], reverse=True)

    # ── 卖：模拟持仓 + 纪律持仓，统一离场结论合并去重 ──
    sell_items: list[dict] = []
    hold_count = 0
    seen: set[str] = set()
    for pos in paper_positions:
        code = pos["code"]
        try:
            sig = await evaluate_sell_signal(code)
            price = prices.get(code) or (sig or {}).get("close")
            advice = _advice_for(pos, price, sig)
        except Exception as exc:
            logger.warning(f"今日待办-卖出评估失败 {code}: {exc}")
            continue
        warns = [r for r in (advice.get("reasons") or []) if r.get("kind") == "warn"]
        if advice.get("advice") != "持有":
            # 只有真正产出卖点时才占位去重；否则「持有」会把同代码的驾驶舱离场信号吞掉
            seen.add(code)
            sell_items.append(_sell_item_from_advice(advice, "exit", "paper", trade_date, pos.get("buy_date")))
        elif warns:
            seen.add(code)
            sell_items.append(_sell_item_from_advice(advice, "warn", "paper", trade_date, pos.get("buy_date")))
        else:
            hold_count += 1

    for pos in cockpit_open:
        code = pos["code"]
        if code in seen:
            continue
        seen.add(code)
        reasons = [
            {"kind": "warn" if pos.get("state") == "warn" else "exit", "text": str(r)}
            for r in (pos.get("reasons") or [])
        ]
        item = {
            "code": code,
            "name": pos.get("name") or code,
            "source": "cockpit",
            "position_id": pos.get("id"),
            "state": "exit" if pos.get("state") == "exit" else ("warn" if pos.get("state") == "warn" else "normal"),
            "quantity": None,
            "avg_cost": pos.get("buy_price"),
            "current_price": pos.get("current_price"),
            "pnl_pct": round((pos.get("pnl_pct") or 0) * 100, 2) if pos.get("pnl_pct") is not None else None,
            "advice": "离场" if pos.get("state") == "exit" else ("预警" if pos.get("state") == "warn" else "持有"),
            "advice_label": "",
            "sell_pct": 1.0 if pos.get("state") == "exit" else 0.0,
            "reference_price": pos.get("current_price"),
            "stop_loss_price": pos.get("stop_loss_line"),
            "reasons": reasons or [{"kind": "flat", "text": "未触发离场条件，继续持有观察"}],
            "summary": "纪律离场" if pos.get("state") == "exit" else ("离场预警" if pos.get("state") == "warn" else "继续持有"),
        }
        if item["state"] == "normal":
            hold_count += 1
        else:
            sell_items.append(item)

    order = {"exit": 0, "warn": 1}
    sell_items.sort(key=lambda x: order.get(x["state"], 9))
    exit_count = sum(1 for x in sell_items if x["state"] == "exit")
    warn_count = sum(1 for x in sell_items if x["state"] == "warn")

    mainline_rows = [
        {"name": k, **v} for k, v in mainlines.items() if v.get("is_mainline")
    ]
    mainline_rows.sort(key=lambda x: (-x["streak"], -(x["net_3d"] or 0)))

    data = {
        "as_of": now.replace(microsecond=0).isoformat(),
        "trade_date": trade_date,
        "session": {"is_intraday": _is_intraday(now), "quote_as_of": quote_as_of},
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
        "environment": _build_environment(gate, trade_date),
        "account": {"cash_cny": round(cash_cny, 2)},
        "buy": {"count": len(buy_items), "items": buy_items},
        "watch": {
            "count": len(watch_items),
            "near_count": sum(1 for x in watch_items if x["distance_to_trigger"] >= -0.02),
            "items": watch_items[:20],
        },
        "sell": {
            "count": len(sell_items),
            "exit_count": exit_count,
            "warn_count": warn_count,
            "hold_count": hold_count,
            "items": sell_items,
        },
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
