"""大盘看板增强指标：市场温度分位 / 宽度曲线 / 风格轮动 / 成交额集中度 / 盘中预警。

分层设计（保证盘中时效，同时不拖慢首屏）：
- 历史基线：`market_metrics_daily` 每交易日一行，收盘后固化（用于分位数与曲线分母）；
- 盘中实时点：直接读 `market_quotes`（2-6 分钟刷新一次全市场快照），单次计算 <2s；
- 返回时把「实时点」拼接进已固化的历史序列，分位数即时可用，无需等收盘。

口径说明：
- 涨停/跌停按各板块涨跌幅阈值近似（主板 9.8%、创业板/科创板 19.8%、北交所 29.5%），
  不含 ST 5% 特例；与东财四池口径存在小幅差异，页面已标注。
- 成交额单位统一换算为亿元。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from app.services.cache_layer import cached
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi")

COLLECTION = "market_metrics_daily"
HISTORY_DAYS = 250
CHART_DAYS = 60
MIN_HISTORY_ROWS = 60
# 单只个股单日成交额上限（元）：超过即视为脏数据，超出部分不参与全市场成交额统计
MAX_STOCK_AMOUNT = 5e10

_BACKFILL_LOCK = asyncio.Lock()
_BACKFILL_TASK: asyncio.Task | None = None

# 数据源优先级（与全项目统一约定一致：tushare > baostock > akshare > sina）
_SOURCE_PRIO = {"tushare": 0, "baostock": 1, "akshare": 2, "sina": 3}


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize_date(v: Any) -> str:
    """统一成 YYYY-MM-DD（market_quotes 为 20261029，日线为 2026-10-28）。"""
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _limit_pct(symbol: str) -> float:
    """按板块返回涨停判定阈值（留 0.2% 容差，近似含接近未封死）。"""
    s = str(symbol or "")
    if s[:2] in ("30", "68"):
        return 19.8
    if s[:1] in ("4", "8") or s[:2] == "92":
        return 29.5
    return 9.8


def _sync_db():
    from app.core.database import get_mongo_db_sync

    return get_mongo_db_sync()


def _rank(values: list[float], x: float) -> int | None:
    """历史分位：中位秩法，取值 0-100。"""
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
# 历史基线：回填 / 状态
# ---------------------------------------------------------------------------

def _history_status(db) -> tuple[bool, int]:
    try:
        n = db[COLLECTION].estimated_document_count()
    except Exception:
        n = 0
    return n >= MIN_HISTORY_ROWS, n


def _backfill_sync(days: int = HISTORY_DAYS) -> int:
    """从日线回填历史温度行（一次性，约 10-15s），按 (日期, 股票) 去重取最高优先级源。"""
    db = _sync_db()
    # 250 个交易日约对应 380 个自然日，留足冗余后一次性回填
    start = (now_tz() - timedelta(days=int(days * 1.6) + 20)).strftime("%Y-%m-%d")

    pipeline = [
        {"$match": {"period": "daily", "trade_date": {"$gte": start}}},
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
        # 脏数据防护：成交额应与 收盘价 × 成交量（股）量级一致。
        # 曾在 tushare/akshare 中见到单条 2447 万亿、71 万亿的脏值，会拉偏全市场成交额与历史分位；
        # 偏离 2 倍以上或超过 500 亿的记录直接置零（不估算，避免引入臆造数据）。
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
                    {"$gt": [{"$ifNull": ["$amt", 0]}, MAX_STOCK_AMOUNT]},
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
            "dt": {"$sum": {"$cond": [{"$lte": ["$pct", {"$multiply": [{"$subtract": ["$lim", 0.2]}, -1]}]}, 1, 0]}},
            "amt": {"$sum": "$amt"},
        }},
        {"$sort": {"_id": 1}},
    ]
    rows = list(db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True))

    turn_map: dict[str, float] = {}
    for r in db["stock_daily_basic"].aggregate([
        {"$match": {"trade_date": {"$gte": start}}},
        {"$group": {"_id": "$trade_date", "avg": {"$avg": "$turnover_rate"}}},
    ]):
        if r.get("avg") is not None:
            turn_map[str(r["_id"])] = round(_f(r["avg"]), 2)

    now = now_tz()
    docs = []
    for r in rows[-HISTORY_DAYS:]:
        d = _normalize_date(r["_id"])
        n = int(r.get("n") or 0)
        if not d or n <= 0:
            continue
        up = int(r.get("up") or 0)
        down = int(r.get("down") or 0)
        docs.append({
            "date": d,
            "n": n,
            "up": up,
            "down": down,
            "flat": max(0, n - up - down),
            "up_pct": round(up / n * 100, 2),
            "zt": int(r.get("zt") or 0),
            "dt": int(r.get("dt") or 0),
            "amount": round(_f(r.get("amt")) / 1e8, 2),
            "avg_turnover": turn_map.get(d),
            "adl_delta": up - down,
            "finalized": True,
            "source": "daily_quotes",
            "updated_at": now,
        })

    if not docs:
        logger.warning("📊 [metrics] 历史温度回填无数据（日线可能尚未入库）")
        return 0

    from pymongo import UpdateOne

    db[COLLECTION].bulk_write(
        [UpdateOne({"date": d["date"]}, {"$set": d}, upsert=True) for d in docs],
        ordered=False,
    )
    logger.info(f"📊 [metrics] 历史温度回填完成：{len(docs)} 个交易日")
    return len(docs)


async def ensure_metrics_history(force: bool = False) -> int:
    """确保历史基线可用（幂等）：已有足够行数时直接跳过。"""
    async with _BACKFILL_LOCK:
        ready, n = await asyncio.to_thread(_history_status_sync)
        if ready and not force:
            return n
        return await asyncio.to_thread(_backfill_sync)


def _history_status_sync() -> tuple[bool, int]:
    return _history_status(_sync_db())


# ---------------------------------------------------------------------------
# 盘中实时点
# ---------------------------------------------------------------------------

def _live_point(db, pools: dict[str, Any] | None = None) -> dict[str, Any]:
    """基于 market_quotes 全市场快照计算当日实时点（<2s）。

    pools 为东财封板池代码集合（与「短线情绪→情绪概览」同源）。日期一致时
    涨停/跌停按池子判定，保证看板各处数字一致；否则回落阈值近似。
    """
    quotes = list(db["market_quotes"].find(
        {}, {"_id": 0, "code": 1, "symbol": 1, "pct_chg": 1, "amount": 1,
             "turnover_rate": 1, "close": 1, "trade_date": 1}
    ))
    if not quotes:
        return {}

    # 只保留最新交易日快照（集合里可能残留少量手工回填的历史行）
    dates = [_normalize_date(q.get("trade_date")) for q in quotes if q.get("trade_date")]
    data_date = max(dates) if dates else ""
    if data_date:
        quotes = [q for q in quotes if _normalize_date(q.get("trade_date")) == data_date]
    use_pool = bool(pools) and str(pools.get("date") or "") == data_date
    zt_codes = set(pools.get("zt") or []) if use_pool else set()
    dt_codes = set(pools.get("dt") or []) if use_pool else set()
    n = len(quotes)
    up = down = zt = dt = 0
    total_amt = 0.0
    turn_sum = 0.0
    turn_cnt = 0
    amounts: list[float] = []
    pcts: dict[str, float] = {}

    for q in quotes:
        pct = _f(q.get("pct_chg"))
        amt = max(0.0, _f(q.get("amount")))
        if amt > MAX_STOCK_AMOUNT:
            amt = 0.0
        sym = str(q.get("code") or q.get("symbol") or "")
        pcts[sym] = pct
        total_amt += amt
        if amt > 0:
            amounts.append(amt)
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        if use_pool:
            # 封板池为唯一口径：未入池个股不计入涨跌停（即便涨幅接近限制）
            if sym in zt_codes:
                zt += 1
            elif sym in dt_codes:
                dt += 1
        else:
            lim = _limit_pct(sym)
            if pct >= lim - 0.2:
                zt += 1
            elif pct <= -(lim - 0.2):
                dt += 1
        tr = q.get("turnover_rate")
        if tr is not None:
            turn_sum += _f(tr)
            turn_cnt += 1

    # 集中度：成交额头部吸金占比 + HHI（按份额平方 ×10000）
    amounts.sort(reverse=True)
    top1 = amounts[0] / total_amt * 100 if total_amt > 0 and amounts else 0.0
    top10 = sum(amounts[:10]) / total_amt * 100 if total_amt > 0 else 0.0
    hhi = sum((a / total_amt) ** 2 for a in amounts) * 10000 if total_amt > 0 else 0.0

    point = {
        "date": data_date,
        "n": n,
        "up": up,
        "down": down,
        "flat": max(0, n - up - down),
        "up_pct": round(up / n * 100, 2) if n else 0.0,
        "zt": zt,
        "dt": dt,
        "amount": round(total_amt / 1e8, 2),
        "avg_turnover": round(turn_sum / turn_cnt, 2) if turn_cnt else None,
        "adl_delta": up - down,
        "finalized": False,
        "source": "market_quotes",
    }

    ma20_above = _ma20_above_ratio(db, data_date, quotes)
    if ma20_above is not None:
        point["ma20_above"] = ma20_above

    concentration = {
        "as_of": data_date,
        "total": round(total_amt / 1e8, 2),
        "top1_share": round(top1, 2),
        "top10_share": round(top10, 2),
        "hhi": round(hhi, 2),
        "count": n,
    }

    style = _style_buckets(db, data_date, pcts)

    return {
        "point": point,
        "concentration": concentration,
        "style": style,
    }


def _ma20_above_ratio(db, data_date: str, quotes: list[dict]) -> float | None:
    """当前价站上 20 日均线的个股占比（需要最近 20 个交易日收盘）。"""
    try:
        dates = [d for d in db["stock_daily_quotes"].distinct(
            "trade_date", {"period": "daily", "trade_date": {"$lte": data_date}}
        )]
        dates = sorted(_normalize_date(d) for d in dates if d)
        dates = dates[-20:]
        if len(dates) < 20:
            return None

        rows = db["stock_daily_quotes"].find(
            {"period": "daily", "trade_date": {"$in": dates}},
            {"_id": 0, "symbol": 1, "trade_date": 1, "close": 1, "data_source": 1},
        )
        # 同源重复：(股票, 日期) 只保留优先级最高的记录
        best: dict[tuple[str, str], tuple[int, float]] = {}
        for r in rows:
            sym = str(r.get("symbol") or "")
            if not sym:
                continue
            d = _normalize_date(r.get("trade_date"))
            close = r.get("close")
            if close is None:
                continue
            prio = _SOURCE_PRIO.get(str(r.get("data_source") or ""), 4)
            key = (sym, d)
            if key not in best or prio < best[key][0]:
                best[key] = (prio, _f(close))

        per_symbol: dict[str, list[float]] = {}
        for (sym, d), (_, close) in best.items():
            per_symbol.setdefault(sym, []).append(close)

        above = valid = 0
        for q in quotes:
            sym = str(q.get("symbol") or "")
            closes = per_symbol.get(sym)
            if not closes or len(closes) < 20:
                continue
            ma20 = sum(closes) / len(closes)
            cur = q.get("close")
            if cur is None:
                continue
            valid += 1
            if _f(cur) > ma20:
                above += 1
        return round(above / valid * 100, 2) if valid else None
    except Exception as e:
        logger.warning(f"📊 [metrics] MA20 宽度计算失败（忽略）: {e}")
        return None


def _style_buckets(db, data_date: str, pcts: dict[str, float]) -> dict[str, Any] | None:
    """大小盘风格：以最新流通市值三分位分组，比较各组当日平均涨跌幅。"""
    try:
        latest = [d for d in db["stock_daily_basic"].distinct(
            "trade_date", {"trade_date": {"$lte": data_date}}
        )]
        if not latest:
            return None
        latest = sorted(_normalize_date(d) for d in latest if d)
        basic_date = latest[-1]

        rows = db["stock_daily_basic"].find(
            {"trade_date": basic_date}, {"_id": 0, "symbol": 1, "circ_mv": 1}
        )
        mv: dict[str, float] = {}
        for r in rows:
            sym = str(r.get("symbol") or "")
            v = r.get("circ_mv")
            if sym and v is not None and _f(v) > 0:
                mv[sym] = _f(v)

        pairs = [(s, m) for s, m in mv.items() if s in pcts]
        if len(pairs) < 200:
            return None
        pairs.sort(key=lambda x: x[1])
        total = len(pairs)
        cut1 = total // 3
        cut2 = total * 2 // 3

        groups = {
            "small": pairs[:cut1],
            "mid": pairs[cut1:cut2],
            "large": pairs[cut2:],
        }
        labels = {"large": "大盘", "mid": "中盘", "small": "小盘"}
        out = []
        for key in ("large", "mid", "small"):
            g = groups[key]
            if not g:
                continue
            avg = sum(pcts[s] for s, _ in g) / len(g)
            out.append({
                "key": key,
                "label": labels[key],
                "pct": round(avg, 2),
                "share": round(len(g) / total * 100, 1),
                "count": len(g),
            })
        spread = round(out[0]["pct"] - out[-1]["pct"], 2) if len(out) >= 2 else 0.0
        # 涨跌幅是当日实时价，市值分组基于最近已入库交易日（通常是昨日）
        return {"as_of": data_date, "mv_as_of": basic_date, "buckets": out, "spread": spread}
    except Exception as e:
        logger.warning(f"📊 [metrics] 风格分组计算失败（忽略）: {e}")
        return None


# ---------------------------------------------------------------------------
# 汇总 / 预警
# ---------------------------------------------------------------------------

_TEMP_DEFS = [
    ("zt", "涨停家数", "家", True, "涨停家数越多，短线做多情绪越强（东财封板池口径；历史分位以涨跌幅阈值近似）"),
    ("amount", "成交额", "亿", True, "全市场成交额，反映资金参与度"),
    ("avg_turnover", "平均换手", "%", True, "个股平均换手率，反映筹码活跃度"),
    ("up_pct", "上涨率", "%", True, "上涨家数占比，反映市场广度"),
]


def _temperature(history: list[dict], live: dict) -> list[dict]:
    out = []
    for key, label, unit, hot, desc in _TEMP_DEFS:
        # 历史分位排除当日实时点，避免"自己和自己比"
        vals = [
            _f(h.get(key))
            for h in history
            if h.get(key) is not None and h.get("date") != live.get("date")
        ]
        cur = live.get(key)
        if cur is None:
            continue
        cur_f = _f(cur)
        rank = _rank(vals, cur_f)
        med = _median(vals)
        out.append({
            "key": key,
            "label": label,
            "unit": unit,
            "value": round(cur_f, 2),
            "rank": rank,
            "median": round(med, 2) if med is not None else None,
            "samples": len(vals),
            "higher_is_hot": hot,
            "desc": desc,
        })
    return out


def _breadth_series(history: list[dict], live: dict) -> list[dict]:
    hist = [h for h in history if h.get("date") != live.get("date")]
    seq = hist[-CHART_DAYS:]
    if live.get("date"):
        seq.append(live)
    out = []
    adl = 0
    for h in seq:
        adl += int(h.get("adl_delta") or 0)
        out.append({
            "date": h.get("date"),
            "adl": adl,
            "up_pct": round(_f(h.get("up_pct")), 1),
            "ma20_above": h.get("ma20_above"),
            "zt": int(h.get("zt") or 0),
        })
    return out


def _alerts(temp: list[dict], live: dict) -> list[dict]:
    by_key = {t["key"]: t for t in temp}
    out: list[dict] = []

    def add(level: str, title: str, detail: str):
        if len(out) < 4:
            out.append({"level": level, "title": title, "detail": detail})

    dt_val = int(live.get("dt") or 0)
    if dt_val >= 50:
        add("danger", "跌停家数异常", f"当前跌停 {dt_val} 家，抛压明显")

    amt = by_key.get("amount")
    if amt and amt.get("rank") is not None and amt["rank"] <= 20:
        add("warning", "成交额萎缩", f"成交额 {amt['value']}亿，处于近一年 {amt['rank']}% 分位")

    up = by_key.get("up_pct")
    if up and up.get("rank") is not None and up["rank"] <= 25:
        add("warning", "市场广度偏弱", f"上涨率 {up['value']}%，近一年 {up['rank']}% 分位")

    ma20 = live.get("ma20_above")
    if ma20 is not None and ma20 <= 30:
        add("warning", "中期结构走弱", f"仅 {ma20}% 个股站上 20 日均线")

    zt = by_key.get("zt")
    if zt and zt.get("rank") is not None and zt["rank"] >= 90:
        add("info", "短线热度偏高", f"涨停 {zt['value']} 家，近一年 {zt['rank']}% 分位，注意追高风险")

    return out


async def _pool_sets() -> dict[str, Any] | None:
    """东财封板池代码集合（与「短线情绪→情绪概览」复用同一份 Redis 快照）。"""
    try:
        from app.services.market_overview import get_short_term_emotion

        emo = await asyncio.wait_for(get_short_term_emotion(), timeout=25)
        pools = emo.get("pools") or {}
        zt = {str(p.get("code") or "").split(".")[0] for p in pools.get("zt") or []}
        dt = {str(p.get("code") or "").split(".")[0] for p in pools.get("dt") or []}
        if not zt and not dt:
            return None
        return {"date": str(emo.get("date") or ""), "zt": zt, "dt": dt}
    except Exception as e:
        logger.warning(f"📊 [metrics] 封板池不可用，涨停/跌停回落阈值近似: {e}")
        return None


async def _build_metrics() -> dict[str, Any]:
    db = _sync_db()
    ready, count = await asyncio.to_thread(_history_status, db)

    pools = await _pool_sets()
    live_data = await asyncio.to_thread(_live_point, db, pools)
    live = (live_data or {}).get("point") or {}

    history: list[dict] = []
    if ready:
        history = list(db[COLLECTION].find(
            {}, {"_id": 0}
        ).sort("date", 1))
    else:
        # 基线缺失：后台构建，本次先返回实时点（不缓存空结果）
        _kick_backfill()

    temp = _temperature(history, live) if live else []
    series = _breadth_series(history, live) if live else []

    return {
        "ready": ready and count >= MIN_HISTORY_ROWS,
        "as_of": live.get("date") or "",
        # 实时快照（盘中/刚收盘）为 True；19:50 固化任务写入 finalized=True 后转 False
        "is_live": not bool(live.get("finalized")),
        "updated": now_tz().isoformat(),
        "temperature": temp,
        "breadth": {
            "series": series,
            "ma20_above": live.get("ma20_above"),
            "zt": live.get("zt"),
            "dt": live.get("dt"),
        },
        "style": (live_data or {}).get("style"),
        "concentration": (live_data or {}).get("concentration"),
        "alerts": _alerts(temp, live) if live else [],
        "note": "涨停/跌停取东财封板池（与短线情绪页一致）；历史分位的历史序列按涨跌幅阈值近似",
    }


def _kick_backfill() -> None:
    global _BACKFILL_TASK
    if _BACKFILL_TASK and not _BACKFILL_TASK.done():
        return
    try:
        _BACKFILL_TASK = asyncio.get_running_loop().create_task(ensure_metrics_history())
    except RuntimeError:
        logger.warning("📊 [metrics] 无运行中事件循环，跳过历史回填")


async def get_market_metrics() -> dict[str, Any]:
    """大盘看板增强指标（Redis 缓存：交易时段 120s / 非交易时段 900s）。"""
    from app.utils.trading_time import is_trading_time

    ttl = 120 if is_trading_time() else 900
    data = await cached("vibe:market:metrics", _build_metrics, ttl=ttl)
    if not isinstance(data, dict) or not data.get("as_of"):
        return data if isinstance(data, dict) else {}
    return data


async def finalize_market_metrics() -> dict[str, Any]:
    """收盘后固化当日温度行（供分位数与曲线使用），由定时任务/预热调用。"""
    db = _sync_db()
    live_data = await asyncio.to_thread(_live_point, db)
    point = (live_data or {}).get("point") or {}
    if not point.get("date"):
        return {"ok": False, "reason": "no_quote"}

    doc = dict(point)
    doc["finalized"] = True
    doc["updated_at"] = now_tz()

    from pymongo import UpdateOne

    await asyncio.to_thread(
        lambda: db[COLLECTION].bulk_write([UpdateOne({"date": doc["date"]}, {"$set": doc}, upsert=True)],
                                         ordered=False)
    )
    logger.info(f"📊 [metrics] 当日温度已固化: {doc['date']} 涨停{doc.get('zt')} 跌停{doc.get('dt')}")
    return {"ok": True, "date": doc["date"]}
