"""策略筛选服务 — 移植自 tickflow-stock-panel 的 ScreenerService。

流程：加载全市场日线(warmup历史) → 计算指标/信号 → 在某交易日过滤 → 评分排序。
"""
from __future__ import annotations
from app.utils.timezone import now_tz

import logging
import threading
import time
from collections import OrderedDict
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
WARMUP_DAYS = 130

# 筛选只需目标交易日当天的指标，最长指标窗口为 60 个交易日（ma60/momentum60/high60d）。
# 因此在 compute_all 前把面板裁剪到最近 SCREEN_MAX_WINDOW_DAYS 个交易日，
# 避免对全量历史行计算指标，显著降低耗时。
SCREEN_MAX_WINDOW_DAYS = 70

# run-all 筛选结果缓存集合：同一交易日结果幂等，缓存后再次打开页面可直接返回（含 computed_at）
SCREEN_CACHE_COLLECTION = "strategy_screen_cache"

# ──────────────────────────────────────────────────────────────
# 进程内面板/目标日缓存（LRU + TTL）
# 筛查最贵的两步是 load_daily_panel(全市场日线 ~7s) + compute_all(指标 ~17s) +
# enrich_target(基本面/分红 ~4s)。同一交易日的面板与指标是确定的：
#  - as_of 即最新交易日，交易日变化 → key 变化 → 自动失效，无脏数据；
#  - refresh=True 只重算"策略结果"，底层面板/基本面数据不变，仍可复用缓存。
# 缓存后重复请求（含单个策略筛选、频繁打开页面）从 ~60s 降到毫秒级。
# 内存控制：仅保留最近 2 个面板 + 2 个目标日，8GB 受限容器内安全。
# ──────────────────────────────────────────────────────────────
_PANEL_CACHE_MAX = 2
_TARGET_CACHE_MAX = 2
# TTL 6 小时：日线为收盘后 EOD 数据（18:30 后才写入新交易日），同一交易日内
# stock_daily_quotes 冻结，且缓存键含 as_of（交易日）→ 新交易日落地后键变化自动失效。
# 10 分钟 TTL 会让用户间隔稍久再打开页面就触发全量重算（~20s），故延长至 6 小时。
_CACHE_TTL_SECONDS = 21600
_panel_cache: OrderedDict[tuple, tuple[float, pd.DataFrame]] = OrderedDict()
_target_cache: OrderedDict[tuple, tuple[float, pd.DataFrame]] = OrderedDict()
_cache_lock = threading.Lock()

