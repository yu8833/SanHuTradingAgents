"""个股四象限分析数据层 —— 「个股分析 · 六图四象限 + 30日时间轴」的帧数据源。

数据形态（供前端六图散点图渲染）：
- `dates`: 最近交易日列表（YYYY-MM-DD，最多 31 个：30 个历史 + 1 个当日/最新交易日）；
- `meta`: {code: {name, industry}}，全市场静态属性只传一次；
- `frames`: {date: {code: [8 元组]}}，8 元组 = [pct, amt, turn, pe, mv, main, board, d5]：
    pct   涨跌幅 %
    amt   成交额 亿元
    turn  换手率 %
    pe    市盈率（当日帧与历史帧统一取 pe_ttm，保证时间轴可比）
    mv    总市值 亿元
    main  主力净流入 亿元
    board 连板高度（None=涨停池不可用；0=未涨停；1=首板；2+=连板）
    d5    5 日涨跌幅 %（(当前价 / 5 个交易日前收盘 - 1) * 100）

来源：
- 当日帧（盘中）：主源为 market_quotes 当日实时全量（120s 采集轮，全市场统一口径，
  涨跌幅/成交额/收盘价），stock_basic_info 静态兜底（pe_ttm/turnover_rate/total_mv）；
  东财 clist 仅作增强（实时主力 f62、实时现价、名称行业，抓多少算多少，不影响帧完整性）
  + 东财涨停池 board。
- 历史帧：stock_daily_quotes（涨跌幅/成交额/收盘价序列）+
  stock_daily_basic（pe_ttm/turnover_rate/total_mv）+ stock_daily_moneyflow（main_net）+
  stock_daily_zt_pool（连板，按日缓存，缺失自动回填）。

口径约定（跟随项目约束：资金数据不估计、外部接口失败返回 unavailable）：
- pe：当日帧与历史帧统一 pe_ttm，避免同帧内混用动态 PE/TTM 导致估值轴不可比；
- main：clist f62（实时增强）→ 当日已入库 stock_daily_moneyflow（盘后 19:30 真实值）→ None；
- 涨停池失败 → 该帧 board 为 None（图6 提示连板数据不可用），不阻塞其余图。
"""

from __future__ import annotations

