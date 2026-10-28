"""市场总览数据层 —— 市场情绪 + 板块资金流（板块/大盘级公开数据，不涉个股推荐）。

省流量：全站共享一份缓存（Redis + 内存二级缓存），多个用户/多次打开只抓一次；
盘中分级TTL：大盘/板块 3分钟，实时行情 30秒，新闻 5分钟；
非交易时段自动延长TTL，减少数据源压力。数据源全免费、无 key。
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.services import vibe_astock as astock
from app.services import vibe_gstock as gstock
from app.services.cache_layer import cached
from app.services.data_sources.akshare_adapter import _parse_cn_amount, _parse_pct_str

BEIJING = timezone(timedelta(hours=8))
logger = logging.getLogger(__name__)


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _sentiment() -> dict:
    """市场情绪：涨跌家数/涨停跌停/活跃度 + 大盘宽度、题材投机（客观数据机械分档）。"""
    try:
        # akshare 惰性导入（同 astock 模式）：未装时降级返回空，不挡整个服务启动
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
    except Exception:
        return {}
    up, down, flat = _num(d.get("上涨")), _num(d.get("下跌")), _num(d.get("平盘"))
    zt, zt_real = _num(d.get("涨停")), _num(d.get("真实涨停"))
    dt, dt_real = _num(d.get("跌停")), _num(d.get("真实跌停"))
    r = up / max(down, 1)
    if up < 600:
        breadth = "冰点"
    elif r < 0.7:
        breadth = "偏弱"
    elif r < 1.2:
        breadth = "中性"
    elif r < 2.5:
        breadth = "偏强"
    else:
        breadth = "普涨"
    speculation = "亢奋" if zt_real >= 100 else "活跃" if zt_real >= 60 else "普通" if zt_real >= 30 else "冰点"
    return {
        "up": up, "down": down, "flat": flat,
        "zt": zt, "zt_real": zt_real, "dt": dt, "dt_real": dt_real,
        "active": str(d.get("活跃度", "")),
        "breadth": breadth, "speculation": speculation,
        "date": str(d.get("统计日期", "")),
    }


def _fund_amount(v) -> float:
    """行业资金流金额 → 数值（单位：元）。

    AKShare stock_fund_flow_industry 的金额列可能返回「X.XX亿/万」字符串，
    也可能是纯数字（该接口纯数字以「亿」为单位）。统一归一为「元」，
    便于下游 _industry_rank 再除以 1e8 转为「亿」。
    """
    if isinstance(v, (int, float)):
        return float(v) * 1e8  # 该接口纯数字以「亿」为单位
    val = _parse_cn_amount(v)
    return float(val) if val is not None else 0.0


def _sectors() -> list[dict]:
    """行业资金流（按净额降序）。含领涨股/行业指数等字段。

    AKShare stock_fund_flow_industry 金额列返回「X.XX亿/万」字符串或纯数字（亿），
    统一用 _fund_amount 规范化为数值（单位：元），
    _industry_rank 再除以 1e8 转为「亿」。
    """
    try:
        f = astock._akshare().stock_fund_flow_industry(symbol="即时")
        # 规范化金额列（「亿/万」字符串或纯数字「亿」）为数值（单位：元）
        for col in ("净额", "流入资金", "流出资金"):
            if col in f.columns:
                f[col] = f[col].map(_fund_amount)
        # 涨跌幅为「21.43%」字符串 → 数值（%）
        for col in ("行业-涨跌幅",):
            if col in f.columns:
                f[col] = f[col].map(_parse_pct_str)
        f = f.sort_values("净额", ascending=False)
    except Exception:
        return []

    # 行业名 -> 同花顺行业板块代码（881xxx）。同花顺一级行业与东财
    # stock_fund_flow_industry 名称完全一致（90/90），供前端热力图点击跳转
    # 同花顺行业详情页 https://q.10jqka.com.cn/thshy/detail/code/{code}/
    ths_map: dict[str, str] = {}
    try:
        bb = astock._akshare().stock_board_industry_name_ths()
        ths_map = {
            str(r["name"]).strip(): str(r["code"]).strip()
            for _, r in bb.iterrows()
        }
    except Exception:
        pass

    out = []
    for _, row in f.iterrows():
        # 金额列已在上面 map(_fund_amount) 归一为「元」，此处仅安全取数值，不再重复换算
        net_val = float(row.get("净额", 0) or 0)
        inflow_val = float(row.get("流入资金", 0) or 0)
        outflow_val = float(row.get("流出资金", 0) or 0)
        pct_val = _parse_pct_str(row.get("行业-涨跌幅", 0)) or 0
        # 行业指数/当前价为纯数字（非亿/万字符串），直接取数；勿走 _fund_amount（会误乘 1e8）
        out.append({
            "name": str(row["行业"]),
            "pct": round(float(pct_val), 2),
            "net": round(float(net_val), 2),
            "inflow": round(float(inflow_val), 2),
            "outflow": round(float(outflow_val), 2),
            "firms": _num(row.get("公司家数")),
            "ths_code": ths_map.get(str(row["行业"]).strip(), ""),
            "index": round(float(row.get("行业指数", 0) or 0), 2),      # 行业指数点位
            "lead": str(row.get("领涨股") or "").strip(),                # 领涨股名称
            "lead_pct": round(float(_parse_pct_str(row.get("领涨股-涨跌幅", 0)) or 0), 2),   # 领涨股涨跌幅 %
            "lead_price": round(float(row.get("当前价", 0) or 0), 2),    # 领涨股当前价 元
        })
    return out


async def get_overview() -> dict:
    """市场情绪 + 板块资金（Redis缓存，大盘/板块级 TTL）。资金轮动由前端从 sectors 头尾取。"""
    def build():
        from app.utils.trading_time import get_market_trade_date

        return {
            "sentiment": _sentiment(),
            "sectors": _sectors(),
            # 数据日期＝市场当前参考交易日（交易时段=当日，盘前=最近已完成交易日）；
            # updated 是构建时刻（带 +08:00），不能当数据日
            "trade_date": get_market_trade_date().strftime("%Y-%m-%d"),
            "updated": datetime.now(BEIJING).replace(microsecond=0).isoformat(),
        }
    return await cached(
        "vibe:market_overview", build,
        category="market",
        valid=lambda v: bool(v.get("sentiment") or v.get("sectors"))
    )


def _emotion() -> dict:
    """短线情绪（聚合口径，**零个股名**）：连板梯队 / 最高连板 / 炸板率 / 封板率 / 晋级率 / 涨跌停家数。

    数据源＝东财涨停板四池（push2ex）。只把池子聚合成计数与比率，
    **不输出任何个股 code/name**——守产品「零标的」红线（个股清单是甩名单，不做）。
    """
    # 定位最近交易日：从今天往前回溯，第一日有涨停池即取（休息日/盘前返空则继续回溯）。
    # 注意：东财涨停池在休息日/盘前也会回吐数据（请求当日返回最近一份池子），
    # 必须先按权威交易日历过滤，且「今天」在未开盘(9:30)前不接受——否则会把
    # 尚未产生的当日数据误当成数据日期（盘前显示 09-28 而最近已完成交易日是 09-24）。
    from datetime import time as dtime

    from app.utils.trading_time import is_trading_day

    now = datetime.now(BEIJING)
    today = now.date()
    resolved, zt = "", []
    for back in range(8):
        d = (today - timedelta(days=back)).strftime("%Y%m%d")
        if not is_trading_day(d):
            continue
        # 今天未开盘（<9:30）：跳过，保证数据日期在盘前=最近已完成交易日、盘中=当日
        if d == today.strftime("%Y%m%d") and now.time() < dtime(9, 30):
            continue
        zt = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
        if zt:
            resolved = d
            break
    if not resolved:
        return {}

    zb = astock.em_zt_topic_pool("getTopicZBPool", resolved, "fbt:asc")    # 炸板池
    dt = astock.em_zt_topic_pool("getTopicDTPool", resolved, "fund:asc")   # 跌停池
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", resolved, "zs:desc")  # 昨涨停池

    boards = [_num(p.get("lbc")) or 1 for p in zt]      # 每只连板数（缺省按 1 板）
    lianban = [b for b in boards if b >= 2]             # 2 板及以上（连板）
    # 连板梯队：2/3/4/5+ 各多少家（5 代表 5 板及以上），只保留有家数的档
    tiers = Counter(min(b, 5) for b in lianban)
    ladder = [{"boards": b, "count": tiers[b], "plus": b >= 5} for b in sorted(tiers)]

    # 连板股清单（2 板+，客观公开榜单数据；按连板数、成交额降序）。
    # 产品定位调整（2026-07-05）：从「零标的」→「展示客观榜单但不推荐/不预测/不评分」。
    # 东财 pool 无流通市值字段、成交额可能为 '-'/字符串 → 用实时行情批量补全缺失值。
    lianban_codes = [str(p.get("c", "")) for p in zt if (_num(p.get("lbc")) or 1) >= 2]
    quote_map = astock.realtime_quote_map(lianban_codes) if lianban_codes else {}
    lianban_stocks = sorted(
        ({
            "code": str(p.get("c", "")), "name": p.get("n", ""),
            "boards": _num(p.get("lbc")) or 1,
            "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
            "pct": round(astock._numf(p.get("zdp")) or 0, 2),
            "amount": astock._numf(p.get("amount"))
            or (quote_map.get(str(p.get("c", ""))) or {}).get("amount"),  # 成交额,元
            "float_cap": astock._numf(p.get("ltsz"))
            or (quote_map.get(str(p.get("c", ""))) or {}).get("float_cap"),  # 流通市值,元
            "industry": p.get("hybk", ""),  # 概念/行业
        } for p in zt if (_num(p.get("lbc")) or 1) >= 2),
        key=lambda x: (-x["boards"], -(x["amount"] or 0)),
    )

    # 三池清单（涨停/炸板/跌停）：客观公开榜单，仅供查看，不推荐/不评分
    def _pool_brief(pool: list[dict], extra: tuple[str, ...] = ()) -> list[dict]:
        out = []
        for p in pool:
            row = {
                "code": str(p.get("c", "")),
                "name": p.get("n", ""),
                "price": round((astock._numf(p.get("p")) or 0) / 1000, 2),
                "pct": round(astock._numf(p.get("zdp")) or 0, 2),
                "amount": astock._numf(p.get("amount")),
                "industry": p.get("hybk", ""),
            }
            for k in extra:
                src = {"boards": "lbc", "break_times": "zbc", "days": "days"}.get(k, k)
                # 连板数/连续跌停天数缺省按 1（榜单里出现即至少 1 板/1 天）
                row[k] = (_num(p.get(src)) or 1) if k in ("days", "boards") else _num(p.get(src))
            out.append(row)
        return out

    zt_count, zb_count, yzt_count = len(zt), len(zb), len(yzt)
    attempts = zt_count + zb_count                       # 尝试涨停 = 封住 + 炸板
    seal_rate = round(zt_count / attempts, 3) if attempts else None      # 封板率
    break_rate = round(zb_count / attempts, 3) if attempts else None     # 炸板率
    # 晋级率＝今日 2 板+（＝昨涨停今又停）÷ 昨日涨停家数
    promotion_rate = round(len(lianban) / yzt_count, 3) if yzt_count else None

    # 补充真实涨停/跌停数据（来自乐谷，与大盘总览一致）
    zt_real, dt_real = 0, 0
    try:
        df = astock._akshare().stock_market_activity_legu()
        d = {row["item"]: row["value"] for _, row in df.iterrows()}
        zt_real = _num(d.get("真实涨停"))
        dt_real = _num(d.get("真实跌停"))
    except Exception:
        pass

    return {
        "date": f"{resolved[:4]}-{resolved[4:6]}-{resolved[6:]}",
        # 数据获取时刻（东财涨停池构建时刻），带 +08:00 便于前端按瞬时解析
        "updated": datetime.now(BEIJING).replace(microsecond=0).isoformat(),
        "zt_count": zt_count,
        "dt_count": len(dt),
        "zt_real": zt_real,
        "dt_real": dt_real,
        "zb_count": zb_count,
        "max_boards": max(boards) if boards else 0,
        "lianban_count": len(lianban),
        "ladder": ladder,
        "lianban_stocks": lianban_stocks,
        "pools": {
            "zt": sorted(_pool_brief(zt, ("boards",)),
                         key=lambda x: (-x["boards"], -(x["amount"] or 0))),
            "zb": _pool_brief(zb, ("break_times",)),
            "dt": _pool_brief(dt, ("days",)),
            # 昨涨停池：供「晋级阶梯」点击查看昨日涨停明细（晋级分母口径）
            "yzt": sorted(_pool_brief(yzt, ("boards",)),
                          key=lambda x: (-x["boards"], -(x["amount"] or 0))),
        },
        "seal_rate": seal_rate,
        "break_rate": break_rate,
        "promotion_rate": promotion_rate,
        "yzt_count": yzt_count,
    }


async def get_short_term_emotion() -> dict:
    """短线情绪（Redis缓存，market级TTL）。"""
    return await cached("vibe:short_term_emotion", _emotion, category="market")


def _emotion_history(days: int = 10) -> dict:
    """近 N 个交易日的情绪序列（涨停/炸板/跌停家数、最高连板、封板率）。

    东财四池无批量历史接口，逐日回放；仅在情绪页按需加载，独立缓存 1 小时，
    不拖慢主情绪接口。单日三池并发抓取，避免串行等待。
    """
    from concurrent.futures import ThreadPoolExecutor
    from datetime import time as dtime

    from app.utils.trading_time import is_trading_day

    now = datetime.now(BEIJING)
    today = now.date()
    dates: list[str] = []
    for back in range(days * 3 + 10):
        if len(dates) >= days:
            break
        d = today - timedelta(days=back)
        ds = d.strftime("%Y%m%d")
        if not is_trading_day(ds):
            continue
        # 今日未开盘不接受（与 _emotion 同口径，避免把尚未产生的当日数据当成历史点）
        if d == today and now.time() < dtime(9, 30):
            continue
        dates.append(ds)
    dates.reverse()

    def _fetch(ds: str) -> tuple[str, list, list, list]:
        return (
            ds,
            astock.em_zt_topic_pool("getTopicZTPool", ds, "fbt:asc"),
            astock.em_zt_topic_pool("getTopicZBPool", ds, "fbt:asc"),
            astock.em_zt_topic_pool("getTopicDTPool", ds, "fund:asc"),
        )

    results = []
    if dates:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(_fetch, dates))

    series = []
    for ds, zt, zb, dt in results:
        if not zt and not zb and not dt:
            continue  # 该日尚未产出数据（盘中早段/数据源缺失）
        boards = [_num(p.get("lbc")) or 1 for p in zt]
        attempts = len(zt) + len(zb)
        series.append({
            "date": f"{ds[:4]}-{ds[4:6]}-{ds[6:]}",
            "zt": len(zt),
            "zb": len(zb),
            "dt": len(dt),
            "max_boards": max(boards) if boards else 0,
            "lianban": sum(1 for b in boards if b >= 2),
            "seal_rate": round(len(zt) / attempts, 3) if attempts else None,
        })

    return {
        "days": len(series),
        "series": series,
        "updated": datetime.now(BEIJING).replace(microsecond=0).isoformat(),
    }


async def get_emotion_history(days: int = 10) -> dict:
    """近 N 交易日情绪序列（独立长缓存 1 小时，供情绪页曲线/周期判断）。"""
    return await cached(
        "vibe:emotion_history", lambda: _emotion_history(days),
        category="market", ttl=3600,
        valid=lambda v: bool(v.get("series")),
    )


# 开盘情景分档：以 A50 夜盘涨跌幅定档，只预判开盘缺口，不代表全天方向
_PREOPEN_BANDS = (
    {"key": "deep_down", "label": "大幅低开", "tone": "down", "lo": None, "hi": -1.0},
    {"key": "down", "label": "低开", "tone": "down", "lo": -1.0, "hi": -0.3},
    {"key": "flat", "label": "平开", "tone": "flat", "lo": -0.3, "hi": 0.3},
    {"key": "up", "label": "高开", "tone": "up", "lo": 0.3, "hi": 1.0},
    {"key": "deep_up", "label": "大幅高开", "tone": "up", "lo": 1.0, "hi": None},
)

# 盘前展示顺序：A50 最直接，其次美股期货，再到定价 A 股资源/成长板块的商品
_PREOPEN_ORDER = ("a50fut", "ndxfut", "spxfut", "wti", "copper", "gold")


def _preopen_band(pct: float) -> dict:
    if pct <= -1.0:
        return _PREOPEN_BANDS[0]
    if pct < -0.3:
        return _PREOPEN_BANDS[1]
    if pct < 0.3:
        return _PREOPEN_BANDS[2]
    if pct < 1.0:
        return _PREOPEN_BANDS[3]
    return _PREOPEN_BANDS[4]


def _preopen_structure(series: list[dict]) -> dict | None:
    """上一完整交易日的情绪结构 + 日环比（series 末点若是今日盘中数据则跳过）。"""
    if not series:
        return None
    today = datetime.now(BEIJING).strftime("%Y-%m-%d")
    prev = [p for p in series if p.get("date") and p["date"] != today] or series
    last = prev[-1]
    before = prev[-2] if len(prev) >= 2 else None

    def delta(key: str):
        if not before:
            return None
        a, b = last.get(key), before.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(a - b, 3)
        return None

    seal = last.get("seal_rate")
    seal_delta_pt = None
    if isinstance(seal, (int, float)) and before and isinstance(before.get("seal_rate"), (int, float)):
        seal_delta_pt = round((seal - before["seal_rate"]) * 100, 1)

    return {
        "date": last.get("date"),
        "zt": last.get("zt"),
        "zt_delta": delta("zt"),
        "max_boards": last.get("max_boards"),
        "max_boards_delta": delta("max_boards"),
        "lianban": last.get("lianban"),
        "lianban_delta": delta("lianban"),
        "seal_rate": seal,
        "seal_delta_pt": seal_delta_pt,
    }


async def _build_pre_open() -> dict:
    """盘前聚合：隔夜外盘（A50/美股期货/商品）+ 上一交易日情绪结构。

    外盘抓取与情绪序列并行，各自硬超时降级；任一失败只影响对应字段，
    不阻塞整块（盘前没有行情也必须能给出「昨日结构」）。
    """
    futures: list[dict] = []
    try:
        futures = await asyncio.wait_for(
            asyncio.to_thread(gstock.index_futures), timeout=25
        )
    except Exception:
        logger.warning("盘前外盘期货抓取失败/超时，降级为空")

    history: dict = {}
    try:
        history = await asyncio.wait_for(get_emotion_history(10), timeout=20)
    except Exception:
        logger.warning("盘前情绪历史获取失败/超时，降级为空")

    items = {it.get("key"): it for it in (futures or [])}
    basis = items.get("a50fut") or items.get("ndxfut") or items.get("spxfut")
    pct = basis.get("change_pct") if basis else None
    band = _preopen_band(float(pct)) if isinstance(pct, (int, float)) else None
    degraded = bool(basis) and basis.get("key") != "a50fut"

    overseas = [
        {
            "key": key,
            "name": items[key].get("name"),
            "price": items[key].get("price"),
            "change_pct": items[key].get("change_pct"),
        }
        for key in _PREOPEN_ORDER
        if key in items
    ]

    return {
        "as_of": datetime.now(BEIJING).replace(microsecond=0).isoformat(),
        "bands": [
            {"key": b["key"], "label": b["label"], "tone": b["tone"], "lo": b["lo"], "hi": b["hi"]}
            for b in _PREOPEN_BANDS
        ],
        "gap": {
            "pct": pct,
            "band": band["key"] if band else None,
            "label": band["label"] if band else "待定",
            "tone": band["tone"] if band else "flat",
            "basis_name": basis.get("name") if basis else "",
            "degraded": degraded,
        },
        "overseas": overseas,
        "structure": _preopen_structure((history or {}).get("series") or []),
        "note": "期货为延时行情，与 A 股不同源；仅用于开盘情景，不代表全天方向",
    }


async def get_pre_open() -> dict:
    """开盘情景（Redis 缓存 5 分钟）：盘前结论快、刷新也快。"""
    return await cached(
        "vibe:pre_open", _build_pre_open,
        category="market", ttl=300,
        valid=lambda v: bool(v.get("overseas") or v.get("structure")),
    )


async def get_turnover_top() -> dict:
    """全市场成交额榜 Top20（客观公开榜单，Redis缓存 market 级TTL）。"""
    def build():
        return {
            "stocks": astock.market_turnover_rank(20),
            "updated": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
        }

    return await cached(
        "vibe:turnover_top", build,
        category="market",
        valid=lambda v: bool(v.get("stocks"))
    )


async def get_global_indices() -> list[dict]:
    """全球指数快照（美股 / 港股，Redis缓存 news 级TTL）。空结果不缓存。"""
    return await cached("vibe:global_indices", gstock.global_indices, category="news", valid=bool)


async def get_global_famous_stocks() -> list[dict]:
    """全球著名股票（美股/港股蓝筹）涨跌，Redis news 级缓存。

    东财 push2 行情在当前网络环境较慢/受限，单次 13 只并发抓取可能 20s+。
    该数据变化频率低，与全球指数同一缓存策略（交易 5 分钟 / 非交易 1 小时），
    避免大盘看板每次打开都实时抓取导致数秒到数十秒等待。空结果不缓存。

    valid 校验「至少一条取到价格」才写入：源不可达时 famous_stocks 返回全 null
    占位行列表（或空列表），若按 bool 判断非空会把占位数据误缓存，导致页面
    长期显示「—」且刷新无效。
    """
    def _has_quote(v: list) -> bool:
        return bool(v) and any(x.get("price") is not None for x in v)

    return await cached(
        "vibe:global_famous_stocks", gstock.famous_stocks, category="news", valid=_has_quote
    )
