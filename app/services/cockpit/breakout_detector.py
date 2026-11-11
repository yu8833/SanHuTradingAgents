"""盘中突破检测（交易驾驶舱 · 区块 04 右侧确认）

口径统一：右侧确认复用三买三卖 B2 突破买点（放量 + 中阳 + 站上 MA55&MA60），
与 Candidate 页同一真源，不再另写「触发价 + 量比」规则。

挂入盘中统一扫描（每 15 分钟）：
1. 读观察池（watching/near，池内已满足 03 = B1 ∩ 积累区）标的
2. 逐只调用 three_buys_three_sells_service.check_single_stock（已合并当日实时快照）
3. 命中 B2 → 右侧确认信号：更新池状态 → 写 monitor_alerts → 通知推送（每码每日仅一次）
4. 顺带评估纪律持仓的盘中预警（统一走 evaluate_unified_exit），每仓每日每类一次
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.core.collections import Collections
from app.core.database import get_mongo_db
from app.services.notifications_service import NotificationCreate, get_notifications_service
from app.services.quotes_service import get_quotes_service
from app.services.retail.exit_rule_engine import PositionExitContext, evaluate_unified_exit
from app.utils.timezone import now_tz
from app.utils.trading_time import is_trading_day

logger = logging.getLogger(__name__)

# 触发去重：code -> 已触发的交易日（内存态，池文档 last_triggered_date 双保险）
_last_fire: dict[str, str] = {}
# 持仓预警去重：(position_id, warn_type) -> 交易日
_last_pos_warn: dict[tuple[str, str], str] = {}

NEAR_THRESHOLD = 0.02  # 距触发 <2% 视为临近

# 预警类型 → 通知标签
_WARN_LABELS = {
    "stop_loss": "触发止损",
    "false_breakout": "假突破预警",
    "ma_break": "跌破MA5预警",
    "ma5_break": "跌破MA5预警",
    "take_profit": "触及止盈",
    "signal": "卖点信号",
    "time_stop": "持仓超期",
}


def _session_progress(now: datetime) -> float | None:
    """盘中时间进度（0~1）。非连续竞价时段返回 None。"""
    minutes = now.hour * 60 + now.minute
    am_start, am_end = 9 * 60 + 30, 11 * 60 + 30
    pm_start, pm_end = 13 * 60, 15 * 60
    if am_start <= minutes <= am_end:
        return (minutes - am_start) / 240.0
    if pm_start <= minutes <= pm_end:
        return (120 + minutes - pm_start) / 240.0
    return None


async def _notify_breakout(notif, user_ids: list[str], code: str, name: str, close: float, trigger: float, vol_ratio: float | None) -> None:
    title = f"【B2 突破买点】{name or code} 放量站上中期均线"
    content = (
        f"现价 {close:.2f}，量比 {vol_ratio if vol_ratio is not None else '—'}，"
        f"满足 B2 突破买点（放量 + 中阳 + 站上 MA55/MA60）。\n"
        f"积累区观察池标的完成右侧确认，请到模拟交易 · 交易驾驶舱查看并执行纪律。"
    )
    for uid in user_ids:
        try:
            await notif.create_and_publish(
                payload=NotificationCreate(
                    user_id=uid,
                    type="alert",
                    title=title,
                    content=content,
                    link="/paper",
                    source="cockpit_breakout",
                    severity="info",
                    metadata={"symbol": code, "trigger_price": trigger, "vol_ratio": vol_ratio},
                )
            )
        except Exception as exc:
            logger.error(f"推送突破通知失败: user={uid}, {code}, error={exc}")


async def _notify_position_exit(notif, user_id: str, code: str, name: str, warn_type: str, detail: str) -> None:
    label = _WARN_LABELS.get(warn_type, "持仓预警")
    try:
        await notif.create_and_publish(
            payload=NotificationCreate(
                user_id=user_id,
                type="alert",
                title=f"【{label}】{name or code} 需要关注",
                content=detail,
                link="/paper",
                source="cockpit_exit",
                severity="warning",
                metadata={"symbol": code, "warn_type": warn_type},
            )
        )
    except Exception as exc:
        logger.error(f"推送持仓预警失败: user={user_id}, {code}, error={exc}")


async def _check_b2(code: str) -> dict | None:
    """单只股票的三买三卖检查（含实时快照合并），返回原始结果。"""
    from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service

    try:
        return await get_three_buys_three_sells_service().check_single_stock(code)
    except Exception as exc:
        logger.warning(f"B2 检测失败 {code}: {exc}")
        return None


async def check_breakout_signals() -> None:
    """盘中统一扫描第 3 步：观察池 B2 突破确认。"""
    now = now_tz()
    progress = _session_progress(now)
    if progress is None:
        return
    if not is_trading_day(now.strftime("%Y%m%d")):
        return

    trade_date = now.strftime("%Y-%m-%d")
    db = get_mongo_db()
    pool_coll = db[Collections.cockpit_watch_pool]

    pool = await pool_coll.find(
        {"status": {"$in": ["watching", "near"]}},
        {"code": 1, "name": 1, "industry": 1, "trigger_price": 1, "last_triggered_date": 1},
    ).to_list(500)
    if not pool:
        return

    semaphore = asyncio.Semaphore(5)

    async def _evaluate(doc: dict) -> tuple[dict, dict | None]:
        async with semaphore:
            return doc, await _check_b2(doc["code"])

    results = await asyncio.gather(*[_evaluate(d) for d in pool])

    now_utc = now.astimezone(timezone.utc)
    check_ts = now.replace(microsecond=0)
    triggered_list: list[dict] = []

    for doc, res in results:
        code = doc["code"]
        if not res or not res.get("success"):
            continue
        close = res.get("close")
        trigger = doc.get("trigger_price")
        if not close:
            continue

        signals = res.get("signals") or []
        b2 = next((s for s in signals if s.get("type") == "B2"), None)
        distance = close / trigger - 1 if trigger else None

        update: dict = {
            "last_price": close,
            "last_intraday_check": check_ts,
        }
        if distance is not None:
            update["distance_to_trigger"] = round(distance, 4)

        new_status = None
        if b2:
            new_status = "triggered"
        elif distance is not None and -NEAR_THRESHOLD <= distance < 0:
            new_status = "near"
        elif doc.get("status") == "near":
            new_status = "watching"

        if new_status:
            update["status"] = new_status

        if b2:
            vol_ratio = b2.get("volume_ratio")
            update.update(
                {
                    "b2_trigger_price": b2.get("trigger_price"),
                    "b2_volume_ratio": vol_ratio,
                    "b2_ma55": b2.get("ma55"),
                    "b2_ma60": b2.get("ma60"),
                }
            )
            # 去重：内存 + 文档双保险
            if _last_fire.get(code) == trade_date or doc.get("last_triggered_date") == trade_date:
                update["status"] = "triggered"
            else:
                _last_fire[code] = trade_date
                update["status"] = "triggered"
                update["triggered_at"] = now_utc
                update["last_triggered_date"] = trade_date
                triggered_list.append({**doc, "close": close, "vol_ratio": vol_ratio, "b2": b2})

        await pool_coll.update_one({"code": code}, {"$set": update})

    if not triggered_list:
        return

    # 通知目标：纪律持仓用户 ∪ 模拟持仓用户（单用户系统即本人）
    try:
        uids_cockpit = await db[Collections.cockpit_positions].distinct("user_id", {"status": "open"})
        uids_paper = await db[Collections.paper_positions].distinct("user_id", {"quantity": {"$gt": 0}})
        user_ids = sorted({str(u) for u in (uids_cockpit + uids_paper) if u})
    except Exception as exc:
        logger.error(f"获取通知用户失败: {exc}")
        user_ids = []

    notif = get_notifications_service()
    alerts_coll = db[Collections.monitor_alerts]
    for item in triggered_list:
        code, name = item["code"], item.get("name", "")
        close, trigger, vol_ratio = item["close"], item.get("trigger_price"), item.get("vol_ratio")
        try:
            await alerts_coll.insert_one(
                {
                    "rule_id": "cockpit_b2_breakout",
                    "scope": "cockpit",
                    "symbol": code,
                    "name": name,
                    "ts": now_utc,
                    "trade_date": trade_date,
                    "price": close,
                    "severity": "info",
                    "message": f"B2 突破买点：现价 {close:.2f}，量比 {vol_ratio if vol_ratio is not None else '—'}",
                    "extra": {"trigger_price": trigger, "vol_ratio": vol_ratio, "industry": item.get("industry", "")},
                    "source": "cockpit_b2_breakout",
                    "created_at": now_utc,
                }
            )
        except Exception as exc:
            logger.error(f"写入 monitor_alerts 失败: {code}, error={exc}")

    if user_ids:
        for item in triggered_list:
            await _notify_breakout(
                notif, user_ids, item["code"], item.get("name", ""),
                item["close"], item.get("trigger_price"), item.get("vol_ratio"),
            )

    logger.info(f"✅ 驾驶舱 B2 突破检测: 新触发 {len(triggered_list)} 只 → {[t['code'] for t in triggered_list]}")


async def check_position_exit_warnings() -> None:
    """盘中统一扫描第 4 步：纪律持仓离场预警（统一走 evaluate_unified_exit）。

    同时消费三买三卖卖点（S1/S2/S3/SafetyNet/TrailingStop），并把结论落库到
    持仓文档，供 05 区块直接展示（避免接口内重复重算）。
    T+1 约束：买入当日不发预警（当日无法卖出），次日起生效。
    """
    now = now_tz()
    progress = _session_progress(now)
    if progress is None or not is_trading_day(now.strftime("%Y%m%d")):
        return

    trade_date = now.strftime("%Y-%m-%d")
    db = get_mongo_db()
    positions = await db[Collections.cockpit_positions].find({"status": "open"}).to_list(200)
    if not positions:
        return

    codes = [p["code"] for p in positions]
    quotes = await get_quotes_service().get_quotes(codes)
    if not quotes:
        return

    pool_docs = await db[Collections.cockpit_watch_pool].find(
        {"code": {"$in": codes}}, {"code": 1, "ma5": 1, "ma20": 1, "trigger_price": 1}
    ).to_list(None)
    pool_map = {d["code"]: d for d in pool_docs}

    from app.services.intraday_guide_service import evaluate_sell_signal

    notif = get_notifications_service()
    now_utc = now.astimezone(timezone.utc)
    for pos in positions:
        code = pos["code"]
        q = quotes.get(code) or {}
        close = q.get("close")
        if not close:
            continue

        pool = pool_map.get(code) or {}
        pos_id = str(pos.get("_id"))
        name = pos.get("name", "")

        sig = await evaluate_sell_signal(code)
        signal = (
            {
                "signal_type": sig.get("signal_type"),
                "sell_pct": sig.get("sell_pct"),
                "reasons": sig.get("reasons"),
            }
            if sig and sig.get("signal_type")
            else None
        )

        decision = evaluate_unified_exit(
            PositionExitContext(
                symbol=code,
                buy_price=float(pos.get("buy_price") or 0),
                current_price=close,
                buy_date=pos.get("buy_date"),
                trade_date=trade_date,
                trigger_price=pos.get("trigger_price") or pool.get("trigger_price"),
                stop_loss_price=pos.get("stop_loss_price"),
                ma5=(sig or {}).get("ma5") or pool.get("ma5"),
                ma20=(sig or {}).get("ma20") or pool.get("ma20"),
                is_intraday=True,
                signal=signal,
            )
        )

        # 落库统一结论（当日有效），05 区块直接读取
        try:
            await db[Collections.cockpit_positions].update_one(
                {"_id": pos["_id"]},
                {
                    "$set": {
                        "exit_state": decision.state,
                        "exit_reasons": [r["text"] for r in decision.reasons],
                        "exit_signal_type": decision.signal_type,
                        "exit_pnl_pct": round(decision.current_pnl_pct, 4),
                        "exit_trade_date": trade_date,
                        "exit_checked_at": now_utc,
                    }
                },
            )
        except Exception as exc:
            logger.warning(f"落库离场结论失败 {code}: {exc}")

        if pos.get("buy_date") == trade_date:
            continue  # T+1：买入当日无法卖出，不预警
        if decision.state == "normal" or not decision.reasons:
            continue
        warn_type = decision.reason.value if decision.reason.value != "none" else "ma5_break"
        if _last_pos_warn.get((pos_id, warn_type)) == trade_date:
            continue
        _last_pos_warn[(pos_id, warn_type)] = trade_date
        detail = "；".join(r["text"] for r in decision.reasons[:2])
        await _notify_position_exit(notif, str(pos.get("user_id")), code, name, warn_type, detail)