import asyncio
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

    实测（2026-09）东财 clist 将单页返回硬截断为 100 条，total 仍为全市场总数；
    若沿用旧的「单页不足 5000 即停」停页条件，会只取到第一页 100 只
    （按代码倒序恰是 920 开头北交所），令当日帧只剩 99 只有成交额的股票。
    这里改为：读 total + 首页实际条数推算总页数 → 并发拉取剩余页 →
    失败页顺序重试 + 总量不足时顺延补页（页容量推断偏差兜底），全量收齐后再过滤。
    ⚠️ 不走 em_get 的 auto 探测：push2 行情域在当前网络下可能整体不可达，
    em_get 会在两个 host 上各做「直连-降级代理」探测（约 20s/host），
    令缓存 miss 时的接口构建拖到 40s+ 引发前端超时。这里用 requests 直连 + 5s
    短超时快速失败，不可达时立即返回 [] 交给降级路径（market_quotes×stock_basic_info）。
    返回 [{code, name, price, pct, amount, turn, pe, mv, main, industry}]（金额单位元）。
    """
    import concurrent.futures as cf

    import requests as _requests

    def _fetch_page(host: str, pn: int) -> tuple[int, list[dict]]:
        """单页拉取：(total, diff)；失败抛异常由调用方重试/忽略。"""
        direct = _requests.Session()
        direct.trust_env = False  # 强直连（忽略系统代理）
        params = {
            "pn": pn, "pz": 5000, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": "f12", "fs": _EM_FS, "fields": _EM_FIELDS,
        }
        r = direct.get(
            f"https://{host}/api/qt/clist/get", params=params,
            headers={"User-Agent": astock.UA, "Referer": "https://quote.eastmoney.com/"},
            timeout=5,
        )
        data = r.json().get("data") or {}
        return int(data.get("total") or 0), (data.get("diff") or [])

    rows: list[dict] = []
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com"):
        try:
            total, first = _fetch_page(host, 1)
        except Exception as e:
            logger.debug(f"clist({host}) 直连失败（快失败）: {type(e).__name__}")
            continue
        if not first:
            continue  # 空响应 → 换下一个 host
        got: list[dict] = list(first)
        # 以首页实际返回条数估算页容量（当前服务端硬截断 100），算总页数并发补齐
        page_size = len(first)
        last_pn = math.ceil(total / page_size) if total and page_size else 1
        ok_pages = {1}
        if last_pn > 1:
            with cf.ThreadPoolExecutor(max_workers=6) as ex:
                futs = {ex.submit(_fetch_page, host, pn): pn for pn in range(2, last_pn + 1)}
                for fu in cf.as_completed(futs):
                    pn = futs[fu]
                    try:
                        _, diff = fu.result()
                        if diff:
                            got.extend(diff)
                            ok_pages.add(pn)
                    except Exception as e:
                        logger.debug(f"clist({host}) 第{pn}页并发拉取失败: {type(e).__name__}")
            # 兜底一：并发失败的页顺序重试
            for pn in range(2, last_pn + 1):
                if pn in ok_pages:
                    continue
                for _ in range(2):
                    try:
                        _, diff = _fetch_page(host, pn)
                        if diff:
                            got.extend(diff)
                            ok_pages.add(pn)
                        break
                    except Exception:
                        pass
        # 兜底二：总量仍未收齐（页容量推断偏差/服务端抖动）→ 顺延补页直到空页
        if total and len(got) < total:
            pn = last_pn + 1
            while len(got) < total and pn <= 300:
                try:
                    _, diff = _fetch_page(host, pn)
                except Exception:
                    break
                if not diff:
                    break
                got.extend(diff)
                pn += 1
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


async def _build_today_frame(today_mf: dict[str, float | None],
                             snapshot: list[dict] | None = None,
                             today_zt: dict[str, int] | None = None) -> dict[str, Any]:
    """当日帧：market_quotes 当日实时全量为主源，clist 仅作增强（全市场统一口径）。

    数据优先级（避免同帧口径混用，页面时间轴 30 天可比）：
    - pct / amt / turn / pe / mv：一律取 market_quotes × stock_basic_info
      （pe 统一 pe_ttm，与历史帧一致；不混入 clist 动态 PE）；
    - main：clist f62（实时增强）→ 当日已入库 stock_daily_moneyflow（盘后真实值）→ None；
    - price（d5 基准现价）：clist 实时现价 → market_quotes.close；
    - board：当日涨停池。

    snapshot 为空（clist 失败/风控）不影响帧完整性，仅资金/现价增强略去。
    """
    if today_zt is None:
        today_zt = {}
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

    snap_map: dict[str, dict] = {s["code"]: s for s in (snapshot or []) if s.get("code")}

    frame: dict[str, list] = {}
    meta: dict[str, dict] = {}
    price: dict[str, float | None] = {}
    for code, q in qmap.items():
        amt = q.get("amt")
        if amt is None or amt <= 0:
            continue  # 停牌/无成交额不入当日帧（排除 market_quotes 占位空记录）
        b = bmap.get(code) or {}
        sn = snap_map.get(code) or {}
        main_raw = sn.get("main") if sn.get("main") is not None else today_mf.get(code)
        frame[code] = [
            _r(q.get("pct")),
            _yi(amt),
            _r(b.get("turnover_rate")),
            _r(b.get("pe_ttm"), 2),          # pe 统一 pe_ttm（与历史帧一致）
            _r(b.get("total_mv")),           # stock_basic_info.total_mv 已是亿元
            _yi(main_raw) if main_raw is not None else None,
            today_zt.get(code),              # board（非涨停股为 None → 前端按 0 处理）
            None,                            # d5 由组装时补齐
        ]
        meta[code] = {"name": sn.get("name") or b.get("name") or "",
                      "industry": sn.get("industry") or b.get("industry") or ""}
        price[code] = sn.get("price") if sn.get("price") is not None else q.get("close")
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
        for code, series in quotes_map.items():
            row = series.get(d)
            if row is None or row.get("amt") is None:
                continue  # 该日无成交额不入帧
            b = basic_map.get(code, {}).get(d) or {}
            mf = mf_map.get(code, {}).get(d)
            # chg5d 结构 {code: {date: pct}}（外层 key 是 code，勿按日期索引）
            d5 = chg5d.get(code, {}).get(d)
            frame[code] = [
                _r(row.get("pct")),
                _yi(row.get("amt")),
                _r(b.get("turn")),
                _r(b.get("pe")),
                _r(b.get("mv")),
                _yi(mf),
                day_zt.get(code),           # board（无涨停池 → None）
                _r(d5),
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
    # 资金流范围扩到今日：当日 moneyflow 盘后 19:30 即入库，今日帧 main 可直接回填（非估计）
    import asyncio

    quotes_map, basic_map, mf_map, zt, today_zt, snapshot = await asyncio.gather(
        _fetch_quotes_map(fetch_start, fetch_end),
        _fetch_basic_map(hist_dates[0], hist_dates[-1]),
        _fetch_moneyflow_map(hist_dates[0], today),
        _load_zt_pools(hist_dates),
        _safe_zt(),
        asyncio.to_thread(_fetch_clist_snapshot),
    )
    chg5d = _compute_chg5d(quotes_map, hist_dates)

    frames = _assemble_history_frames(hist_dates, quotes_map, basic_map, mf_map, zt, chg5d)

    # 当日资金流映射 {code: main_net(元)}：仅当日行情已入库时为非空，否则空 dict（main 置 None）
    today_mf: dict[str, float | None] = {}
    for code, dm in mf_map.items():
        if (dm or {}).get(today) is not None:
            today_mf[code] = dm[today]

    # 当日帧：market_quotes 当日实时全量为主源（120s 采集轮，全市场统一口径），
    # clist 仅作增强（实时 f62/现价/名称行业），失败或抓不全不影响帧完整性。
    today_out = {"frame": {}, "meta": {}, "price": {}}
    try:
        today_out = await _build_today_frame(today_mf, snapshot, today_zt)
    except Exception as e:
        logger.warning(f"当日帧构建失败（去掉 clist 增强重试）: {e}")
        today_out = await _build_today_frame(today_mf, None, today_zt)
    if snapshot:
        logger.info(f"当日帧：market_quotes 主源组装完成 + clist 增强 {len(snapshot)} 只（实时 f62/现价/名称）")
    else:
        logger.info("当日帧：market_quotes 主源组装完成（clist 不可用，资金/现价增强略去）")

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


# ---------------------------------------------------------------------------
# 4) 单股 AI 操作结论（基于「个股趋势」帧数据）
# ---------------------------------------------------------------------------
# 数据源与页面完全一致：复用 get_stock_quadrant() 的缓存（今日帧 8 元组 +
# 近 N 个交易日该股帧序列 + meta.name/industry）。
# 流程：优先调用 LLM（配置走 MongoDB llm_configs，与综合研判同一来源 _get_llm_cfg，
# 当前模型 deepseek-v4-flash）；LLM 未配置/失败时降级为确定性规则引擎
# （六图四象限同口径打分），保证结论始终可用。返回 engine=llm|rule 供前端标注。
# 分析维度：涨跌幅 / 成交额 / 换手率 / PE / 总市值 / 主力净流入 / 连板 / 5日涨跌。

_AI_RECENT_N = 8  # 结论参考的近期交易日数

# 评分 → 操作档位（分数越高越积极）
_AI_ACTION_TABLE: list[tuple[float, str, str]] = [
    (55, "strong_buy", "积极买入"),
    (30, "buy", "逢低关注"),
    (10, "hold", "持有观察"),
    (-10, "wait", "观望等待"),
    (-34, "reduce", "减仓防范"),
    (-999, "avoid", "回避为主"),
]


def _score_to_action(score: int) -> tuple[str, str]:
    """评分 → (action, action_label)。"""
    for lo, action, label in _AI_ACTION_TABLE:
        if score >= lo:
            return action, label
    return "avoid", "回避为主"


def _band(v: float | None, table: list[tuple[float, float, int]]) -> int:
    """按区间表打分：table=[(lo, hi, score)]，闭区间顺序匹配；None 得 0 分。"""
    if v is None:
        return 0
    for lo, hi, s in table:
        if lo <= v <= hi:
            return s
    return 0


def _rule_conclusion(name: str, code: str, today: list, recent: list[dict]) -> dict:
    """确定性规则引擎：个股趋势 8 元组 × 近 N 日序列 → 操作结论。"""
    pct = _num(today[IDX_PCT])
    amt = _num(today[IDX_AMT])
    turn = _num(today[IDX_TURN])
    pe = _num(today[IDX_PE])
    mv = _num(today[IDX_MV])
    main = _num(today[IDX_MAIN])
    board = today[IDX_BOARD]
    d5 = _num(today[IDX_D5])
    main_ratio = (main / amt * 100) if (main is not None and amt) else None
    cum_n = sum(x["pct"] for x in recent if x["pct"] is not None) if recent else None
    board_i = None if board is None else int(board)

    # ── 多维度打分（-100 ~ 100，越高越积极）──
    score = 0
    score += _band(pct, [(9.5, 999, 25), (5, 9.5, 18), (2, 5, 12), (0, 2, 6),
                         (-2, 0, 0), (-5, -2, -8), (-9.5, -5, -15), (-999, -9.5, -25)])
    score += _band(d5, [(15, 999, 15), (8, 15, 10), (3, 8, 6), (0, 3, 2),
                        (-3, 0, -2), (-8, -3, -6), (-999, -8, -12)])
    score += _band(main_ratio, [(15, 999, 20), (8, 15, 14), (3, 8, 8), (0, 3, 3),
                                (-3, 0, -3), (-8, -3, -8), (-15, -8, -14), (-999, -15, -20)])
    score += _band(turn, [(2, 12, 8), (12, 20, 4), (20, 999, 0), (-999, 2, -2)])
    if pe is not None:
        score += -6 if pe < 0 else _band(pe, [(0, 20, 10), (20, 50, 5), (50, 100, 0), (100, 9999, -3)])
    score += _band(mv, [(0, 50, 2), (50, 2000, 0), (2000, 99999, -2)])
    if board_i is not None:
        score += {0: 0, 1: 5}.get(board_i, 8 if board_i <= 3 else 3)
    score += _band(cum_n, [(15, 9999, 10), (5, 15, 5), (-5, 5, 0), (-15, -5, -5), (-9999, -15, -10)])

    # 连涨天数（从最新往前连续上涨）
    up_days = 0
    for r_ in reversed(recent):
        if (r_["pct"] or 0) > 0:
            up_days += 1
        else:
            break

    action, action_label = _score_to_action(score)

    # ── 判断要点（正向信号）──
    reasons: list[str] = []
    if amt is None or amt <= 0:
        reasons.append("当日无成交额（停牌/未开盘或数据未就绪）")
    if pct is not None and pct >= 5:
        reasons.append(f"当日上涨 {_r(pct)}%，表现强势")
    if main_ratio is not None and main_ratio >= 8:
        reasons.append(f"主力净流入 {_r(main, 3)} 亿（占成交额 {_r(main_ratio)}%），资金积极")
    if main is not None and pct is not None and main > 0 and pct > 0:
        reasons.append("流入+上涨「强势共振」")
    if turn is not None and 2 <= turn <= 12 and pct is not None and pct > 0:
        reasons.append(f"换手率 {_r(turn)}% 温和放量上行")
    if pe is not None and 0 <= pe <= 20 and pct is not None and pct > 0:
        reasons.append(f"低估值（PE {_r(pe)}）叠加上涨，估值修复")
    if d5 is not None and d5 >= 8:
        reasons.append(f"5日动量 {_r(d5)}%，趋势延续")
    if board_i is not None and 1 <= board_i <= 3:
        reasons.append(f"当前连板 {board_i} 板，情绪上攻")
    if cum_n is not None and cum_n >= 5:
        reasons.append(f"近 {len(recent)} 日累计 {_r(cum_n)}%，趋势向好")
    # 弱市情形：判断要点给出负向驱动因子，避免空泛
    if not reasons and pct is not None and pct <= -2:
        reasons.append(f"当日下跌 {_r(pct)}%，走势走弱")
    if not reasons and d5 is not None and d5 <= -8:
        reasons.append(f"5日动量 {_r(d5)}%，趋势偏弱")
    if not reasons and main_ratio is not None and main_ratio <= -8:
        reasons.append(f"主力净流出 {_r(main_ratio)}%（净流入 {_r(main, 3)} 亿）")
    if not reasons:
        reasons.append("各项数据暂未形成明确方向信号")

    # ── 风险提示 ──
    risks: list[str] = []
    if main_ratio is not None and main_ratio <= -8:
        risks.append(f"主力资金净流出 {_r(main_ratio)}%（净流入 {_r(main, 3)} 亿），警惕砸盘")
    if turn is not None and turn >= 15 and pct is not None and pct < 0:
        risks.append(f"高换手下跌（{_r(turn)}%），疑似放量出货")
    if board_i is not None and board_i >= 4:
        risks.append(f"高位连板 {board_i} 板，炸板/情绪退潮风险大")
    if pct is not None and pct >= 9.5 and turn is not None and turn > 15:
        risks.append("放巨量涨停，注意炸板分歧")
    if pe is not None and pe < 0:
        risks.append("市盈率（PE）为负，公司处于亏损状态，基本面风险")
    if d5 is not None and d5 <= -8:
        risks.append(f"5日累计下跌 {_r(d5)}%，趋势偏弱")
    if up_days >= 4:
        risks.append(f"已连续上涨 {up_days} 个交易日，短线乖离过大，谨防回吐")
    if main is not None and pct is not None and main < 0 and pct > 0:
        risks.append("股价上涨但主力净流出，持续性存疑")
    if main is not None and pct is not None and main > 0 and pct < 0:
        risks.append("股价下跌但主力净流入，暂不急于追进")

    # ── 一句话结论 ──
    parts = [f"{name}（{code}）"]
    if pct is not None:
        parts.append(f"今日 {_r(pct)}%")
    if main is not None and amt:
        parts.append(("主力净流入" if main >= 0 else "主力净流出") + f" {abs(_r(main, 3))} 亿")
    if d5 is not None:
        parts.append(f"5日 {_r(d5)}%")
    parts.append(f"综合评分 {score} 分")
    parts.append(f"操作建议：{action_label}")
    summary = "，".join(parts) + "。"

    return {
        "action": action, "action_label": action_label, "score": score,
        "reasons": reasons, "risks": risks, "summary": summary,
    }


# ── LLM 路径（配置与综合研判同源：MongoDB llm_configs → _get_llm_cfg）──

_AI_SYSTEM_PROMPT = (
    "你是一名资深 A 股交易员与机构策略师，精通短线量价、资金、情绪与估值分析。\n"
    "我会给你一只股票在「个股趋势」页面（六维四象限）的量化帧数据（今日 8 个维度 + 近期走势），"
    "请基于这些数据给出该股当前的操作结论。\n"
    "只输出一个 JSON 对象，不要输出任何解释文字、不要使用 markdown 代码块：\n"
    '{"action":"strong_buy|buy|hold|wait|reduce|avoid","action_label":"积极买入|逢低关注|持有观察|观望等待|减仓防范|回避为主",'
    '"score":<必填，-100~100 的整数，越高越积极>,"summary":"1-2 句话的操作结论","reasons":["判断要点 2-4 条，每条一句话，必须基于给定数据"],'
    '"risks":["风险提示 0-3 条"]}\n'
    "action 六档含义：strong_buy=积极买入（趋势+资金+情绪共振且估值有利）；buy=逢低关注（有支撑逻辑但需等待买点）；"
    "hold=持有观察（趋势未破，不加不砍）；wait=观望等待（方向不明或性价比不足）；reduce=减仓防范（趋势走弱/资金流出）；"
    "avoid=回避为主（破位/高估/风险显著）。\n"
    "数据可能有缺失（值为空）：缺失时依据已有信息判断并在结论中体现，不要臆造数据。篇幅：全文 300 字以内。"
)

_AI_RETRY_TAIL = (
    "\n\n【重要】直接输出符合上述 JSON 结构的原始 JSON："
    "不要输出任何解释文字，不要使用 markdown 代码块（不要以 ``` 开头），结尾不要追加说明。"
)

_AI_ACTION_ALIAS: dict[str, tuple[str, str]] = {
    "strong_buy": ("strong_buy", "积极买入"), "积极买入": ("strong_buy", "积极买入"),
    "强烈买入": ("strong_buy", "积极买入"), "买入": ("buy", "逢低关注"),
    "buy": ("buy", "逢低关注"), "逢低关注": ("buy", "逢低关注"), "低吸": ("buy", "逢低关注"),
    "hold": ("hold", "持有观察"), "持有": ("hold", "持有观察"), "持有观察": ("hold", "持有观察"),
    "wait": ("wait", "观望等待"), "观望": ("wait", "观望等待"), "观望等待": ("wait", "观望等待"),
    "reduce": ("reduce", "减仓防范"), "减仓": ("reduce", "减仓防范"), "减仓防范": ("reduce", "减仓防范"),
    "卖出": ("reduce", "减仓防范"), "sell": ("reduce", "减仓防范"),
    "avoid": ("avoid", "回避为主"), "回避": ("avoid", "回避为主"), "回避为主": ("avoid", "回避为主"),
}


def _llm_cfg() -> dict | None:
    """获取快速分析模型配置 {model, api_base, api_key, ...}；无配置返回 None。"""
    try:
        from app.services.macro.macro_service import _get_llm_cfg
        return _get_llm_cfg()
    except Exception as e:
        logger.warning(f"个股趋势AI分析获取 LLM 配置失败（将降级规则）: {e}")
        return None


def _llm_chat(cfg: dict, system: str, user: str, max_tokens: int = 900) -> dict:
    """非流式调用 chat/completions 并解析 JSON 对象；任何失败抛异常（调用方降级）。"""
    import requests

    from app.services.macro.macro_service import _parse_llm_json

    api_base = cfg["api_base"].rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base += "/chat/completions"
    resp = requests.post(
        api_base,
        json={
            "model": cfg["model"],
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": max_tokens,
            "stream": False,
        },
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    res = _parse_llm_json(content)
    if isinstance(res, list) and res and isinstance(res[0], dict):
        res = res[0]  # 模型偶发把对象包进数组
    if not isinstance(res, dict):
        raise ValueError("LLM 输出不是 JSON 对象")
    return res


def _fmt_or(v, unit: str = "") -> str:
    """金额/百分比等数值 → 展示文本；空 → '空'。"""
    return f"{_r(v)}{unit}" if v is not None else "空"


def _build_ai_prompt(name: str, code: str, industry: str,
                     today: dict, recent: list[dict], rule: dict) -> str:
    """把该股在个股趋势中的数据+规则引擎参考打包成 LLM 的 user prompt。"""
    board = today.get("board")
    board_s = "无" if board is None else ("未涨停" if board == 0 else f"{board} 板")
    trend_s = " → ".join(f"{r['date'][5:]}:{_r(r['pct'])}%" for r in recent) or "空"
    return (
        f"【股票】{name}（{code}） · 行业 {industry}\n"
        "【今日个股趋势帧数据】\n"
        f"- 涨跌幅: {_fmt_or(today.get('pct'))}%\n"
        f"- 成交额: {_fmt_or(today.get('amt'))} 亿\n"
        f"- 换手率: {_fmt_or(today.get('turn'))}%\n"
        f"- 市盈率 PE: {_fmt_or(today.get('pe'))}\n"
        f"- 总市值: {_fmt_or(today.get('mv'))} 亿\n"
        f"- 主力净流入: {_fmt_or(today.get('main'))} 亿\n"
        f"- 连板高度: {board_s}\n"
        f"- 5日涨跌: {_fmt_or(today.get('d5'))}%\n"
        "【近期走势（近若干交易日收盘涨跌幅，旧→新）】\n"
        f"  {trend_s}\n"
        f"【规则引擎参考】该股基于个股趋势六维数据的规则评分 {rule['score']} 分，"
        f"方向：{rule['action_label']}（仅供模型参考，请独立判断）\n"
        "请基于上述个股趋势数据，给出该股当前的操作结论 JSON。"
    )


def _normalize_llm_result(res: dict, rule: dict) -> dict:
    """LLM 输出归一化：action 归一到六档、score 收敛到 [-100,100]，缺字段用规则兜底。"""
    score_raw = res.get("score")
    score = int(round(float(score_raw))) if score_raw not in (None, "") else rule["score"]
    score = max(-100, min(100, score))
    action_raw = str(res.get("action") or "").strip()
    action, action_label = _AI_ACTION_ALIAS.get(action_raw, (_score_to_action(score)))
    reasons = [str(x).strip() for x in (res.get("reasons") or []) if str(x).strip()][:6]
    risks = [str(x).strip() for x in (res.get("risks") or []) if str(x).strip()][:5]
    summary = str(res.get("summary") or "").strip()
    return {
        "action": action, "action_label": action_label, "score": score,
        "reasons": reasons or rule["reasons"],
        "risks": risks or rule["risks"],
        "summary": summary or rule["summary"],
    }


async def analyze_stock_operation(code: str) -> dict[str, Any]:
    """对个股趋势中的一只股票给出操作结论（LLM 优先，规则兜底）。

    返回：
      found / code / name / industry / as_of / engine（llm|rule）
      action / action_label / score（-100~100）/ reasons / risks / summary
      data.today（8 元组转可读字段） data.recent_trend（近 8 个交易日 pct）
    """
    full = await get_stock_quadrant()
    frames = full.get("frames") or {}
    dates = full.get("dates") or []
    meta_all = full.get("meta") or {}
    meta = meta_all.get(code) or {}
    name = meta.get("name") or code
    industry = meta.get("industry") or ""

    # 收集该股最近 N 个有数据的交易日（今日优先，随后历史帧）
    today: list | None = None
    recent: list[dict[str, Any]] = []
    for d in reversed(dates):
        row = (frames.get(d) or {}).get(code)
        if row is None or not row:
            continue
        if today is None:
            today = row
        recent.append({"date": d, "pct": _r(row[IDX_PCT])})
        if len(recent) >= _AI_RECENT_N:
            break
    recent.reverse()

    if today is None:
        return {
            "found": False, "code": code, "name": name, "industry": industry,
            "message": f"未在「个股趋势」中找到 {name}（{code}）的帧数据（可能停牌或当日无成交）",
        }

    today_readable = {
        "pct": _r(_num(today[IDX_PCT])),
        "amt": _r(_num(today[IDX_AMT]), 3),
        "turn": _r(_num(today[IDX_TURN])),
        "pe": _r(_num(today[IDX_PE])),
        "mv": _r(_num(today[IDX_MV])),
        "main": _r(_num(today[IDX_MAIN]), 3),
        "board": None if today[IDX_BOARD] is None else int(today[IDX_BOARD]),
        "d5": _r(_num(today[IDX_D5])),
    }

    # 规则引擎始终先行（供兜底 + 作为 LLM 的参考信号）
    rule = _rule_conclusion(name, code, today, recent)

    # LLM 优先：失败/未配置 → 规则兜底
    engine = "rule"
    pick = {k: rule[k] for k in ("action", "action_label", "score", "reasons", "risks", "summary")}
    cfg = _llm_cfg()
    if cfg:
        for attempt in (1, 2):
            try:
                user_p = _build_ai_prompt(name, code, industry, today_readable, recent, rule)
                if attempt == 2:
                    user_p += _AI_RETRY_TAIL
                res = await asyncio.to_thread(_llm_chat, cfg, _AI_SYSTEM_PROMPT, user_p)
                pick = _normalize_llm_result(res, rule)
                engine = "llm"
                break
            except Exception as e:
                logger.warning(f"个股趋势AI分析 LLM 第 {attempt}/2 次失败（降级规则）: {type(e).__name__}: {str(e)[:120]}")

    return {
        "found": True,
        "code": code, "name": name, "industry": industry,
        "as_of": full.get("as_of", ""),
        "engine": engine,
        "action": pick["action"], "action_label": pick["action_label"],
        "score": pick["score"],
        "reasons": pick["reasons"], "risks": pick["risks"], "summary": pick["summary"],
        "data": {"today": today_readable, "recent_trend": recent},
    }


# ---------------------------------------------------------------------------
# 5) 候选股维度一致性分析（股票筛选 · AI 分析强化版）
# ---------------------------------------------------------------------------
# 筛选页把「趋势象限 / 择时信号 / ΔG 象限 / 辅助预警」四个独立维度与个股趋势帧
# 一并交给 LLM，判断各维度是“共振”还是“背离”，并解释冲突。LLM 失败时降级为
# 确定性规则：按各维度支持度方向（>0 偏多 / <0 偏空）聚合出一致性结论。
# 操作结论（action/score/reasons/risks）仍复用 _rule_conclusion（六维帧规则），
# 保证与个股趋势页口径一致；LLM 只负责解释一致性。

_DIM_TREND = "趋势象限"
_DIM_SIGNAL = "择时信号"
_DIM_DG = "ΔG 象限"
_DIM_ALERT = "辅助预警"

_TREND_QUAD_VIEW = {
    "强势共振": "资金流入+股价上涨，短线多空强弱共振，方向最顺",
    "缩量上行": "资金流出但股价上行，持续性存疑，需防冲高回落",
    "低位承接": "资金流入但股价下跌，或有承接吸筹，属左侧观察",
    "弱势杀跌": "资金流出+股价下跌，双弱格局，回避为主",
}
_TREND_QUAD_SUPPORT = {"强势共振": 1.0, "缩量上行": 0.3, "低位承接": 0.3, "弱势杀跌": -1.0}

_SIGNAL_VIEW = {
    "B1": "左侧买点：超跌/震荡低位触发，提前埋伏",
    "B2": "突破买点：突破确认，右侧进场",
    "B3": "回踩买点：强势回踩不破，加仓机会",
    "S1": "加速卖点：冲高放量，兑现离场",
    "S2": "跌破卖点：破位下行，防守减仓",
    "S3": "清仓卖出：趋势破坏，清仓回避",
}
_SIGNAL_SUPPORT = {"B1": 1.0, "B2": 1.0, "B3": 0.6, "S1": -1.0, "S2": -1.0, "S3": -1.0}

_DG_VIEW = {
    "双击": "盈利增长向上+估值向上，景气兑现",
    "反转": "盈利结构改善，困境反转",
    "见顶": "景气见顶回落风险，需谨慎",
    "双杀": "盈利与估值双杀，回避",
}
_DG_SUPPORT = {"双击": 1.0, "反转": 0.6, "见顶": -0.6, "双杀": -1.0}


def _dg_lookup(dg: str) -> tuple[str, str, float]:
    """ΔG 象限取值可能是「戴维斯双击」等全称，按关键词包含匹配兜底。"""
    for key in ("双击", "反转", "见顶", "双杀"):
        if key in dg:
            return dg, _DG_VIEW[key], _DG_SUPPORT[key]
    return dg, "财务报表量化出的景气/定价象限", 0.0

_CONSISTENCY_TABLE = {
    "align": "多维共振",
    "partial": "存在分歧",
    "diverg": "多空背离",
    "neutral": "方向不明",
}


def _trend_quad_of(today_view: dict) -> str | None:
    """由今日帧（pct/main）计算出趋势象限标签（与筛选页 trendTagOf 同口径）。"""
    pct = today_view.get("pct")
    main = today_view.get("main")
    if pct is None or main is None:
        return None
    if main >= 0 and pct >= 0:
        return "强势共振"
    if main < 0 and pct >= 0:
        return "缩量上行"
    if main >= 0 and pct < 0:
        return "低位承接"
    return "弱势杀跌"


def _candidate_dimensions(today_view: dict, signal_type: str, signal_label: str,
                          dg_quadrant: str, aux_warnings: list[str]) -> list[dict]:
    """组装四维信号（支撑度：>0 偏多，<0 偏空，0 中性）。"""
    dims: list[dict] = []
    quad = _trend_quad_of(today_view)
    if quad:
        dims.append({"name": _DIM_TREND, "value": quad,
                     "view": _TREND_QUAD_VIEW.get(quad, ""),
                     "support": _TREND_QUAD_SUPPORT.get(quad, 0.0)})
    sig = (signal_label or signal_type or "").strip()
    st = (signal_type or sig).strip()
    if sig:
        dims.append({"name": _DIM_SIGNAL, "value": sig,
                     "view": _SIGNAL_VIEW.get(st, "择时系统给出的买卖点信号"),
                     "support": _SIGNAL_SUPPORT.get(st, 0.0)})
    dg = (dg_quadrant or "").strip()
    if dg:
        dg_value, dg_view, dg_support = _dg_lookup(dg)
        dims.append({"name": _DIM_DG, "value": dg_value,
                     "view": dg_view,
                     "support": dg_support})
    warns = [w for w in (aux_warnings or []) if str(w).strip()]
    if warns:
        dims.append({"name": _DIM_ALERT,
                     "value": "；".join(str(w).strip() for w in warns[:2]) + ("…" if len(warns) > 2 else ""),
                     "view": "辅助信号系统预警，提示量价/抱团/情绪过热等风险",
                     "support": -0.7})
    return dims


def _rule_consistency(dims: list[dict]) -> tuple[str, str, list[str]]:
    """规则兜底：按支撑度方向聚合出一致性结论与冲突解释。"""
    if not dims:
        return "neutral", _CONSISTENCY_TABLE["neutral"], []
    positives = [d for d in dims if d["support"] > 0]
    negatives = [d for d in dims if d["support"] < 0]
    if positives and negatives:
        consistency, label = "diverg", _CONSISTENCY_TABLE["diverg"]
    elif positives:
        consistency, label = "align", _CONSISTENCY_TABLE["align"] + "（偏多）"
    elif negatives:
        consistency, label = "align", _CONSISTENCY_TABLE["align"] + "（偏空）"
    else:
        consistency, label = "neutral", _CONSISTENCY_TABLE["neutral"]
    conflicts: list[str] = []
    for p in positives:
        for n in negatives:
            conflicts.append(
                f"{p['name']}偏积极（{p['value']}），但{n['name']}偏谨慎（{n['value']}）"
                f"——{n['value']}可能提示{p['value']}的持续性存疑")
            if len(conflicts) >= 2:
                break
        if len(conflicts) >= 2:
            break
    return consistency, label, conflicts


def _rule_consistency_summary(name: str, dims: list[dict], label: str, conflicts: list[str]) -> str:
    parts = [f"{name}：{label}"]
    if dims:
        pos = [d["name"] for d in dims if d["support"] > 0]
        neg = [d["name"] for d in dims if d["support"] < 0]
        if pos:
            parts.append("积极因素：" + "、".join(pos))
        if neg:
            parts.append("谨慎因素：" + "、".join(neg))
    if conflicts:
        parts.append(conflicts[0].strip())
    return "。".join(x for x in parts if x) + "。"


def _build_consistency_prompt(name: str, code: str, industry: str,
                              today_view: dict, recent: list[dict], dims: list[dict],
                              rule: dict) -> str:
    """把个股趋势帧 + 四维信号打包成 LLM 的 user prompt（只解释一致性）。"""
    board = today_view.get("board")
    board_s = "无" if board is None else ("未涨停" if board == 0 else f"{board} 板")
    trend_s = " → ".join(f"{r['date'][5:]}:{_r(r['pct'])}%" for r in recent) or "空"
    dim_s = "\n".join(
        f"- {d['name']}: {d['value']}（{d['view'] or '见名称'};支撑度 {d['support']:+.1f} 表示偏多/偏空）"
        for d in dims
    ) or "- 暂无可用维度"
    return (
        f"【股票】{name}（{code}） · 行业 {industry}\n"
        "【今日个股趋势帧数据】\n"
        f"- 涨跌幅: {_fmt_or(today_view.get('pct'))}%\n"
        f"- 换手率: {_fmt_or(today_view.get('turn'))}%\n"
        f"- 主力净流入: {_fmt_or(today_view.get('main'))} 亿\n"
        f"- 连板高度: {board_s}\n"
        f"- 5日涨跌: {_fmt_or(today_view.get('d5'))}%\n"
        "【近期走势（近若干交易日收盘涨跌幅，旧→新）】\n"
        f"  {trend_s}\n"
        "【筛选页四维信号（股票筛选系统独立产出，可能相互一致或背离）】\n"
        f"{dim_s}\n"
        f"【规则引擎参考】趋势帧规则评分 {rule['score']} 分，方向：{rule['action_label']}（仅参考）\n"
        "请判断这四维信号是否彼此共振/背离：若方向一致说明共振逻辑；若背离，指出具体冲突与可能的解释"
        "（如短期强势但择时已触发卖点=高位兑现）。参考规则评分与近期走势辅助判断。"
    )


_CONSISTENCY_SYSTEM_PROMPT = (
    "你是一名资深 A 股交易员与机构策略师，擅长把不同分析维度的信号对齐/冲突识别出来。\n"
    "我会给你一只股票的四类独立信号（短期趋势象限、择时买卖点、ΔG 景气象限、辅助预警）"
    "以及个股趋势帧数据与规则评分。这几类信号来自不同系统、回答不同问题，经常表面矛盾"
    "（例如短期资金强势但同时触发卖出点），请识别并解释。\n"
    "只输出一个 JSON 对象，不要输出解释文字、不要用 markdown 代码块：\n"
    '{"consistency":"align|partial|diverg|neutral","consistency_label":"多维共振|存在分歧|多空背离|方向不明",'
    '"summary":"1-2 句话的总评（说明整体是共振还是背离、站在哪一边）",'
    '"dimensions":[{"name":"维度名","value":"该维度取值","view":"一句话解释该维度现在的含义","support":-1到1的浮点，>0偏多<0偏空}],'
    '"conflicts":["冲突解释 0-3 条，每条一句话，明确列出相互矛盾的两维与可能的真相"]}\n'
    "consistency 语义：align=各维度指向同一边（共振）；partial=部分维度同向、部分中性；"
    "diverg=明确出现多空对立；neutral=信息不足方向不明。dimensions 请保留四个维度名与取值，不要增减。"
    "篇幅：全文 220 字以内。"
)


def _normalize_consistency_result(res: dict, rule_dims: list[dict]) -> dict:
    """LLM 输出归一化（consistency 枚举收敛；缺失字段用规则兜底）。"""
    consistency_raw = str(res.get("consistency") or "").strip()
    if consistency_raw not in _CONSISTENCY_TABLE:
        consistency_raw = "neutral"
    dims_out: list[dict] = []
    for d in res.get("dimensions") or []:
        if not isinstance(d, dict):
            continue
        n = str(d.get("name") or "").strip()
        if not n:
            continue
        try:
            support = float(d.get("support", 0))
        except (TypeError, ValueError):
            support = 0.0
        dims_out.append({
            "name": n,
            "value": str(d.get("value") or "").strip(),
            "view": str(d.get("view") or "").strip(),
            "support": max(-1.0, min(1.0, support)),
        })
    if not dims_out:
        dims_out = rule_dims
    conflicts = [str(x).strip() for x in (res.get("conflicts") or []) if str(x).strip()][:3]
    summary = str(res.get("summary") or "").strip()
    return {
        "consistency": consistency_raw,
        "consistency_label": _CONSISTENCY_TABLE[consistency_raw],
        "dimensions": dims_out,
        "conflicts": conflicts,
        "summary": summary,
    }


async def analyze_candidate_consistency(code: str, name: str = "", industry: str = "",
                                        signal_type: str = "", signal_label: str = "",
                                        dg_quadrant: str = "", aux_warnings: list[str] | None = None) -> dict:
    """股票筛选 · 候选股维度一致性分析（LLM 优先，规则兜底）。

    输入为筛选页候选股的四维信号（择时/ΔG/预警），叠加个股趋势帧，
    输出：
      found / code / name / industry / as_of / engine（llm|rule）
      consistency / consistency_label / consistency_summary / dimensions / conflicts
      action / action_label / score / reasons / risks / summary（趋势帧操作结论，口径同个股趋势页）
      data.today / data.recent_trend
    """
    aux_warnings = [str(w) for w in (aux_warnings or [])]
    full = await get_stock_quadrant()
    frames = full.get("frames") or {}
    dates = full.get("dates") or []
    meta_all = full.get("meta") or {}
    meta = meta_all.get(code) or {}
    if not name:
        name = meta.get("name") or code
    if not industry:
        industry = meta.get("industry") or ""

    today: list | None = None
    recent: list[dict] = []
    for d in reversed(dates):
        row = (frames.get(d) or {}).get(code)
        if row is None or not row:
            continue
        if today is None:
            today = row
        recent.append({"date": d, "pct": _r(row[IDX_PCT])})
        if len(recent) >= _AI_RECENT_N:
            break
    recent.reverse()

    if today is None:
        return {
            "found": False, "code": code, "name": name, "industry": industry,
            "message": f"未在「个股趋势」中找到 {name}（{code}）的帧数据（可能停牌或当日无成交）",
        }

    today_view = {
        "pct": _r(_num(today[IDX_PCT])),
        "amt": _r(_num(today[IDX_AMT]), 3),
        "turn": _r(_num(today[IDX_TURN])),
        "pe": _r(_num(today[IDX_PE])),
        "mv": _r(_num(today[IDX_MV])),
        "main": _r(_num(today[IDX_MAIN]), 3),
        "board": None if today[IDX_BOARD] is None else int(today[IDX_BOARD]),
        "d5": _r(_num(today[IDX_D5])),
    }

    # 规则层：操作结论（趋势帧口径）+ 一致性（四维信号聚合）
    rule = _rule_conclusion(name, code, today, recent)
    dims = _candidate_dimensions(today_view, signal_type, signal_label, dg_quadrant, aux_warnings)
    consistency, consistency_label, rule_conflicts = _rule_consistency(dims)

    # LLM 优先：仅解释一致性；失败/未配置 → 规则一致性
    engine = "rule"
    pick_consistency = {
        "consistency": consistency,
        "consistency_label": consistency_label,
        "dimensions": dims,
        "conflicts": rule_conflicts,
        "summary": _rule_consistency_summary(name, dims, consistency_label, rule_conflicts),
    }
    cfg = _llm_cfg()
    if cfg:
        for attempt in (1, 2):
            try:
                user_p = _build_consistency_prompt(name, code, industry, today_view, recent, dims, rule)
                if attempt == 2:
                    user_p += _AI_RETRY_TAIL
                res = await asyncio.to_thread(_llm_chat, cfg, _CONSISTENCY_SYSTEM_PROMPT, user_p)
                pick_consistency = _normalize_consistency_result(res, dims)
                engine = "llm"
                break
            except Exception as e:
                logger.warning(f"维度一致性 LLM 第 {attempt}/2 次失败（降级规则）: {type(e).__name__}: {str(e)[:120]}")

    return {
        "found": True,
        "code": code, "name": name, "industry": industry,
        "as_of": full.get("as_of", ""),
        "engine": engine,
        "consistency": pick_consistency["consistency"],
        "consistency_label": pick_consistency["consistency_label"],
        "consistency_summary": pick_consistency["summary"],
        "dimensions": pick_consistency["dimensions"],
        "conflicts": pick_consistency["conflicts"],
        "action": rule["action"], "action_label": rule["action_label"],
        "score": rule["score"],
        "reasons": rule["reasons"], "risks": rule["risks"], "summary": rule["summary"],
        "data": {"today": today_view, "recent_trend": recent},
    }