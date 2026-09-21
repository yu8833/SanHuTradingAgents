"""板块象限分析数据层 ——「趋势分析」概念趋势 / 行业趋势 的当前帧数据源。

与个股象限共用 8 元组帧结构（前端 makeQuadrantOption 零改动复用）：
    [pct, amt, turn, pe, mv, main, board, d5]

- 概念帧（get_concept_analysis，Redis market 级缓存秒开）：
    pct=概念涨跌幅, turn=换手率, main=净流入(亿元)，其余维度板块级暂无 → None
- 行业帧（etf_radar_snapshot 最新快照，读库无网络）：
    pct=行业涨跌幅（优先同花顺交叉校验值，回退代表ETF涨跌幅），
    turn=代表ETF换手率, mv=代表ETF总市值(亿元)，
    main=行业净流入(优先同花顺亿元值，回退ETF主力净流入换算亿元)

只输出最新一帧（无 30 日时间轴）；meta 携带跳转链接：
- 概念 → 同花顺概念详情页 https://q.10jqka.com.cn/gn/detail/code/{cid}/
- 行业 → 东方财富代表ETF行情页 https://quote.eastmoney.com/{sh|sz}{etf_code}.html
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta, timezone
from typing import Any

from app.services.cache_layer import cached

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# 帧 8 元组字段索引（与个股象限/前端共存）
IDX_PCT, IDX_AMT, IDX_TURN, IDX_PE, IDX_MV, IDX_MAIN, IDX_BOARD, IDX_D5 = range(8)


def _num(v) -> float | None:
    """归一 float/None，'-'/NaN 置 None。"""
    try:
        if v is None:
            return None
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _r(v, n: int = 2) -> float | None:
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


def _breadth(frame: dict[str, list]) -> dict:
    up = sum(1 for v in frame.values() if (v[IDX_PCT] or 0) > 0)
    down = sum(1 for v in frame.values() if (v[IDX_PCT] or 0) < 0)
    pcts = [v[IDX_PCT] for v in frame.values() if v[IDX_PCT] is not None]
    avg_pct = round(sum(pcts) / len(pcts), 2) if pcts else 0
    return {"up": up, "down": down, "avg_pct": avg_pct}


async def _build_concept_quadrant() -> dict[str, Any]:
    """概念当前帧：复用概念分析（已含同花顺行情 + 主力净流入，Redis 秒开）。"""
    from app.services.concept_analysis import get_concept_analysis

    data = await get_concept_analysis()
    concepts = data.get("concepts") or []
    frame: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for c in concepts:
        code = str(c.get("code") or "").strip()
        if not code:
            continue
        lead = str(c.get("lead_code") or "").strip() or code
        frame[code] = [
            _r(c.get("pct_chg")),          # pct
            None,                          # amt 板块级暂无
            _r(c.get("turnover")),         # turn 换手率
            None,                          # pe 板块级暂无
            None,                          # mv 板块级暂无
            _r(c.get("money_flow")),       # main 净流入（亿元）
            None,                          # board 板块无连板
            None,                          # d5 仅当前快照
        ]
        meta[code] = {
            "name": c.get("name") or "",
            "industry": "概念",
            "link": f"https://q.10jqka.com.cn/gn/detail/code/{lead}/",
        }
    return {
        "as_of": data.get("as_of") or "",
        "total": len(frame),
        "breadth": _breadth(frame),
        "meta": meta,
        "frame": frame,
    }


async def _build_industry_quadrant() -> dict[str, Any]:
    """行业当前帧：代表ETF快照（读库无网络），优先同花顺行业交叉校验值。"""
    from app.services.etf_radar import get_etf_radar_service

    data = await get_etf_radar_service().get_summary(top_n=300)
    items = data.get("rankings") or []
    frame: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for it in items:
        code = str(it.get("etf_code") or "").strip()
        if not code:
            continue
        # 行业级值优先（同花顺交叉校验，金额单位为亿元），否则回退代表ETF（金额为元）
        pct = it.get("sector_pct_chg")
        if pct is None:
            pct = it.get("pct_chg")
        main = _num(it.get("sector_net_inflow"))
        if main is None:
            main = (_num(it.get("fund_net_inflow")) or 0) / 1e8
        frame[code] = [
            _r(pct),                       # pct
            None,                          # amt
            _r(it.get("turnover_rate")),   # turn 换手率
            None,                          # pe
            _yi(it.get("total_mv")),       # mv 代表ETF总市值（亿元）
            _r(main),                      # main 净流入（亿元）
            None,                          # board
            None,                          # d5
        ]
        mkt = "sh" if code.startswith("5") else "sz"
        meta[code] = {
            "name": str(it.get("industry") or "").strip() or str(it.get("etf_name") or ""),
            "industry": "行业",
            "link": f"https://quote.eastmoney.com/{mkt}{code}.html",
        }
    return {
        "as_of": _dash(data.get("as_of") or ""),
        "total": len(frame),
        "breadth": _breadth(frame),
        "meta": meta,
        "frame": frame,
    }


async def get_board_quadrant(scope: str) -> dict[str, Any]:
    """概念/行业象限数据：Redis market 级缓存（与个股象限同策略）。"""
    if scope == "industry":
        return await cached(
            "vibe:board_quadrant:industry", _build_industry_quadrant,
            category="market",
            valid=lambda v: bool(v.get("frame")),
        )
    return await cached(
        "vibe:board_quadrant:concept", _build_concept_quadrant,
        category="market",
        valid=lambda v: bool(v.get("frame")),
    )