# single-flight：同一 (as_of, pool) 面板/目标日被并发请求时只允许一个线程真正加载，
# 其余线程在锁上等待后命中缓存。避免候选池并行打分流式时对全市场面板重复加载（~10×DB）。
_panel_load_locks: dict[tuple, threading.Lock] = {}
_target_load_locks: dict[tuple, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_load_lock(lock_map: dict[tuple, threading.Lock], key: tuple) -> threading.Lock:
    with _locks_guard:
        lk = lock_map.get(key)
        if lk is None:
            lk = threading.Lock()
            lock_map[key] = lk
        return lk


def _panel_cache_key(as_of: str, pool: list[str] | None) -> tuple:
    return (as_of, tuple(sorted(pool)) if pool else None)


def _cache_get(cache, key: tuple) -> pd.DataFrame | None:
    now = time.monotonic()
    with _cache_lock:
        hit = cache.get(key)
        if hit is None:
            return None
        ts, df = hit
        if now - ts > _CACHE_TTL_SECONDS:
            del cache[key]
            return None
        cache.move_to_end(key)  # LRU：命中后移到末尾
        return df


def _cache_put(cache, key: tuple, df: pd.DataFrame, max_size: int) -> None:
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
        cache[key] = (time.monotonic(), df)
        while len(cache) > max_size:
            cache.popitem(last=False)


def _load_computed_panel(db, pool: list[str] | None, as_of_date: str) -> pd.DataFrame:
    """加载全市场日线面板并计算指标，结果按 (as_of, pool) 进程内缓存。

    对应原流程：load_daily_panel → _trim_to_last_days → compute_all。
    """
    key = _panel_cache_key(as_of_date, pool)
    cached = _cache_get(_panel_cache, key)
    if cached is not None:
        return cached

    # single-flight：并发首次请求时只加载一次，其余线程等待后命中缓存
    with _get_load_lock(_panel_load_locks, key):
        cached = _cache_get(_panel_cache, key)
        if cached is not None:
            return cached
        as_of_dt = pd.to_datetime(as_of_date)
        start_dt = as_of_dt - timedelta(days=WARMUP_DAYS)
        raw = data_adapter.load_daily_panel(db, pool, start_dt, as_of_date)
        if raw.empty:
            return raw
        # 仅保留最近 SCREEN_MAX_WINDOW_DAYS 个交易日（足以为最长60日窗口提供warmup）
        raw = _trim_to_last_days(raw, SCREEN_MAX_WINDOW_DAYS)
        df = compute_all(raw)
        _cache_put(_panel_cache, key, df, _PANEL_CACHE_MAX)
        return df


def _load_raw_panel(db, pool: list[str] | None, as_of_date: str) -> pd.DataFrame:
    """加载最近 SCREEN_MAX_WINDOW_DAYS 个交易日的原始日线面板（不计算指标）。

    供盘中实时增强面板复用：原始日K历史 + 今日实时bar 拼合后再统一 compute_all，
    避免对已含指标列的面板重复计算产生重复列。结果按 (raw, as_of, pool) 进程内缓存。
    """
    key = ("raw", _panel_cache_key(as_of_date, pool))
    cached = _cache_get(_panel_cache, key)
    if cached is not None:
        return cached
    with _get_load_lock(_panel_load_locks, key):
        cached = _cache_get(_panel_cache, key)
        if cached is not None:
            return cached
        as_of_dt = pd.to_datetime(as_of_date)
        start_dt = as_of_dt - timedelta(days=WARMUP_DAYS)
        raw = data_adapter.load_daily_panel(db, pool, start_dt, as_of_date)
        if raw.empty:
            return raw
        raw = _trim_to_last_days(raw, SCREEN_MAX_WINDOW_DAYS)
        _cache_put(_panel_cache, key, raw, _PANEL_CACHE_MAX)
        return raw


def _get_enriched_target(db, panel: pd.DataFrame, pool: list[str] | None, as_of_date: str) -> pd.DataFrame:
    """取目标交易日行并注入基本面/分红，结果按 (as_of, pool) 进程内缓存。"""
    key = _panel_cache_key(as_of_date, pool)
    cached = _cache_get(_target_cache, key)
    if cached is not None:
        return cached

    # single-flight：并发首次请求时只 enrich 一次，其余线程等待后命中缓存
    with _get_load_lock(_target_load_locks, key):
        cached = _cache_get(_target_cache, key)
        if cached is not None:
            return cached
        target = panel[panel["date"] == as_of_date].copy()
        if target.empty:
            return target
        target = _enrich_target(db, target, as_of_date)
        _cache_put(_target_cache, key, target, _TARGET_CACHE_MAX)
        return target


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


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _trim_to_last_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    """裁剪面板，每只股票只保留最近 days 个交易日（输入需按 symbol/date 升序）。

    筛选只需目标交易日当天的指标，且最长指标窗口为 60 个交易日，
    因此保留最近 days(=70) 个交易日已足以为 ma60/60日动量等提供 warmup。
    """
    if df is None or df.empty or days <= 0:
        return df
    return df.groupby("symbol", sort=False).tail(days).reset_index(drop=True)


def _load_fundamentals(db, symbols) -> pd.DataFrame:
    """从 stock_basic_info 加载行业/市值/估值字段，返回 symbol 去重后的 DataFrame。

    单位约定：total_mv 为亿元。

    stock_basic_info 中同一 code 可能有多条记录（多数据源重复写入），部分记录
    industry / pe / pb / total_mv 为空。这里按 code 聚合，优先挑选字段最完整的记录
    （industry 非空优先，其次 pe/pb/total_mv 有效），避免因取到空记录导致
    行业龙头等依赖行业字段的策略失效。
    """
    if not symbols:
        return pd.DataFrame()
    sym_list = [str(s) for s in symbols]
    cursor = db["stock_basic_info"].find(
        {"$or": [{"code": {"$in": sym_list}}, {"symbol": {"$in": sym_list}}]},
        {
            "_id": 0, "code": 1, "symbol": 1, "industry": 1,
            "total_mv": 1, "pe": 1, "pb": 1, "pe_ttm": 1, "pb_mrq": 1,
            "roe": 1,
        },
    )

    def _pick_score(industry, pe, pb, mv) -> int:
        """记录完整度评分：industry 非空 > 有效估值 > 有效市值，值越大代表字段越完整。"""
        score = 0
        if industry:  # 行业龙头等策略强依赖行业字段
            score += 4
        if pe or pb:  # 任一有效估值字段
            score += 2
        if mv:  # 有效市值
            score += 1
        return score

    best: dict[str, dict] = {}
    for doc in cursor:
        code = str(doc.get("code") or doc.get("symbol") or "").strip()
        if not code:
            continue
        industry = (doc.get("industry") or "").strip()
        pe = _to_float(doc.get("pe_ttm")) or _to_float(doc.get("pe"))
        pb = _to_float(doc.get("pb")) or _to_float(doc.get("pb_mrq"))
        mv = _to_float(doc.get("total_mv"))
        roe = _to_float(doc.get("roe"))
        score = _pick_score(industry, pe, pb, mv)
        prev = best.get(code)
        if prev is None or score > prev["_score"]:
            best[code] = {
                "_score": score,
                "symbol": code,
                "industry": industry,
                "total_mv": mv,
                "pe_ttm": pe,
                "pb": pb,
                "roe": roe,
            }

    rows = [v for v in best.values()]
    return pd.DataFrame(rows)


def _load_valuation_asof(db, symbols, as_of_date: str) -> pd.DataFrame:
    """加载截至 as_of_date 的每日估值（PE/PB/市值），每股取 as_of 当日或之前最近一条。

    PIT（point-in-time）正确：筛选历史日期时使用当时的估值，而非最新快照，
    避免"低估值高股息"等依赖估值条件的策略在未来函数下高估命中。
    返回列：symbol, pe_ttm, pb, total_mv。无每日数据的股票不返回（由调用方兜底）。

    性能：以 as_of 为界并回溯 90 天，用聚合按 (code/symbol) 取 trade_date 最新一条，
    只返回每股一行。不能对全量历史 find + 逐条扫描——stock_daily_basic 达数百万行，
    无下界查询会读整库导致筛选接口卡死（bug-021）。
    """
    if not symbols:
        return pd.DataFrame(columns=["symbol", "pe_ttm", "pb", "total_mv"])
    sym_list = [str(s) for s in symbols]
    asof_dt = pd.to_datetime(as_of_date)
    since = (asof_dt - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    pipeline = [
        {
            "$match": {
                "trade_date": {"$gte": since, "$lte": asof_dt.strftime("%Y-%m-%d")},
                "$or": [{"code": {"$in": sym_list}}, {"symbol": {"$in": sym_list}}],
            }
        },
        {"$sort": {"trade_date": -1}},
        {
            "$group": {
                "_id": {"$ifNull": ["$code", "$symbol"]},
                "pe_ttm": {"$first": "$pe_ttm"},
                "pb": {"$first": "$pb"},
                "total_mv": {"$first": "$total_mv"},
            }
        },
    ]
    rows = [
        {
            "symbol": str(doc["_id"]),
            "pe_ttm": _to_float(doc.get("pe_ttm")),
            "pb": _to_float(doc.get("pb")),
            "total_mv": _to_float(doc.get("total_mv")),
        }
        for doc in db["stock_daily_basic"].aggregate(pipeline)
    ]
    return pd.DataFrame(rows)


def _load_dividend_metrics(db, symbols, as_of_date: str) -> dict:
    """从 stock_dividend 计算每只股票的股息指标。

    返回 {symbol: {"div_12m_ps": 近12个月每股现金分红(税后),
                   "div_paying_years": 近5个自然年度内有分红(现金>0)的年数}}
    """
    if not symbols:
        return {}
    from datetime import date as _date
    sym_list = [str(s) for s in symbols]
    cursor = db["stock_dividend"].find(
        {"code": {"$in": sym_list}},
        {"_id": 0, "code": 1, "ex_date": 1, "ann_date": 1, "end_date": 1,
         "cash_div": 1, "cash_div_tax": 1},
    )
    as_of_d = pd.to_datetime(as_of_date).date()
    as_of_year = as_of_d.year

    ps_sum: dict[str, float] = {}
    years: dict[str, set] = {}
    for doc in cursor:
        code = str(doc.get("code") or "")
        if not code:
            continue
        cash = _to_float(doc.get("cash_div_tax")) or _to_float(doc.get("cash_div"))
        if not cash or cash <= 0:
            continue
        date_str = str(doc.get("ex_date") or doc.get("ann_date") or "").strip()
        if len(date_str) < 8:
            continue
        try:
            dt = _date.fromisoformat(date_str[:10])
        except ValueError:
            continue
        if (as_of_d - dt).days <= 365:
            ps_sum[code] = ps_sum.get(code, 0.0) + cash
        years.setdefault(code, set()).add(dt.year)

    out: dict[str, dict] = {}
    for code in set(ps_sum.keys()) | set(years.keys()):
        yset = {y for y in years.get(code, set()) if as_of_year - 5 < y <= as_of_year}
        out[code] = {
            "div_12m_ps": round(ps_sum.get(code, 0.0), 4),
            "div_paying_years": len(yset),
        }
    return out


def _load_growth_metrics(db, symbols) -> dict:
    """从 stock_financial_data 加载每只股票最新一期财务增速与盈利指标。

    返回 {symbol: {"revenue_yoy": 营收同比, "net_profit_yoy": 净利同比, "roe": 净资产收益率}}。
    每股取 report_period 倒序的第一条（最新报告期），供困境反转/小盘价值等策略过滤。
    性能：按 symbol 查询该股最新一期，避免全量扫描。
    """
    if not symbols:
        return {}
    sym_list = [str(s) for s in symbols]
    out: dict[str, dict] = {}
    for sym in sym_list:
        doc = db["stock_financial_data"].find_one(
            {"symbol": sym},
            {"_id": 0, "revenue_yoy": 1, "net_profit_yoy": 1,
             "roe": 1, "report_period": 1},
            sort=[("report_period", -1)],
        )
        if not doc:
            continue
        out[sym] = {
            "revenue_yoy": _to_float(doc.get("revenue_yoy")),
            "net_profit_yoy": _to_float(doc.get("net_profit_yoy")),
            "roe": _to_float(doc.get("roe")),
        }
    return out


def _enrich_target(db, target: pd.DataFrame, as_of_date: str) -> pd.DataFrame:
    """把基本面(行业/市值/估值)、分红与财务增速数据 join 进目标日筛选 DataFrame。

    新增列：industry, total_mv, pe_ttm, pb, div_12m_ps, div_paying_years, div_yield,
    revenue_yoy, net_profit_yoy。
    """
    if target.empty:
        return target
    symbols = [str(s) for s in target["symbol"].unique().tolist()]

    out = target.copy()
    fund = _load_fundamentals(db, symbols)  # 行业(静态) + 最新快照兜底

    # PIT 每日估值：优先取 as_of 当日/最近估值，避免筛选历史日期用到未来快照（未来函数）。
    # 无每日估值数据时回退到最新快照广播（保持历史行为）。
    val = _load_valuation_asof(db, symbols, as_of_date)
    if not val.empty:
        # 行业为静态字段，始终来自快照
        if not fund.empty:
            out = out.merge(fund[["symbol", "industry"]], on="symbol",
                            how="left", suffixes=("", "_fund"))
        out = out.merge(val, on="symbol", how="left", suffixes=("", "_val"))
        # 无每日估值的股票用最新快照兜底（保证列非空）
        if not fund.empty:
            snap_cols = ["symbol", "total_mv", "pe_ttm", "pb"]
            snap = fund[snap_cols]
            out = out.merge(snap, on="symbol", how="left", suffixes=("", "_snap"))
            for c in ("total_mv", "pe_ttm", "pb"):
                snap_col = f"{c}_snap"
                # 仅对存在 _snap 后缀列的字段做快照兜底，避免 KeyError。
                if snap_col in out.columns:
                    out[c] = out[c].fillna(out[snap_col])
            out = out.drop(columns=[f"{c}_snap" for c in ("total_mv", "pe_ttm", "pb")
                                    if f"{c}_snap" in out.columns])
    else:
        if not fund.empty:
            out = out.merge(fund, on="symbol", how="left", suffixes=("", "_fund"))

    div_map = _load_dividend_metrics(db, symbols, as_of_date)
    out["div_12m_ps"] = out["symbol"].map(lambda s: div_map.get(str(s), {}).get("div_12m_ps", 0.0))
    out["div_paying_years"] = out["symbol"].map(lambda s: div_map.get(str(s), {}).get("div_paying_years", 0))

    close = pd.to_numeric(out["close"], errors="coerce")
    out["div_yield"] = (out["div_12m_ps"] / close.where(close > 0)).round(4)

    # 财务指标：每股取最新报告期，注入 revenue_yoy / net_profit_yoy / roe
    # （困境反转、小盘价值等策略依赖）。roe 权威来源为 stock_financial_data，
    # 不从 stock_basic_info 快照读取（该集合无 roe 字段）。
    growth = _load_growth_metrics(db, symbols)
    out["revenue_yoy"] = out["symbol"].map(lambda s: growth.get(str(s), {}).get("revenue_yoy"))
    out["net_profit_yoy"] = out["symbol"].map(lambda s: growth.get(str(s), {}).get("net_profit_yoy"))
    out["roe"] = out["symbol"].map(lambda s: growth.get(str(s), {}).get("roe"))
    return out


def _build_intraday_target(db, pool: list[str] | None):
    """构建盘中实时增强面板的『今日』目标行。

    历史日K截至最新 EOD 交易日，拼接今日实时合成K后重算指标，返回 today 行。
    若今日日线已入库（as_of==today）或无法取到实时行情，返回 (None, as_of_date, False)，
    由调用方回落到常规 EOD 面板。

    Returns:
        (target, as_of_date, is_intraday): target 为今日行 DataFrame；is_intraday=True
        表示已采用实时合成面板。
    """
    if not pool:
        return None, None, False
    pool = [str(s) for s in pool if s]
    if not pool:
        return None, None, False
    as_of_date = _resolve_as_of(db, None)
    today = date.today().strftime("%Y-%m-%d")
    if as_of_date == today:
        return None, as_of_date, False
    df = _load_raw_panel(db, pool, as_of_date)
    if df.empty:
        return None, as_of_date, False
    bars = _fetch_live_bars(pool)
    today_rows = _build_intraday_rows(pool, bars, today)
    if today_rows.empty:
        return None, as_of_date, False
    enhanced = pd.concat([df, today_rows], ignore_index=True, sort=False)
    enhanced = compute_all(enhanced)
    target = enhanced[enhanced["date"] == today].copy()
    if target.empty:
        return None, as_of_date, False
    return target, today, True


def run_strategy(
    db,
    strategy_id: str,
    as_of=None,
    params: dict | None = None,
    limit: int = 100,
    pool: list[str] | None = None,
    realtime: bool = False,
) -> dict:
    """运行单个策略筛选，返回命中股票列表。

    realtime=True 且提供 pool 时，用「历史日K + 当日实时合成K」做盘中实时信号触发
    （仅支持自选/持仓等小池，避免全市场过于繁重）；否则走常规 EOD 日K面板。
    """
    t0 = time.perf_counter()
    strategy = get_strategy(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")

    is_intraday = False
    target = None
    as_of_date = None
    if realtime and pool:
        target, as_of_date, is_intraday = _build_intraday_target(db, pool)

    if target is None:
        as_of_date = _resolve_as_of(db, as_of)
        df = _load_computed_panel(db, pool, as_of_date)
        if df.empty:
            return _empty_result(as_of_date, strategy_id, "无行情数据")
        target = _get_enriched_target(db, df, pool, as_of_date)
    else:
        as_of_date = as_of_date or _resolve_as_of(db, as_of)
        # 实时合成面板未做基本面/估值增强，与 EOD 路径保持一致地补全
        target = _enrich_target(db, target, as_of_date)

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

    result = {
        "as_of": as_of_date,
        "strategy_id": strategy_id,
        "strategy_name": strategy.get("name"),
        "total": len(items),
        "items": items,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }
    # 实时合成面板标记，供前端识别为盘中实时触发结果
    if is_intraday:
        result["realtime"] = True
    return result


# 策略信号列 → 中文标签（用于把命中信号转译为可读的买入/卖出原因）
_SIGNAL_LABELS: dict[str, str] = {
    "signal_ma_golden_5_20": "MA5 上穿 MA20",
    "signal_ma_dead_5_20": "MA5 下穿 MA20",
    "signal_ma_golden_20_60": "MA20 上穿 MA60",
    "signal_macd_golden": "MACD 金叉（DIF 上穿 DEA）",
    "signal_macd_dead": "MACD 死叉（DIF 下穿 DEA）",
    "signal_ma5_breakout": "站上 MA5",
    "signal_ma5_breakdown": "跌破 MA5",
    "signal_ma10_breakout": "站上 MA10",
    "signal_ma10_breakdown": "跌破 MA10",
    "signal_ma20_breakout": "向上突破 MA20",
    "signal_ma20_breakdown": "跌破 MA20",
    "signal_n_day_high": "创 60 日新高",
    "signal_n_day_low": "创 60 日新低",
    "signal_boll_breakout_upper": "突破布林上轨",
    "signal_boll_breakdown_lower": "跌破布林下轨",
    "signal_volume_surge": "放量（量比≥2）",
}

# 信号列 → 参与数值接续的指标列（用于在原因里补充关键数值）
_SIGNAL_VALUE_COLS: dict[str, tuple[str, ...]] = {
    "signal_ma_golden_5_20": ("ma5", "ma20"),
    "signal_ma_dead_5_20": ("ma5", "ma20"),
    "signal_ma_golden_20_60": ("ma20", "ma60"),
    "signal_macd_golden": ("macd_dif", "macd_dea"),
    "signal_macd_dead": ("macd_dif", "macd_dea"),
    "signal_ma5_breakout": ("ma5",),
    "signal_ma5_breakdown": ("ma5",),
    "signal_ma10_breakout": ("ma10",),
    "signal_ma10_breakdown": ("ma10",),
    "signal_ma20_breakout": ("ma20",),
    "signal_ma20_breakdown": ("ma20",),
    "signal_boll_breakout_upper": ("boll_upper",),
    "signal_boll_breakdown_lower": ("boll_lower",),
}


def _fmt2(v) -> str:
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "-"


def _fmt3(v) -> str:
    try:
        return f"{float(v):.3f}"
    except Exception:
        return "-"


def _describe_hits(
    strategy: dict,
    target: pd.DataFrame,
    hit_codes: list[str],
    direction: str,
) -> dict[str, str]:
    """为命中（买入/卖出）股票构建人类可读的详细原因。

    在策略名称之外补充具体触发信号与关键指标数值，便于持仓追踪与交易复盘回溯。
    返回 {code: reason}，如：
      "MACD 金叉（DIF 上穿 DEA）；DIF 0.214 上穿 DEA 0.186；现价 14.20，较昨收 +3.2%"
    """
    if direction not in ("entry", "exit"):
        direction = "entry"
    sig_columns = (
        (strategy.get("entry_signals") or [])
        if direction == "entry"
        else (strategy.get("exit_signals") or [])
    )
    if not sig_columns:
        return {}

    out: dict[str, str] = {}
    idx = target.set_index("symbol")
    for code in hit_codes:
        if code not in idx.index:
            continue
        try:
            row = idx.loc[code]
        except KeyError:
            continue
        parts: list[str] = []
        for c in sig_columns:
            if c not in row.index:
                continue
            try:
                fired = bool(row[c])
            except Exception:
                fired = False
            if not fired:
                continue
            label = _SIGNAL_LABELS.get(c, c)
            # 补充关键数值：如 DIF/DEA、MA5/MA20
            extra = ""
            for vc in _SIGNAL_VALUE_COLS.get(c, ()):
                if vc in row.index and row[vc] is not None and not pd.isna(row[vc]):
                    extra += f" {vc}={_fmt3(row[vc])}" if vc.startswith("macd") else f" {vc}={_fmt2(row[vc])}"
            parts.append(label + extra)
        try:
            close = float(row["close"])
        except Exception:
            close = None
        if close is not None:
            price_bit = f"现价 {close:.2f}"
            try:
                pct = float(row["pct_chg"]) * 100
                price_bit += f"，较昨收 {pct:+.2f}%"
            except Exception:
                pass
            parts.append(price_bit)
        if not parts:
            parts.append("触发信号")
        out[code] = "；".join(parts)
    return out


def run_strategy_signals(
    db,
    strategy_id: str,
    pool: list[str] | None = None,
    as_of: str | None = None,
) -> dict:
    """对指定股票池运行策略，返回筛选命中与离场信号命中的代码列表。

    供「常用策略监控」使用：
      - entry: 策略筛选命中（买入信号）的股票代码
      - exit:  策略离场信号（exit_signals 任一布尔列触发）的股票代码

    复用面板/指标缓存，小池子（自选/持仓）开销可控。
    """
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"entry": [], "exit": []}

    as_of_date = _resolve_as_of(db, as_of)
    df = _load_computed_panel(db, pool, as_of_date)
    if df.empty:
        return {"entry": [], "exit": []}
    target = _get_enriched_target(db, df, pool, as_of_date)
    if target.empty:
        return {"entry": [], "exit": []}

    # 买入：策略筛选过滤命中
    mask = run_strategy_filter(strategy_id, target, {}).fillna(False)
    entry_codes = [str(s) for s in target.loc[mask, "symbol"]]

    # 卖出：任一 exit_signal 布尔列触发
    exit_codes: list[str] = []
    exit_sigs = strategy.get("exit_signals", []) or []
    if exit_sigs:
        exit_mask = pd.Series(False, index=target.index)
        for sig in exit_sigs:
            if sig in target.columns:
                exit_mask |= target[sig].fillna(False).astype(bool)
        exit_codes = [str(s) for s in target.loc[exit_mask, "symbol"]]

    return {
        "entry": entry_codes,
        "exit": exit_codes,
        "entry_reasons": _describe_hits(strategy, target, entry_codes, "entry"),
        "exit_reasons": _describe_hits(strategy, target, exit_codes, "exit"),
    }


# ──────────────────────────────────────────────────────────────
# 盘中实时增强面板（阶段2）
# 盘中扫描仅覆盖自选+持仓，用"昨收日K历史 + 今日实时bar"合成增强面板，
# 重算指标/信号，检测 MACD 金叉等策略信号实时触发。
# MACD 盘中确认接受噪音：直接以实时收盘价参与金叉判断，不等待日线收盘确认。
# ──────────────────────────────────────────────────────────────

def _fetch_live_bars(pool: list[str]) -> dict[str, dict]:
    """从实时行情构建今日K线字段（open/high/low/close/volume/amount/pct_chg）。

    优先腾讯源（字段全：现价/开/高/低/量）。无法返回 OHLC 的股票用现价兜底 open/
    high/low（MACD 信号仅依赖 close，不受影响）。amount 单位为元（amount_wan→*10000）。
    """
    from app.services.unified_quotes import get_unified_quotes

    try:
        raw = get_unified_quotes(pool, prefer_source="tencent")
    except Exception as e:
        logger.warning(f"⚠️ 盘中实时行情获取失败: {e}")
        raw = {}

    bars: dict[str, dict] = {}
    for sym in pool:
        q = raw.get(sym) or {}
        close = _to_float(q.get("price"))
        if close is None or close <= 0:
            continue
        open_ = _to_float(q.get("open")) or close
        high = _to_float(q.get("high")) or close
        low = _to_float(q.get("low")) or close
        volume = _to_float(q.get("volume")) or 0.0
        amount_wan = _to_float(q.get("amount_wan"))
        pct = _to_float(q.get("change_pct"))
        bars[sym] = {
            "symbol": sym,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": (amount_wan * 10000) if amount_wan is not None else None,
            # 与日线面板一致：pct_chg 为小数（tencent 为百分数 → /100）
            "pct_chg": (pct / 100.0) if pct is not None else None,
        }
    return bars


def _build_intraday_rows(pool: list[str], bars: dict[str, dict], today: str) -> pd.DataFrame:
    """把实时 bar 组装为今日K线行（列与日线面板一致）。"""
    if not bars:
        return pd.DataFrame(columns=data_adapter.PANEL_COLUMNS)
    rows = []
    for sym in pool:
        b = bars.get(sym)
        if not b:
            continue
        rows.append({
            "symbol": b["symbol"],
            "date": today,
            "open": b["open"],
            "high": b["high"],
            "low": b["low"],
            "close": b["close"],
            "volume": b["volume"],
            "amount": b["amount"],
            "pct_chg": b["pct_chg"],
        })
    df = pd.DataFrame(rows, columns=data_adapter.PANEL_COLUMNS)
    for col in ("open", "high", "low", "close", "pct_chg", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float32", copy=False)
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df


def run_strategy_signals_intraday(
    db,
    strategy_id: str,
    pool: list[str] | None,
) -> dict:
    """盘中实时扫描自选+持仓的增强面板（昨收日K + 今日实时bar）。

    历史日K截至最新 EOD 交易日（as_of），拼接今日实时合成行后再算指标/信号，
    对"今日"行执行策略过滤，返回命中（entry）与离场（exit）代码列表。
    若今日日线已入库（as_of==today，如收盘后），自动回落常规日线扫描，避免重复。

    注意：今日量能仅为盘中已成交量，vol_ratio 类过滤在盘中会失真；策略过滤是否
    依赖量能由具体策略决定（MACD金叉不依赖量能，可安全盘中实时触发）。
    """
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return {"entry": [], "exit": []}
    pool = [str(s) for s in pool if s]
    if not pool:
        return {"entry": [], "exit": []}

    as_of_date = _resolve_as_of(db, None)
    today = date.today().strftime("%Y-%m-%d")
    if as_of_date == today:
        return run_strategy_signals(db, strategy_id, pool, as_of=today)

    df = _load_raw_panel(db, pool, as_of_date)
    if df.empty:
        return {"entry": [], "exit": []}

    bars = _fetch_live_bars(pool)
    today_rows = _build_intraday_rows(pool, bars, today)
    if today_rows.empty:
        return {"entry": [], "exit": []}

    # 原始日K历史 + 今日实时bar 拼合后统一算指标/信号（避免重复列）
    enhanced = pd.concat(
        [df, today_rows], ignore_index=True, sort=False
    )
    enhanced = compute_all(enhanced)
    target = enhanced[enhanced["date"] == today].copy()
    if target.empty:
        return {"entry": [], "exit": []}

    # 买入：策略筛选过滤命中
    mask = run_strategy_filter(strategy_id, target, {}).fillna(False)
    entry_codes = [str(s) for s in target.loc[mask, "symbol"]]

    # 卖出：任一 exit_signal 布尔列触发
    exit_codes: list[str] = []
    exit_sigs = strategy.get("exit_signals", []) or []
    if exit_sigs:
        exit_mask = pd.Series(False, index=target.index)
        for sig in exit_sigs:
            if sig in target.columns:
                exit_mask |= target[sig].fillna(False).astype(bool)
        exit_codes = [str(s) for s in target.loc[exit_mask, "symbol"]]

    return {
        "entry": entry_codes,
        "exit": exit_codes,
        "entry_reasons": _describe_hits(strategy, target, entry_codes, "entry"),
        "exit_reasons": _describe_hits(strategy, target, exit_codes, "exit"),
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
    realtime: bool = False,
) -> dict:
    """批量运行全部策略，返回每个策略的命中数与 top 结果。

    realtime=True 且提供 pool 时，用「历史日K + 当日实时合成K」做盘中实时触发
    （仅支持自选/持仓等小池）；此时结果逐次多变，不做 MongoDB 缓存。
    否则默认流程：结果按 (as_of, pool) 缓存到 MongoDB，同一交易日幂等。
    """
    t0 = time.perf_counter()

    is_intraday = False
    target = None
    as_of_date = None
    if realtime and pool:
        target, as_of_date, is_intraday = _build_intraday_target(db, pool)

    if target is None:
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

        df = _load_computed_panel(db, pool, as_of_date)
        if df.empty:
            return {"as_of": as_of_date, "strategies": [], "elapsed_ms": 0}

        target = _get_enriched_target(db, df, pool, as_of_date)
        if target.empty:
            return {"as_of": as_of_date, "strategies": [], "elapsed_ms": 0}
    else:
        as_of_date = as_of_date or _resolve_as_of(db, as_of)
        key = None
        # 实时合成面板未做基本面/估值增强，与 EOD 路径保持一致地补全
        target = _enrich_target(db, target, as_of_date)
        if target.empty:
            return {"as_of": as_of_date, "strategies": [], "elapsed_ms": 0, "realtime": True}

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
    result["realtime"] = is_intraday
    # 实时结果逐次多变，不做缓存；仅 EOD 结果按 (as_of, pool) 持久化
    if not is_intraday:
        computed_at = now_tz().strftime("%Y-%m-%d %H:%M:%S")
        result["computed_at"] = computed_at
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