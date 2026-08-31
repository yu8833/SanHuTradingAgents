"""作战室聚合 API 路由（P4）。

设计文档《第六章·交易工具与日常流程》§4 缺口4 + 附录A A.4：
- GET /api/war-room/today  聚合「当前时段 + 各段待办计数 + 今日快照是否已生成」，
                           供速览页"今日流程引导条"与作战室顶部使用。
"""

from __future__ import annotations

import logging
from datetime import time as dtime

from fastapi import APIRouter, Depends

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.utils.timezone import now_tz

router = APIRouter(prefix="/api/war-room", tags=["war-room"])
logger = logging.getLogger("webapi")


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


@router.get("/today")
async def war_room_today(user: dict = Depends(get_current_user)):
    """今日作战聚合：当前时段 + 各段待办计数 + 宏观快照是否已生成。"""
    try:
        db = get_mongo_db()
        today = now_tz().strftime("%Y-%m-%d")

        # 盘前：今日宏观快照是否已生成 + 当日计划待执行数
        macro_snap = await db["macro_daily_snapshots"].find_one(
            {"date": today}, {"_id": 0, "date": 1}
        )
        plan_pending = await db["daily_plans"].count_documents(
            {"user_id": user["id"], "date": today, "status": "pending"}
        )
        plan_total = await db["daily_plans"].count_documents(
            {"user_id": user["id"], "date": today}
        )

        # 盘中：当前持仓数（非空仓）
        holding_count = await db["paper_positions"].count_documents(
            {"user_id": user["id"], "quantity": {"$gt": 0}}
        )
        # 监控预警数（stock_alerts 集合）
        alert_count = await db["stock_alerts"].count_documents(
            {"user_id": user["id"]}
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
        weekly_done = (
            await db["weekly_reviews"].count_documents(
                {"user_id": user["id"], "week_start": week_start}
            )
            > 0
        )

        return ok({
            "current_period": _current_period(),
            "today": today,
            "week_start": week_start,
            "pre_market": {
                "macro_snapshot_ready": bool(macro_snap),
                "plan_pending": plan_pending,
                "plan_total": plan_total,
            },
            "intraday": {
                "holding_count": holding_count,
                "alert_count": alert_count,
            },
            "post_market": {
                "signal_pending": signal_pending,
                "signal_total": signal_total,
            },
            "weekly": {
                "done": weekly_done,
            },
            "total_todo": plan_pending + alert_count + signal_pending,
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
