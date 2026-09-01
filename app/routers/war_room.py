"""作战室聚合 API 路由（P4）。

设计文档《第六章·交易工具与日常流程》§4 缺口4 + 附录A A.4：
- GET /api/war-room/today  聚合「当前时段 + 各段待办计数 + 今日快照是否已生成」，
                           供速览页"今日流程引导条"与作战室顶部使用。
"""

from __future__ import annotations

import logging
from datetime import time as dtime

from fastapi import APIRouter, Depends, Header

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/war-room", tags=["war-room"])
logger = logging.getLogger("webapi")


async def _get_optional_user(authorization: str | None = Header(default=None)) -> dict:
    """可选鉴权：无 token 视为 guest（返回空 user_id）。"""
    if not authorization:
        return {"id": None, "username": "guest", "is_guest": True}
    try:
        user = await get_current_user(authorization)
        user["is_guest"] = False
        return user
    except Exception:
        return {"id": None, "username": "guest", "is_guest": True}


def _current_period() -> str:
    """按北京时间判断当前时段：pre_market / intraday / post_market / weekly。"""
    now = now_tz()
    if now.weekday() == 4 and now.time() >= dtime(15, 0):  # 周五盘后
        return "weekly"
    t = now.time()
    if dtime(8, 0) <= t < dtime(9, 30):
        return "pre_market"
    if dtime(9, 30) <= t < dtime(15, 0):
        return "intraday"
    if dtime(20, 0) <= t < dtime(21, 30):
        return "post_market"
    # 其余时段：20点前归入盘中延伸/盘后待办，21:30 后视为盘后
    return "post_market"


@router.get("/today-trades")
async def war_room_today_trades(user: dict = Depends(get_current_user)):
    """当日成交记录（盘后 Tab3③ 交易复盘）：按用户+当日 paper_trades 流水，倒序返回。"""
    try:
        db = get_mongo_db()
        today = now_tz().strftime("%Y-%m-%d")
        # timestamp 为 BSON datetime（UTC 存库）；今日北京时区窗口 [00:00, 明日 00:00)
        from datetime import datetime as _dt, timedelta as _td
        from app.utils.timezone import now_tz as _now_tz
        now_bj = _now_tz()
        start = _dt.combine(now_bj.date(), dtime(0, 0))
        end = start + _td(days=1)
        docs = await db["paper_trades"].find({
            "user_id": user["id"],
            "$or": [
                {"timestamp": {"$gte": start, "$lt": end}},
                {"trade_date": today},
            ],
        }).sort("timestamp", -1).limit(50).to_list(length=50)
        items = []
        for t in docs:
            ts = t.get("timestamp")
            items.append({
                "code": t.get("code", ""),
                "name": t.get("stock_name") or t.get("code", ""),
                "side": t.get("side"),
                "quantity": int(t.get("quantity") or 0),
                "price": t.get("price"),
                "amount": t.get("amount"),
                "pnl": t.get("pnl"),
                "strategy": t.get("strategy"),
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
            })
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"当日成交记录读取失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="当日成交记录读取失败")


