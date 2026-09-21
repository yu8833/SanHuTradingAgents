"""个股四象限分析数据层 —— 「个股分析 · 六图四象限 + 30日时间轴」的帧数据源。

数据形态（供前端六图散点图渲染）：
- `dates`: 最近交易日列表（YYYY-MM-DD，最多 31 个：30 个历史 + 1 个当日/最新交易日）；
- `meta`: {code: {name, industry}}，全市场静态属性只传一次；
- `frames`: {date: {code: [8 元组]}}，8 元组 = [pct, amt, turn, pe, mv, main, board, d5]：
    pct   涨跌幅 %
    amt   成交额 亿元
    turn  换手率 %
    pe    市盈率（当日帧=东财动态PE，历史帧=pe_ttm）
    mv    总市值 亿元
    main  主力净流入 亿元
    board 连板高度（None=涨停池不可用；0=未涨停；1=首板；2+=连板）
    d5    5 日涨跌幅 %（(当前价 / 5 个交易日前收盘 - 1) * 100）

来源：
- 当日帧（盘中实时）：东财 clist 实时全市场快照
  （f2 现价、f62 主力净流入、f8 换手、f9 PE、f20 总市值、f6 成交额、f100 行业，一次分页拉全）+ 东财涨停池。
- 历史帧：stock_daily_quotes（涨跌幅/成交额/收盘价序列）+
  stock_daily_basic（pe_ttm/turnover_rate/total_mv）+ stock_daily_moneyflow（main_net）+
  stock_daily_zt_pool（连板，按日缓存，缺失自动回填）。

降级（遵循项目约束：资金数据不估计、外部接口失败返回 unavailable）：
- clist 失败 → market_quotes × stock_basic_info 组合当日帧，main 置 None（图1/6 资金轴提示不可用）；
- 涨停池失败 → 该帧 board 为 None（图6 提示连板数据不可用），不阻塞其余图。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.collections import col
from app.services import vibe_astock as astock
from app.services.cache_layer import cached

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# 帧 8 元组字段索引（前端蓝图 cfg 引用同一组索引）
IDX_PCT, IDX_AMT, IDX_TURN, IDX_PE, IDX_MV, IDX_MAIN, IDX_BOARD, IDX_D5 = range(8)

# 时间轴规模
FRAME_COUNT = 31          # 30 历史交易日 + 1 当日帧
CHG5D_LOOKBACK = 5        # 5 日涨跌前置窗口（拉取范围需多覆盖）
ZT_BACKFILL_NATURAL_DAYS = 10  # 涨停池缺失回填窗口（自然日，控制首次请求量）

# 交易日序列进程内缓存：distinct 全表扫描约 20-25s（仅首次构建受影响），
# 交易日序列一天只变一次 → 缓存 24h；刷新失败回退旧值，避免周期性卡顿。
_TRADE_DATES_CACHE: dict = {"ts": 0.0, "dates": []}
_TRADE_DATES_TTL = 24 * 3600

# 东财 clist 全市场 A 股集合（含沪深京）
_EM_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
_EM_FIELDS = "f12,f14,f2,f3,f6,f8,f9,f20,f62,f184,f100"


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _num(v) -> float | None:
    """东财/库存值可能是 '-'/None/NaN → 归一成 float 或 None。"""
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _r(v, n: int = 2):
    x = _num(v)
    return round(x, n) if x is not None else None


def _yi(v, n: int = 3) -> float | None:
    """元 → 亿元。"""
    x = _num(v)
    return round(x / 1e8, n) if x is not None else None


def _dash(ymd: str) -> str:
    """yyyymmdd ↔ yyyy-mm-dd 归一为 yyyy-mm-dd。"""
    s = str(ymd).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if len(s) >= 10 else s


def _compact(ymd: str) -> str:
    s = _dash(ymd)
    return s.replace("-", "") if len(s) == 10 else s


def _today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


async def _run_in_thread(fn, *args, **kwargs):
    """统一把同步阻塞调用放线程池（构建热路径，避免阻塞事件循环）。"""
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


# ---------------------------------------------------------------------------
# 1) 当日帧：东财 clist 实时全市场快照 + 涨停池
# ---------------------------------------------------------------------------

def _fetch_clist_snapshot() -> list[dict]:
    """东财 clist 全市场实时快照（分页拉全）。

    一次请求 pz=5000（clist 分页上限），翻页收集直到空页。
    ⚠️ 不走 em_get 的 auto 探测：push2 行情域在当前网络下可能整体不可达，
    em_get 会在两个 host 上各做「直连-降级代理」探测（约 20s/host），
    令缓存 miss 时的接口构建拖到 40s+ 引发前端超时。这里用 requests 直连 + 5s
    短超时快速失败，不可达时立即返回 [] 交给降级路径（market_quotes×stock_basic_info）。
    返回 [{code, name, price, pct, amount, turn, pe, mv, main, industry}]（金额单位元）。
    """
    import requests as _requests

    rows: list[dict] = []
    direct = _requests.Session()
    direct.trust_env = False  # 强直连（忽略系统代理，与 em_get 直连策略一致）
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        got: list[dict] = []
        pn = 1
        try:
            while True:
                params = {
                    "pn": pn, "pz": 5000, "po": 1, "np": 1, "fltt": 2, "invt": 2,
                    "fid": "f12", "fs": _EM_FS, "fields": _EM_FIELDS,
                }
                r = direct.get(
                    f"https://{host}/api/qt/clist/get", params=params,
                    headers={"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"},
                    timeout=5,
                )
                diff = (r.json().get("data") or {}).get("diff") or []
                if not diff:
                    break
                got.extend(diff)
                if len(diff) < 5000:
                    break
                pn += 1
        except Exception as e:
            logger.debug(f"clist({host}) 直连失败（快失败）: {type(e).__name__}")
            got = []
            continue
        if got:
            rows = got
            break

    out = []
    for d in rows:
        code = str(d.get("f12", "")).strip()
        if not code:
            continue
        amt = _num(d.get("f6"))
        if amt is None:
            continue  # 停牌/无成交额（含盘前）不入当日帧
        out.append({
            "code": code,
            "name": str(d.get("f14", "")).strip() or "",
            "price": _num(d.get("f2")),
            "pct": _r(d.get("f3")),
            "amount": amt,                       # 元
            "turn": _r(d.get("f8")),
            "pe": _r(d.get("f9"), 2),
            "mv": _num(d.get("f20")),            # 元
            "main": _num(d.get("f62")),          # 元
            "industry": str(d.get("f100", "")).strip() or "",
        })
    return out


async def _fetch_zt_board(date_ymd: str) -> dict[str, int]:
    """东财涨停池当日连板数映射 {code: lbc}；失败/非交易日返回 {}。"""
    pool = await _run_in_thread(astock.em_zt_topic_pool, "getTopicZTPool", _compact(date_ymd), "fbt:asc")
    return {str(p.get("c", "")).strip(): int(_num(p.get("lbc")) or 1) for p in pool if p.get("c")}


def _build_today_frame(snapshot: list[dict], board: dict[str, int]) -> dict[str, Any]:
    """把 clist 快照组装成当日帧（金额统一亿元）。main/board 缺失置 None（不估计）。"""
    frame: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for s in snapshot:
        code = s["code"]
        frame[code] = [
            _r(s["pct"]),                  # pct
            _yi(s["amount"]),              # amt
            _r(s["turn"]),                 # turn
            _r(s["pe"], 2),                # pe
            _yi(s["mv"]),                  # mv
            _yi(s["main"]),                # main
            board.get(code),               # board（非涨停股为 None → 前端按 0 处理）
            None,                          # d5 由组装时补齐
        ]
        meta[code] = {"name": s["name"], "industry": s["industry"]}
    return {"frame": frame, "meta": meta, "price": {s["code"]: s["price"] for s in snapshot}}


async def _build_today_frame_fallback() -> dict[str, Any]:
    """clist 不可达时：market_quotes × stock_basic_info 组合当日帧（资金维度不可用）。"""
    quotes = col("market_quotes")
    basics = col("stock_basic_info")
    latest = None
    async for doc in quotes.find({}, {"trade_date": 1}).sort("trade_date", -1).limit(1):
        latest = _dash(doc.get("trade_date"))
    if not latest:
        return {"frame": {}, "meta": {}, "price": {}}

    qmap: dict[str, dict] = {}
    async for q in quotes.find({"trade_date": {"$in": [latest, _compact(latest)]}},
                               {"code": 1, "pct_chg": 1, "amount": 1, "close": 1}):
        code = str(q.get("code") or "").strip()
        if not code:
            continue
        qmap[code] = {"pct": _num(q.get("pct_chg")), "amt": _num(q.get("amount")), "close": _num(q.get("close"))}

    bmap: dict[str, dict] = {}
    async for b in basics.find({"source": "tushare"},
                               {"code": 1, "name": 1, "industry": 1, "pe_ttm": 1,
                                "turnover_rate": 1, "total_mv": 1}):
        code = str(b.get("code") or "").strip()
        if not code:
            continue
        bmap[code] = b

    frame: dict[str, list] = {}
    meta: dict[str, dict] = {}
    price: dict[str, float | None] = {}
    for code, q in qmap.items():
        b = bmap.get(code, {})
        if q.get("amt") is None:
            continue
        frame[code] = [
            _r(q.get("pct")),
            _yi(q.get("amt")),
            _r(b.get("turnover_rate")),
            _r(b.get("pe_ttm"), 2),
            _r(b.get("total_mv")),           # stock_basic_info.total_mv 已是亿元
            None,                            # main 不可用
            None,
            None,
        ]
        meta[code] = {"name": b.get("name") or "", "industry": b.get("industry") or ""}
        price[code] = q.get("close")
    return {"frame": frame, "meta": meta, "price": price}


# ---------------------------------------------------------------------------
# 2) 历史帧：本地库存聚合
# ---------------------------------------------------------------------------

async def _recent_dates(count: int) -> list[str]:
    """最近 count 个已收盘交易日（stock_daily_quotes distinct，兼容两种日期存储格式）。

    全表 distinct 约 20-25s，结果做 24h 进程内缓存（交易日序列一天只变一次）；
    刷新失败回退旧缓存，避免后台预热/首刷周期性卡顿。
    """
    global _TRADE_DATES_CACHE
    import time

    if _TRADE_DATES_CACHE["dates"]:
        if (time.time() - _TRADE_DATES_CACHE["ts"]) < _TRADE_DATES_TTL:
            return _TRADE_DATES_CACHE["dates"][-count:]
        # 过期：后台刷新一次；失败则沿用旧序列，不影响本次构建
        try:
            raw = await col("stock_daily_quotes").distinct("trade_date", {"period": "daily"})
        except Exception as e:
            logger.warning(f"刷新交易日序列失败，沿用旧缓存: {e}")
            return _TRADE_DATES_CACHE["dates"][-count:]
        days = sorted({_dash(x) for x in raw if len(_dash(x)) == 10})
        if days:
            _TRADE_DATES_CACHE = {"ts": time.time(), "dates": days}
        return _TRADE_DATES_CACHE["dates"][-count:]

    # 首次构建（启动后首个 build）：distinct 较慢但不可回避，交给预热后台承担
    raw = await col("stock_daily_quotes").distinct("trade_date", {"period": "daily"})
    days = sorted({_dash(x) for x in raw if len(_dash(x)) == 10})
    if days:
        _TRADE_DATES_CACHE = {"ts": time.time(), "dates": days}
    return days[-count:] if len(days) >= count else days


async def _fetch_quotes_map(start: str, end: str) -> dict[str, dict[str, dict]]:
    """[start, end] 全市场日线：{code: {"date": {close, pct, amt}}}（兼容 '-'/'compact' 两种存储）。"""
    out: dict[str, dict[str, dict]] = {}
    start_c, end_c = _compact(start), _compact(end)
    cursor = col("stock_daily_quotes").find(
        {"period": "daily", "$or": [
            {"trade_date": {"$gte": start, "$lte": end}},
            {"trade_date": {"$gte": start_c, "$lte": end_c}},
        ]},
        {"code": 1, "trade_date": 1, "close": 1, "pct_chg": 1, "amount": 1},
    )
    async for q in cursor:
        code = str(q.get("code") or q.get("symbol") or "").strip()
        d = _dash(q.get("trade_date"))
        if not code or len(d) != 10:
            continue
        out.setdefault(code, {})[d] = {
            "close": _num(q.get("close")),
            "pct": _r(q.get("pct_chg")),
            "amt": _num(q.get("amount")),
        }
    return out


async def _fetch_basic_map(start: str, end: str) -> dict[str, dict[str, dict]]:
    """[start, end] 全市场 daily_basic：{code: {"date": {turn, pe, mv}}}（trade_date 为 '-' 格式入库）。"""
    out: dict[str, dict[str, dict]] = {}
    cursor = col("stock_daily_basic").find(
        {"trade_date": {"$gte": start, "$lte": end}},
        {"code": 1, "trade_date": 1, "pe_ttm": 1, "turnover_rate": 1, "total_mv": 1},
    )
    async for b in cursor:
        code = str(b.get("code") or "").strip()
        d = _dash(b.get("trade_date"))
        if not code or len(d) != 10:
            continue
        out.setdefault(code, {})[d] = {
            "turn": _r(b.get("turnover_rate")),
            "pe": _r(b.get("pe_ttm"), 2),
            "mv": _r(b.get("total_mv")),  # 亿元
        }
    return out


async def _fetch_moneyflow_map(start: str, end: str) -> dict[str, dict[str, float | None]]:
    """[start, end] 全市场资金流：{code: {"date": main_net(元)}}；集合缺数据返回空。"""
    out: dict[str, dict[str, float | None]] = {}
    async for m in col("stock_daily_moneyflow").find(
        {"trade_date": {"$gte": start, "$lte": end}},
        {"code": 1, "trade_date": 1, "main_net": 1},
    ):
        code = str(m.get("code") or "").strip()
        d = _dash(m.get("trade_date"))
        if not code or len(d) != 10:
            continue
        out.setdefault(code, {})[d] = _num(m.get("main_net"))
    return out


async def _load_zt_pools(dates: list[str]) -> dict[str, dict[str, int]]:
    """读取每日涨停池连板映射（缺失日自动回填：仅回填最近 ZT_BACKFILL_NATURAL_DAYS 自然日内）。"""
    out: dict[str, dict[str, int]] = {}
    if not dates:
        return out
    now = datetime.now(BEIJING).date()

    stored: dict[str, dict[str, int]] = {}
    async for doc in col("stock_daily_zt_pool").find({"date": {"$in": dates}}, {"date": 1, "pool": 1}):
        d = _dash(doc.get("date"))
        pool = doc.get("pool") or []
        stored[d] = {str(p.get("code", "")).strip(): int(_num(p.get("lbc")) or 1) for p in pool if p.get("code")}

    to_fetch: list[str] = []
    for d in dates:
        if d in stored:
            out[d] = stored[d]
            continue
        try:
            day = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (now - day).days <= ZT_BACKFILL_NATURAL_DAYS:
            to_fetch.append(d)
        else:
            out[d] = {}  # 早期缺口：置空，不阻塞接口

    if to_fetch:
        for d in to_fetch:
            try:
                pool = await _run_in_thread(astock.em_zt_topic_pool, "getTopicZTPool", _compact(d), "fbt:asc")
                doc_pool = [{"code": str(p.get("c", "")).strip(), "lbc": int(_num(p.get("lbc")) or 1)}
                            for p in pool if p.get("c")]
                await col("stock_daily_zt_pool").update_one(
                    {"date": d},
                    {"$set": {"date": d, "pool": doc_pool, "updated_at": datetime.now(BEIJING)}},
                    upsert=True,
                )
                out[d] = {p["code"]: p["lbc"] for p in doc_pool}
            except Exception as e:
                logger.warning(f"涨停池回填 {d} 失败（该日连板数据置空）: {e}")
                out[d] = {}
    return out


def _compute_chg5d(quotes: dict[str, dict[str, dict]], dates: list[str]) -> dict[str, dict[str, float | None]]:
    """按每只股票自身日线序列算 5 日涨跌：{code: {date: pct}}（不足 5 个前置数据置 None）。"""
    out: dict[str, dict[str, float | None]] = {}
    for code, series in quotes.items():
        ordered = sorted(series.items())  # [(date, row)] asc
        h = {d: i for i, (d, _) in enumerate(ordered)}
        by_date: dict[str, float | None] = {}
        for d in dates:
            i = h.get(d)
            if i is None or i < CHG5D_LOOKBACK:
                by_date[d] = None
                continue
            c_t = series.get(ordered[i][0], {}).get("close")
            c_b = series.get(ordered[i - CHG5D_LOOKBACK][0], {}).get("close")
            if c_t is None or c_b is None or not c_b:
                by_date[d] = None
            else:
                by_date[d] = round((c_t / c_b - 1) * 100.0, 2)
        out[code] = by_date
    return out


def _assemble_history_frames(
    dates: list[str],
    quotes_map: dict[str, dict[str, dict]],
    basic_map: dict[str, dict[str, dict]],
    mf_map: dict[str, dict[str, float | None]],
    zt: dict[str, dict[str, int]],
    chg5d: dict[str, dict[str, float | None]],
) -> dict[str, dict[str, list]]:
    """组装历史帧。codes = quotes 全量（涨跌/成交额必需），其余字段缺失置 None。"""
    frames: dict[str, dict[str, list]] = {}
    for d in dates:
        frame: dict[str, list] = {}
        day_zt = zt.get(d) or {}
        day_chg = chg5d.get(d) or {}
        for code, series in quotes_map.items():
            row = series.get(d)
            if row is None or row.get("amt") is None:
                continue  # 该日无成交额不入帧
            b = basic_map.get(code, {}).get(d) or {}
            mf = mf_map.get(code, {}).get(d)
            frame[code] = [
                _r(row.get("pct")),
                _yi(row.get("amt")),
                _r(b.get("turn")),
                _r(b.get("pe")),
                _r(b.get("mv")),
                _yi(mf),
                day_zt.get(code),           # board（无涨停池 → None）
                _r(day_chg.get(code)),
            ]
        frames[d] = frame
    return frames


# ---------------------------------------------------------------------------
# 3) 组装、meta 与缓存
# ---------------------------------------------------------------------------

async def _load_meta_names(codes: set[str]) -> dict[str, dict]:
    """从 stock_basic_info 补齐 name/industry（当日快照之外的历史 code）。"""
    if not codes:
        return {}
    out: dict[str, dict] = {}
    for chunk in _chunks(sorted(codes), 3000):
        async for b in col("stock_basic_info").find(
            {"code": {"$in": chunk}},
            {"code": 1, "name": 1, "industry": 1},
        ):
            code = str(b.get("code") or "").strip()
            if code:
                out[code] = {"name": b.get("name") or "", "industry": b.get("industry") or ""}
    return out


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


async def build_stock_quadrant() -> dict[str, Any]:
    """构建个股四象限帧数据（30 历史帧 + 1 当日帧 + meta + dates）。"""
    fetch_dates = await _recent_dates(FRAME_COUNT + CHG5D_LOOKBACK + 4)  # 含 chg5d 前置交易日
    if not fetch_dates:
        return {"as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"), "total": 0,
                "breadth": {"up": 0, "down": 0, "avg_pct": 0}, "dates": [], "meta": {}, "frames": {}}

    # 最近 30 个历史交易日为时间轴主体（前置 5~10 个仅用于算 5 日涨跌）
    hist_dates = fetch_dates[-(FRAME_COUNT - 1):] if len(fetch_dates) >= FRAME_COUNT - 1 else fetch_dates
    fetch_start, fetch_end = fetch_dates[0], fetch_dates[-1]
    today = _today()

    async def _safe_zt() -> dict[str, int]:
        try:
            return await _fetch_zt_board(today)
        except Exception:
            return {}

    # 五源并行：历史帧 mongo 三源 + 当日涨停池 + clist 实时快照（聚合耗时集中在它们）
    import asyncio

    quotes_map, basic_map, mf_map, zt, today_zt, snapshot = await asyncio.gather(
        _fetch_quotes_map(fetch_start, fetch_end),
        _fetch_basic_map(hist_dates[0], hist_dates[-1]),
        _fetch_moneyflow_map(hist_dates[0], hist_dates[-1]),
        _load_zt_pools(hist_dates),
        _safe_zt(),
        asyncio.to_thread(_fetch_clist_snapshot),
    )
    chg5d = _compute_chg5d(quotes_map, hist_dates)

    frames = _assemble_history_frames(hist_dates, quotes_map, basic_map, mf_map, zt, chg5d)

    # 当日帧：盘中实时 clist；失败降级本地库存（main 置 None）
    today_out = {"frame": {}, "meta": {}, "price": {}}
    try:
        if snapshot:
            today_out = _build_today_frame(snapshot, today_zt)
        else:
            # push2 行情域不可达（clist 空）→ 本地库存降级；涨停池仍可单独补（push2ex 域独立）
            logger.warning("clist 实时快照为空，当日帧降级 market_quotes × stock_basic_info（资金维度不可用）")
            today_out = await _build_today_frame_fallback()
            for code, lb in today_zt.items():
                if code in today_out["frame"]:
                    today_out["frame"][code][IDX_BOARD] = lb
    except Exception as e:
        logger.warning(f"当日帧 clist 构建失败，降级本地库存: {e}")
        today_out = await _build_today_frame_fallback()

    hist_last = hist_dates[-1]
    gap_days = (datetime.strptime(today, "%Y-%m-%d").date()
                - datetime.strptime(hist_last, "%Y-%m-%d").date()).days if hist_dates else 99
    is_weekday = datetime.now(BEIJING).weekday() < 5
    # 并入条件：今日未收盘入库（today 不在历史帧）且今日疑似交易日（有涨停池 / 工作日且与最新历史日邻近）
    if (today_out["frame"] and today not in hist_dates
            and (bool(today_zt) or (is_weekday and 0 <= gap_days <= 3))):
        # 当日帧 d5：现价 vs 第 5 个历史交易日收盘
        for code, price_t in today_out["price"].items():
            series_rows = quotes_map.get(code, {})
            if not series_rows or price_t is None:
                continue
            ordered = sorted(series_rows.items())
            j = len(ordered) - CHG5D_LOOKBACK - 1
            if j >= 0:
                c_b = series_rows.get(ordered[j][0], {}).get("close")
                if c_b:
                    today_out["frame"][code][IDX_D5] = round((price_t / c_b - 1) * 100.0, 2)
        frames[today] = today_out["frame"]

    dates = sorted(frames.keys())

    # meta：当日快照 + 历史 code 兜底（stock_basic_info）
    all_codes: set[str] = set()
    for f in frames.values():
        all_codes |= set(f.keys())
    meta_names = await _load_meta_names(all_codes)
    meta_names.update(today_out.get("meta") or {})

    # 汇总 KPI（以最新帧为准）
    latest = dates[-1] if dates else ""
    latest_frame = frames.get(latest) or {}
    up = sum(1 for v in latest_frame.values() if (v[IDX_PCT] or 0) > 0)
    down = sum(1 for v in latest_frame.values() if (v[IDX_PCT] or 0) < 0)
    pcts = [v[IDX_PCT] for v in latest_frame.values() if v[IDX_PCT] is not None]
    avg_pct = round(sum(pcts) / len(pcts), 2) if pcts else 0

    return {
        "as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        "total": len(latest_frame),
        "breadth": {"up": up, "down": down, "avg_pct": avg_pct},
        "dates": dates,
        "meta": meta_names,
        "frames": frames,
    }


async def get_stock_quadrant() -> dict[str, Any]:
    """个股趋势数据：Redis 分级缓存（category market：交易时段 600s / 非交易 1800s）。

    启用 stale-while-revalidate：缓存过期瞬间访问直接返回旧数据（秒开），
    后台异步重建新缓存，避免用户撞上 30-40s 的冷构建窗口（页面"打不开"）。
    """
    return await cached(
        "vibe:stock_quadrant", build_stock_quadrant,
        category="market",
        valid=lambda v: bool(v.get("frames")),
        swr=True,
        stale_ttl=2 * 3600,
    )