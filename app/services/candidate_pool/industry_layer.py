"""候选池 · 第1层：强势行业轮动。

数据来源：本地 `stock_basic_info.industry` 反查（用户确认，避免依赖外部 EASTMONEY/同花顺成分股接口）。
流程：加载全市场日线面板 + 指标 + 基本面 enrichment → 按行业聚合成分股的动量/量能，合成行业强度分 sector_score。

口径说明：行业字段混有申万行业与概念式口径（190 个行业），但均为本地可稳定读取的「行业」维度，
与个股多因子打分（同屏使用 industry 列）天然对齐。故第 1 版以「本地行业」为准，不依赖网络。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from app.core.database import get_mongo_db_sync
from app.strategy_system import data_adapter
from app.strategy_system.screener import _resolve_as_of

logger = logging.getLogger(__name__)

# 行业强度分合成的动量窗口（权重）
_MOM_WINDOWS = [("momentum_5d", 0.2), ("momentum_10d", 0.25),
                ("momentum_20d", 0.3), ("momentum_60d", 0.25)]
# 量能因子权重（叠加项）
_VOL_WEIGHT = 0.15
# 行业最小成分股数（避免噪声行业）
_MIN_MEMBERS = 5
# 默认返回的强势行业数
_DEFAULT_TOP_N = 20


def _industry_panel(db, as_of_date: str) -> pd.DataFrame:
    """加载全市场日线面板 + 指标 + 行业/基本面 enrichment，返回目标日行。

    复用 screener 的进程内缓存（load_daily_panel + compute_all + enrich，
    按 (as_of, pool) LRU 缓存），避免候选池请求重复做最贵的面板加载与指标计算。
    """
    from app.strategy_system.screener import _get_enriched_target, _load_computed_panel

    panel = _load_computed_panel(db, None, as_of_date)
    if panel.empty:
        return panel
    return _get_enriched_target(db, panel, None, as_of_date)


def _sector_score(g: pd.DataFrame) -> float:
    """合成单个行业的强度分（0-100）。

    成分股动量窗口加权平均 → 行业动量；叠加上行比例与量能，映射到 0-100。
    """
    if g.empty:
        return 0.0
    mom_sum = 0.0
    wsum = 0.0
    for col, w in _MOM_WINDOWS:
        if col in g.columns:
            vals = pd.to_numeric(g[col], errors="coerce").dropna()
            if len(vals):
                mom_sum += vals.mean() * w
                wsum += w
    mom = mom_sum / wsum if wsum else 0.0

    # 上行比例：近 20 日动量为正的成分股占比
    up_ratio = 0.0
    if "momentum_20d" in g.columns:
        m20 = pd.to_numeric(g["momentum_20d"], errors="coerce").dropna()
        up_ratio = float((m20 > 0).mean()) if len(m20) else 0.0

    # 量能：平均换手/量比（vol_ratio_5d）
    vol = 0.0
    if "vol_ratio_5d" in g.columns:
        vr = pd.to_numeric(g["vol_ratio_5d"], errors="coerce").dropna()
        vol = float(vr.mean()) if len(vr) else 0.0

    # 动量 20 日贡献主体，映射到 0-100：上下界 -0.1 ~ 0.2（约对应 20 日涨跌 -10%~20%）
    score = 50 + (mom - 0.0) * 300
    score += up_ratio * 30
    score += (vol - 1.0) * _VOL_WEIGHT * 100 / 2
    # 强转 Python float：入参为 numpy 标量时 round() 会返回 numpy.float32，
    # 导致响应 JSON 编码失败（'numpy.float32' object is not iterable）。
    return round(float(min(100.0, max(0.0, float(score)))), 2)


def get_industries(top_n: int = _DEFAULT_TOP_N, as_of=None) -> dict:
    """返回强势行业列表（含 sector_score / 成分股数 / 代表个股）。

    Returns:
        {
          "as_of": ..., "industries": [
            {industry, sector_score, member_count, top_members:[{code,name,close,pct_chg,momentum_20d}]}
          ]
        }
    """
    db = get_mongo_db_sync()
    as_of_date = _resolve_as_of(db, as_of)
    target = _industry_panel(db, as_of_date)
    if target.empty:
        return {"as_of": as_of_date, "industries": []}

    # 名称映射
    names = {}
    for s in data_adapter.get_stock_list(db):
        sym = str(s.get("symbol") or "")
        nm = s.get("name") or ""
        if sym and nm:
            names[sym] = nm

    rows = []
    available_cols = set(target.columns)
    for industry, g in target.groupby("industry"):
        ind = str(industry or "").strip()
        if not ind or len(g) < _MIN_MEMBERS:
            continue
        score = _sector_score(g)
        # 代表个股：按 20 日动量排序取前 3
        sort_col = "momentum_20d" if "momentum_20d" in available_cols else "close"
        top_part = g.sort_values(sort_col, ascending=False).head(3)
        top_members = []
        for _, r in top_part.iterrows():
            sym = str(r.get("symbol") or "")
            top_members.append({
                "code": sym,
                "name": names.get(sym, ""),
                "close": _round(r.get("close")),
                "pct_chg": _round(r.get("pct_chg")),
                "momentum_20d": _round(r.get("momentum_20d")),
            })
        rows.append({
            "industry": ind,
            "sector_score": score,
            "member_count": int(len(g)),
            "top_members": top_members,
        })

    rows.sort(key=lambda x: x["sector_score"], reverse=True)
    rows = rows[:top_n]
    return {"as_of": as_of_date, "industries": rows}


def get_industry_members(industry: str, as_of=None) -> dict:
    """返回某行业的成分股清单（含行业强度分与基础行情）。

    从本地行业字段反查；成分股清单来自 enrichment 面板（含基本面/动量列）。
    """
    db = get_mongo_db_sync()
    as_of_date = _resolve_as_of(db, as_of)
    target = _industry_panel(db, as_of_date)
    if target.empty:
        return {"as_of": as_of_date, "industry": industry, "items": []}

    names = {}
    for s in data_adapter.get_stock_list(db):
        sym = str(s.get("symbol") or "")
        nm = s.get("name") or ""
        if sym and nm:
            names[sym] = nm

    g = target[target["industry"] == industry]
    if g.empty:
        return {"as_of": as_of_date, "industry": industry, "items": [],
                "sector_score": None, "member_count": 0}

    items = []
    for _, r in g.iterrows():
        sym = str(r.get("symbol") or "")
        items.append({
            "code": sym,
            "name": names.get(sym, ""),
            "close": _round(r.get("close")),
            "pct_chg": _round(r.get("pct_chg")),
            "momentum_20d": _round(r.get("momentum_20d")),
            "total_mv": _round(r.get("total_mv")),
            "pe_ttm": _round(r.get("pe_ttm")),
            "revenue_yoy": _round(r.get("revenue_yoy")),
        })

    return {
        "as_of": as_of_date,
        "industry": industry,
        "sector_score": _sector_score(g),
        "member_count": int(len(g)),
        "items": items,
    }


def _round(v):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    if isinstance(v, pd.DataFrame) and v.empty:
        return None
    try:
        if pd.isna(v):
            return None
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None