@router.get("/today-alerts")
async def war_room_today_alerts(user: dict = Depends(get_current_user)):
    """今日触发预警列表（盘中 Tab 预警待办）：monitor_alerts 今日记录，时间倒序。
    与 /today 的 intraday.alert_count 同口径（ts >= 今日 00:00），保证角标数=列表行数。"""
    try:
        db = get_mongo_db()
        now_bj = now_tz()
        day_start_ms = int(now_bj.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        docs = await db["monitor_alerts"].find(
            {"ts": {"$gte": day_start_ms}}
        ).sort("ts", -1).limit(100).to_list(length=100)
        items = []
        for a in docs:
            items.append({
                "id": str(a.get("_id")),
                "ts": a.get("ts"),
                "rule_name": a.get("rule_name", ""),
                "source": a.get("source", ""),
                "symbol": a.get("symbol", ""),
                "name": a.get("name", ""),
                "message": a.get("message", ""),
                "price": a.get("price"),
                "change_pct": a.get("change_pct"),
                "signals": a.get("signals", []),
                "severity": a.get("severity", "info"),
            })
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"今日预警读取失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="今日预警读取失败")


@router.get("/today")
async def war_room_today(user: dict = Depends(_get_optional_user)):
    """今日作战聚合：当前时段 + 各段待办计数 + 宏观快照是否已生成。
    可选鉴权：guest 也可访问，用户相关字段（计划/持仓/周复盘）返回 0/False。"""
    try:
        db = get_mongo_db()
        today = now_tz().strftime("%Y-%m-%d")
        uid = user.get("id")

        # 盘前：今日宏观快照是否已生成 + 当日计划待执行数
        macro_snap = await db["macro_daily_snapshots"].find_one(
            {"date": today}, {"_id": 0, "date": 1}
        )
        if uid:
            plan_pending = await db["daily_plans"].count_documents(
                {"user_id": uid, "date": today, "status": "pending"}
            )
            plan_total = await db["daily_plans"].count_documents(
                {"user_id": uid, "date": today}
            )
        else:
            plan_pending = 0
            plan_total = 0

        # 盘中：当前持仓数（非空仓）
        if uid:
            holding_count = await db["paper_positions"].count_documents(
                {"user_id": uid, "quantity": {"$gt": 0}}
            )
        else:
            holding_count = 0
        # 盘中待办：今日触发的监控预警（monitor_alerts 触发记录，对应监控中心"预警"Tab）。
        # 注意：不用 stock_alerts（那是"预警规则"，是配置不是待办），否则会把规则数误当预警数。
        now_bj = now_tz()
        day_start_ms = int(now_bj.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        alert_count = await db["monitor_alerts"].count_documents(
            {"ts": {"$gte": day_start_ms}}
        )

        # 盘后：待验证信号数（signal_tracking）
        signal_pending = await db["signal_tracking"].count_documents(
            {"status": "pending"}
        )
        signal_total = await db["signal_tracking"].count_documents({})

        # 周度：本周复盘是否已生成
        week_start = (now_tz().date() - __import__("datetime").timedelta(
            days=now_tz().weekday()
        )).strftime("%Y-%m-%d")
        if uid:
            weekly_done = (
                await db["weekly_reviews"].count_documents(
                    {"user_id": uid, "week_start": week_start}
                )
                > 0
            )
        else:
            weekly_done = False

        # 周度待办：仅当「已到本周五盘后 17:30」且尚未生成复盘时才记待办；
        # 未到周五盘前/盘中不提示，避免周一到周五一整天都顶着红色角标。
        now_dt = now_tz()
        friday_1730 = (now_dt - __import__("datetime").timedelta(
            days=now_dt.weekday() - 4
        )).replace(hour=17, minute=30, second=0, microsecond=0)
        weekly_due = now_dt >= friday_1730
        weekly_todo = 0 if (weekly_done or not weekly_due) else 1

        # 各段待办计数（与前端 flowSegments 角标口径完全一致，保证「待办合计」= 四段角标之和）
        pre_todo = plan_pending + (0 if bool(macro_snap) else 1)
        intra_todo = alert_count
        post_todo = signal_pending
        total_todo = pre_todo + intra_todo + post_todo + weekly_todo

        return ok({
            "current_period": _current_period(),
            "today": today,
            "week_start": week_start,
            "pre_market": {
                "macro_snapshot_ready": bool(macro_snap),
                "plan_pending": plan_pending,
                "plan_total": plan_total,
                "todo": pre_todo,
            },
            "intraday": {
                "holding_count": holding_count,
                "alert_count": alert_count,
                "todo": intra_todo,
            },
            "post_market": {
                "signal_pending": signal_pending,
                "signal_total": signal_total,
                "todo": post_todo,
            },
            "weekly": {
                "done": weekly_done,
                "todo": weekly_todo,
            },
            "total_todo": total_todo,
        })
    except Exception as e:
        logger.error(f"作战室今日聚合失败: {e}", exc_info=True)
        today = now_tz().strftime("%Y-%m-%d")
        return ok({
            "current_period": "pre_market",
            "today": today,
            "pre_market": {"macro_snapshot_ready": False, "plan_pending": 0, "plan_total": 0},
            "intraday": {"holding_count": 0, "alert_count": 0},
            "post_market": {"signal_pending": 0, "signal_total": 0},
            "weekly": {"done": False},
            "total_todo": 0,
        }, message="作战室今日聚合失败")
