"""大盘当前位置：长期历史分位 / 历史分位映射未来收益 / 位置与动能背离。

用途：回答「现在贵不贵、热不热、是不是接近历史底部或顶部」。
- 分位窗口固定近 10 年（后端常量，前端不传参）；估值受基础数据限制，窗口按实际样本标注。
- 未来 20 日收益分布仅在历史样本 >= 3 年时返回，样本不足时前端隐藏该块。
- 历史基线写入 `market_position_daily`，首次构建在后台分块执行，接口先返回 ready=false。
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Any

from app.services.cache_layer import cached
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi")

COLLECTION = "market_position_daily"
POSITION_YEARS = 10
# 约 3 年交易日：不足则隐藏「历史分位→未来收益」分布
MIN_FORWARD_ROWS = 750
MIN_HISTORY_ROWS = 60
FORWARD_DAYS = 20
# 单批回填的自然日跨度：控制单次聚合内存与耗时，整体在后台分块跑完
CHUNK_DAYS = 400

_BACKFILL_TASK: asyncio.Task | None = None
_STALE_CHECK_TS = 0.0
_STALE_CHECK_INTERVAL = 6 * 3600

_ZONE_MAP = [
    (80, "overheated", "高位区", "情绪与资金同时处在历史高位，追高性价比下降，优先控制仓位、留出撤退空间"),
    (60, "warm", "偏高位", "位置偏高但趋势仍强，持仓为主，新增仓位等回踩确认"),
    (40, "neutral", "中位区", "位置中性，跟随趋势与事件交易，不做位置层面的加减仓"),
    (20, "cool", "偏低区", "位置偏低，可关注修复机会，等待宽度与量能同步改善"),
    (0, "oversold", "低位区", "处于历史低位区，恐慌释放后留意反转信号，但需右侧确认"),
]

_SOURCE_PRIO = {"tushare": 0, "baostock": 1, "akshare": 2, "sina": 3}
_MAX_STOCK_AMOUNT = 5e10


def _sync_db():
    from app.core.database import get_mongo_db_sync

    return get_mongo_db_sync()


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize_date(v: Any) -> str:
    s = str(v or "")
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def _rank(values: list[float], x: float) -> int | None:
    """中位秩分位（0-100）。"""
    if not values:
        return None
    less = sum(1 for v in values if v < x)
    eq = sum(1 for v in values if v == x)
    return int(round((less + 0.5 * eq) / len(values) * 100))


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    arr = sorted(values)
    n = len(arr)
    mid = n // 2
    return (arr[mid] + arr[n - 1 - mid]) / 2


# ---------------------------------------------------------------------------
# 历史基线：构建 / 状态
# ---------------------------------------------------------------------------

def _latest_quote_date(db) -> str:
    try:
        doc = db["stock_daily_quotes"].find(
            {"period": "daily", "trade_date": {"$type": "string"}},
            {"trade_date": 1},
        ).sort("trade_date", -1).limit(1)
        row = next(doc, None)
        return _normalize_date(row.get("trade_date")) if row else ""
    except Exception:
        logger.exception("📊 [position] 最新交易日查询失败")
        return ""


def _status_sync(db) -> tuple[int, str]:
    try:
        count = db[COLLECTION].estimated_document_count()
        doc = db[COLLECTION].find({}, {"date": 1}).sort("date", -1).limit(1)
        row = next(doc, None)
        return count, (row or {}).get("date", "")
    except Exception:
        logger.exception("📊 [position] 历史基线状态查询失败")
        return 0, ""


def _aggregate_quotes(db, start: str, end: str | None) -> list[dict]:
    """按交易日聚合全市场涨跌家数 / 涨停数 / 成交额 / 等权平均涨跌幅。"""
    date_match: dict[str, Any] = {"$gte": start}
    if end:
        date_match["$lte"] = end
    pipeline = [
        {"$match": {"period": "daily", "trade_date": date_match, "pct_chg": {"$ne": None}}},
        {"$addFields": {"prio": {"$switch": {
            "branches": [
                {"case": {"$eq": ["$data_source", "tushare"]}, "then": 0},
                {"case": {"$eq": ["$data_source", "baostock"]}, "then": 1},
                {"case": {"$eq": ["$data_source", "akshare"]}, "then": 2},
            ],
            "default": 3,
        }}}},
        {"$sort": {"trade_date": 1, "symbol": 1, "prio": 1}},
        {"$group": {
            "_id": {"d": "$trade_date", "s": "$symbol"},
            "pct": {"$first": "$pct_chg"},
            "amt": {"$first": "$amount"},
            "sym": {"$first": "$symbol"},
            "vol": {"$first": "$volume"},
            "close": {"$first": "$close"},
        }},
        # 脏数据防护：成交额应与 收盘价 × 成交量（股）量级一致
        {"$addFields": {
            "est": {"$multiply": [{"$ifNull": ["$close", 0]}, {"$ifNull": ["$vol", 0]}]},
            "amt": {"$cond": [
                {"$or": [
                    {"$lte": ["$est", 0]},
                    {"$and": [
                        {"$lte": [{"$ifNull": ["$amt", 0]}, {"$multiply": ["$est", 2]}]},
                        {"$gte": [{"$ifNull": ["$amt", 0]}, {"$multiply": ["$est", 0.5]}]},
                    ]},
                ]},
                {"$cond": [
                    {"$gt": [{"$ifNull": ["$amt", 0]}, _MAX_STOCK_AMOUNT]},
                    0,
                    {"$ifNull": ["$amt", 0]},
                ]},
                0,
            ]},
        }},
        {"$addFields": {"lim": {"$switch": {
            "branches": [
                {"case": {"$in": [{"$substrCP": ["$sym", 0, 2]}, ["30", "68"]]}, "then": 19.8},
                {"case": {"$in": [{"$substrCP": ["$sym", 0, 1]}, ["4", "8"]]}, "then": 29.5},
                {"case": {"$eq": [{"$substrCP": ["$sym", 0, 2]}, "92"]}, "then": 29.5},
            ],
            "default": 9.8,
        }}}},
        {"$group": {
            "_id": "$_id.d",
            "n": {"$sum": 1},
            "up": {"$sum": {"$cond": [{"$gt": ["$pct", 0]}, 1, 0]}},
            "down": {"$sum": {"$cond": [{"$lt": ["$pct", 0]}, 1, 0]}},
            "zt": {"$sum": {"$cond": [{"$gte": ["$pct", {"$subtract": ["$lim", 0.2]}]}, 1, 0]}},
            "amount": {"$sum": "$amt"},
            "avg_pct": {"$avg": "$pct"},
        }},
        {"$sort": {"_id": 1}},
    ]
    return list(db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True))


def _aggregate_valuation(db, start: str, end: str | None) -> dict[str, float]:
    """按交易日计算全市场平均 PE（仅取有效正数，剔除极端脏值）。"""
    date_match: dict[str, Any] = {"$gte": start}
    if end:
        date_match["$lte"] = end
    pipeline = [
        {"$match": {
            "trade_date": date_match,
            "pe": {"$gt": 0, "$lte": 500},
        }},
        {"$group": {"_id": "$trade_date", "pe": {"$avg": "$pe"}}},
    ]
    out: dict[str, float] = {}
    for r in db["stock_daily_basic"].aggregate(pipeline, allowDiskUse=True):
        d = _normalize_date(r.get("_id"))
        if d and r.get("pe") is not None:
            out[d] = round(_f(r["pe"]), 2)
    return out


def _upsert_docs(db, docs: list[dict]) -> int:
    if not docs:
        return 0
    from pymongo import UpdateOne

    db[COLLECTION].bulk_write(
        [UpdateOne({"date": d["date"]}, {"$set": d}, upsert=True) for d in docs],
        ordered=False,
    )
    return len(docs)


def _build_sync(full: bool = False) -> int:
    db = _sync_db()
    latest = _latest_quote_date(db)
    if not latest:
        logger.warning("📊 [position] 无日线数据，跳过历史基线构建")
        return 0
    latest_dt = datetime.strptime(latest, "%Y-%m-%d")

    _, last_stored = _status_sync(db)
    if full or not last_stored:
        start_dt = latest_dt - timedelta(days=POSITION_YEARS * 365 + 30)
    else:
        try:
            start_dt = datetime.strptime(last_stored, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            start_dt = latest_dt - timedelta(days=POSITION_YEARS * 365 + 30)

    total = 0
    cursor = start_dt
    now = now_tz()
    while cursor <= latest_dt:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), latest_dt)
        s, e = cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        quotes = _aggregate_quotes(db, s, e)
        valuation = _aggregate_valuation(db, s, e)
        docs = []
        for r in quotes:
            d = _normalize_date(r.get("_id"))
            n = int(r.get("n") or 0)
            if not d or n <= 0:
                continue
            up = int(r.get("up") or 0)
            docs.append({
                "date": d,
                "n": n,
                "up": up,
                "down": int(r.get("down") or 0),
                "up_pct": round(up / n * 100, 2),
                "zt": int(r.get("zt") or 0),
                "amount": round(_f(r.get("amount")) / 1e8, 2),
                "avg_pct": round(_f(r.get("avg_pct")), 3),
                "avg_pe": valuation.get(d),
                "updated_at": now,
            })
        total += _upsert_docs(db, docs)
        cursor = chunk_end + timedelta(days=1)

    logger.info(f"📊 [position] 历史分位基线构建完成：{total} 个交易日（{start_dt.date()} ~ {latest_dt.date()}）")
    return total


async def ensure_market_position_history(force: bool = False) -> int:
    count, last = await asyncio.to_thread(_status_sync, _sync_db())
    if count >= MIN_HISTORY_ROWS and not force:
        latest = await asyncio.to_thread(_latest_quote_date, _sync_db())
        if latest and last and last >= latest:
            return count
    return await asyncio.to_thread(_build_sync, force)


def _kick_build() -> None:
    global _BACKFILL_TASK
    if _BACKFILL_TASK and not _BACKFILL_TASK.done():
        return
    try:
        _BACKFILL_TASK = asyncio.get_running_loop().create_task(
            asyncio.to_thread(_build_sync, False)
        )
    except RuntimeError:
        logger.warning("📊 [position] 无运行中事件循环，跳过历史基线构建")


def _maybe_refresh_stale(db) -> bool:
    """每 6 小时最多检查一次：历史基线落后于最新交易日时返回 True（由调用方触发增量构建）。"""
    global _STALE_CHECK_TS
    now = time.time()
    if now - _STALE_CHECK_TS < _STALE_CHECK_INTERVAL:
        return False
    _STALE_CHECK_TS = now
    _, last = _status_sync(db)
    latest = _latest_quote_date(db)
    return bool(latest and last and last < latest)


# -----------------------------------------------------------------------------
# 响应计算（纯函数，便于单测）
# -----------------------------------------------------------------------------

def _rank_series(values: list[float | None]) -> list[int | None]:
    """按扩展窗口计算每个点的历史分位（只用当天之前的数据，避免未来函数）。"""
    prev: list[float] = []
    out: list[int | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        if len(prev) < MIN_HISTORY_ROWS:
            out.append(None)
        else:
            out.append(round(bisect.bisect_right(prev, v) / len(prev) * 100))
        bisect.insort(prev, v)
    return out


def _zone_of(pct: float | None) -> dict[str, Any]:
    if pct is None:
        return {"zone": "unknown", "label": "构建中", "advice": "历史样本不足，暂不给出位置结论"}
    for threshold, zone, label, advice in _ZONE_MAP:
        if pct >= threshold:
            return {"zone": zone, "label": label, "advice": advice}
    return {"zone": "unknown", "label": "构建中", "advice": ""}


def _window_years(dates: list[str]) -> float:
    if len(dates) < 2:
        return 0.0
    try:
        a = datetime.strptime(dates[0], "%Y-%m-%d")
        b = datetime.strptime(dates[-1], "%Y-%m-%d")
    except ValueError:
        return 0.0
    return round((b - a).days / 365.25, 1)


def _forward_stats(rows: list[dict], composite_series: list[int | None]) -> dict[str, Any] | None:
    """把历史按合成分位分成 5 档，统计未来 20 日等权收益的中位数与胜率。"""
    if len(rows) < MIN_FORWARD_ROWS:
        return None

    log_ret: list[float] = []
    for r in rows:
        v = r.get("avg_pct")
        log_ret.append(math.log1p(_f(v) / 100) if v is not None else 0.0)
    # 前缀和：prefix[i] = sum(log_ret[:i])
    prefix = [0.0]
    for v in log_ret:
        prefix.append(prefix[-1] + v)

    bins = [
        {"key": f"b{i}", "label": f"{i * 20}–{i * 20 + 20}%", "lo": i * 20, "hi": i * 20 + 20,
         "n": 0, "returns": []}
        for i in range(5)
    ]
    for i, pct in enumerate(composite_series):
        j = i + FORWARD_DAYS
        if pct is None or j >= len(rows):
            continue
        if j + 1 >= len(prefix):
            continue
        fwd = math.expm1(prefix[j + 1] - prefix[i + 1])
        idx = min(4, pct // 20)
        bins[idx]["n"] += 1
        bins[idx]["returns"].append(fwd * 100)

    total_n = sum(b["n"] for b in bins)
    if total_n < 100:
        return None

    out_bins = []
    for b in bins:
        rets = b["returns"]
        out_bins.append({
            "key": b["key"],
            "label": b["label"],
            "lo": b["lo"],
            "hi": b["hi"],
            "n": b["n"],
            "median_return": round(_median(rets) or 0.0, 2) if rets else None,
            "win_rate": round(sum(1 for v in rets if v > 0) / len(rets) * 100, 1) if rets else None,
        })

    current = composite_series[-1] if composite_series else None
    current_bin = None
    if current is not None:
        current_bin = f"b{min(4, current // 20)}"
    return {
        "day": FORWARD_DAYS,
        "samples": total_n,
        "window_years": _window_years([r["date"] for r in rows]),
        "bins": out_bins,
        "current_bin": current_bin,
        "current_percentile": current,
    }


def _divergence(position: dict[str, dict], composite: float | None) -> list[dict[str, Any]]:
    val = position.get("valuation", {}).get("percentile")
    breadth = position.get("breadth", {}).get("percentile")
    funds = position.get("funds", {}).get("percentile")
    sentiment = position.get("sentiment", {}).get("percentile")

    out: list[dict[str, Any]] = []
    if val is not None and breadth is not None:
        if val >= 70 and breadth <= 35:
            out.append({"level": "danger", "title": "估值与宽度背离",
                        "detail": f"估值处 {val}% 高位，但上涨家数仅 {breadth}% 分位，指数可能由少数权重支撑"})
        elif val <= 30 and breadth >= 65:
            out.append({"level": "info", "title": "估值与宽度背离",
                        "detail": f"估值处 {val}% 低位，但宽度已回升至 {breadth}% 分位，留意估值修复"})
    if breadth is not None and funds is not None:
        if breadth >= 65 and funds <= 35:
            out.append({"level": "warning", "title": "量价背离",
                        "detail": f"上涨家数处 {breadth}% 分位，但成交额仅 {funds}% 分位，上涨缺少量能支撑"})
        elif breadth <= 35 and funds >= 70:
            out.append({"level": "warning", "title": "放量下跌",
                        "detail": f"上涨家数仅 {breadth}% 分位，成交额却在 {funds}% 高位，抛压需要时间消化"})
    if sentiment is not None and breadth is not None and sentiment >= 80 and breadth <= 35:
        out.append({"level": "warning", "title": "情绪与宽度背离",
                    "detail": f"短线情绪 {sentiment}% 高位，但下跌家数仍多，赚钱效应集中在少数强势股"})
    if composite is not None and composite >= 80 and not out:
        out.append({"level": "info", "title": "位置进入高位区",
                    "detail": "情绪、宽度与资金同时处于历史高位，继续追高需要更强的催化"})
    return out[:3]


def compute_position_payload(rows: list[dict]) -> dict[str, Any]:
    """由历史日度行计算当前位置、未来收益分布与背离（纯函数）。"""
    if not rows:
        return _empty_payload("历史样本为空")

    rows = sorted(rows, key=lambda r: r["date"])
    latest = rows[-1]
    history = rows[:-1]

    def build_metric(key: str, label: str, unit: str, field: str, desc: str) -> dict[str, Any]:
        vals = [r.get(field) for r in rows if r.get(field) is not None]
        hist_vals = [r.get(field) for r in history if r.get(field) is not None]
        dates = [r["date"] for r in rows if r.get(field) is not None]
        cur_raw = latest.get(field)
        cur = round(_f(cur_raw), 2) if cur_raw is not None else None
        pct = _rank([_f(v) for v in hist_vals], _f(cur_raw)) if (cur_raw is not None and hist_vals) else None
        return {
            "key": key,
            "label": label,
            "unit": unit,
            "value": cur,
            "percentile": pct,
            "window_years": _window_years(dates),
            "samples": len(hist_vals),
            "desc": desc,
        }

    position = {
        "valuation": build_metric("valuation", "估值", "倍", "avg_pe",
                                  "全市场平均 PE，越高代表整体估值越贵"),
        "sentiment": build_metric("sentiment", "情绪", "家", "zt",
                                  "涨停家数，越多代表短线做多情绪越强"),
        "breadth": build_metric("breadth", "宽度", "%", "up_pct",
                                "上涨家数占比，越高代表上涨越普遍"),
        "funds": build_metric("funds", "资金", "亿", "amount",
                              "全市场成交额，越高代表资金参与度越强"),
    }

    # 合成分位：宽度 / 情绪 / 资金；估值窗口不足 3 年时不参与合成，避免短样本主导
    usable = []
    for key in ("breadth", "sentiment", "funds"):
        p = position[key]["percentile"]
        if p is not None:
            usable.append(p)
    if position["valuation"]["window_years"] >= 3 and position["valuation"]["percentile"] is not None:
        usable.append(position["valuation"]["percentile"])
    composite = round(sum(usable) / len(usable)) if usable else None

    breadth_series = [r.get("up_pct") for r in rows]
    sentiment_series = [r.get("zt") for r in rows]
    funds_series = [r.get("amount") for r in rows]
    rank_series = []
    for s in (breadth_series, sentiment_series, funds_series):
        rank_series.append(_rank_series([_f(v) if v is not None else None for v in s]))
    composite_series: list[int | None] = []
    for i in range(len(rows)):
        vals = [rs[i] for rs in rank_series if rs[i] is not None]
        composite_series.append(round(sum(vals) / len(vals)) if vals else None)

    zone = _zone_of(composite)
    divergence = _divergence(position, composite)

    return {
        "ready": True,
        "as_of": latest["date"],
        "updated": now_tz().isoformat(),
        "window_years": _window_years([r["date"] for r in rows]),
        "samples": len(history),
        "position": [position[k] for k in ("valuation", "sentiment", "breadth", "funds")],
        "composite": {
            "percentile": composite,
            "label": zone["label"],
            "zone": zone["zone"],
            "advice": zone["advice"],
        },
        "forward": _forward_stats(rows, composite_series),
        "divergence": divergence,
        "note": "分位窗口固定近 10 年；估值仅统计全市场平均 PE，样本自 2024-07 起，不足 3 年时不参与合成",
    }


def _empty_payload(note: str = "历史分位基线首次构建中") -> dict[str, Any]:
    return {
        "ready": False,
        "as_of": "",
        "updated": now_tz().isoformat(),
        "window_years": 0,
        "samples": 0,
        "position": [],
        "composite": {"percentile": None, "label": "构建中", "zone": "unknown", "advice": ""},
        "forward": None,
        "divergence": [],
        "note": f"{note}，首次构建约需 1~2 分钟，完成后自动显示",
    }


async def _build() -> dict[str, Any]:
    db = _sync_db()
    count, _last = await asyncio.to_thread(_status_sync, db)
    if count < MIN_HISTORY_ROWS:
        _kick_build()
        return _empty_payload()
    rows = await asyncio.to_thread(lambda: list(db[COLLECTION].find({}, {"_id": 0}).sort("date", 1)))
    return await asyncio.to_thread(compute_position_payload, rows)


async def get_market_position() -> dict[str, Any]:
    """大盘当前位置（Redis 缓存：交易时段 5 分钟 / 非交易时段 15 分钟）。

    未就绪时不写缓存，便于前端短间隔重试；返回 ready=false 后由前端显示占位。
    """
    db = _sync_db()
    count, _last = await asyncio.to_thread(_status_sync, db)
    if count < MIN_HISTORY_ROWS:
        _kick_build()
        return _empty_payload()

    if await asyncio.to_thread(_maybe_refresh_stale, db):
        _kick_build()

    from app.utils.trading_time import is_trading_time

    ttl = 300 if is_trading_time() else 900
    return await cached("vibe:market:position", _build, ttl=ttl)
