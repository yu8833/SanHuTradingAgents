"""L3 执行规则（纯函数）：过滤候选、计算仓位、合并卖出结论。

输入 Snapshot，输出可直接渲染的买/盯/卖三块结论。
同一份 Snapshot 必然得到同一个结果（除 hash 外无任何 IO、时间与随机）。
"""

from __future__ import annotations

import hashlib
import json

from app.core.industry import OTHER_THS
from app.services.decision.models import Candidate, Direction, Holding, Snapshot
from app.services.decision.sizing import size_position

RULE_VERSION = "today-decide-1.0"

DAY_DRAWDOWN_STOP = -0.03  # 单日回撤 ≤ -3% 停止开新仓
WATCH_LIMIT = 20  # 观察清单最多展示 20 只（count 与 items 同步截断，避免数量对不上）

_CONFIRM_TEXT = "确认条件：放量（量比 ≥1.5）+ 中阳（实体 ≥5%）+ 收盘站上 MA55/MA60，缺一不买"


def _snapshot_hash(snap: Snapshot) -> str:
    payload = {
        "trade_date": snap.trade_date,
        "gate": snap.gate,
        "degraded": snap.gate_degraded,
        "direction": [snap.direction.status, list(snap.direction.attack), list(snap.direction.avoid)],
        "candidates": [
            [c.code, c.price, c.trigger_price, c.score, c.bias60, c.structure_stop, c.stale]
            for c in snap.candidates
        ],
        "holdings": [[h.code, h.state, h.quantity, h.current_price] for h in snap.holdings],
        "cash": snap.cash,
        "equity": snap.equity,
        "day_drawdown_pct": snap.day_drawdown_pct,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _industry_reason(industry: str, mainlines: dict[str, dict]) -> dict:
    if not mainlines:
        # 接口失败时只说明数据缺失，不能断言「不在主线」
        return {"kind": "warn", "text": "行业资金主线数据缺失，暂无法判断是否为主线（不作否定结论）"}
    if not industry or industry == OTHER_THS:
        return {"kind": "warn", "text": "行业归属未知，未做主线判断（建议先补齐行业分类）"}
    info = mainlines.get(industry)
    if info is None:
        return {"kind": "warn", "text": f"行业「{industry}」不在本次资金流统计内，未做主线判断"}
    if info.get("is_mainline"):
        return {
            "kind": "mainline",
            "text": (
                f"主线共振：行业「{industry}」连续 {info.get('streak')} 日累计净流入为正，"
                f"3 日涨幅 {info.get('pct_3d', 0):+.2f}%、净流入 {info.get('net_3d', 0):.2f} 亿"
            ),
        }
    return {
        "kind": "flat",
        "text": f"行业「{industry}」连续净流入不足 3 日，当前不在主线内（不享受主线溢价）",
    }


def _direction_reason(direction: Direction, industry: str) -> dict:
    if not direction.usable:
        return {
            "kind": "warn",
            "text": f"方向过滤未生效：{direction.note or '今日结论缺少主攻/回避行业'}",
        }
    if direction.avoid and industry in direction.avoid:
        return {"kind": "risk", "text": f"行业「{industry}」属于今日结论的回避方向，不参与候选"}
    return {
        "kind": "signal",
        "text": (
            f"方向匹配：行业「{industry}」属于今日结论主攻方向"
            f"（{'、'.join(direction.attack[:6]) or '未列主攻'}）"
        ),
    }


def _gate_block_reason(snap: Snapshot) -> str:
    if snap.gate == "red":
        return "环境红灯（空仓等待）：信号成立也暂停买入，等闸门转黄/绿"
    if snap.gate_degraded:
        return "环境数据降级：按纪律禁止新开仓，等画像/情绪数据恢复"
    if snap.day_drawdown_pct is not None and snap.day_drawdown_pct <= DAY_DRAWDOWN_STOP:
        return (
            f"当日回撤 {snap.day_drawdown_pct * 100:.2f}% 触及 -3% 纪律线，"
            "当日停止开新仓"
        )
    return ""


def _execution_reasons(
    *, entry: float, stop: float, take: float, qty: int, amount: float, position_pct: float, caps: list[str]
) -> list[dict]:
    cap_text = f"（受{'、'.join(caps)}约束）" if caps else ""
    return [
        {
            "kind": "risk",
            "text": (
                f"执行参数：买价 {entry:.2f} · 止损 {stop:.2f}（结构止损与 -8% 取更紧）"
                f" · 止盈 {take:.2f}（+15% 先卖一半）"
            ),
        },
        {
            "kind": "risk",
            "text": (
                f"仓位：{qty} 股 / 约 {amount:.2f} 元 / 占总资产 {position_pct * 100:.1f}%{cap_text}"
            ),
        },
        {"kind": "risk", "text": "A股 T+1：今日买入次日才能卖出；买入当日所有离场信号只作预警"},
    ]


def _candidate_reasons(c: Candidate, snap: Snapshot, blocked_reason: str) -> list[dict]:
    reasons: list[dict] = []
    if c.source == "b2":
        reasons.append(
            {
                "kind": "signal",
                "text": (
                    f"全市场 B2 突破已触发（{c.trigger_date or '—'} 盘后确认）：收盘 "
                    f"{c.trigger_price:.2f} 放量中阳站上 MA55/MA60，评分 {c.score}"
                    + (f"，现价 {c.price:.2f}" if c.price else "，现价缺失")
                ),
            }
        )
        if c.bias60 is not None:
            b = float(c.bias60)
            reasons.append(
                {
                    "kind": "signal",
                    "text": f"BIAS60 {b:+.2f}%（相对 MA60 {'不过热，追高风险小' if b < 10 else '偏离较大，注意追高'}）",
                }
            )
    else:
        reasons.append(
            {
                "kind": "signal",
                "text": (
                    f"观察池 B2 买点已触发（{c.trigger_date or '—'}）："
                    f"触发价 {c.trigger_price:.2f}"
                    + (f"，现价 {c.price:.2f}" if c.price else "，现价缺失")
                ),
            }
        )
    reasons.extend(dict(r) for r in c.reasons)
    reasons.append(_industry_reason(c.industry, snap.mainlines))
    reasons.append(_direction_reason(snap.direction, c.industry))
    if snap.gate == "red":
        reasons.append({"kind": "risk", "text": _gate_block_reason(snap)})
    if blocked_reason:
        reasons.append({"kind": "risk", "text": blocked_reason})
    if c.price is None:
        reasons.append(
            {"kind": "warn", "text": "取不到实时/收盘价：不输出买入股数与止损，避免用信号日价格冒充现价"}
        )
    elif c.price_source == "signal":
        reasons.append(
            {"kind": "warn", "text": "当前价来自信号日收盘快照（非实时），仅供估算，下单前需核对实时价"}
        )
    return reasons


def _candidate_distance(c: Candidate) -> float | None:
    if not c.price or not c.trigger_price or c.price <= 0:
        return None
    return max(c.trigger_price / c.price - 1, 0.0)


def _sort_key(c: Candidate) -> tuple:
    dist = _candidate_distance(c)
    return (
        -int(c.score or 0),
        float(c.bias60) if c.bias60 is not None else float("inf"),
        dist if dist is not None else float("inf"),
        c.code,
    )


def _build_buy_and_watch(snap: Snapshot) -> tuple[list[dict], list[dict], dict]:
    direction = snap.direction
    attack = set(direction.attack)
    avoid = set(direction.avoid)

    filtered = {"avoid": 0, "not_attack": 0}
    buy_items: list[dict] = []
    watch_items: list[dict] = []

    gate_block = _gate_block_reason(snap)
    position_count = len({h.code for h in snap.holdings})
    industry_exposure: dict[str, float] = {}
    for h in snap.holdings:
        industry_exposure[h.industry] = industry_exposure.get(h.industry, 0.0) + (h.market_value or 0.0)

    def _allowed(industry: str) -> tuple[bool, str]:
        if not direction.usable:
            return True, ""
        ind = industry or OTHER_THS
        if ind in avoid:
            filtered["avoid"] += 1
            return False, f"行业「{ind}」属于今日结论的回避方向，已从候选剔除"
        if attack and ind not in attack:
            filtered["not_attack"] += 1
            return False, f"行业「{ind}」不在今日结论的主攻方向内，已从候选剔除"
        return True, ""

    triggered = [c for c in snap.candidates if c.status == "triggered" and not c.stale]
    triggered.sort(key=_sort_key)

    for c in triggered:
        ok, _ = _allowed(c.industry)
        if not ok:
            continue

        blocked_reason = ""
        blocked = False
        sizing = None

        if c.held:
            blocked, blocked_reason = True, "已持有该标的（同码互斥），不重复开仓"
        elif gate_block:
            blocked, blocked_reason = True, gate_block
        elif c.price is None:
            blocked, blocked_reason = True, "取不到现价，无法计算仓位与止损"
        else:
            sizing = size_position(
                entry=c.price,
                structure_stop=c.structure_stop,
                score=c.score,
                equity=snap.equity,
                cash=snap.cash,
                gate=snap.gate,
                position_count=position_count,
                industry=c.industry,
                industry_exposure=industry_exposure.get(c.industry, 0.0),
                portfolio_risk_used=sum(x["risk_amount"] for x in buy_items if not x["blocked"]),
            )
            if sizing.blocked:
                blocked, blocked_reason = True, sizing.block_reason
            else:
                position_count += 1
                industry_exposure[c.industry] = (
                    industry_exposure.get(c.industry, 0.0) + sizing.amount
                )

        entry = c.price
        sized = sizing is not None and not sizing.blocked
        stop = sizing.stop if sized else None
        take = round(entry * 1.15, 2) if (entry and sized) else None

        reasons = _candidate_reasons(c, snap, blocked_reason)
        if sized:
            reasons.extend(
                _execution_reasons(
                    entry=entry,
                    stop=stop,
                    take=take,
                    qty=sizing.qty,
                    amount=sizing.amount,
                    position_pct=sizing.position_pct,
                    caps=sizing.caps,
                )
            )

        buy_items.append(
            {
                "code": c.code,
                "name": c.name,
                "industry": c.industry,
                "signal_label": "B2 突破买点",
                "trigger_date": c.trigger_date,
                "score": c.score,
                "bias60": c.bias60,
                "current_price": round(entry, 2) if entry else None,
                "price_source": c.price_source,
                "trigger_price": round(c.trigger_price, 2) if c.trigger_price else None,
                "stop_loss_price": stop,
                "take_profit_price": take,
                "position_pct": sizing.position_pct if sized else 0.0,
                "suggest_qty": sizing.qty if sized else 0,
                "suggest_amount": sizing.amount if sized else 0.0,
                "risk_amount": sizing.risk_amount if sized else 0.0,
                "held": c.held,
                "blocked": blocked,
                "block_reason": blocked_reason,
                "action": "暂停" if blocked else "买入",
                "summary": (
                    blocked_reason
                    if blocked
                    else f"B2 已确认 · 评分 {c.score} · 仓位 {sizing.position_pct * 100:.1f}% · 止损 {stop:.2f}"
                ),
                "reasons": reasons,
            }
        )

    # 盯：观察池待触发 + 已过期触发（退回观察）
    watching = [c for c in snap.candidates if c.status != "triggered" or c.stale]
    for c in watching:
        ok, _ = _allowed(c.industry)
        if not ok:
            continue
        if c.price is None or not c.trigger_price:
            continue
        reason: list[dict] = []
        if c.stale:
            reason.append(
                {
                    "kind": "warn",
                    "text": f"触发已过期（{c.trigger_date or '—'} 的信号未在当日执行），退回观察，不按旧信号下单",
                }
            )
        distance = c.price / c.trigger_price - 1
        to_trigger = -distance
        reason.append(
            {
                "kind": "signal",
                "text": (
                    f"距突破触发价 {c.trigger_price:.2f} 还差 {to_trigger * 100:.2f}%（现价 {c.price:.2f}），"
                    + ("已进入 2% 临近区，明天开盘重点盯住" if distance >= -0.02 else "仍在观察区，等靠近再盯")
                ),
            }
        )
        reason.append({"kind": "signal", "text": _CONFIRM_TEXT})
        reason.extend(dict(r) for r in c.reasons)
        reason.append(_industry_reason(c.industry, snap.mainlines))
        reason.append(_direction_reason(snap.direction, c.industry))
        watch_items.append(
            {
                "code": c.code,
                "name": c.name,
                "industry": c.industry,
                "status": "stale" if c.stale else c.status,
                "stale": c.stale,
                "current_price": round(c.price, 2),
                "trigger_price": round(c.trigger_price, 2),
                "distance_to_trigger": round(distance, 4),
                "to_trigger_pct": round(to_trigger, 4),
                "action": "盯",
                "summary": (
                    f"信号过期 · 距触发 {to_trigger * 100:.2f}%"
                    if c.stale
                    else f"距触发 {to_trigger * 100:.2f}% · 触发价 {c.trigger_price:.2f}"
                ),
                "reasons": reason,
            }
        )
    watch_items.sort(key=lambda x: (x["to_trigger_pct"], x["code"]))
    watch_items = watch_items[:WATCH_LIMIT]

    return buy_items, watch_items, filtered


def _holding_item(h: Holding) -> dict:
    state = h.state
    sell_pct = h.sell_pct
    advice = h.advice
    if h.t1_locked and state == "exit":
        state, sell_pct = "warn", 0.0
        advice = f"{advice}（T+1 当日只预警，次日执行）"

    reasons = [dict(r) for r in h.reasons]
    if h.avg_cost and h.current_price:
        reasons.append(
            {
                "kind": "flat",
                "text": (
                    f"持仓：成本 {h.avg_cost:.2f} → 现价 {h.current_price:.2f}"
                    f"（{(h.pnl_pct or 0):+.2f}%）"
                ),
            }
        )
    return {
        "code": h.code,
        "name": h.name,
        "source": h.source,
        "position_id": h.position_id,
        "state": state,
        "quantity": h.quantity,
        "avg_cost": h.avg_cost,
        "current_price": h.current_price,
        "pnl_pct": h.pnl_pct,
        "advice": advice,
        "advice_label": h.advice_label,
        "sell_pct": sell_pct,
        "reference_price": h.reference_price or h.current_price,
        "stop_loss_price": h.stop_loss_price,
        "reasons": reasons,
        "summary": f"{h.advice_label or ''} · {advice}".strip(" ·"),
    }


def decide(snap: Snapshot) -> dict:
    """执行规则层：返回买/盯/卖 + 方向过滤信息 + 可复现元数据。"""
    buy_items, watch_items, filtered = _build_buy_and_watch(snap)

    sell_items = [
        _holding_item(h) for h in snap.holdings if h.state in ("exit", "warn")
    ]
    sell_items.sort(key=lambda x: 0 if x["state"] == "exit" else 1)
    hold_count = sum(1 for h in snap.holdings if h.state not in ("exit", "warn"))

    direction = snap.direction
    return {
        "buy": {
            "count": len(buy_items),
            "actionable_count": sum(1 for x in buy_items if not x["blocked"]),
            "items": buy_items,
            "filtered": filtered,
        },
        "watch": {
            "count": len(watch_items),
            "near_count": sum(
                1 for x in watch_items if not x["stale"] and x["distance_to_trigger"] >= -0.02
            ),
            "items": watch_items,
        },
        "sell": {
            "count": len(sell_items),
            "exit_count": sum(1 for x in sell_items if x["state"] == "exit"),
            "warn_count": sum(1 for x in sell_items if x["state"] == "warn"),
            "hold_count": hold_count,
            "items": sell_items,
        },
        "direction": {
            "status": direction.status,
            "usable": direction.usable,
            "attack_industries": list(direction.attack),
            "avoid_industries": list(direction.avoid),
            "as_of": direction.as_of,
            "direction": direction.direction,
            "conclusion": direction.conclusion,
            "note": direction.note,
        },
        "meta": {
            "rule_version": RULE_VERSION,
            "snapshot_hash": _snapshot_hash(snap),
            "as_of": snap.as_of,
            "trade_date": snap.trade_date,
            "rule_engine": "deterministic",
            "data_quality": list(snap.data_quality),
        },
    }
