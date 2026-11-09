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
from app.services.market_metrics import _session_progress, _intraday_amount_share
from app.utils.timezone import now_tz

logger = logging.getLogger("webapi")

COLLECTION = "market_position_daily"
# 行业日度表现基线（同分位时点行业榜数据源）：{date, industry, avg_pct, up_pct, n}
INDUSTRY_PERF_COLLECTION = "industry_daily_perf"
POSITION_YEARS = 10
# 约 3 年交易日：不足则隐藏「历史分位→未来收益」分布
MIN_FORWARD_ROWS = 750
MIN_HISTORY_ROWS = 60
FORWARD_DAYS = 20
# 逃顶 / 判断底部的合成分位阈值（与 _ZONE_MAP 的 80 / 20 分区一致）
TOP_THRESHOLD = 80
BOTTOM_THRESHOLD = 20
# 合成分位历史曲线最多返回的点数（前端折线图用，等距抽稀）
MAX_SERIES_POINTS = 180
# 单批回填的自然日跨度：控制单次聚合内存与耗时，整体在后台分块跑完
CHUNK_DAYS = 400

_BACKFILL_TASK: asyncio.Task | None = None
_STALE_CHECK_TS = 0.0
_STALE_CHECK_INTERVAL = 6 * 3600

_ZONE_MAP = [
    (80, "overheated", "高位区",
     "「逃顶」信号区：多项指标同时处于历史最热 20%，继续追高的赔率下降；"
     "操作上分批止盈、不追高，宽度与量能同步走弱时加快撤退"),
    (60, "warm", "偏高位",
     "位置偏高但趋势仍强，继续追高的性价比下降；持仓为主，新增仓位等回踩确认"),
    (40, "neutral", "中位区",
     "位置中性，跟随趋势与事件交易，不做位置层面的加减仓"),
    (20, "cool", "偏低区",
     "位置偏低，可开始关注修复机会，但仍需宽度与量能同步改善才算确认"),
    (0, "oversold", "低位区",
     "「判断底部」观察区：多项指标同时处于历史最冷 20%，下跌惯性往往仍在；"
     "只做观察、不抢跑，需宽度回升 + 波动率回落 + 年线偏离收窄确认后再分批建仓"),
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


def _live_row_sync(db) -> dict[str, Any] | None:
    """用当日全市场实时快照补出「今天」这一行，让当前位置包含今日数据。

    历史基线只写完整交易日（收盘后固化），当日日线在盘中并不完整，会被
    `_build_sync` 的覆盖率守卫跳过，导致 as_of 倒退到上一个完整交易日。
    这里按与日线相同的口径从 `market_quotes`（120s 全量快照）重算今天的
    涨跌家数 / 成交额 / 振幅 / 低价股占比；PE/PB 快照没有，取最新一日
    `stock_daily_basic` 并在返回值里单独标注日期。
    """
    try:
        quotes = db["market_quotes"]
        newest = next(quotes.find({}, {"trade_date": 1}).sort("updated_at", -1).limit(1), None)
        date = _normalize_date((newest or {}).get("trade_date"))
        if not date:
            return None
        _, last = _status_sync(db)
        if last and date <= last:
            return None  # 基线已包含该交易日，无需重复补行

        pipeline = [
            {"$match": {"trade_date": {"$in": [date, date.replace("-", "")]},
                        "pct_chg": {"$ne": None}}},
            {"$addFields": {"amt": {"$cond": [
                {"$gt": [{"$ifNull": ["$amount", 0]}, _MAX_STOCK_AMOUNT]},
                0,
                {"$ifNull": ["$amount", 0]},
            ]}}},
            # 涨停判定：与历史日线口径一致（按板块前缀确定涨停幅度）
            {"$addFields": {
                "sym": {"$ifNull": ["$symbol", "$code"]},
                "lim": {"$switch": {
                    "branches": [
                        {"case": {"$in": [{"$substrCP": ["$sym", 0, 2]}, ["30", "68"]]}, "then": 19.8},
                        {"case": {"$in": [{"$substrCP": ["$sym", 0, 1]}, ["4", "8"]]}, "then": 29.5},
                        {"case": {"$eq": [{"$substrCP": ["$sym", 0, 2]}, "92"]}, "then": 29.5},
                    ],
                    "default": 9.8,
                }},
            }},
            {"$group": {
                "_id": None,
                "n": {"$sum": 1},
                "up": {"$sum": {"$cond": [{"$gt": ["$pct_chg", 0]}, 1, 0]}},
                "down": {"$sum": {"$cond": [{"$lt": ["$pct_chg", 0]}, 1, 0]}},
                "zt": {"$sum": {"$cond": [{"$gte": ["$pct_chg", {"$subtract": ["$lim", 0.2]}]}, 1, 0]}},
                "amount": {"$sum": "$amt"},
                "avg_pct": {"$avg": "$pct_chg"},
                "amp": {"$avg": {"$cond": [
                    {"$and": [
                        {"$gt": [{"$ifNull": ["$high", 0]}, 0]},
                        {"$gt": [{"$ifNull": ["$low", 0]}, 0]},
                        {"$gt": [{"$ifNull": ["$pre_close", 0]}, 0]},
                    ]},
                    {"$multiply": [{"$divide": [{"$subtract": ["$high", "$low"]}, "$pre_close"]}, 100]},
                    None,
                ]}},
                "low_small": {"$sum": {"$cond": [
                    {"$and": [{"$gt": [{"$ifNull": ["$close", 0]}, 0]}, {"$lt": ["$close", 3]}]},
                    1, 0,
                ]}},
            }},
        ]
        agg = next(quotes.aggregate(pipeline, allowDiskUse=True), None)
        n = int((agg or {}).get("n") or 0)
        refs = [int(r.get("n") or 0) for r in db[COLLECTION].find({}, {"n": 1}).sort("date", -1).limit(30)]
        ref_n = int(_median([v for v in refs if v > 0]) or 0)
        if not n or (ref_n and n < ref_n * 0.6):
            logger.info(f"📊 [position] 今日快照仅 {n} 只（参考 {ref_n}），视为不完整，跳过实时行")
            return None

        # 估值：取最新一日的全市场估值/换手（日线快照本身没有 PE/PB）
        vrow = next(db["stock_daily_basic"].find({}, {"trade_date": 1}).sort("trade_date", -1).limit(1), None)
        vdate = _normalize_date((vrow or {}).get("trade_date"))
        vmeta: dict[str, Any] = {}
        if vdate:
            vmeta = _aggregate_valuation(db, vdate, vdate).get(vdate, {})

        up = int((agg or {}).get("up") or 0)
        zt = int((agg or {}).get("zt") or 0)
        # 站上 250 日线占比需逐股均线，盘中无法实时重算，沿用上一交易日值（该值变化极慢）
        prev_row = next(db[COLLECTION].find({}, {"ma250_pct": 1}).sort("date", -1).limit(1), None)
        ma250_pct = (prev_row or {}).get("ma250_pct")
        return {
            "date": date,
            "n": n,
            "up": up,
            "down": int((agg or {}).get("down") or 0),
            "up_pct": round(up / n * 100, 2),
            "zt": zt,
            "zt_pct": round(zt / n * 100, 2),
            "amount": round(_f((agg or {}).get("amount")) / 1e8, 2),
            "avg_pct": round(_f((agg or {}).get("avg_pct")), 3),
            "amp_pct": round(_f((agg or {}).get("amp")), 2) if (agg or {}).get("amp") is not None else None,
            "low_pct": round(int((agg or {}).get("low_small") or 0) / n * 100, 2),
            "avg_pe": vmeta.get("pe"),
            "avg_pb": vmeta.get("pb"),
            "pe_med": vmeta.get("pe_med"),
            "net_pct": vmeta.get("net_pct"),
            "turnover_pct": vmeta.get("turnover"),
            "ma250_pct": ma250_pct,
            "valuation_date": vdate,
        }
    except Exception:
        logger.exception("📊 [position] 今日实时行计算失败")
        return None


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
            # 振幅 / 低价股占比：同一天同一只票多源只取一条（按数据源优先级）
            "hi": {"$first": "$high"},
            "lo": {"$first": "$low"},
            "pc": {"$first": "$pre_close"},
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
            # 全市场平均振幅（%）：(最高-最低)/昨收，衡量日内波动与情绪
            "amp": {"$avg": {"$cond": [
                {"$and": [
                    {"$gt": [{"$ifNull": ["$hi", 0]}, 0]},
                    {"$gt": [{"$ifNull": ["$lo", 0]}, 0]},
                    {"$gt": [{"$ifNull": ["$pc", 0]}, 0]},
                ]},
                {"$multiply": [
                    {"$divide": [{"$subtract": ["$hi", "$lo"]}, "$pc"]},
                    100,
                ]},
                None,
            ]}},
            # 收盘价低于 3 元的个股数（底部特征：熊市末期低价股扎堆）
            "low_small": {"$sum": {"$cond": [
                {"$and": [{"$gt": [{"$ifNull": ["$close", 0]}, 0]}, {"$lt": ["$close", 3]}]},
                1, 0,
            ]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    return list(db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True))


def _aggregate_valuation(db, start: str, end: str | None) -> dict[str, dict[str, Any]]:
    """按交易日聚合全市场估值与参与度。

    返回 {日期: {pe, pb, pe_med, net_pct, turnover}}：
    - pe / pb：均值（剔除极端脏值）
    - pe_med：PE 中位数（MongoDB 4.4 无 $median，取当日有效 PE 列表在 Python 端求中位数）
    - net_pct：破净率（PB < 1 个股占比，%）
    - turnover：换手率均值（%）
    """
    date_match: dict[str, Any] = {"$gte": start}
    if end:
        date_match["$lte"] = end
    pipeline = [
        {"$match": {"trade_date": date_match}},
        {"$group": {
            "_id": "$trade_date",
            "pe": {"$avg": {"$cond": [
                {"$and": [{"$gt": ["$pe", 0]}, {"$lte": ["$pe", 500]}]}, "$pe", None,
            ]}},
            "pb": {"$avg": {"$cond": [
                {"$and": [{"$gt": ["$pb", 0]}, {"$lte": ["$pb", 50]}]}, "$pb", None,
            ]}},
            "turnover": {"$avg": {"$cond": [
                {"$and": [{"$gt": ["$turnover_rate", 0]}, {"$lte": ["$turnover_rate", 100]}]},
                "$turnover_rate", None,
            ]}},
            # 破净率：PB 有效且小于 1 的只数 / PB 有效总只数
            "pb_n": {"$sum": {"$cond": [
                {"$and": [{"$gt": ["$pb", 0]}, {"$lte": ["$pb", 50]}]}, 1, 0,
            ]}},
            "pb_net": {"$sum": {"$cond": [
                {"$and": [{"$gt": ["$pb", 0]}, {"$lt": ["$pb", 1]}]}, 1, 0,
            ]}},
            # 单日 5000 只个股的 PE 列表（约 40KB）远小于文档上限，可整日推送后在 Python 端求中位数
            "pe_vals": {"$push": {"$cond": [
                {"$and": [{"$gt": ["$pe", 0]}, {"$lte": ["$pe", 500]}]}, "$pe", "$$REMOVE",
            ]}},
        }},
    ]
    out: dict[str, dict[str, Any]] = {}
    for r in db["stock_daily_basic"].aggregate(pipeline, allowDiskUse=True):
        d = _normalize_date(r.get("_id"))
        if not d:
            continue
        pe_vals = [_f(v) for v in (r.get("pe_vals") or [])]
        pb_n = int(r.get("pb_n") or 0)
        pb_net = int(r.get("pb_net") or 0)
        out[d] = {
            "pe": round(_f(r["pe"]), 2) if r.get("pe") is not None else None,
            "pb": round(_f(r["pb"]), 2) if r.get("pb") is not None else None,
            "pe_med": round(_median(pe_vals), 2) if pe_vals else None,
            "net_pct": round(pb_net / pb_n * 100, 2) if pb_n else None,
            "turnover": round(_f(r["turnover"]), 2) if r.get("turnover") is not None else None,
        }
    return out


def _ma250_breadth_map(db, start: str, end: str) -> dict[str, float]:
    """站上 250 日线（年线）的个股占比（%），按交易日统计。

    这是位置判断最有力的广度证据：回答「多数股票是否真的处在长期上升趋势里」。
    逐股滚动均线的计算量无法用一次聚合完成，这里按 symbol 推送收盘价序列
    （单只票一个文档），在 Python 端滚动求 MA250，游标逐条处理以控制内存。
    日期早于 start 的只参与均线预热，不产出结果。
    """
    try:
        lookback = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=420)).strftime("%Y-%m-%d")
    except ValueError:
        return {}
    pipeline = [
        {"$match": {"period": "daily", "trade_date": {"$gte": lookback},
                    "close": {"$gt": 0}, "pct_chg": {"$ne": None}}},
        {"$project": {"symbol": 1, "trade_date": 1, "close": 1}},
        {"$group": {"_id": "$symbol",
                    "pairs": {"$push": {"d": "$trade_date", "c": "$close"}}}},
    ]
    above: dict[str, int] = {}
    total: dict[str, int] = {}
    for doc in db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True):
        # 同一只票可能多源重复：按日期去重（保留首条有效收盘价）
        by_date: dict[str, float] = {}
        for p in doc.get("pairs") or []:
            d = _normalize_date((p or {}).get("d"))
            c = _f((p or {}).get("c"))
            if d and c > 0 and d not in by_date:
                by_date[d] = c
        if len(by_date) < 250:
            continue
        pairs = sorted(by_date.items())
        arr = [c for _, c in pairs]
        win_sum = 0.0
        for i, (d, c) in enumerate(pairs):
            win_sum += c
            if i >= 250:
                win_sum -= arr[i - 250]
            if i + 1 < 250 or d < start or d > end:
                continue
            ma = win_sum / 250
            total[d] = total.get(d, 0) + 1
            if c > ma:
                above[d] = above.get(d, 0) + 1
    return {d: round(above.get(d, 0) / n * 100, 2) for d, n in total.items() if n >= 100}


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

    # 站上 250 日线占比：逐股滚动均线，一次算好整段映射（毫秒级查库 + 秒级计算）
    breadth_map = _ma250_breadth_map(db, start_dt.strftime("%Y-%m-%d"), latest)

    total = 0
    cursor = start_dt
    now = now_tz()
    # 参考样本数：最近已入库的 30 个交易日 + 本次已处理块的样本数中位数。
    # 低于参考 60% 的交易日视为「行情数据不完整」（当日盘中快照、分源回填中途），
    # 直接跳过不写库，避免把半天的成交额/涨跌家数写进 10 年基线。
    stored_ns = [
        int(r.get("n") or 0)
        for r in db[COLLECTION].find({}, {"n": 1}).sort("date", -1).limit(30)
        if int(r.get("n") or 0) > 0
    ]
    batch_ns: list[int] = []
    while cursor <= latest_dt:
        chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), latest_dt)
        s, e = cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        quotes = _aggregate_quotes(db, s, e)
        valuation = _aggregate_valuation(db, s, e)
        ref_ns = stored_ns + batch_ns
        ref_n = int(_median(ref_ns) or 0) if ref_ns else 0
        docs = []
        for r in quotes:
            d = _normalize_date(r.get("_id"))
            n = int(r.get("n") or 0)
            if not d or n <= 0:
                continue
            if ref_n and n < ref_n * 0.6:
                logger.info(f"📊 [position] 跳过不完整交易日 {d}：仅 {n} 只个股（参考 {ref_n}）")
                continue
            up = int(r.get("up") or 0)
            zt = int(r.get("zt") or 0)
            v = valuation.get(d) or {}
            docs.append({
                "date": d,
                "n": n,
                "up": up,
                "down": int(r.get("down") or 0),
                "up_pct": round(up / n * 100, 2),
                "zt": zt,
                # 涨停家数占比（%）：情绪极值，与波动率互补
                "zt_pct": round(zt / n * 100, 2),
                "amount": round(_f(r.get("amount")) / 1e8, 2),
                "avg_pct": round(_f(r.get("avg_pct")), 3),
                # 平均振幅（%）与低价股（<3 元）占比（%）
                "amp_pct": round(_f(r.get("amp")), 2) if r.get("amp") is not None else None,
                "low_pct": round(int(r.get("low_small") or 0) / n * 100, 2),
                "avg_pe": v.get("pe"),
                "avg_pb": v.get("pb"),
                # 估值中位 / 破净率 / 换手率：估值与底部特征的佐证项
                "pe_med": v.get("pe_med"),
                "net_pct": v.get("net_pct"),
                "turnover_pct": v.get("turnover"),
                # 站上 250 日线的个股占比（%）：广度确认
                "ma250_pct": breadth_map.get(d),
                "updated_at": now,
            })
        batch_ns.extend(int(r.get("n") or 0) for r in quotes if int(r.get("n") or 0) > 0)
        total += _upsert_docs(db, docs)
        cursor = chunk_end + timedelta(days=1)

    logger.info(f"📊 [position] 历史分位基线构建完成：{total} 个交易日（{start_dt.date()} ~ {latest_dt.date()}）")
    # 行业表现基线随位置基线同步增量（幂等 upsert），供「同分位时点行业榜」查询
    try:
        ind_total = _build_industry_perf_sync(
            db, start_dt.strftime("%Y-%m-%d"), latest_dt.strftime("%Y-%m-%d"))
        logger.info(f"📊 [position] 行业表现基线同步完成：{ind_total} 条")
    except Exception:
        logger.exception("📊 [position] 行业表现基线同步失败（不影响位置基线）")
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
    """按扩展窗口计算每个点的历史分位（只用当天之前的数据，避免未来函数）。

    与 _rank 同为中位秩口径（重复值取两侧均值），保证历史曲线与指标卡分位一致。
    """
    prev: list[float] = []
    out: list[int | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        if len(prev) < MIN_HISTORY_ROWS:
            out.append(None)
        else:
            mid_rank = (bisect.bisect_left(prev, v) + bisect.bisect_right(prev, v)) / 2
            out.append(round(mid_rank / len(prev) * 100))
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


def _pct_series(series: list[float | None]) -> list[int | None]:
    """对整条序列做扩展窗口分位（无未来函数）。"""
    return _rank_series([_f(v) if v is not None else None for v in series])


def _zt_ratio(row: dict) -> float | None:
    """涨停家数占比（%）：新行直接有 zt_pct，旧行用 zt / n 现算。"""
    v = row.get("zt_pct")
    if v is not None:
        return _f(v)
    zt, n = int(row.get("zt") or 0), int(row.get("n") or 0)
    return round(zt / n * 100, 2) if n else None


def _heat_of(pct: int | None, higher_is_hot: bool) -> int | None:
    """把「指标分位」统一成「热度分位」：越高越热。"""
    if pct is None:
        return None
    return pct if higher_is_hot else 100 - pct


def _index_series(rows: list[dict]) -> list[float]:
    """等权全市场指数（用当日个股等权平均涨跌幅复利累乘）。"""
    idx = 100.0
    out: list[float] = []
    for r in rows:
        v = r.get("avg_pct")
        idx *= 1 + (_f(v) / 100 if v is not None else 0.0)
        out.append(idx)
    return out


# 量比基准要求的最少历史天数（约 1 年）：不足则量比为 None，曲线该段不参与合成
RATIO_MIN_BASE_DAYS = 200
# 开盘不足 60 分钟（25% 进度）时不给成交额分位：开盘放量占全天比例在 7%~15% 之间波动，
# 任何折算都会放大成极端分位（实测 09:34 线性折算得出 9 万亿 → 100 分位）
AMOUNT_PROJECT_MIN_PROGRESS = 0.25


def _ratio_series(values: list[float | None], window: int = 250) -> list[float | None]:
    """量比序列：当日值 ÷ 前 window 日均值（不含当日）。

    成交额等累计型指标随市场扩容长期上行，绝对值分位在 10 年窗口里必然持续偏高，
    改用「相对近一年常态的放量倍数」算分位，剔除扩容趋势；前 RATIO_MIN_BASE_DAYS
    天基准不足返回 None（曲线该段本就是「参照系未成形」阴影区）。
    """
    out: list[float | None] = []
    for i, v in enumerate(values):
        if v is None:
            out.append(None)
            continue
        base = [x for x in values[max(0, i - window): i] if x is not None and x > 0]
        if len(base) < RATIO_MIN_BASE_DAYS:
            out.append(None)
            continue
        mean = sum(base) / len(base)
        out.append(round(_f(v) / mean, 4) if mean > 0 else None)
    return out


def _drawdown_series(idx: list[float], window: int = 250) -> list[float | None]:
    """距近 250 个交易日最高点的回撤（%，正数表示低于高点多少）。"""
    out: list[float | None] = []
    for i, v in enumerate(idx):
        hi = max(idx[max(0, i - window + 1): i + 1])
        out.append(round((hi - v) / hi * 100, 2) if hi > 0 else None)
    return out


def _ma_dev_series(idx: list[float], window: int = 250) -> list[float | None]:
    """相对 250 日均线（年线）的偏离（%），正值为年线上方。"""
    out: list[float | None] = []
    for i, v in enumerate(idx):
        seg = idx[max(0, i - window + 1): i + 1]
        ma = sum(seg) / len(seg)
        out.append(round((v / ma - 1) * 100, 2) if ma > 0 else None)
    return out


def _momentum_series(idx: list[float], window: int = 20) -> list[float | None]:
    """等权指数近 N 个交易日涨幅（%）：回答「最近在往上还是往下」。"""
    out: list[float | None] = []
    for i, v in enumerate(idx):
        if i < window:
            out.append(None)
            continue
        base = idx[i - window]
        out.append(round((v / base - 1) * 100, 2) if base > 0 else None)
    return out


def _low_gain_series(idx: list[float], window: int = 250) -> list[float | None]:
    """距近 250 个交易日最低点的涨幅（%）：与「距高点回撤」配对，构成位置区间。"""
    out: list[float | None] = []
    for i, v in enumerate(idx):
        lo = min(idx[max(0, i - window + 1): i + 1])
        out.append(round((v / lo - 1) * 100, 2) if lo > 0 else None)
    return out


def _volatility_series(rows: list[dict], window: int = 20) -> list[float | None]:
    """等权指数近 N 日日收益的年化标准差（%）。"""
    rets = [
        math.log1p(_f(r.get("avg_pct")) / 100) if r.get("avg_pct") is not None else None
        for r in rows
    ]
    out: list[float | None] = []
    for i in range(len(rows)):
        seg = [v for v in rets[max(0, i - window + 1): i + 1] if v is not None]
        if len(seg) < 5:
            out.append(None)
            continue
        m = sum(seg) / len(seg)
        var = sum((v - m) ** 2 for v in seg) / len(seg)
        out.append(round(math.sqrt(var) * math.sqrt(252) * 100, 2))
    return out


def _forward_returns(rows: list[dict]) -> list[float | None]:
    """每个时点之后 FORWARD_DAYS 个交易日的等权收益（%）。"""
    log_ret = [
        math.log1p(_f(r.get("avg_pct")) / 100) if r.get("avg_pct") is not None else 0.0
        for r in rows
    ]
    prefix = [0.0]
    for v in log_ret:
        prefix.append(prefix[-1] + v)
    out: list[float | None] = []
    for i in range(len(rows)):
        j = i + FORWARD_DAYS
        if j + 1 >= len(prefix):
            out.append(None)
        else:
            out.append(round(math.expm1(prefix[j + 1] - prefix[i + 1]) * 100, 2))
    return out


def _forward_stats(rows: list[dict], composite_series: list[int | None],
                   fwd_returns: list[float | None]) -> dict[str, Any] | None:
    """把历史按合成分位分成 5 档，统计未来 20 日等权收益的中位数与胜率。"""
    if len(rows) < MIN_FORWARD_ROWS:
        return None

    bins = [
        {"key": f"b{i}", "label": f"{i * 20}–{i * 20 + 20}%", "lo": i * 20, "hi": i * 20 + 20,
         "n": 0, "returns": []}
        for i in range(5)
    ]
    for i, pct in enumerate(composite_series):
        ret = fwd_returns[i]
        if pct is None or ret is None:
            continue
        idx = min(4, pct // 20)
        bins[idx]["n"] += 1
        bins[idx]["returns"].append(ret)

    total_n = sum(b["n"] for b in bins)
    if total_n < 100:
        return None

    def stat(rets: list[float]) -> dict[str, Any]:
        return {
            "n": len(rets),
            "median_return": round(_median(rets) or 0.0, 2) if rets else None,
            "win_rate": round(sum(1 for v in rets if v > 0) / len(rets) * 100, 1) if rets else None,
        }

    out_bins = []
    for b in bins:
        out_bins.append({
            "key": b["key"],
            "label": b["label"],
            "lo": b["lo"],
            "hi": b["hi"],
            **stat(b["returns"]),
        })

    current = composite_series[-1] if composite_series else None
    current_bin = f"b{min(4, current // 20)}" if current is not None else None
    return {
        "day": FORWARD_DAYS,
        "samples": total_n,
        "window_years": _window_years([r["date"] for r in rows]),
        "bins": out_bins,
        "current_bin": current_bin,
        "current_percentile": current,
        # 逃顶 / 判断底部的历史证据：最热 20% 与最冷 20% 的未来 20 日表现
        "zones": {
            "hot": {"label": "合成分位 ≥80%（历史最热 20%）", **stat(bins[4]["returns"])},
            "cold": {"label": "合成分位 ≤20%（历史最冷 20%）", **stat(bins[0]["returns"])},
        },
    }


def _composite_points(rows: list[dict], composite_series: list[int | None],
                      max_points: int = MAX_SERIES_POINTS,
                      keep_dates: set[str] | None = None) -> list[dict[str, Any]]:
    """合成分位历史曲线（等距抽稀，末点固定为最新交易日）。

    keep_dates：必须保留在曲线上的日期（如同分位历史时点），否则抽稀后
    前端散点找不到对应 x 轴位置而丢失。
    """
    pts = [(rows[i]["date"], v) for i, v in enumerate(composite_series) if v is not None]
    if not pts:
        return []
    if len(pts) <= max_points:
        return [{"date": d, "pct": int(v)} for d, v in pts]
    step = (len(pts) - 1) / (max_points - 1)
    picked = [pts[int(round(i * step))] for i in range(max_points)]
    picked[-1] = pts[-1]
    if keep_dates:
        have = {d for d, _ in picked}
        picked.extend(p for p in pts if p[0] in keep_dates and p[0] not in have)
        picked.sort(key=lambda p: p[0])
    return [{"date": d, "pct": int(v)} for d, v in picked]


def _analogs(rows: list[dict], dims: list[list[int | None]], composite_series: list[int | None],
             fwd_returns: list[float | None], top_n: int = 6, min_gap: int = 30) -> dict[str, Any] | None:
    """历史类比：在「热度分位」空间里找最像今天的交易日，统计其未来 20 日表现。"""
    n = len(rows)
    if n < MIN_FORWARD_ROWS:
        return None
    target = [d[-1] for d in dims]
    if any(t is None for t in target):
        return None

    usable = [
        i for i in range(n)
        if fwd_returns[i] is not None and all(d[i] is not None for d in dims)
    ]
    if len(usable) < 50:
        return None

    dist = {i: sum((d[i] - t) ** 2 for d, t in zip(dims, target)) for i in usable}
    picked: list[int] = []
    for i in sorted(usable, key=lambda k: dist[k]):
        if any(abs(i - p) < min_gap for p in picked):
            continue
        picked.append(i)
        if len(picked) >= top_n:
            break
    if not picked:
        return None

    cases = []
    for i in picked:
        rms = math.sqrt(dist[i] / len(dims))
        cases.append({
            "date": rows[i]["date"],
            "composite": composite_series[i],
            "forward_return": fwd_returns[i],
            "similarity": int(round(max(0, 100 - rms))),
        })
    rets = [c["forward_return"] for c in cases]
    return {
        "metric": "合成分位 + 回撤 + 宽度 + 成交额 + 振幅",
        "day": FORWARD_DAYS,
        "n": len(cases),
        "median_return": round(_median(rets) or 0.0, 2),
        "win_rate": round(sum(1 for v in rets if v > 0) / len(rets) * 100, 1),
        "cases": cases,
        "note": "在历史热度分位空间里找最像今天的交易日（相邻样本至少间隔 30 个交易日）；"
                "收益为之后 20 个交易日的等权涨跌幅，仅作历史统计，不代表未来",
    }


def _guidance(zone: dict[str, Any], composite: float | None,
              fwd: dict[str, Any] | None) -> dict[str, Any]:
    """把「逃顶 / 判断底部」的判据与历史证据整理成前端可直接渲染的说明块。"""
    zones = (fwd or {}).get("zones") or {}

    def stat_text(z: dict[str, Any] | None, default: str) -> str:
        if not z or not z.get("n"):
            return default
        med = z.get("median_return")
        win = z.get("win_rate")
        if med is None or win is None:
            return default
        return (f"历史 {z['n']} 个同类交易日，其后 {FORWARD_DAYS} 日等权收益中位数 {med}%，"
                f"上涨概率 {win}%")

    short = "历史样本不足 3 年，暂不给出统计"
    return {
        "top": {
            "key": "top",
            "title": "逃顶（高位区）",
            "rule": f"合成分位 ≥{TOP_THRESHOLD}：位置、情绪、参与度多数处于历史高位",
            "stats": stat_text(zones.get("hot"), short),
            "threshold": TOP_THRESHOLD,
            "active": bool(composite is not None and composite >= TOP_THRESHOLD),
            "advice": "优先减仓兑现，不追高；宽度与量能同步走弱时加快撤退",
        },
        "bottom": {
            "key": "bottom",
            "title": "判断底部（低位区）",
            "rule": f"合成分位 ≤{BOTTOM_THRESHOLD}：回撤接近历史极值、低价股占比抬升、波动率处于高位",
            "stats": stat_text(zones.get("cold"), short),
            "threshold": BOTTOM_THRESHOLD,
            "active": bool(composite is not None and composite <= BOTTOM_THRESHOLD),
            "advice": "低位区只是观察区，不抢跑；需宽度回升 + 波动率回落 + 年线偏离收窄确认后再分批建仓",
        },
        "current": {"zone": zone.get("zone"), "label": zone.get("label"),
                    "percentile": composite, "advice": zone.get("advice", "")},
    }


def _divergence(percentiles: dict[str, int | None], composite: float | None) -> list[dict[str, Any]]:
    """用当前位置指标分位识别背离（指标分位，不是热度分位）。"""
    val = percentiles.get("valuation_pe")
    breadth = percentiles.get("up_pct")
    funds = percentiles.get("amount")
    dd = percentiles.get("drawdown")
    vol = percentiles.get("volatility")

    out: list[dict[str, Any]] = []
    if val is not None and breadth is not None:
        if val >= 70 and breadth <= 35:
            out.append({"level": "danger", "title": "估值与宽度背离",
                        "detail": f"PE 处 {val}% 高位，但上涨家数仅 {breadth}% 分位，指数可能由少数权重支撑"})
        elif val <= 30 and breadth >= 65:
            out.append({"level": "info", "title": "估值与宽度背离",
                        "detail": f"PE 处 {val}% 低位，但宽度已回升至 {breadth}% 分位，留意估值修复"})
    if breadth is not None and funds is not None:
        if breadth >= 65 and funds <= 35:
            out.append({"level": "warning", "title": "量价背离",
                        "detail": f"上涨家数处 {breadth}% 分位，但成交额仅 {funds}% 分位，上涨缺少量能支撑"})
        elif breadth <= 35 and funds >= 70:
            out.append({"level": "warning", "title": "放量下跌",
                        "detail": f"上涨家数仅 {breadth}% 分位，成交额却在 {funds}% 高位，抛压需要时间消化"})
    if dd is not None and vol is not None and dd >= 80 and vol >= 80:
        out.append({"level": "danger", "title": "深回撤 + 高波动",
                    "detail": f"指数距 250 日高点回撤深度处 {dd}% 分位，波动率同时处于 {vol}% 高位，"
                              "属于下跌加速段，不宜抢反弹"})
    if composite is not None and composite >= 80 and not out:
        out.append({"level": "info", "title": "位置进入高位区",
                    "detail": "位置、情绪与参与度同时处于历史高位，继续追高需要更强的催化"})
    if composite is not None and composite <= 20 and not out:
        out.append({"level": "info", "title": "位置进入低位区",
                    "detail": "多项指标同时处于历史低位，进入「判断底部」观察区，等宽度回升与波动率回落再确认"})
    return out[:3]


def _series_metric(rows: list[dict], series: list[float | None], *, key: str, group: str, label: str,
                   unit: str, higher_is_hot: bool, desc: str,
                   rank_series: list[float | None] | None = None) -> dict[str, Any]:
    """由一条序列生成指标卡：当前值 + 当前值在历史中的分位。

    rank_series 用于「展示值与分位口径不同」的指标（如盘中成交额按交易进度
    折算后再比全天历史），未传时与展示序列一致。
    """
    valid = [i for i, v in enumerate(series) if v is not None]
    if not valid:
        return {"key": key, "group": group, "label": label, "unit": unit, "value": None,
                "percentile": None, "percentile_1y": None, "window_years": 0, "samples": 0,
                "as_of": "", "higher_is_hot": higher_is_hot, "desc": desc}
    cur_i = valid[-1]
    rank_src = rank_series if rank_series is not None else series
    # 分位序列可能含 None（如量比的基准未成形段），必须过滤，避免被 _f 压成 0 污染分位
    hist = [_f(rank_src[i]) for i in valid if i < cur_i and rank_src[i] is not None]
    cur = round(_f(series[cur_i]), 2)
    pct = (_rank(hist, _f(rank_src[cur_i]))
           if hist and rank_src[cur_i] is not None else None)
    # 近 1 年分位对照：短窗口受长期趋势漂移影响小；与 10 年分位差距大即提示结构性漂移
    try:
        cutoff_1y = (datetime.strptime(rows[cur_i]["date"], "%Y-%m-%d")
                     - timedelta(days=365)).strftime("%Y-%m-%d")
    except ValueError:
        cutoff_1y = ""
    hist_1y = [_f(rank_src[i]) for i in valid
               if i < cur_i and rank_src[i] is not None and rows[i]["date"] >= cutoff_1y]
    pct_1y = (_rank(hist_1y, _f(rank_src[cur_i]))
              if len(hist_1y) >= MIN_HISTORY_ROWS and rank_src[cur_i] is not None else None)
    return {
        "key": key,
        "group": group,
        "label": label,
        "unit": unit,
        "value": cur,
        "percentile": pct,
        "percentile_1y": pct_1y,
        "window_years": _window_years([rows[i]["date"] for i in valid]),
        "samples": len(hist),
        # 当前值实际所属交易日（估值取 daily_basic，可能比实时行早一天）
        "as_of": rows[cur_i]["date"],
        "higher_is_hot": higher_is_hot,
        "desc": desc,
    }


def compute_position_payload(rows: list[dict], live_row: dict[str, Any] | None = None,
                             progress: float = 1.0) -> dict[str, Any]:
    """由历史日度行计算当前位置、历史类比、未来收益分布与背离（纯函数）。

    live_row 为当日实时快照补出的行（由 _live_row_sync 生成），传入后「最新一行」
    即为今天，合成分位、背离、历史类比都会用今天的数据；progress 是当日交易进度，
    用于把盘中累计成交额折算成全天口径后再比历史分位（否则午间必然显示低分位）。
    """
    if not rows:
        return _empty_payload("历史样本为空")

    rows = sorted(rows, key=lambda r: r["date"])
    latest = rows[-1]
    history = rows[:-1]
    is_live = bool(live_row) and latest["date"] == _normalize_date((live_row or {}).get("date"))

    idx = _index_series(rows)
    specs = [
        # key, group, label, unit, series, higher_is_hot, desc, 是否参与合成
        ("valuation_pe", "估值", "PE 均值", "倍", [r.get("avg_pe") for r in rows], True,
         "全市场平均市盈率，越高代表整体估值越贵；样本自 2024-07 起", False),
        ("valuation_pb", "估值", "PB 均值", "倍", [r.get("avg_pb") for r in rows], True,
         "全市场平均市净率，越低代表资产价格越便宜；样本自 2024-07 起", False),
        ("drawdown", "位置", "距 250 日高点回撤", "%", _drawdown_series(idx), False,
         "等权全市场指数距近 250 个交易日最高点还差多少，回撤越深位置越低（分位越高越冷）", True),
        ("ma250_dev", "位置", "年线偏离", "%", _ma_dev_series(idx), True,
         "等权指数相对 250 日均线（年线）的偏离，正值为年线上方，越高越热", True),
        ("amplitude", "情绪", "平均振幅", "%", [r.get("amp_pct") for r in rows], True,
         "全市场个股日内振幅（最高-最低）/昨收 的平均值，越高说明日内博弈越激烈", True),
        ("volatility", "情绪", "20 日波动率", "%", _volatility_series(rows), True,
         "等权指数近 20 日收益的年化标准差，越高说明市场越不稳定", True),
        ("amount", "参与度", "成交额", "亿", [r.get("amount") for r in rows], True,
         "全市场成交额（亿）；分位按「当日 ÷ 近 250 日均值」的量比计算，"
         "剔除市场扩容带来的长期上行趋势，越高说明资金参与越活跃", True),
        ("up_pct", "参与度", "上涨家数占比", "%", [r.get("up_pct") for r in rows], True,
         "上涨家数占全市场比重，越高说明上涨越普遍", True),
        ("low_price", "底部特征", "3 元以下个股占比", "%", [r.get("low_pct") for r in rows], False,
         "收盘价低于 3 元的个股占比，熊市末期往往明显抬升（分位越高越冷）", True),
        # 以下为佐证项：只作为标尺上的独立证据点，不参与合成分位，避免改变既有口径
        ("ma250_breadth", "广度", "站上 250 日线占比", "%", [r.get("ma250_pct") for r in rows], True,
         "收盘价高于自身 250 日均线（年线）的个股占比，衡量多数股票是否真的处在长期上升趋势里", False),
        ("momentum20", "趋势", "20 日动量", "%", _momentum_series(idx), True,
         "等权指数近 20 个交易日涨幅，正值为上涨趋势；用来区分「低位止跌」与「低位续跌」", False),
        ("low_gain", "位置", "距 250 日低点涨幅", "%", _low_gain_series(idx), True,
         "等权指数相对近 250 日最低点已反弹多少，与「距高点回撤」配对构成完整的位置区间", False),
        ("zt_ratio", "情绪", "涨停家数占比", "%", [_zt_ratio(r) for r in rows], True,
         "当日涨停家数占全市场比重，衡量投机资金的极端活跃度，与波动率互补", False),
        ("break_net", "底部特征", "破净率", "%", [r.get("net_pct") for r in rows], False,
         "市净率低于 1 倍的个股占比，越高说明越多个股跌破净资产；熊市底部往往明显抬升（分位越高越冷）", False),
        ("pe_median", "估值", "PE 中位数", "倍", [r.get("pe_med") for r in rows], True,
         "全市场市盈率中位数，比均值更抗极端值；越高代表整体估值越贵；样本自 2024-07 起", False),
        ("turnover", "参与度", "平均换手率", "%", [r.get("turnover_pct") for r in rows], True,
         "全市场个股换手率均值，衡量资金换手活跃度，比绝对成交额更可跨期比较；样本自 2024-07 起", False),
    ]

    series_by_key = {spec[0]: spec[4] for spec in specs}
    # 分位口径序列：成交额改用「量比」（当日 ÷ 近 250 日均值）比分位，剔除扩容趋势；
    # 展示值仍是实际成交额（亿）。盘中先按交易进度折算全天成交额再算量比。
    rank_series_by_key = {k: list(v) for k, v in series_by_key.items()}
    rank_series_by_key["amount"] = _ratio_series(series_by_key["amount"])
    amount_projected = None
    amount_too_early = is_live and 0.0 < progress < AMOUNT_PROJECT_MIN_PROGRESS
    if is_live and 0.0 < progress:
        actual = _f(series_by_key["amount"][-1])
        base = [x for x in series_by_key["amount"][-1 - 250: -1] if x is not None and x > 0]
        base_ok = len(base) >= RATIO_MIN_BASE_DAYS
        if amount_too_early:
            # 开盘不到 60 分钟时，开盘放量占全天的比例本身波动极大（7%~15%），
            # 任何折算都会给出极端分位（曾出现 09:34 折算出 9 万亿 → 100 分位）。
            # 此时不给分位数字，内部按量比 1.0（中性）参与合成，避免污染其他判断。
            if base_ok:
                rank_series_by_key["amount"][-1] = 1.0
        else:
            # 60 分钟之后按日内成交曲线折算，而不是按时间进度线性外推
            share = _intraday_amount_share(progress)
            if actual > 0 and share > 0:
                amount_projected = round(actual / share, 2)
                if base_ok:
                    rank_series_by_key["amount"][-1] = round(
                        amount_projected / (sum(base) / len(base)), 4
                    )

    metrics: list[dict[str, Any]] = []
    for key, group, label, unit, series, hot, desc, in_composite in specs:
        m = _series_metric(rows, series, key=key, group=group, label=label, unit=unit,
                           higher_is_hot=hot, desc=desc, rank_series=rank_series_by_key[key])
        m["in_composite"] = in_composite
        if is_live:
            m["live"] = True
            # 估值来自 daily_basic，若其日期早于实时行，卡片需标注真实数据日期
            if key in ("valuation_pe", "valuation_pb", "break_net", "pe_median", "turnover"):
                vdate = _normalize_date((live_row or {}).get("valuation_date"))
                if vdate:
                    m["as_of"] = vdate
                    m["live"] = False
            if key == "amount" and amount_projected is not None:
                m["projected_value"] = amount_projected
                m["progress"] = round(progress, 4)
                m["desc"] = f"{desc}（盘中已交易 {round(progress * 240)} 分钟，按日内成交曲线折算全天后算量比）"
            elif key == "amount" and amount_too_early:
                # 开盘不足 60 分钟：值照常展示，但不给分位数字（合成里按中性计入）
                m["percentile"] = None
                m["desc"] = f"{desc}（开盘不足 60 分钟，开盘放量占比波动大，分位暂不折算）"
        metrics.append(m)

    # 合成分位：长历史指标统一折算成热度分位后取均值；估值样本不足 3 年时不参与合成
    hot_by_key = {spec[0]: spec[5] for spec in specs}
    long_keys = [spec[0] for spec in specs if spec[7]]

    heat_series = [
        [_heat_of(p, hot_by_key[k]) for p in _pct_series(rank_series_by_key[k])]
        for k in long_keys
    ]
    composite_series: list[int | None] = []
    for i in range(len(rows)):
        vals = [hs[i] for hs in heat_series if hs[i] is not None]
        composite_series.append(round(sum(vals) / len(vals)) if vals else None)
    composite = composite_series[-1] if composite_series else None

    zone = _zone_of(composite)
    fwd_returns = _forward_returns(rows)
    fwd = _forward_stats(rows, composite_series, fwd_returns)
    percentiles = {m["key"]: m["percentile"] for m in metrics}
    same_level = _same_level_points(rows, composite_series, fwd_returns)

    # 历史类比用的状态向量：整体热度 + 回撤深度 + 宽度 + 成交额 + 振幅（均已折算成热度）
    def heat_of_key(key: str) -> list[int | None]:
        return [_heat_of(p, hot_by_key[key]) for p in _pct_series(rank_series_by_key[key])]

    dims = [
        composite_series,
        heat_of_key("drawdown"),
        heat_of_key("up_pct"),
        heat_of_key("amount"),
        heat_of_key("amplitude"),
    ]

    return {
        "ready": True,
        "as_of": latest["date"],
        # live=True 表示最后一行来自当日实时快照（盘中），而非收盘后固化的完整日线
        "live": is_live,
        "baseline_as_of": history[-1]["date"] if history else "",
        "amount_projected": amount_projected,
        "progress": round(progress, 4) if is_live else 1.0,
        "updated": now_tz().isoformat(),
        # 分位窗口：固定近 10 年设计值 + 真实起止日期（前端统一展示，不再显示「10.1 年」）
        "window": {"start": rows[0]["date"], "end": latest["date"], "years": POSITION_YEARS},
        "window_years": _window_years([r["date"] for r in rows]),
        "samples": len(history),
        "position": metrics,
        "composite": {
            "percentile": composite,
            "label": zone["label"],
            "zone": zone["zone"],
            "advice": zone["advice"],
            "components": [m["key"] for m in metrics if m["in_composite"]],
            # 历史合成分位曲线 + 逃顶 / 判底阈值；same_level 日期强制保留在曲线上
            "series": _composite_points(rows, composite_series,
                                        keep_dates={p["date"] for p in same_level}),
            "thresholds": {"top": TOP_THRESHOLD, "bottom": BOTTOM_THRESHOLD},
        },
        "forward": fwd,
        "guidance": _guidance(zone, composite, fwd),
        "analogs": _analogs(rows, dims, composite_series, fwd_returns),
        "divergence": _divergence(percentiles, composite),
        # 与当前合成分位相同（±2）的历史时点：走势图高亮 + 行业榜联动
        "same_level": same_level,
        "note": "分位窗口固定近 10 年；成交额按「当日 ÷ 近 250 日均值」量比分位以剔除扩容趋势；"
                "PE / PB 仅有 2024-07 之后的样本，不足 3 年不参与合成，仅供参考",
    }


def _same_level_points(rows: list[dict], composite_series: list[int | None],
                       fwd_returns: list[float | None], band: int = 2,
                       max_points: int = 20) -> list[dict[str, Any]]:
    """与当前合成分位相同（±band）的历史时点（时间均匀抽稀，供走势图高亮与行业榜联动）。"""
    if not composite_series or composite_series[-1] is None:
        return []
    cur = composite_series[-1]
    cands = [
        i for i in range(len(rows) - 1)
        if composite_series[i] is not None and abs(composite_series[i] - cur) <= band
        and fwd_returns[i] is not None
    ]
    if len(cands) > max_points:
        step = len(cands) / max_points
        cands = [cands[int(i * step)] for i in range(max_points)]
    return [
        {"date": rows[i]["date"], "pct": composite_series[i], "fwd20": fwd_returns[i]}
        for i in cands
    ]


def _empty_payload(note: str = "历史分位基线首次构建中") -> dict[str, Any]:
    return {
        "ready": False,
        "as_of": "",
        "updated": now_tz().isoformat(),
        "window": {"start": "", "end": "", "years": POSITION_YEARS},
        "window_years": 0,
        "samples": 0,
        "position": [],
        "composite": {"percentile": None, "label": "构建中", "zone": "unknown", "advice": "",
                      "components": [], "series": [],
                      "thresholds": {"top": TOP_THRESHOLD, "bottom": BOTTOM_THRESHOLD}},
        "forward": None,
        "guidance": _guidance({"zone": "unknown", "label": "构建中", "advice": ""}, None, None),
        "analogs": None,
        "divergence": [],
        "same_level": [],
        "note": f"{note}，首次构建约需 1~2 分钟，完成后自动显示",
    }


async def _build() -> dict[str, Any]:
    db = _sync_db()
    count, _last = await asyncio.to_thread(_status_sync, db)
    if count < MIN_HISTORY_ROWS:
        _kick_build()
        return _empty_payload()
    rows = await asyncio.to_thread(lambda: list(db[COLLECTION].find({}, {"_id": 0}).sort("date", 1)))
    # 历史基线只含完整交易日；补一行当日实时快照，让「今日结论」真正用今天的数据。
    # 收盘后日线补齐、基线写入当天后，_live_row_sync 会自动返回 None，回到固化口径。
    live = await asyncio.to_thread(_live_row_sync, db)
    if live:
        from app.utils.date_utils import today_str

        progress = _session_progress() if live.get("date") == today_str() else 1.0
        return await asyncio.to_thread(compute_position_payload, rows + [live], live, progress)
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
    return await cached("vibe:market:position:v3", _build, ttl=ttl)


# ---------------------------------------------------------------------------
# 行业日度表现基线（industry_daily_perf）：「同分位时点行业榜」数据源
# ---------------------------------------------------------------------------

# THS_TO_LOCAL_INDUSTRIES 未覆盖的本地行业名补充（仅用于本聚合口径，不改筛选行为）；
# 目标名为同花顺行业口径（含该表缺失的 种植业与林业 / 养殖业 两个真同花顺行业）。
_INDUSTRY_LOCAL_SUPPLEMENT = {
    "机械基件": "通用设备",
    "建筑工程": "建筑装饰",
    "运输设备": "轨交设备",
    "农业综合": "种植业与林业",
    "种植业": "种植业与林业",
    "畜牧业": "养殖业",
    "渔业": "养殖业",
    "矿物制品": "非金属材料",
    "其他建材": "建筑材料",
    "机床制造": "通用设备",
    "饲料": "农产品加工",
    "综合类": "其他社会服务",
    "路桥": "公路铁路运输",
    "水务": "环境治理",
    "农用机械": "专用设备",
    "化工机械": "专用设备",
    "摩托车": "汽车整车",
}

_INDUSTRY_MAP_CACHE: dict[str, str] | None = None


def _symbol_industry_map(db) -> dict[str, str]:
    """symbol -> 同花顺行业名：THS_TO_LOCAL_INDUSTRIES 反向映射 + 补充表（进程内缓存）。

    口径说明：行业归属取当前 stock_basic_info 快照，回算历史存在轻微口径漂移
    （公司行业变更 / 新上市），对「行业等权涨跌榜」级别的展示影响可忽略。
    """
    global _INDUSTRY_MAP_CACHE
    if _INDUSTRY_MAP_CACHE is not None:
        return _INDUSTRY_MAP_CACHE
    from app.services.candidate_pool.candidate_pool_service import THS_TO_LOCAL_INDUSTRIES

    local2ths: dict[str, str] = {}
    for ths, locals_ in THS_TO_LOCAL_INDUSTRIES.items():
        for loc in locals_:
            local2ths.setdefault(loc, ths)
    for loc, ths in _INDUSTRY_LOCAL_SUPPLEMENT.items():
        local2ths.setdefault(loc, ths)

    out: dict[str, str] = {}
    for row in db["stock_basic_info"].find({}, {"symbol": 1, "industry": 1}):
        sym = str(row.get("symbol") or "")
        ths = local2ths.get(str(row.get("industry") or ""))
        if sym and ths:
            out[sym] = ths
    _INDUSTRY_MAP_CACHE = out
    return out


def _industry_perf_status(db) -> str:
    try:
        doc = db[INDUSTRY_PERF_COLLECTION].find({}, {"date": 1}).sort("date", -1).limit(1)
        row = next(doc, None)
        return (row or {}).get("date", "")
    except Exception:
        return ""


def _industry_perf_earliest(db) -> str:
    try:
        doc = db[INDUSTRY_PERF_COLLECTION].find({}, {"date": 1}).sort("date", 1).limit(1)
        row = next(doc, None)
        return (row or {}).get("date", "")
    except Exception:
        return ""


def _build_industry_perf_sync(db, start: str, end: str) -> int:
    """按日聚合行业等权涨跌幅（复用日线数据源优先级去重），写入 industry_daily_perf。"""
    sym_ind = _symbol_industry_map(db)
    if not sym_ind:
        return 0
    try:
        db[INDUSTRY_PERF_COLLECTION].create_index(
            [("date", 1), ("industry", 1)], unique=True,
            name="date_industry_uniq", background=True)
    except Exception:
        pass  # 索引已存在或并发创建冲突，不影响写入
    pipeline = [
        {"$match": {"period": "daily", "trade_date": {"$gte": start, "$lte": end},
                    "pct_chg": {"$ne": None}}},
        {"$addFields": {"prio": {"$switch": {
            "branches": [
                {"case": {"$eq": ["$data_source", "tushare"]}, "then": 0},
                {"case": {"$eq": ["$data_source", "baostock"]}, "then": 1},
                {"case": {"$eq": ["$data_source", "akshare"]}, "then": 2},
            ],
            "default": 3,
        }}}},
        {"$sort": {"trade_date": 1, "symbol": 1, "prio": 1}},
        # 同一 (交易日, 股票) 跨源重复时按数据源优先级取一条
        {"$group": {"_id": {"d": "$trade_date", "s": "$symbol"},
                    "pct": {"$first": "$pct_chg"}}},
    ]
    # (date, industry) -> [涨跌幅和, 家数, 上涨家数]
    acc: dict[tuple[str, str], list[float]] = {}
    for r in db["stock_daily_quotes"].aggregate(pipeline, allowDiskUse=True):
        d = _normalize_date(r["_id"]["d"])
        ind = sym_ind.get(str(r["_id"]["s"]))
        if not d or not ind:
            continue
        pct = _f(r.get("pct"))
        cell = acc.setdefault((d, ind), [0.0, 0.0, 0.0])
        cell[0] += pct
        cell[1] += 1
        cell[2] += 1 if pct > 0 else 0

    from pymongo import UpdateOne

    ops = []
    for (d, ind), (s, n, up) in acc.items():
        if n <= 0:
            continue
        ops.append(UpdateOne(
            {"date": d, "industry": ind},
            {"$set": {"date": d, "industry": ind,
                      "avg_pct": round(s / n, 3),
                      "up_pct": round(up / n * 100, 2),
                      "n": int(n),
                      "updated_at": now_tz()}},
            upsert=True,
        ))
    if ops:
        db[INDUSTRY_PERF_COLLECTION].bulk_write(ops, ordered=False)
    return len(ops)


async def ensure_industry_perf_history(force: bool = False) -> int:
    """行业表现基线与位置基线同窗口增量构建（后台任务调用，幂等 upsert）。"""
    db = _sync_db()

    def _run() -> int:
        latest = _latest_quote_date(db)
        if not latest:
            return 0
        latest_dt = datetime.strptime(latest, "%Y-%m-%d")
        window_start_dt = latest_dt - timedelta(days=POSITION_YEARS * 365 + 30)
        last = _industry_perf_status(db)
        if force or not last:
            start_dt = window_start_dt
        else:
            try:
                start_dt = datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                start_dt = window_start_dt
        total = 0
        # 头部缺口：历史回填若中断，最新日期已到但首日远晚于窗口起点，先补齐头部
        earliest = _industry_perf_earliest(db)
        if not force and earliest:
            try:
                earliest_dt = datetime.strptime(earliest, "%Y-%m-%d")
            except ValueError:
                earliest_dt = None
            if earliest_dt and earliest_dt > window_start_dt + timedelta(days=5):
                cursor = window_start_dt
                head_end = earliest_dt - timedelta(days=1)
                while cursor <= head_end:
                    chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), head_end)
                    total += _build_industry_perf_sync(
                        db, cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d"))
                    cursor = chunk_end + timedelta(days=1)
        if start_dt > latest_dt:
            return total
        cursor = start_dt
        while cursor <= latest_dt:
            chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), latest_dt)
            total += _build_industry_perf_sync(
                db, cursor.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d"))
            cursor = chunk_end + timedelta(days=1)
        return total

    return await asyncio.to_thread(_run)


def _industry_at_sync(date: str, mode: str) -> dict[str, Any] | None:
    """指定交易日的行业涨跌榜：mode=day 当日 / mode=fwd20 其后 20 日累计。"""
    db = _sync_db()
    date = _normalize_date(date)
    if not date:
        return None
    coll = db[INDUSTRY_PERF_COLLECTION]

    def top_rows(rows: list[dict], pct_key: str) -> dict[str, list[dict]]:
        rows = [r for r in rows if r.get(pct_key) is not None]
        rows.sort(key=lambda r: r[pct_key], reverse=True)
        def pick(rr: list[dict]) -> list[dict]:
            return [{"industry": r["industry"], "pct": round(r[pct_key], 2),
                     "up_pct": r.get("up_pct"), "n": r.get("n")} for r in rr]
        return {"up": pick(rows[:5]), "down": pick([*reversed(rows[-5:])]) if len(rows) >= 5 else []}

    if mode == "day":
        rows = list(coll.find({"date": date}, {"_id": 0}))
        if not rows:
            return None
        return {"date": date, "mode": mode, **top_rows(rows, "avg_pct")}

    # fwd20：该日期之后 FORWARD_DAYS 个交易日的行业等权累计收益（复利）
    dates = sorted(coll.distinct("date", {"date": {"$gt": date}}))[:FORWARD_DAYS]
    if len(dates) < FORWARD_DAYS:
        return None
    acc: dict[str, dict[str, float]] = {}
    for r in coll.find({"date": {"$in": dates}}, {"_id": 0}):
        cell = acc.setdefault(r["industry"], {"ret": 1.0, "up_sum": 0.0, "days": 0, "n": 0})
        cell["ret"] *= 1 + _f(r.get("avg_pct")) / 100
        cell["up_sum"] += _f(r.get("up_pct"))
        cell["days"] += 1
        cell["n"] = r.get("n") or 0
    rows = [{"industry": k,
             "cum_pct": round((v["ret"] - 1) * 100, 2),
             "up_pct": round(v["up_sum"] / v["days"], 2) if v["days"] else None,
             "n": int(v["n"])}
            for k, v in acc.items() if v["days"] >= FORWARD_DAYS * 0.9]
    if not rows:
        return None
    return {"date": date, "mode": mode, "days": len(dates),
            "end": dates[-1], **top_rows(rows, "cum_pct")}


_INDUSTRY_BACKFILL_TASK: asyncio.Task | None = None


async def get_industry_at(date: str, mode: str = "day") -> dict[str, Any] | None:
    """行业榜查询（Redis 缓存 30 分钟；基线缺失时后台补建后返回 None）。"""
    global _INDUSTRY_BACKFILL_TASK
    if mode not in ("day", "fwd20"):
        mode = "day"

    async def _run() -> dict[str, Any] | None:
        global _INDUSTRY_BACKFILL_TASK
        db = _sync_db()
        status = await asyncio.to_thread(_industry_perf_status, db)
        result = await asyncio.to_thread(_industry_at_sync, date, mode) if status else None
        if result is None:
            # 基线未建 / 该日未覆盖（头部缺口）：后台补建（幂等，任务去重），本次先返回 None
            if _INDUSTRY_BACKFILL_TASK is None or _INDUSTRY_BACKFILL_TASK.done():
                _INDUSTRY_BACKFILL_TASK = asyncio.get_running_loop().create_task(
                    ensure_industry_perf_history(False))
            return None
        return result

    return await cached(f"vibe:market:position:industry-at:{date}:{mode}", _run, ttl=1800)
