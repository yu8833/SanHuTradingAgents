"""候选池 · 第2层：个股多因子质量分。

对指定行业/代码池内的成分股做多因子打分，输出 quality_score（0-100）。
因子（行业中性化 + 绝对项）：
  - 景气趋势（Δ因子，预测力最强，对齐教材 ΔG 五指标）：dg(Δ盈利增速)、
    d_or_yoy(Δ收入增速)、d_roe(ΔROE)（高优，来自 dg_prosperity）
  - 盈利：roe（中高优）、盈利增速 g
  - 成长：绝对收入增速 or_yoy / 盈利（高优）
  - 估值：pe_ttm / pb（低优，行业中位数中性化）
  - 动量：momentum_20d
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

# 因子权重（总和归一化）。Δ 因子预测力最强（教材 ΔG 五指标：ΔG>Δ收入增速>ΔROE>收入增速>盈利增速）。
_FACTOR_WEIGHTS = {
    "dg": 0.20,          # Δ盈利增速（ΔG）
    "d_or_yoy": 0.14,    # Δ收入增速
    "d_roe": 0.12,       # ΔROE
    "or_yoy": 0.08,      # 收入增速（绝对值）
    "g": 0.08,           # 盈利增速（绝对值）
    "roe": 0.08,         # 盈利质量
    "pe_ttm": 0.10,      # 低优
    "pb": 0.08,          # 低优
    "momentum_20d": 0.08,
    "total_mv": 0.04,    # 中小盘略优
}


def _load_enriched_target(db, as_of_date: str, pool: list[str] | None = None) -> pd.DataFrame:
    """加载日线面板 + 指标 + 基本面，返回目标日行（复用 screener 进程内缓存）。

    pool 指定时只加载该代码池（默认全市场），供候选池默认视图缩小加载范围、缩短冷启动。
    """
    from app.strategy_system.screener import _get_enriched_target, _load_computed_panel

    panel = _load_computed_panel(db, pool, as_of_date)
    if panel.empty:
        return panel
    return _get_enriched_target(db, panel, pool, as_of_date)


def _load_dg_factors(db, codes: list[str]) -> dict:
    """从 dg_prosperity 批量取每股最新一期的 Δ 因子（ΔG/Δ收入增速/ΔROE 及绝对增速）。

    Returns:
        {code_zfill6: {dg, or_yoy, roe, g, d_or_yoy, d_roe, report_period}, ...}
    """
    if not codes:
        return {}
    syms = {str(c).zfill(6) for c in codes}
    try:
        cursor = db["dg_prosperity"].aggregate([
            {"$match": {"code": {"$in": list(syms)}}},
            {"$sort": {"report_period": -1}},
            {"$group": {
                "_id": "$code",
                "dg": {"$first": "$dg"},
                "or_yoy": {"$first": "$or_yoy"},
                "roe": {"$first": "$roe"},
                "g": {"$first": "$g"},
                "d_or_yoy": {"$first": "$d_or_yoy"},
                "d_roe": {"$first": "$d_roe"},
            }},
        ])
        return {d.pop("_id"): d for d in cursor}
    except Exception as e:  # 缺失时静默降级，不影响打分主流程
        logger.warning(f"[CandidatePool] 读取 ΔG 因子失败: {e}")
        return {}


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


def _quality_score(row: pd.Series, industry_stats: dict, dg: dict | None = None) -> float:
    """对单只股票计算质量分（0-100）。行业中性化：估值类因子与行业中位数比较。

    dg: 来自 dg_prosperity 的 Δ 因子（百分数口径，如 25.3 表示增幅 25.3%）。
    """
    score = 0.0
    wsum = 0.0

    def _num(key):
        return row.get(key)

    def _pct_score(val, lo, hi):
        """百分数因子归一化到 0-1：lo 对应 0 分，hi 对应 1 分，越界 clamp。"""
        if val is None or pd.isna(val):
            return None
        return min(max((float(val) - lo) / (hi - lo), 0), 1)

    def _add(v, w):
        if v is None:
            return
        nonlocal score, wsum
        score += v * w
        wsum += w

    dg = dg or {}
    # Δ因子（预测力最强，高优）：ΔG、Δ收入增速、ΔROE、绝对收入/盈利增速
    _add(_pct_score(dg.get("dg"), -30, 30), _FACTOR_WEIGHTS["dg"])
    _add(_pct_score(dg.get("d_or_yoy"), -50, 50), _FACTOR_WEIGHTS["d_or_yoy"])
    _add(_pct_score(dg.get("d_roe"), -10, 10), _FACTOR_WEIGHTS["d_roe"])
    _add(_pct_score(dg.get("or_yoy"), -20, 80), _FACTOR_WEIGHTS["or_yoy"])
    _add(_pct_score(dg.get("g"), -30, 60), _FACTOR_WEIGHTS["g"])

    # ROE：绝对高优
    roe = _num("roe")
    if roe is not None and pd.notna(roe):
        score += min(max((roe - 0) / 15, 0), 1) * _FACTOR_WEIGHTS["roe"]
        wsum += _FACTOR_WEIGHTS["roe"]

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
                 as_of=None, limit: int = 30, pool: list[str] | None = None) -> dict:
    """对指定代码池（或某行业成分股）多因子打分，返回 top limit 候选。

    硬过滤：ST/退 标记、ΔG double_kill（若可用）。
    pool: 限定底层面板加载的代码池（缩小加载范围，冷启动提速；默认全市场）。
    Returns: {as_of, industry, items:[{code,name,...factors,quality_score}], total}
    """
    db = get_mongo_db_sync()
    as_of_date = _resolve_as_of(db, as_of)
    target = _load_enriched_target(db, as_of_date, pool=pool)
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

    # 批量取 ΔG 五因子（高优，缺失时静默降级）
    dg_factors = _load_dg_factors(db, g["symbol"].tolist())

    items = []
    for _, r in g.iterrows():
        sym = str(r.get("symbol") or "")
        name = names.get(sym, "")
        # 硬过滤：ST/退
        if "ST" in name or "退" in name:
            continue
        # 硬过滤：ΔG 双杀（经 enrichment 的 dg 字段不可用，这里用行业过滤外层承担，
        # 个股双杀过滤依赖 dg_prosperity 批量查询，见 candidate_pool_service）
        dg = dg_factors.get(sym)
        q = _quality_score(r, ind_med, dg)
        # 营收YOY：dg_prosperity 缺失时回退 enrichment 注入的 revenue_yoy。
        # 两者均为百分数口径（6.538=+6.54%），响应需归一为小数以匹配前端 fmtPctFromFraction（×100）。
        _or_yoy_raw = (dg.get("or_yoy") if dg and dg.get("or_yoy") is not None else r.get("revenue_yoy"))
        _or_yoy = _round(_or_yoy_raw / 100.0) if _or_yoy_raw is not None else None
        items.append({
            "code": sym,
            "name": name,
            "industry": r.get("industry") or "",
            "close": _round(r.get("close")),
            "pct_chg": _round(r.get("pct_chg")),
            "quality_score": q,
            "roe": _round(r.get("roe")),
            "pe_ttm": _round(r.get("pe_ttm")),
            "pb": _round(r.get("pb")),
            "total_mv": _round(r.get("total_mv")),
            "momentum_20d": _round(r.get("momentum_20d")),
            # ΔG 五因子（来自 dg_prosperity，百分数口径）
            "dg": _round(dg.get("dg") if dg else None),
            "or_yoy": _or_yoy,
            "g": _round(dg.get("g") if dg else None),
            "d_or_yoy": _round(dg.get("d_or_yoy") if dg else None),
            "d_roe": _round(dg.get("d_roe") if dg else None),
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