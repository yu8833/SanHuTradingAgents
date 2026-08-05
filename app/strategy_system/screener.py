"""策略筛选服务 — 移植自 tickflow-stock-panel 的 ScreenerService。

流程：加载全市场日线(warmup历史) → 计算指标/信号 → 在某交易日过滤 → 评分排序。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from app.strategy_system import data_adapter
from app.strategy_system.indicators import compute_all
from app.strategy_system.strategies import (
    BUILTIN_STRATEGIES,
    get_strategies,
    get_strategy,
    run_strategy_filter,
)

logger = logging.getLogger(__name__)

# 指标 warmup 需要的历史天数（覆盖 ma60/60日动量等长周期）
WARMUP_DAYS = 180

# run-all 筛选结果缓存集合：同一交易日结果幂等，缓存后再次打开页面可直接返回（含 computed_at）
SCREEN_CACHE_COLLECTION = "strategy_screen_cache"


def _latest_trade_date(db) -> str:
    """从 stock_daily_quotes 获取最新交易日。"""
    doc = db["stock_daily_quotes"].find_one(
        {"period": "daily", "trade_date": {"$ne": None}},
        {"_id": 0, "trade_date": 1},
        sort=[("trade_date", -1)],
    )
    return doc["trade_date"] if doc else None


def _score_rank(df: pd.DataFrame, scoring: dict, universe: pd.Series) -> np.ndarray:
    """按评分权重对候选做排序打分（0-100），返回 score 数组。"""
    idx = df.index
    n = len(df)
    score = np.zeros(n, dtype=float)
    if not scoring:
        return score

    executable = []
    for col, weight in scoring.items():
        if not weight or col not in df.columns:
            continue
        val = pd.to_numeric(df[col], errors="coerce")
        executable.append((col, float(weight), val))

    if not executable:
        return score

    total_weight = sum(w for _, w, _ in executable)
    if total_weight <= 0:
        return score

    for _, weight, val in executable:
        w = weight / total_weight
        valid = val.notna()
        if valid.any():
            col_min = val[valid].min()
            col_max = val[valid].max()
            rng = col_max - col_min
            norm = pd.Series(0.5, index=idx)
            if rng > 0:
                norm = (val - col_min) / rng
            norm = norm.where(valid, np.nan)
        else:
            norm = pd.Series(np.nan, index=idx)
        # 仅对候选内计算
        norm = norm.where(universe, np.nan)
        score += norm.fillna(0.0).to_numpy() * w

    return score * 100


def _resolve_as_of(db, as_of=None) -> str:
    """解析目标交易日：默认最新交易日。"""
    if as_of:
        return data_adapter._parse_date(as_of)
    latest = _latest_trade_date(db)
    if latest:
        return latest
    # 兜底：今天
    return date.today().strftime("%Y-%m-%d")


def _stock_name_map(db) -> dict:
    """构建 symbol -> 股票名称 映射，用于结果中展示名称而非代码。"""
    names: dict[str, str] = {}
    for s in data_adapter.get_stock_list(db):
        sym = str(s.get("symbol") or "")
        nm = s.get("name") or ""
        if sym and nm:
            names[sym] = nm
    return names


def run_strategy(
    db,
    strategy_id: str,
    as_of=None,
    params: dict | None = None,
    limit: int = 100,
    pool: list[str] | None = None,
) -> dict:
    """运行单个策略筛选，返回命中股票列表。"""
    t0 = time.perf_counter()
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")

    as_of_date = _resolve_as_of(db, as_of)
    as_of_dt = pd.to_datetime(as_of_date)
    start_dt = as_of_dt - timedelta(days=WARMUP_DAYS)

    df = data_adapter.load_daily_panel(db, pool, start_dt, as_of_date)
    if df.empty:
        return _empty_result(as_of_date, strategy_id, "无行情数据")

    df = compute_all(df)

    # 仅保留目标交易日并需要足够 warmup
    target = df[df["date"] == as_of_date].copy()
    if target.empty:
        return _empty_result(as_of_date, strategy_id, "目标交易日无数据")

    # 过滤（对目标日行向量执行策略 filter）
    mask = run_strategy_filter(strategy_id, target, params or {})
    candidates = target[mask.fillna(False)].copy()

    # 评分排序
    universe = mask.fillna(False)
    scores = _score_rank(target, strategy.get("scoring", {}), universe)
    candidates["score"] = scores[mask.fillna(False).to_numpy()]

    # 排序（返回全部命中，保证行数与命中数一致）
    descending = strategy.get("descending", True)
    candidates = candidates.sort_values("score", ascending=not descending)

    name_map = _stock_name_map(db)
    items = []
    for _, row in candidates.iterrows():
        items.append({
            "symbol": row["symbol"],
            "code": row["symbol"],
            "name": name_map.get(str(row["symbol"]), ""),
            "close": _round(row.get("close")),
            "change_pct": _round(row.get("pct_chg")),
            "open": _round(row.get("open")),
            "high": _round(row.get("high")),
            "low": _round(row.get("low")),
            "volume": _round(row.get("volume")),
            "amount": _round(row.get("amount")),
            "vol_ratio": _round(row.get("vol_ratio_5d")),
            "score": round(float(row.get("score", 0)), 2),
            "date": as_of_date,
        })

    return {
        "as_of": as_of_date,
        "strategy_id": strategy_id,
        "strategy_name": strategy.get("name"),
        "total": len(items),
        "items": items,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def get_trade_dates(db, limit: int = 30) -> list[str]:
    """获取最近 limit 个交易日（倒序），用于前端日期选择下拉。"""
    dates = db["stock_daily_quotes"].distinct(
        "trade_date", {"period": "daily", "trade_date": {"$ne": None}}
    )
    dates = sorted([d for d in dates if d], reverse=True)[: max(1, limit)]
    return dates


def _cache_key(as_of: str, pool: list[str] | None) -> dict:
    return {"as_of": as_of, "pool": sorted(pool) if pool else None}


def run_all_strategies(
    db,
    as_of=None,
    limit: int = 30,
    pool: list[str] | None = None,
    refresh: bool = False,
) -> dict:
    """批量运行全部策略，返回每个策略的命中数与 top 结果。

    结果按 (as_of, pool) 缓存到 MongoDB；同一交易日数据幂等，命中缓存时直接返回，
    并附带 computed_at（计算时间）。refresh=True 时强制重算。
    """
    t0 = time.perf_counter()
    as_of_date = _resolve_as_of(db, as_of)
    key = _cache_key(as_of_date, pool)

    if not refresh:
        cached = db[SCREEN_CACHE_COLLECTION].find_one(
            key, {"_id": 0, "result": 1, "computed_at": 1}
        )
        if cached and cached.get("result"):
            result = cached["result"]
            result["computed_at"] = cached.get("computed_at")
            result["cached"] = True
            return result

    as_of_dt = pd.to_datetime(as_of_date)
    start_dt = as_of_dt - timedelta(days=WARMUP_DAYS)

    df = data_adapter.load_daily_panel(db, pool, start_dt, as_of_date)
    if df.empty:
        return {"as_of": as_of_date, "strategies": [], "elapsed_ms": 0}

    df = compute_all(df)
    target = df[df["date"] == as_of_date].copy()
    if target.empty:
        return {"as_of": as_of_date, "strategies": [], "elapsed_ms": 0}

    strategies = []
    name_map = _stock_name_map(db)
    for strategy in BUILTIN_STRATEGIES:
        sid = strategy["id"]
        try:
            mask = run_strategy_filter(sid, target, {})
            mask = mask.fillna(False)
            universe = mask
            scores = _score_rank(target, strategy.get("scoring", {}), universe)
            cand_idx = mask.to_numpy()
            n_hits = int(cand_idx.sum())
            top_items = []
            if n_hits > 0:
                sub = target[cand_idx].copy()
                sub["score"] = scores[cand_idx]
                # 返回全部命中，保证行数与命中数一致
                sub = sub.sort_values("score", ascending=not strategy.get("descending", True))
                for _, row in sub.iterrows():
                    top_items.append({
                        "symbol": row["symbol"],
                        "code": row["symbol"],
                        "name": name_map.get(str(row["symbol"]), ""),
                        "close": _round(row.get("close")),
                        "change_pct": _round(row.get("pct_chg")),
                        "open": _round(row.get("open")),
                        "high": _round(row.get("high")),
                        "low": _round(row.get("low")),
                        "volume": _round(row.get("volume")),
                        "amount": _round(row.get("amount")),
                        "vol_ratio": _round(row.get("vol_ratio_5d")),
                        "score": round(float(row.get("score", 0)), 2),
                        "date": as_of_date,
                    })
            strategies.append({
                "id": sid,
                "name": strategy.get("name"),
                "description": strategy.get("description"),
                "tags": strategy.get("tags", []),
                "count": n_hits,
                "top": top_items,
            })
        except Exception as e:
            logger.warning("策略 %s 运行失败: %s", sid, e)
            strategies.append({
                "id": sid,
                "name": strategy.get("name"),
                "description": strategy.get("description"),
                "tags": strategy.get("tags", []),
                "count": 0,
                "top": [],
                "error": str(e),
            })

    result = {
        "as_of": as_of_date,
        "strategies": strategies,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    computed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["computed_at"] = computed_at
    result["cached"] = False
    db[SCREEN_CACHE_COLLECTION].update_one(
        key,
        {
            "$set": {
                "result": result,
                "computed_at": computed_at,
                "updated_at": computed_at,
            }
        },
        upsert=True,
    )
    return result


def _round(v):
    if v is None or pd.isna(v):
        return None
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return None


def _empty_result(as_of, strategy_id, msg):
    return {
        "as_of": as_of,
        "strategy_id": strategy_id,
        "strategy_name": "",
        "total": 0,
        "items": [],
        "message": msg,
        "elapsed_ms": 0,
    }


def list_strategies() -> list[dict]:
    return get_strategies()