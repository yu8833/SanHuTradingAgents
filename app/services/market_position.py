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


def _aggregate_valuation(db, start: str, end: str | None) -> dict[str, tuple[float | None, float | None]]:
    """按交易日计算全市场平均 PE / PB（仅取有效正数，剔除极端脏值）。"""
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
        }},
    ]
    out: dict[str, tuple[float | None, float | None]] = {}
    for r in db["stock_daily_basic"].aggregate(pipeline, allowDiskUse=True):
        d = _normalize_date(r.get("_id"))
        if not d:
            continue
        pe = round(_f(r["pe"]), 2) if r.get("pe") is not None else None
        pb = round(_f(r["pb"]), 2) if r.get("pb") is not None else None
        out[d] = (pe, pb)
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
            pe, pb = valuation.get(d, (None, None))
            docs.append({
                "date": d,
                "n": n,
                "up": up,
                "down": int(r.get("down") or 0),
                "up_pct": round(up / n * 100, 2),
                "zt": int(r.get("zt") or 0),
                "amount": round(_f(r.get("amount")) / 1e8, 2),
                "avg_pct": round(_f(r.get("avg_pct")), 3),
                # 平均振幅（%）与低价股（<3 元）占比（%）
                "amp_pct": round(_f(r.get("amp")), 2) if r.get("amp") is not None else None,
                "low_pct": round(int(r.get("low_small") or 0) / n * 100, 2),
                "avg_pe": pe,
                "avg_pb": pb,
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


def _pct_series(series: list[float | None]) -> list[int | None]:
    """对整条序列做扩展窗口分位（无未来函数）。"""
    return _rank_series([_f(v) if v is not None else None for v in series])


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
            "rule": "合成分位 ≥80：位置、情绪、参与度多数处于历史高位",
            "stats": stat_text(zones.get("hot"), short),
            "active": bool(composite is not None and composite >= 80),
            "advice": "优先减仓兑现，不追高；宽度与量能同步走弱时加快撤退",
        },
        "bottom": {
            "key": "bottom",
            "title": "判断底部（低位区）",
            "rule": "合成分位 ≤20：回撤接近历史极值、低价股占比抬升、波动率处于高位",
            "stats": stat_text(zones.get("cold"), short),
            "active": bool(composite is not None and composite <= 20),
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
                   unit: str, higher_is_hot: bool, desc: str) -> dict[str, Any]:
    """由一条序列生成指标卡：当前值 + 当前值在历史中的分位。"""
    valid = [i for i, v in enumerate(series) if v is not None]
    if not valid:
        return {"key": key, "group": group, "label": label, "unit": unit, "value": None,
                "percentile": None, "window_years": 0, "samples": 0,
                "higher_is_hot": higher_is_hot, "desc": desc}
    cur_i = valid[-1]
    hist = [series[i] for i in valid if i < cur_i]
    cur = round(_f(series[cur_i]), 2)
    pct = _rank([_f(v) for v in hist], cur) if hist else None
    return {
        "key": key,
        "group": group,
        "label": label,
        "unit": unit,
        "value": cur,
        "percentile": pct,
        "window_years": _window_years([rows[i]["date"] for i in valid]),
        "samples": len(hist),
        "higher_is_hot": higher_is_hot,
        "desc": desc,
    }


def compute_position_payload(rows: list[dict]) -> dict[str, Any]:
    """由历史日度行计算当前位置、历史类比、未来收益分布与背离（纯函数）。"""
    if not rows:
        return _empty_payload("历史样本为空")

    rows = sorted(rows, key=lambda r: r["date"])
    latest = rows[-1]
    history = rows[:-1]

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
         "全市场成交额，越高说明资金参与越活跃", True),
        ("up_pct", "参与度", "上涨家数占比", "%", [r.get("up_pct") for r in rows], True,
         "上涨家数占全市场比重，越高说明上涨越普遍", True),
        ("low_price", "底部特征", "3 元以下个股占比", "%", [r.get("low_pct") for r in rows], False,
         "收盘价低于 3 元的个股占比，熊市末期往往明显抬升（分位越高越冷）", True),
    ]

    metrics: list[dict[str, Any]] = []
    for key, group, label, unit, series, hot, desc, in_composite in specs:
        m = _series_metric(rows, series, key=key, group=group, label=label, unit=unit,
                           higher_is_hot=hot, desc=desc)
        m["in_composite"] = in_composite
        metrics.append(m)

    # 合成分位：长历史指标统一折算成热度分位后取均值；估值样本不足 3 年时不参与合成
    series_by_key = {spec[0]: spec[4] for spec in specs}
    hot_by_key = {spec[0]: spec[5] for spec in specs}
    long_keys = [spec[0] for spec in specs if spec[7]]

    heat_series = [
        [_heat_of(p, hot_by_key[k]) for p in _pct_series(series_by_key[k])]
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

    # 历史类比用的状态向量：整体热度 + 回撤深度 + 宽度 + 成交额 + 振幅（均已折算成热度）
    def heat_of_key(key: str) -> list[int | None]:
        return [_heat_of(p, hot_by_key[key]) for p in _pct_series(series_by_key[key])]

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
        "updated": now_tz().isoformat(),
        "window_years": _window_years([r["date"] for r in rows]),
        "samples": len(history),
        "position": metrics,
        "composite": {
            "percentile": composite,
            "label": zone["label"],
            "zone": zone["zone"],
            "advice": zone["advice"],
            "components": [m["key"] for m in metrics if m["in_composite"]],
        },
        "forward": fwd,
        "guidance": _guidance(zone, composite, fwd),
        "analogs": _analogs(rows, dims, composite_series, fwd_returns),
        "divergence": _divergence(percentiles, composite),
        "note": "分位窗口固定近 10 年；PE / PB 仅有 2024-07 之后的样本，不足 3 年不参与合成",
    }


def _empty_payload(note: str = "历史分位基线首次构建中") -> dict[str, Any]:
    return {
        "ready": False,
        "as_of": "",
        "updated": now_tz().isoformat(),
        "window_years": 0,
        "samples": 0,
        "position": [],
        "composite": {"percentile": None, "label": "构建中", "zone": "unknown", "advice": "", "components": []},
        "forward": None,
        "guidance": _guidance({"zone": "unknown", "label": "构建中", "advice": ""}, None, None),
        "analogs": None,
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
