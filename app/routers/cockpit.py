"""交易驾驶舱接口

区块化接口设计（各区块独立成败、独立时间戳，前端 Promise.allSettled 并行）：
- GET  /api/cockpit/gate        区块01：环境闸门（画像 × 情绪阶段）
- GET  /api/cockpit/mainline    区块02：主线方向（持续净流入行业 + 多周期矩阵）
- GET  /api/cockpit/pool        区块03：积累区观察池
- GET  /api/cockpit/signals     区块04：突破触发信号
- GET  /api/cockpit/positions   区块05：纪律持仓
- POST /api/cockpit/positions   标记买入
- POST /api/cockpit/positions/{id}/close  卖出/了结
- POST /api/cockpit/pool/rescan 手动重扫观察池（Redis 锁防重入）
- GET  /api/cockpit/replay      区块06：方法验证（最近 N 个交易日回放）
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.collections import Collections
from app.core.database import get_mongo_db, get_mongo_db_sync
from app.core.redis_client import get_redis_service
from app.core.response import fail, ok
from app.routers.auth_db import get_current_user
from app.services.cache_layer import cached
from app.services.cockpit import accumulation_scanner, gate_service, position_service, replay_service
from app.services.cockpit.accumulation_scanner import ACCUM_DEFAULTS, PARAMS_VERSION
from app.services.industry_dashboard import get_industry_period_flows
from app.services.quotes_service import get_quotes_service
from app.utils.timezone import now_tz
from app.utils.trading_time import is_trading_day

logger = logging.getLogger(__name__)
router = APIRouter()


class PositionCreate(BaseModel):
    code: str = Field(..., description="股票代码")
    buy_price: float = Field(..., gt=0, description="买入价")
    buy_date: str | None = Field(None, description="买入日期 YYYY-MM-DD，默认当日")


class PositionClose(BaseModel):
    sell_price: float = Field(..., gt=0, description="卖出价")
    sell_date: str | None = Field(None, description="卖出日期 YYYY-MM-DD，默认当日")


def _is_intraday(now: datetime) -> bool:
    if not is_trading_day(now.strftime("%Y%m%d")):
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 25) <= minutes <= (15 * 60 + 5)


def _fmt_trade_date(raw) -> str | None:
    """YYYYMMDD / YYYY-MM-DD → YYYY-MM-DD。"""
    if not raw:
        return None
    s = str(raw).replace("-", "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else str(raw)


async def _latest_close_map(db, codes: list[str]) -> tuple[dict[str, float], str | None]:
    """非交易时段现价来源：market_quotes 最新交易日收盘快照。

    日线库（stock_daily_quotes）在收盘后约 19:30 才同步当日数据，此窗口期内
    若只用池内日线快照，页面会显示上一交易日的收盘价（用户会误以为数据没更新）。
    用当日收盘快照富集，保证「距触发」始终反映最新真实收盘价。
    """
    if not codes:
        return {}, None
    try:
        latest = await db[Collections.market_quotes].find_one({}, {"trade_date": 1}, sort=[("trade_date", -1)])
        trade_date = (latest or {}).get("trade_date")
        if not trade_date:
            return {}, None
        rows = await db[Collections.market_quotes].find(
            {"trade_date": trade_date, "code": {"$in": codes}}, {"code": 1, "close": 1, "_id": 0}
        ).to_list(None)
        closes = {r["code"]: r["close"] for r in rows if r.get("close")}
        return closes, _fmt_trade_date(trade_date)
    except Exception as exc:
        logger.warning(f"读取当日收盘快照失败（不影响日线快照）: {exc}")
        return {}, None


async def _gate_cached(db) -> dict:
    # cached 依 iscoroutinefunction 判定：必须传 async 函数，lambda 包协程会被当同步函数处理
    async def _build() -> dict:
        return await gate_service.build_gate(db)

    return await cached("cockpit:gate", _build, category="market")


@router.get("/api/cockpit/gate")
async def get_gate(current_user: dict = Depends(get_current_user)):
    """区块 01：环境闸门。"""
    try:
        db = get_mongo_db()
        data = await _gate_cached(db)
        return ok(data)
    except Exception as exc:
        logger.error(f"获取环境闸门失败: {exc}", exc_info=True)
        return fail(f"获取环境闸门失败: {exc}")


@router.get("/api/cockpit/mainline")
async def get_mainline(current_user: dict = Depends(get_current_user)):
    """区块 02：主线方向（持续净流入行业 Top + 多周期资金矩阵）。"""
    try:
        db = get_mongo_db()
        flows = await get_industry_period_flows()
        periods = (flows or {}).get("periods") or {}

        # 池内行业分布（用于「池内 N 只」联动角标）
        pool_counts = await db[Collections.cockpit_watch_pool].aggregate(
            [
                {"$match": {"status": {"$in": ["watching", "near", "triggered"]}, "industry": {"$ne": ""}}},
                {"$group": {"_id": "$industry", "count": {"$sum": 1}}},
            ]
        ).to_list(None)
        pool_map = {d["_id"]: d["count"] for d in pool_counts}

        # 持续主线推导：3 日净额 >0 的行业，按周期前缀一致的最长长度排序。
        # 口径说明：streak 表示 3/5/10/20 日累计净额连续为正的最长前缀，
        # 是「周期净流入均为正」的代理，非逐日连续。页面 tooltip 需说明。
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

        mainlines = []
        for name, nets in net_by_name.items():
            streak = 0
            for key in ("3", "5", "10", "20"):
                if nets.get(key, 0) > 0:
                    streak = int(key)
                else:
                    break
            if streak >= 3:
                mainlines.append(
                    {
                        "name": name,
                        "pct_3d": pct_by_name.get(name, 0),
                        "net_3d": nets.get("3", 0),
                        "streak": streak,
                        "pool_count": pool_map.get(name, 0),
                    }
                )
        mainlines.sort(key=lambda x: (-x["streak"], -(x["net_3d"] or 0)))

        data = {
            "mainlines": mainlines[:10],
            "periods": periods,
            "as_of": (flows or {}).get("as_of"),
            "updated_at": (flows or {}).get("updated_at"),
            "source": "同花顺 90 行业（akshare 实时抓取）",
        }
        return ok(data)
    except Exception as exc:
        logger.error(f"获取主线方向失败: {exc}", exc_info=True)
        return fail(f"获取主线方向失败: {exc}")


@router.get("/api/cockpit/pool")
async def get_pool(
    status: str | None = Query(None, description="状态过滤，逗号分隔：watching/near/triggered"),
    industry: str | None = Query(None, description="行业过滤"),
    current_user: dict = Depends(get_current_user),
):
    """区块 03：积累区观察池。"""
    try:
        db = get_mongo_db()
        statuses = [s.strip() for s in status.split(",") if s.strip()] if status else ["watching", "near", "triggered"]
        query: dict = {"status": {"$in": statuses}}
        if industry:
            query["industry"] = industry

        items = await db[Collections.cockpit_watch_pool].find(query, {"_id": 0}).sort("distance_to_trigger", 1).to_list(500)
        total = len(items)

        # 现价富集：交易时段用实时行情；收盘后用当日收盘快照（日线库尚未同步当日数据的窗口期）
        now = now_tz()
        quote_as_of = None
        if items:
            codes = [i["code"] for i in items]
            if _is_intraday(now):
                try:
                    quotes = await get_quotes_service().get_quotes(codes)
                    for i in items:
                        q = quotes.get(i["code"]) or {}
                        if q.get("close"):
                            i["current_price"] = q["close"]
                            if i.get("trigger_price"):
                                i["distance_to_trigger"] = round(q["close"] / i["trigger_price"] - 1, 4)
                except Exception as exc:
                    logger.warning(f"观察池现价富集失败（不影响快照数据）: {exc}")
            else:
                closes, quote_as_of = await _latest_close_map(db, codes)
                for i in items:
                    c = closes.get(i["code"])
                    if c:
                        i["current_price"] = c
                        if i.get("trigger_price"):
                            i["distance_to_trigger"] = round(c / i["trigger_price"] - 1, 4)

        scanned_at = max((i.get("last_scan_date") or "" for i in items), default="")
        data = {
            "items": items,
            "total": total,
            "scanned_at": scanned_at,
            "quote_as_of": quote_as_of,
            "trading_session": _is_intraday(now),
            "params": {
                "signal": "B1 左侧买点（全市场真源）",
                "accumulation": "积累区四条件",
                "no_new_low": f"{ACCUM_DEFAULTS['no_new_low_long']}日不创新低",
                "vol_pctile_max": ACCUM_DEFAULTS["vol_pctile_max"],
                "converge": f"{ACCUM_DEFAULTS['converge_days']}日振幅收敛≤{ACCUM_DEFAULTS['converge_ratio_max']}",
                "min_avg_amount": "20日日均成交额≥1亿",
                "exclude": "剔除ST/退市/次新",
            },
            "params_version": PARAMS_VERSION,
            "params_note": "经验参数 · 待回测校准",
        }
        return ok(data)
    except Exception as exc:
        logger.error(f"获取观察池失败: {exc}", exc_info=True)
        return fail(f"获取观察池失败: {exc}")


@router.get("/api/cockpit/signals")
async def get_signals(current_user: dict = Depends(get_current_user)):
    """区块 04：B2 突破买点信号（已触发 / 临近 / 观察中）。"""
    try:
        db = get_mongo_db()
        coll = db[Collections.cockpit_watch_pool]
        triggered = (
            await coll.find({"status": "triggered"}, {"_id": 0}).sort("triggered_at", -1).limit(50).to_list(50)
        )
        near = await coll.find({"status": "near"}, {"_id": 0}).sort("distance_to_trigger", -1).to_list(100)
        watching_count = await coll.count_documents({"status": "watching"})
        last_check = await coll.find_one(
            {"last_intraday_check": {"$exists": True}}, {"last_intraday_check": 1}, sort=[("last_intraday_check", -1)]
        )

        # 现价富集：交易时段用实时行情；收盘后用当日收盘快照
        now = now_tz()
        quote_as_of = None
        codes = [t["code"] for t in triggered] + [n["code"] for n in near]
        if codes:
            if _is_intraday(now):
                try:
                    quotes = await get_quotes_service().get_quotes(codes)
                    for row in triggered + near:
                        q = quotes.get(row["code"]) or {}
                        if q.get("close"):
                            row["current_price"] = q["close"]
                except Exception as exc:
                    logger.warning(f"信号区现价富集失败: {exc}")
            else:
                closes, quote_as_of = await _latest_close_map(db, codes)
                for row in triggered + near:
                    c = closes.get(row["code"])
                    if c:
                        row["current_price"] = c

        first_scan = await coll.find_one(
            {"first_seen_date": {"$exists": True}}, {"first_seen_date": 1}, sort=[("first_seen_date", 1)]
        )
        intraday = _is_intraday(now)
        data = {
            "triggered": triggered,
            "near": near,
            "watching_count": watching_count,
            "last_check_at": (last_check or {}).get("last_intraday_check"),
            "trading_session": intraday,
            "quote_as_of": quote_as_of,
            "pool_since": (first_scan or {}).get("first_seen_date"),
            "signal": "B2 突破买点",
            "trigger_basis": "放量 + 中阳 + 站上 MA55/MA60（与 Candidate 同一真源）",
            "scan_note": "盘中每 15 分钟按 B2 扫描" if intraday else "收盘后不扫描 · 下一检测窗口为下一交易日 09:30 起",
        }
        return ok(data)
    except Exception as exc:
        logger.error(f"获取突破信号失败: {exc}", exc_info=True)
        return fail(f"获取突破信号失败: {exc}")


@router.get("/api/cockpit/positions")
async def get_positions(current_user: dict = Depends(get_current_user)):
    """区块 05：纪律持仓。"""
    try:
        db = get_mongo_db()
        user_id = current_user.get("user_id")
        data = await position_service.list_positions(db, user_id)
        return ok(data)
    except Exception as exc:
        logger.error(f"获取纪律持仓失败: {exc}", exc_info=True)
        return fail(f"获取纪律持仓失败: {exc}")


@router.post("/api/cockpit/positions")
async def create_position(payload: PositionCreate, current_user: dict = Depends(get_current_user)):
    """标记买入（从信号转入或手动添加）。"""
    try:
        db = get_mongo_db()
        user_id = current_user.get("user_id")
        doc = await position_service.create_position(db, user_id, payload.code, payload.buy_price, payload.buy_date)
        return ok(doc, message="已标记买入，进入纪律跟踪")
    except ValueError as exc:
        return fail(str(exc))
    except Exception as exc:
        logger.error(f"标记买入失败: {exc}", exc_info=True)
        return fail(f"标记买入失败: {exc}")


@router.post("/api/cockpit/positions/{position_id}/close")
async def close_position(position_id: str, payload: PositionClose, current_user: dict = Depends(get_current_user)):
    """卖出/了结。"""
    try:
        db = get_mongo_db()
        user_id = current_user.get("user_id")
        success = await position_service.close_position(db, user_id, position_id, payload.sell_price, payload.sell_date)
        if not success:
            return fail("持仓不存在或已了结")
        return ok({"id": position_id}, message="已了结")
    except ValueError as exc:
        return fail(str(exc))
    except Exception as exc:
        logger.error(f"了结持仓失败: {exc}", exc_info=True)
        return fail(f"了结持仓失败: {exc}")


@router.get("/api/cockpit/replay")
async def get_replay(
    days: int = Query(10, ge=1, le=10, description="回放交易日数（1~10，默认 10）"),
    current_user: dict = Depends(get_current_user),
):
    """区块 06：方法验证 —— 最近 N 个交易日的积累区突破回放（日线收盘口径）。"""
    try:
        async def _build() -> dict:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, replay_service.replay_recent, days)

        # 回放为全市场重算（较重），用 market 级缓存在非交易时段复用 30 分钟
        data = await cached(f"cockpit:replay:{days}", _build, category="market")
        return ok(data)
    except Exception as exc:
        logger.error(f"回放验证失败: {exc}", exc_info=True)
        return fail(f"回放验证失败: {exc}")


@router.post("/api/cockpit/pool/rescan")
async def rescan_pool(current_user: dict = Depends(get_current_user)):
    """手动重扫观察池（Redis 分布式锁防重入）。"""
    redis_service = get_redis_service()
    lock_key = "lock:cockpit:accumulation_scan"
    lock_value = None
    if redis_service:
        try:
            lock_value = await redis_service.acquire_lock(lock_key, timeout=3600)
            if not lock_value:
                return fail("扫描任务正在执行中，请稍后重试")
        except Exception as exc:
            logger.warning(f"获取扫描锁失败（退化允许执行）: {exc}")

    try:
        db = get_mongo_db()
        sync_db = get_mongo_db_sync()
        latest = sync_db[Collections.stock_daily_quotes].find_one(sort=[("trade_date", -1)])
        trade_date = (latest or {}).get("trade_date")
        if not trade_date:
            return fail("日线数据为空，无法扫描")

        summary = await accumulation_scanner.run_daily_accumulation_scan(db, trade_date)
        return ok(summary, message=f"扫描完成：候选 {summary.get('total', 0)} 只")
    except Exception as exc:
        logger.error(f"手动重扫失败: {exc}", exc_info=True)
        return fail(f"手动重扫失败: {exc}")
    finally:
        if redis_service and lock_value:
            try:
                await redis_service.release_lock(lock_key, lock_value)
            except Exception:
                pass
