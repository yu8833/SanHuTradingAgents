"""数据健康巡检服务 —— 定期扫描关键集合的重复率 / 覆盖率 / 新鲜度，写入 data_metrics。

背景：历史多次出现「人工梳理才发现的存量数据问题」——
  - stock_daily_quotes 10.6% (code,date) 跨源重复；
  - stock_daily_moneyflow 某交易日仅 9% 覆盖（部分同步永久固化）；
  - stock_dividend 同 (code, ex_date) 重复 15%（预案/实施公告重复入库）。

本任务每日定时巡检以下维度，异常即写入 data_metrics（前端数据健康页可查）：
  - stock_dividend    : (code, end_date) 重复组数（>0 即异常，唯一索引防线失效信号）
  - stock_daily_moneyflow : 最近交易日覆盖条数（<5000 视为覆盖不足）
  - stock_daily_quotes: 近 30 交易日跨源重复组合数（(code, trade_date) 对应 >1 个 data_source）
  - 新鲜度            : market_quotes / stock_daily_quotes 最新 trade_date 与当天日期
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# moneyflow 全市场完整覆盖阈值（与 tushare_sync_service 共用 settings.MONEYFLOW_COMPLETE_MIN）
def _moneyflow_complete_min() -> int:
    from app.core.config import settings

    return getattr(settings, "MONEYFLOW_COMPLETE_MIN", 5000)

# 巡检窗口：daily_quotes 重复检测只看近 N 个交易日，避免全表扫描
_DUP_LOOKBACK_DAYS = 30


async def dedupe_cross_source_daily_quotes(db=None, lookback_days: int = _DUP_LOOKBACK_DAYS) -> int:
    """收敛近 N 天 stock_daily_quotes 的跨源重复：同一 (code, trade_date, period) 只保留
    优先级最高的数据源记录（tushare > baostock > akshare > sina），删除其余副本。

    多源存储（唯一索引含 data_source）本身不阻止同股同日被两个源各写一份；读取端虽按
    source_rank 取源，但存量大表会产生冗余与重复计数，故每日按统一优先级收敛。返回删除条数。
    """
    from app.core.data_source_priority import source_rank

    if db is None:
        from app.core.database import get_mongo_db

        db = get_mongo_db()

    since = (datetime.now(BEIJING) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    pipeline = [
        {"$match": {"period": "daily", "trade_date": {"$gte": since}}},
        {"$group": {
            "_id": {"code": "$code", "date": "$trade_date", "period": "$period"},
            "docs": {"$push": {"id": "$_id", "src": {"$ifNull": ["$data_source", ""]}}},
        }},
        {"$match": {"docs.1": {"$exists": True}}},
    ]
    to_delete: list = []
    async for grp in db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True):
        docs = grp["docs"]
        keep = min(docs, key=lambda d: source_rank(d.get("src")))
        to_delete.extend(d["id"] for d in docs if d["id"] != keep["id"])

    removed = 0
    for i in range(0, len(to_delete), 500):
        chunk = to_delete[i:i + 500]
        res = await db["stock_daily_quotes"].delete_many({"_id": {"$in": chunk}})
        removed += res.deleted_count
    if removed:
        logger.info(f"🧹 stock_daily_quotes 跨源重复收敛：删除 {removed} 条低优先级副本")
    return removed


async def run_data_health_check() -> dict:
    """扫描关键集合，返回巡检结果并写入 data_metrics（幂等 upsert）。"""
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    checked_at = datetime.now(BEIJING)
    today = checked_at.strftime("%Y-%m-%d")

    results: dict = {"checked_at": checked_at, "date": today, "items": {}}
    degraded: list[str] = []

    # ── 1) stock_dividend：(code, end_date) 重复组数 ──
    try:
        n = 0
        async for _ in db["stock_dividend"].aggregate([
            {"$group": {"_id": {"code": "$code", "ed": "$end_date"}, "n": {"$sum": 1}}},
            {"$match": {"n": {"$gt": 1}}},
        ]):
            n += 1
        results["items"]["dividend_dup_groups"] = n
        if n > 0:
            degraded.append(f"stock_dividend (code,end_date) 重复组 {n} 组")
    except Exception as e:
        logger.error(f"数据健康巡检 dividend 失败: {e}")
        results["items"]["dividend_dup_groups"] = None

    # ── 2) stock_daily_moneyflow：最近交易日覆盖条数 ──
    try:
        latest_mf = None
        async for doc in db["stock_daily_moneyflow"].find(
            {}, {"trade_date": 1}
        ).sort("trade_date", -1).limit(1):
            latest_mf = str(doc.get("trade_date") or "")
        count = 0
        if latest_mf:
            count = await db["stock_daily_moneyflow"].count_documents(
                {"trade_date": latest_mf}
            )
        results["items"]["moneyflow_latest_date"] = latest_mf
        results["items"]["moneyflow_latest_count"] = count
        if latest_mf and count < _moneyflow_complete_min():
            degraded.append(
                f"stock_daily_moneyflow {latest_mf} 仅 {count} 条（<{_moneyflow_complete_min()}）"
            )
    except Exception as e:
        logger.error(f"数据健康巡检 moneyflow 失败: {e}")

    # ── 3) stock_daily_quotes：近 N 交易日跨源重复（先按优先级收敛，再统计残留）──
    try:
        removed = await dedupe_cross_source_daily_quotes(db)
        results["items"]["daily_quotes_cross_source_dup_removed"] = removed
        dup_combos = 0
        async for doc in db["stock_daily_quotes"].aggregate([
            {"$match": {
                "trade_date": {"$gte": (checked_at - timedelta(days=_DUP_LOOKBACK_DAYS)).strftime("%Y-%m-%d")}
            }},
            {"$group": {
                "_id": {"code": "$code", "date": "$trade_date"},
                "sources": {"$addToSet": "$data_source"},
            }},
            {"$match": {"sources.1": {"$exists": True}}},
        ]):
            dup_combos += 1
        results["items"]["daily_quotes_cross_source_dup_combos"] = dup_combos
        if dup_combos > 0:
            degraded.append(f"stock_daily_quotes 近{_DUP_LOOKBACK_DAYS}天跨源重复组合 {dup_combos} 个")
    except Exception as e:
        logger.error(f"数据健康巡检 daily_quotes 失败: {e}")
        results["items"]["daily_quotes_cross_source_dup_combos"] = None

    # ── 4) 新鲜度：market_quotes / stock_daily_quotes 最新交易日 ──
    try:
        from app.utils.date_utils import normalize_date

        # 两集合 trade_date 存量格式不同（market_quotes 为 YYYYMMDD、日线为 YYYY-MM-DD），
        # 必须归一后再比较，否则字符串比较恒判定日线"落后"
        latest_mq = None
        async for doc in db["market_quotes"].find(
            {}, {"trade_date": 1}
        ).sort("trade_date", -1).limit(1):
            latest_mq = normalize_date(doc.get("trade_date"))
        latest_dq = None
        async for doc in db["stock_daily_quotes"].find(
            {}, {"trade_date": 1}
        ).sort("trade_date", -1).limit(1):
            latest_dq = normalize_date(doc.get("trade_date"))
        results["items"]["market_quotes_latest"] = latest_mq
        results["items"]["daily_quotes_latest"] = latest_dq
        # 日线新鲜度：以行情最新交易日为权威指针（无需交易日历，天然规避周末/节假日误报）
        if latest_dq and latest_mq and latest_dq < latest_mq:
            degraded.append(
                f"stock_daily_quotes 最新交易日 {latest_dq} 落后于行情 {latest_mq}"
            )
        if latest_mq and latest_mq < (checked_at - timedelta(days=3)).strftime("%Y-%m-%d"):
            degraded.append(f"market_quotes 最新交易日 {latest_mq} 距今超过3天")
    except Exception as e:
        logger.error(f"数据健康巡检 新鲜度 失败: {e}")

    results["degraded"] = degraded
    results["ok"] = not degraded

    # 写入 data_metrics（幂等 upsert）
    try:
        await db["data_metrics"].update_one(
            {"job": "data_health_check"},
            {"$set": {
                "job": "data_health_check",
                "checked_at": checked_at,
                "date": today,
                "items": results["items"],
                "degraded": degraded,
                "ok": results["ok"],
                "updated_at": checked_at,
            }},
            upsert=True,
        )
    except Exception as e:
        logger.error(f"数据健康巡检结果写入 data_metrics 失败: {e}")

    logger.info(f"🔍 数据健康巡检完成: ok={results['ok']}, degraded={degraded}")
    return results
