"""作战室聚合 API 路由（P4）。

设计文档《第六章·交易工具与日常流程》§4 缺口4 + 附录A A.4：
- GET /api/war-room/today  聚合「当前时段 + 各段待办计数 + 今日快照是否已生成」，
                           供速览页"今日流程引导条"与作战室顶部使用。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import time as dtime

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

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


@router.get("/intraday-guide")
async def war_room_intraday_guide(user: dict = Depends(get_current_user)):
    """盘中买卖实时指导：
      buys:  当日 pending 买入计划 + 当日未确认买入候选 → 实时价触达/偏离/建议
      sells: 持仓逐只评估 → 持有/减仓/清仓/止损/止盈 建议（含卖出触发价）

    输出与 plan_generation 的 sell_candidates 同源（intraday_guide_service），
    但「盘中」版本叠加实时行情，判定止损/止盈/触达更及时。
    """
    try:
        from app.services.intraday_guide_service import build_intraday_guide
        guide = await build_intraday_guide(user["id"])
        return ok(guide)
    except Exception as e:
        logger.error(f"盘中买卖指导生成失败: {e}", exc_info=True)
        return ok({"as_of": None, "buys": [], "sells": [], "buy_count": 0, "sell_count": 0},
                  message="盘中买卖指导生成失败")


@router.post("/daily-plan/generate")
async def war_room_generate_daily_plan(user: dict = Depends(get_current_user)):
    """5.3 启动当日计划生成任务。

    四段计算较重（约 50-150s 冷算），改为后台任务：立即返回 job_id，前端经
    GET /daily-plan/stream/{job_id} SSE 实时接收 环境→行业→个股→计划 进度，
    done 后经 GET /daily-plan/result/{job_id} 取回候选。不落库，由前端人工确认后写库。
    """
    try:
        from app.services.plan_generation_service import start_plan_job
        job = start_plan_job(user["id"])
        return ok({"job_id": job.get("job_id"), "status": job.get("status"),
                   "progress": job.get("progress", 0), "stage": job.get("stage")})
    except Exception as e:
        logger.error(f"当日计划任务创建失败: {e}", exc_info=True)
        return ok({"job_id": None, "status": "error", "progress": 0}, message="任务创建失败")


@router.get("/daily-plan/today")
async def war_room_today_daily_plan(user: dict = Depends(get_current_user)):
    """读取「今日计划快照」（盘前 8:15 预生成落库）：打开即读、纯读秒回。

    快照未生成（如尚未到盘前任务 / 冷启动）返回 generated=false，前端再走 POST generate。
    """
    from app.services.plan_generation_service import load_daily_plan_snapshot
    today = now_tz().strftime("%Y-%m-%d")
    try:
        result = await load_daily_plan_snapshot()
        return ok({"generated": result is not None, "date": today, "result": result})
    except Exception as e:
        logger.error(f"今日计划快照读取失败: {e}", exc_info=True)
        return ok({"generated": False, "date": today, "result": None}, message="读取失败")


@router.get("/daily-plan/status/{job_id}")
async def war_room_plan_status(job_id: str, user: dict = Depends(get_current_user)):
    """查询计划生成任务状态（供 SSE 断连后轮询兜底）。"""
    from app.services.plan_generation_service import _job_view
    job = _job_view(job_id)
    if not job or job.get("user_id") != user["id"]:
        return ok(None, message="任务不存在")
    return ok(job)


@router.get("/daily-plan/result/{job_id}")
async def war_room_plan_result(job_id: str, user: dict = Depends(get_current_user)):
    """取回已完成任务的候选结果。"""
    from app.services.plan_generation_service import _plan_jobs, get_plan_result
    j = _plan_jobs.get(job_id)
    if not j or j.get("user_id") != user["id"]:
        return ok(None, message="任务不存在")
    result = await get_plan_result(job_id)
    if result is None:
        return ok(None, message="任务尚未完成")
    return ok(result)


@router.get("/daily-plan/stream/{job_id}")
async def war_room_plan_progress(job_id: str, user: dict = Depends(get_current_user)):
    """实时进度流：订阅 Redis pubsub `task_progress:{job_id}`，逐段推送审计进度。"""
    from app.services.plan_generation_service import _job_view
    job = _job_view(job_id)
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def gen():
        try:
            from app.core.database import get_redis_client
            r = get_redis_client()
        except Exception as e:
            logger.error(f"计划进度流 Redis 不可用: {e}")
            yield f"event: error\ndata: {{\"message\":\"Redis 不可用: {str(e)}\"}}\n\n"
            return
        pubsub = r.pubsub()
        channel = f"task_progress:{job_id}"
        await pubsub.subscribe(channel)
        try:
            yield f"event: connected\ndata: {{\"job_id\":\"{job_id}\",\"message\":\"已连接当日计划进度流\"}}\n\n"
            # —— 竞态兜底 ——
            # Redis pubsub 即发即弃（无队列）。当任务在 SSE 订阅前「秒完成」时，
            # 已 publish 的 done 事件会被丢弃，前端将一直等不到终态而永久转圈。
            # 这里在 connected 后直接回查任务真实状态，若已终态则补发并退出，
            # 保证「快任务」与「慢任务」都能可靠送达 done/error。
            from app.services.plan_generation_service import get_plan_result as _get_result
            from app.services.plan_generation_service import _json_default
            job_now = _job_view(job_id)
            if job_now and job_now.get("status") == "done":
                res = await _get_result(job_id)
                payload = {
                    "status": "done",
                    "stage": job_now.get("stage") or "计划",
                    "progress": 100,
                    "result": res,
                }
                yield "event: progress\ndata: " + json.dumps(
                    payload, ensure_ascii=False, default=_json_default
                ) + "\n\n"
                return
            if job_now and job_now.get("status") == "error":
                payload = {
                    "status": "error",
                    "stage": job_now.get("stage") or "环境",
                    "progress": job_now.get("progress", 0),
                    "message": job_now.get("error") or "计划生成失败",
                }
                yield "event: progress\ndata: " + json.dumps(
                    payload, ensure_ascii=False
                ) + "\n\n"
                return
            while True:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                if msg and msg.get("type") == "message":
                    yield f"event: progress\ndata: {msg['data']}\n\n"
                    try:
                        data = __import__("json").loads(msg["data"])
                        if data.get("status") in ("done", "error"):
                            break
                    except Exception:
                        pass
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.close()
            except Exception:
                pass

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        # 盘中待确认指令数（策略指令 Tab 的"待确认指令"，status=pending 的三买三卖订单）。
        pending_orders = await db["monitor_tbs_orders"].count_documents(
            {"user_id": uid, "status": "pending"}
        ) if uid else 0

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
        intra_todo = pending_orders
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
                "pending_orders": pending_orders,
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
