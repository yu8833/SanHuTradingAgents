"""板块象限分析数据层 ——「趋势分析」概念趋势 / 行业趋势 的当前帧数据源。

与个股象限共用 8 元组帧结构（前端 makeQuadrantOption 零改动复用）：
    [pct, amt, turn, pe, mv, main, board, d5]

- 概念帧（get_concept_analysis，Redis market 级缓存秒开）：
    pct=概念涨跌幅, turn=换手率, main=净流入(亿元)，其余维度板块级暂无 → None
- 行业帧（etf_radar_snapshot 最新快照 + 实时同花顺行业资金流交叉）：
    pct=行业涨跌幅（优先实时同花顺行业值——与「大盘热力图·行业板块全景」同源同时点，
    回退快照同花顺交叉校验值→代表ETF涨跌幅），
    turn=代表ETF换手率, mv=代表ETF总市值(亿元)，
    main=行业净流入(优先实时同花顺亿元值，回退快照同花顺亿元值→ETF主力净流入换算亿元)

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
    """yyyymmdd ↔ yyyy-mm-dd 归一为 yyyy-mm-dd（委托统一日期工具；非法回退截断，保持原约定）。"""
    from app.utils.date_utils import normalize_date
    norm = normalize_date(ymd)
    if norm is not None:
        return norm
    s = str(ymd).strip()
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


async def get_board_quadrant() -> dict[str, Any]:
    """概念象限数据：Redis market 级缓存（与个股象限同策略）。

    行业象限已随「行业趋势」改用同花顺行业全景（IndustryPanorama），
    原 ETF 行业分支（_build_industry_quadrant）已删除。
    """
    return await cached(
        "vibe:board_quadrant:concept", _build_concept_quadrant,
        category="market",
        valid=lambda v: bool(v.get("frame")),
    )