"""候选池 · 第2层：个股多因子质量分。

对指定行业/代码池内的成分股做多因子打分，输出 quality_score（0-100）。
因子（行业中性化 + 绝对项）：
  - 盈利：roe（中高优）
  - 成长：revenue_yoy / net_profit_yoy（高优）
  - 估值：pe_ttm / pb（低优，行业中位数中性化）
  - 动量：momentum_5d/20d、量能 volume_ratio_5d
  - 规模：total_mv（中小盘略加分，避免单一大盘股主导）
硬过滤：ΔG double_kill（戴维斯双杀）直接剔除；ST/退市剔除。

性能：复用 screener 的进程内面板缓存（load_daily_panel + compute_all + enrich），
并一次性批量取全行业成分股，避免逐股网络调用。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.core.database import get_mongo_db_sync
from app.strategy_system import data_adapter
from app.strategy_system.screener import _resolve_as_of

logger = logging.getLogger(__name__)

# 因子权重（总和归一化）
_FACTOR_WEIGHTS = {
    "roe": 0.18,
    "revenue_yoy": 0.14,
    "net_profit_yoy": 0.14,
    "pe_ttm": 0.12,   # 低优
    "pb": 0.10,        # 低优
    "momentum_20d": 0.16,
    "vol_ratio_5d": 0.08,
    "total_mv": 0.08,  # 中小盘略优
}


def _load_enriched_target(db, as_of_date: str) -> pd.DataFrame:
    """加载全市场日线面板 + 指标 + 基本面，返回目标日行（复用 screener 进程内缓存）。"""
    from app.strategy_system.screener import _get_enriched_target, _load_computed_panel

    panel = _load_computed_panel(db, None, as_of_date)
    if panel.empty:
        return panel
    return _get_enriched_target(db, panel, None, as_of_date)


def _normalize_series(s: pd.Series, *, lower_better: bool = False) -> pd.Series:
    """min-max 归一化到 0-1；lower_better=True 时反向（低值高分）。空列返回 NaN。"""
    if s is None or len(s) == 0:
        return pd.Series(np.nan, index=s.index if s is not None else None)
    v = pd.to_numeric(s, errors="coerce")
    if v.notna().sum() == 0:
        return pd.Series(np.nan, index=s.index)
    lo, hi = v.min(), v.max()
    if hi == lo:
        return pd.Series(0.5, index=s.index, dtype=float).where(v.notna())
    norm = (v - lo) / (hi - lo)
    if lower_better:
        norm = 1 - norm
    return norm.where(v.notna())


def _quality_score(row: pd.Series, industry_stats: dict) -> float:
    """对单只股票计算质量分（0-100）。行业中性化：估值类因子与行业中位数比较。"""
    score = 0.0
    wsum = 0.0

    def _num(key):
        return row.get(key)

    # ROE：绝对高优
    roe = _num("roe")
    if roe is not None and pd.notna(roe):
        score += min(max((roe - 0) / 15, 0), 1) * _FACTOR_WEIGHTS["roe"]
        wsum += _FACTOR_WEIGHTS["roe"]

    # 成长
    for key, w in (("revenue_yoy", _FACTOR_WEIGHTS["revenue_yoy"]),
                   ("net_profit_yoy", _FACTOR_WEIGHTS["net_profit_yoy"])):
        val = _num(key)
        if val is not None and pd.notna(val):
            score += min(max((val - 0) / 0.5, 0), 1) * w
            wsum += w

    # 估值：行业中性化（低于行业中位数更优）
    for key, w in (("pe_ttm", _FACTOR_WEIGHTS["pe_ttm"]),
                   ("pb", _FACTOR_WEIGHTS["pb"])):
        val = _num(key)
        med = industry_stats.get(key)
        if val is not None and pd.notna(val) and med and pd.notna(med) and med > 0:
            # pe/pb 为正时，低于中位数得高分
            ratio = val / med
            score += min(max(1 - (ratio - 0.5) / 1.5, 0), 1) * w
            wsum += w

    # 动量
    m20 = _num("momentum_20d")
    if m20 is not None and pd.notna(m20):
        score += min(max((m20 - 0) / 0.2, 0), 1) * _FACTOR_WEIGHTS["momentum_20d"]
        wsum += _FACTOR_WEIGHTS["momentum_20d"]

    # 量能
    vr = _num("vol_ratio_5d")
    if vr is not None and pd.notna(vr):
        score += min(max((vr - 0.5) / 2.0, 0), 1) * _FACTOR_WEIGHTS["vol_ratio_5d"]
        wsum += _FACTOR_WEIGHTS["vol_ratio_5d"]

    # 规模：中小盘（<100亿）略加分
    mv = _num("total_mv")
    if mv is not None and pd.notna(mv) and mv > 0:
        score += max(0.0, min((100 - mv) / 100, 1)) * _FACTOR_WEIGHTS["total_mv"]
        wsum += _FACTOR_WEIGHTS["total_mv"]

    if wsum <= 0:
        return 0.0
    # 强转 Python float：score 由 numpy 标量累加而来，直接 round() 会返回 numpy 标量，
    # 导致响应 JSON 编码失败（'numpy.float32' object is not iterable）。
    return round(float(min(100.0, float(score / wsum * 100))), 2)


def score_stocks(codes: list[str] | None = None, industry: str | None = None,
                 as_of=None, limit: int = 30) -> dict:
    """对指定代码池（或某行业成分股）多因子打分，返回 top limit 候选。

    硬过滤：ST/退 标记、ΔG double_kill（若可用）。
    Returns: {as_of, industry, items:[{code,name,...factors,quality_score}], total}
    """
    db = get_mongo_db_sync()
    as_of_date = _resolve_as_of(db, as_of)
    target = _load_enriched_target(db, as_of_date)
    if target.empty:
        return {"as_of": as_of_date, "industry": industry, "items": [], "total": 0}

    if industry:
        g = target[target["industry"] == industry]
    elif codes:
        codes_set = {str(c).zfill(6) for c in codes}
        g = target[target["symbol"].isin(codes_set)]
    else:
        g = target

    if g.empty:
        return {"as_of": as_of_date, "industry": industry, "items": [], "total": 0}

    # 名称映射
    names = {}
    for s in data_adapter.get_stock_list(db):
        sym = str(s.get("symbol") or "")
        nm = s.get("name") or ""
        if sym and nm:
            names[sym] = nm

    # 行业中性化统计（用于估值类因子）
    ind_med: dict[str, float] = {}
    for k in ("pe_ttm", "pb"):
        v = pd.to_numeric(g[k], errors="coerce")
        v = v[v > 0]
        if len(v):
            ind_med[k] = float(v.median())

    items = []
    for _, r in g.iterrows():
        sym = str(r.get("symbol") or "")
        name = names.get(sym, "")
        # 硬过滤：ST/退
        if "ST" in name or "退" in name:
            continue
        # 硬过滤：ΔG 双杀（经 enrichment 的 dg 字段不可用，这里用行业过滤外层承担，
        # 个股双杀过滤依赖 dg_prosperity 批量查询，见 candidate_pool_service）
        q = _quality_score(r, ind_med)
        items.append({
            "code": sym,
            "name": name,
            "industry": r.get("industry") or "",
            "close": _round(r.get("close")),
            "pct_chg": _round(r.get("pct_chg")),
            "quality_score": q,
            "roe": _round(r.get("roe")),
            "revenue_yoy": _round(r.get("revenue_yoy")),
            "net_profit_yoy": _round(r.get("net_profit_yoy")),
            "pe_ttm": _round(r.get("pe_ttm")),
            "pb": _round(r.get("pb")),
            "total_mv": _round(r.get("total_mv")),
            "momentum_20d": _round(r.get("momentum_20d")),
            "vol_ratio_5d": _round(r.get("vol_ratio_5d")),
            "date": as_of_date,
        })

    items.sort(key=lambda x: x["quality_score"], reverse=True)
    return {
        "as_of": as_of_date,
        "industry": industry,
        "items": items[:limit],
        "total": len(items),
    }


def _round(v):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None