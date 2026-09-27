"""统一交易日历服务 —— 单一事实来源(trade_calendar 表) + 内存视图 + 实收交叉校验。

背景：此前交易日历按用途分裂为三套（trading_time.is_trading_day 用 chinese_calendar 规则、
_recent_dates 用 stock_daily_quotes distinct 实收口径、tushare 同步各自用 trade_cal），
判定易冲突（如周末/调休日被当日伪帧吞并 → 资金类图为空）。

本服务收敛为：
- `trade_calendar` 集合：Tushare `trade_cal(exchange="SSE")` 全量入库（含 is_open），每日刷新；
- 内存视图（开市日集合）：`is_open_day()` 纯同步 O(1) 判定，供 trading_time.is_trading_day
  统一走权威日历，零 DB 开销；未装载时返回 None 由调用方降级 chinese_calendar；
- `query_trade_days()` / `effective_trade_days()`：区间开市日 + 与 stock_daily_quotes 实收交叉校验，
  供 _recent_dates 以「官方日历为候选、实收数据为准」替代全表 distinct（消除 20s 冷建）。

约定：日期统一 YYYY-MM-DD 存储；入库含 is_open 便于权威判断。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.collections import col

logger = logging.getLogger(__name__)

# 日历覆盖范围（Tushare trade_cal 全量区间）
_CAL_START_YEAR = 2000
_CAL_END_YEAR = 2035

# 内存视图：开市日集合(YYYY-MM-DD)；loaded_date 记录内存装载日期(当天有效)
_STATE: dict = {"open": frozenset(), "loaded_date": None}


def _norm(d) -> str:
    """date/datetime/YYYYMMDD/YYYY-MM-DD → 'YYYY-MM-DD'（委托统一日期工具；非法回退截断，保持原约定）。"""
    from app.utils.date_utils import normalize_date
    norm = normalize_date(d)
    if norm is not None:
        return norm
    s = str(d).strip()
    return s[:10] if len(s) >= 10 else s


def _is_open_day_memory(d: str) -> bool | None:
    """内存视图判定。内存未装载返回 None（调用方自行降级）。"""
    if not _STATE["open"]:
        return None
    return d in _STATE["open"]


def is_open_day(date_arg) -> bool | None:
    """同步判定某天是否为开市日（内存 O(1)，不访问 DB/网络）。

    返回 True/False；内存未装载（进程冷启动早期）返回 None，调用方应降级。
    """
    try:
        d = _norm(date_arg)
    except (TypeError, ValueError):
        return None
    return _is_open_day_memory(d)


def _fetch_year_calendar_blocking(year: int) -> list[dict]:
    """单年 Tushare trade_cal 拉取（阻塞，供 to_thread）；返回 [{date, is_open}]。"""
    import os

    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        logger.warning("Tushare token 缺失，无法同步交易日历")
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    ts.set_token(token)
    pro = ts.pro_api()
    df = pro.trade_cal(
        exchange="SSE",
        start_date=f"{year}0101",
        end_date=f"{year}1231",
    )
    if df is None or getattr(df, "empty", True):
        return []
    rows = []
    for _, r in df.iterrows():
        cd = str(r.get("cal_date") or "")
        if len(cd) == 8 and cd.isdigit():
            rows.append({
                "date": f"{cd[:4]}-{cd[4:6]}-{cd[6:]}",
                "is_open": int(r.get("is_open") or 0),
            })
    return rows


async def sync_trade_calendar(years: list[int] | None = None) -> int:
    """按年拉取 Tushare trade_cal 并 upsert 入库（幂等）。返回入库新增/更新条数。"""
    import pymongo

    years = years or list(range(_CAL_START_YEAR, _CAL_END_YEAR + 1))
    total = 0
    for year in years:
        try:
            rows = await asyncio.to_thread(_fetch_year_calendar_blocking, year)
        except Exception as e:
            logger.warning(f"交易日历同步失败({year}): {type(e).__name__}: {str(e)[:120]}")
            continue
        if not rows:
            continue
        ops = [pymongo.UpdateOne(
            {"date": r["date"]},
            {"$set": {"date": r["date"], "is_open": r["is_open"],
                      "updated_at": datetime.utcnow().isoformat()}},
            upsert=True,
        ) for r in rows]
        if ops:
            try:
                res = await col("trade_calendar").bulk_write(ops, ordered=False)
                total += res.upserted_count + res.modified_count
            except Exception as e:
                logger.warning(f"交易日历入库失败({year}): {type(e).__name__}: {str(e)[:120]}")
    logger.info(f"📅 交易日历同步完成：共处理 {len(years)} 年，更新 {total} 条")
    return total


async def _load_open_to_memory() -> int:
    """从库装载全量开市日到内存视图（当日有效，避免跨日陈旧）。"""
    open_dates = set()
    cursor = col("trade_calendar").find({"is_open": 1}, {"date": 1, "_id": 0})
    async for doc in cursor:
        d = _norm(doc.get("date"))
        if len(d) == 10:
            open_dates.add(d)
    _STATE["open"] = frozenset(open_dates)
    _STATE["loaded_date"] = datetime.now().strftime("%Y-%m-%d")
    return len(open_dates)


async def ensure_trade_calendar_loaded(refresh: bool = False) -> None:
    """确保日历数据与内存视图就绪（启动预热 / 每日刷新任务调用）。

    - 库内无数据 → 主动同步（失败仅告警，下次再重试）；
    - refresh=True 或内存跨日 → 重新装载内存，并补最近 366 天增量。
    """
    db_cnt = await col("trade_calendar").count_documents({})
    if db_cnt == 0 or refresh:
        if refresh:
            # 每日刷新：补最近一年（覆盖调休/跨年变更），不做全量重拉
            year_now = datetime.now().year
            await sync_trade_calendar(list(range(max(_CAL_START_YEAR, year_now - 1),
                                                 min(_CAL_END_YEAR, year_now) + 1)))
        else:
            # 冷启动建表：全量
            await sync_trade_calendar()
    await _load_open_to_memory()
    logger.info(f"📅 交易日历内存视图就绪：{len(_STATE['open'])} 个开市日")


async def query_trade_days(start: str, end: str) -> list[str]:
    """区间 [start, end] 开市日（YYYY-MM-DD 升序）。库查询优先；库空时尝试同步。"""
    start_n, end_n = _norm(start), _norm(end)
    calendar = col("trade_calendar")
    if await calendar.count_documents({}) == 0:
        import contextlib

        with contextlib.suppress(Exception):
            await sync_trade_calendar()
    try:
        cursor = calendar.find(
            {"date": {"$gte": start_n, "$lte": end_n}, "is_open": 1},
            {"date": 1, "_id": 0},
        ).sort("date", 1)
        days = [_norm(doc["date"]) async for doc in cursor]
        return [d for d in days if len(d) == 10]
    except Exception as e:
        logger.warning(f"区间交易日查询失败({start_n}~{end_n}): {e}")
        return []


async def effective_trade_days(candidates: list[str]) -> list[str]:
    """实收交叉校验：候选开市日中，stock_daily_quotes 实际有记录者（按日期去重返回）。

    作用：官方日历含但本库未同步成功的日期不进入时间轴，保证「实收为准」口径，
    与旧 distinct 行为一致但查询量级小（仅候选日期聚合，非全表扫描）。
    """
    if not candidates:
        return []
    cand_n = sorted({_norm(x) for x in candidates if len(_norm(x)) == 10})
    if not cand_n:
        return []
    # 兼容 stock_daily_quotes 的两种日期存储格式（YYYY-MM-DD 与 YYYYMMDD）
    cand_compact = {d.replace("-", "") for d in cand_n}
    cand_both = list(cand_compact) + cand_n
    present: set[str] = set()
    try:
        pipe = [
            {"$match": {"period": "daily", "trade_date": {"$in": cand_both}}},
            {"$group": {"_id": "$trade_date"}},
        ]
        async for doc in col("stock_daily_quotes").aggregate(pipe):
            raw = doc.get("_id")
            if raw:
                present.add(_norm(str(raw)))
    except Exception as e:
        logger.warning(f"实收交易日校验失败: {e}")
        return []
    return [d for d in cand_n if d in present]