"""回测引擎 — 移植自 tickflow-stock-panel 的 backtest 模块（pandas/numpy 实现）。

包含四个模块：
- 策略回测 (strategy)：按策略信号构建组合逐日撮合，输出净值/回撤/交易/指标。
- 因子回测 (factor)：IC/IR、分层收益、多空组合。
- 参数优化 (optimizer)：网格搜索参数组合，以目标函数排序。
- 步进优化 (walkforward)：滚动训练/测试窗口，评估参数稳健性。

数据来源：MongoDB stock_daily_quotes（经 data_adapter 加载）。
"""
from __future__ import annotations

import ast
import inspect
import itertools
import logging
import time
import uuid
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from app.strategy_system import data_adapter
from app.strategy_system import screener
from app.strategy_system.indicators import SIGNAL_INDICATOR_DEPS, compute_all
from app.strategy_system.strategies import run_strategy_filter

logger = logging.getLogger(__name__)

WARMUP_DAYS = 180


# ──────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────

from datetime import datetime as _dt


def _parse_date(d) -> str:
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, (_dt, date)):
        return d.strftime("%Y-%m-%d")
    return str(d)[:10]


# 过滤器辅助函数中，列名位于第 index 个参数（_lt(df, col, val) → col 为第 1 个参数）
_FILTER_HELPER_COL_ARG = {"_lt": 1, "_gt": 1, "_ge": 1, "_signal": 1}

# 基本面/股息列（由 _enrich_panel_fundamentals 注入）。仅依赖技术指标的策略
# （如"超跌反弹"）无需这些列，跳过注入可避免全市场加载估值/分红数据，显著省内存。
FUNDAMENTAL_COLUMNS = {
    "industry", "total_mv", "pe_ttm", "pb",
    "div_12m_ps", "div_paying_years", "div_yield",
}


def _strategy_needs_fundamentals(strategy_id: str) -> bool:
    """判断策略是否依赖基本面/股息列，决定 _load_panel 是否注入基本面数据。"""
    return bool(_strategy_required_columns(strategy_id) & FUNDAMENTAL_COLUMNS)


def _extract_filter_columns(filter_fn) -> set[str]:
    """从策略 filter 函数源码解析其引用的列名（df["col"] 与 _lt/_gt/_ge/_signal(df, "col")）。

    用于"按需计算指标/信号列"：只计算策略真正用到的列，压缩全市场回测面板内存。
    解析失败时保守返回空集（调用方会通过 entry/exit/scoring 兜底，不会缺列）。
    """
    cols: set[str] = set()
    try:
        src = inspect.getsource(filter_fn)
        tree = ast.parse(src)
    except Exception:  # noqa: BLE001
        return cols
    for node in ast.walk(tree):
        # df["col"] 形式
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name) and node.value.id == "df"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            cols.add(node.slice.value)
        # _gt/_lt/_ge/_signal(df, "col", ...) 形式
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in _FILTER_HELPER_COL_ARG):
            idx = _FILTER_HELPER_COL_ARG[node.func.id]
            if len(node.args) > idx and isinstance(node.args[idx], ast.Constant) and isinstance(node.args[idx].value, str):
                cols.add(node.args[idx].value)
    return cols


def _strategy_required_columns(strategy_id: str) -> set[str]:
    """返回某策略回测所需的最小列集合（信号列 + 指标列 + 评分列）。

    组成：
    - 进出场信号列（entry_signals / exit_signals）及其依赖的指标列
    - 评分列（scoring 的键）
    - filter 函数直接引用的列
    基础列（symbol/date/open/high/low/close/volume）恒被保留，无需在此列出。
    """
    strategy = _get_strategy_map().get(strategy_id) or {}
    req: set[str] = set()
    for sig in (strategy.get("entry_signals") or []) + (strategy.get("exit_signals") or []):
        req.add(sig)
    req |= set((strategy.get("scoring") or {}).keys())
    filter_fn = strategy.get("filter")
    if filter_fn is not None:
        req |= _extract_filter_columns(filter_fn)
    # 展开信号列的指标依赖（如 signal_ma5_breakout 需要 ma5）
    for sig in list(req):
        if sig.startswith("signal_"):
            req |= SIGNAL_INDICATOR_DEPS.get(sig, set())
    return req


def _load_panel(db, config, end_extra_days: int = 0,
                progress_cb: Callable[[float, str], None] | None = None,
                keep_columns: set[str] | None = None,
                enrich_fundamentals: bool = True) -> pd.DataFrame:
    """加载回测区间 + warmup 历史，并计算指标/信号。

    keep_columns（可选）：只计算并保留策略所需的指标/信号列，压缩全市场长区间
    回测面板内存，避免 3 年期回测触发容器 OOM。默认 None 计算全部列。
    enrich_fundamentals（可选）：基本面/股息策略置 True 注入估值/分红列；纯技术
    策略（如超跌反弹）置 False 跳过注入，避免全市场加载每日估值，进一步省内存。

    通过 progress_cb 分阶段上报进度，避免长时数据加载期间前端进度条长时间停留
    """
    def _report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    start = _parse_date(config.get("start"))
    end = _parse_date(config.get("end"))
    end_dt = pd.to_datetime(end)
    start_dt = pd.to_datetime(start) - pd.Timedelta(days=WARMUP_DAYS)
    load_end = end_dt + pd.Timedelta(days=end_extra_days)

    _report(0.01, "正在加载行情数据…")
    symbols = config.get("symbols")
    df = data_adapter.load_daily_panel(
        db, symbols, start_dt, load_end.strftime("%Y-%m-%d")
    )
    if df.empty:
        return df
    _report(0.02, "正在计算技术指标…")
    # 指标计算阶段耗时最长（全市场可占大头），映射到 [0.02, 0.045] 并报分批进度，
    # 避免长时计算期间进度条长时间停留在 2% 造成"卡死"假象。
    def _ind_cb(p: float, msg: str) -> None:
        _report(0.02 + 0.025 * min(1.0, max(0.0, float(p))), msg)

    df = compute_all(df, progress_cb=_ind_cb, keep_columns=keep_columns)
    # 统一转回字符串便于下游字符串比较。compute_all 不改变 date 的 dtype
    # （load_daily_panel 已返回 "%Y-%m-%d" 字符串），这里用 to_datetime 兜底，
    # 兼容 date 为字符串或 datetime64 两种入参，避免 .dt 访问器报错。
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    # 注入基本面(行业/市值/估值)与分红列，供价值/股息类策略在回测中也能产生信号，
    # 与筛选侧 screener._enrich_target 保持一致的口径
    if enrich_fundamentals:
        _report(0.045, "正在注入基本面与股息数据（全市场可能较慢）…")
        # 将子阶段的 0-1 进度映射到整体 [0.045, 0.05]，避免子进度直接写回导致进度条跳变
        base_from, base_to = 0.045, 0.05

        def _child(p: float, msg: str, _a: float = base_from, _b: float = base_to) -> None:
            _report(_a + (_b - _a) * min(1.0, max(0.0, float(p))), msg)

        df = _enrich_panel_fundamentals(db, df, progress_cb=_child)
    # 兜底：全市场面板（407万行×60+列）在 8GB 容器中必须压缩 dtype。
    # 指标/merge 引入的 float64 列统一降 float32，内存减半，避免全局 OOM。
    float64_cols = [c for c in df.columns if df[c].dtype == "float64"]
    if float64_cols:
        df[float64_cols] = df[float64_cols].astype("float32")
    return df


def _enrich_panel_fundamentals(db, df: pd.DataFrame,
                               progress_cb: Callable[[float, str], None] | None = None) -> pd.DataFrame:
    """为回测面板逐行注入基本面与分红列：industry, total_mv, pe_ttm, pb,
    div_12m_ps, div_paying_years, div_yield。

    估值/市值（pe_ttm/pb/total_mv）优先使用每日历史数据（stock_daily_basic，
    按 (symbol, date) 对齐并前向填充），使依赖估值条件的策略能在估值变化时
    触发卖出；无每日数据时回退到每股最新快照广播（保持历史行为）。
    行业（industry）为静态字段，始终来自快照。
    股息指标按面板内每个交易日内存批量计算（div_yield = div_12m_ps / 当日 close）。
    与筛选侧 _enrich_target 口径一致，使依赖基本面列的策略回测能产生信号。
    """
    if df.empty:
        return df
    symbols = [str(s) for s in df["symbol"].unique().tolist() if s]
    if not symbols:
        return df

    # 1) 行业/市值/估值快照（每股最新，用于行业字段与估值兜底）
    fund = screener._load_fundamentals(db, symbols)

    # 2) 每日历史估值（pe_ttm/pb/total_mv），按 (symbol, date) 对齐 + 前向填充
    if progress_cb:
        progress_cb(0.05, "正在注入每日估值数据…")
    val = _load_valuation_panel(db, symbols, df)
    if val.empty:
        # 无每日估值数据 → 快照广播（历史行为）。此时 PE/PB 在整个回测期恒定，
        # 依赖估值条件的策略（如"低估值高股息龙头"）将无法在估值变化时触发卖出，
        # 表现为"买入/卖出日期相同（从头持有到尾）"。给出醒目告警便于排查。
        logger.warning(
            "⚠️ stock_daily_basic 无数据（可能未启用每日估值同步），回测回退到每股最新快照广播。"
            "依赖 PE/PB 的策略将不会因估值变化触发卖出，易出现全程持有。"
        )
        if not fund.empty:
            df = df.merge(fund, on="symbol", how="left", suffixes=("", "_fund"))
    else:
        # 行业仍来自快照（静态字段，无每日历史）
        if not fund.empty:
            df = df.merge(fund[["symbol", "industry"]], on="symbol",
                          how="left", suffixes=("", "_fund"))
        df = df.merge(val, on=["symbol", "date"], how="left")
        # 缺值逐 symbol 前向填充（非交易日/未同步日沿用上一估值）
        df = df.sort_values(["symbol", "date"])
        for col in ("pe_ttm", "pb", "total_mv"):
            df[col] = df.groupby("symbol")[col].ffill()
        # 仍缺失的估值列用最新快照兜底（保证列非空）
        if not fund.empty:
            snap = fund[["symbol", "total_mv", "pe_ttm", "pb"]]
            df = df.merge(snap, on="symbol", how="left", suffixes=("", "_snap"))
            for col in ("total_mv", "pe_ttm", "pb"):
                df[col] = df[col].fillna(df[f"{col}_snap"])
            df = df.drop(columns=[f"{col}_snap" for col in ("total_mv", "pe_ttm", "pb")])

    # 3) 股息指标——逐交易日内存计算（一次性加载记录，避免逐日查库）
    div_df = _load_dividend_panel(db, symbols, df, progress_cb=progress_cb)
    if not div_df.empty:
        df = df.merge(div_df, on=["symbol", "date"], how="left")
        df["div_12m_ps"] = df["div_12m_ps"].fillna(0.0)
        df["div_paying_years"] = df["div_paying_years"].fillna(0)
    else:
        df["div_12m_ps"] = 0.0
        df["div_paying_years"] = 0

    close = pd.to_numeric(df["close"], errors="coerce")
    df["div_yield"] = (df["div_12m_ps"] / close.where(close > 0)).round(4)
    return df


def _load_valuation_panel(db, symbols, df: pd.DataFrame,
                          progress_cb: Callable[[float, str], None] | None = None) -> pd.DataFrame:
    """从 stock_daily_basic 批量加载每日估值（pe_ttm/pb/total_mv），按 (symbol, date) 对齐。

    返回列: symbol, date, pe_ttm, pb, total_mv。仅返回面板日期区间内存在数据的行。
    单位约定：total_mv 为亿元（与 stock_basic_info / 策略一致）。
    性能：单次批量查询（按 code/trade_date 过滤日期区间），避免逐日逐股查库。
    """
    sym_list = [str(s) for s in symbols if s]
    if not sym_list or df.empty:
        return pd.DataFrame(columns=["symbol", "date", "pe_ttm", "pb", "total_mv"])
    dmin = str(df["date"].min())[:10]
    dmax = str(df["date"].max())[:10]
    cursor = db["stock_daily_basic"].find(
        {
            "trade_date": {"$gte": dmin, "$lte": dmax},
            "$or": [{"code": {"$in": sym_list}}, {"symbol": {"$in": sym_list}}],
        },
        {"_id": 0, "code": 1, "symbol": 1, "trade_date": 1,
         "pe_ttm": 1, "pb": 1, "total_mv": 1},
    )
    rows: list[dict] = []
    for doc in cursor:
        code = str(doc.get("code") or doc.get("symbol") or "").strip()
        trade_date = str(doc.get("trade_date") or "").strip()
        if not code or not trade_date:
            continue
        rows.append({
            "symbol": code,
            "date": trade_date[:10],
            "pe_ttm": screener._to_float(doc.get("pe_ttm")),
            "pb": screener._to_float(doc.get("pb")),
            "total_mv": screener._to_float(doc.get("total_mv")),
        })
    if not rows:
        return pd.DataFrame(columns=["symbol", "date", "pe_ttm", "pb", "total_mv"])
    return pd.DataFrame(rows)


def _load_dividend_panel(db, symbols, df: pd.DataFrame,
                         progress_cb: Callable[[float, str], None] | None = None) -> pd.DataFrame:
    """批量加载 symbols 的全部分红记录，按面板内每个交易日计算股息指标。

    返回列: date, symbol, div_12m_ps(近12个月每股现金分红), div_paying_years(近5年分红年数)。
    计算口径与 screener._load_dividend_metrics 一致，仅改为批量/逐日。

    性能：按股票分组，用"排序 + 前缀和 + 二分查找"一次性算出所有交易日的结果，
    内存与耗时均为 O(分红记录 + 股票数 × 交易日)，大幅低于 O(交易日 × 记录) 的逐日
    布尔掩码方案，避免全市场回测因内存峰值过高而触发容器 OOM。
    """
    from datetime import date as _date
    from collections import defaultdict

    sym_list = [str(s) for s in symbols]
    cursor = db["stock_dividend"].find(
        {"code": {"$in": sym_list}},
        {"_id": 0, "code": 1, "ex_date": 1, "ann_date": 1,
         "cash_div": 1, "cash_div_tax": 1},
    )
    # 按股票收集 (距今天数, 现金分红, 自然年)
    by_code: dict[str, list[tuple[int, float, int]]] = defaultdict(list)
    for doc in cursor:
        code = str(doc.get("code") or "")
        if not code:
            continue
        cash = screener._to_float(doc.get("cash_div_tax"))
        if cash is None or cash != cash:  # NaN 视为无效
            cash = screener._to_float(doc.get("cash_div"))
        if not cash or cash != cash or cash <= 0:
            continue
        date_str = str(doc.get("ex_date") or doc.get("ann_date") or "").strip()
        if len(date_str) < 8:
            continue
        try:
            dt = _date.fromisoformat(date_str[:10])
        except ValueError:
            continue
        # 用基数日(ordinal)代替 datetime，避免逐日比较的对象开销
        by_code[code].append((dt.toordinal(), cash, dt.year))

    if not by_code:
        return pd.DataFrame(columns=["date", "symbol", "div_12m_ps", "div_paying_years"])

    # 面板内交易日（升序），转成基数日与自然年数组
    dates = pd.DatetimeIndex(pd.to_datetime(pd.unique(df["date"]))).sort_values()
    panel_ord = np.array([d.toordinal() for d in dates], dtype=np.int64)  # 与分红记录 toordinal 同尺度
    panel_year = np.array([d.year for d in dates], dtype=np.int64)
    date_to_str = {int(o): d.strftime("%Y-%m-%d")
                   for o, d in zip(panel_ord, dates)}

    codes = sorted(by_code.keys())
    total = len(codes)
    frames: list[pd.DataFrame] = []
    for i, code in enumerate(codes):
        if progress_cb and (i % 5 == 0 or i == total - 1):
            progress_cb((i + 1) / total, f"正在计算股息指标（{i + 1}/{total}）…")
        rec = by_code[code]
        rec.sort(key=lambda r: r[0])
        ords = np.array([r[0] for r in rec], dtype=np.int64)
        cashs = np.array([r[1] for r in rec], dtype=np.float64)
        years = np.array([r[2] for r in rec], dtype=np.int64)

        # 前缀和：cum[k] = 前 k 条分红之和
        cum = np.concatenate([[0.0], np.cumsum(cashs)])

        # div_12m_ps：近365天(含当天)内现金分红之和
        right = np.searchsorted(ords, panel_ord, side="right")
        left = np.searchsorted(ords, panel_ord - 365, side="left")
        div12 = cum[right] - cum[left]

        # div_paying_years：近5个自然年度内有分红(现金>0)的年数
        uniq_years = np.unique(years)
        yr_right = np.searchsorted(uniq_years, panel_year, side="right")
        yr_left = np.searchsorted(uniq_years, panel_year - 5, side="right")
        dy = yr_right - yr_left

        mask = (div12 != 0) | (dy != 0)
        idx = np.nonzero(mask)[0]
        if idx.size == 0:
            continue
        frames.append(pd.DataFrame({
            "date": [date_to_str[panel_ord[j]] for j in idx],
            "symbol": code,
            "div_12m_ps": np.round(div12[idx], 4),
            "div_paying_years": dy[idx].astype(int),
        }))

    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "div_12m_ps", "div_paying_years"])
    return pd.concat(frames, ignore_index=True)


def _effective_params(strategy: dict, params: dict | None) -> dict:
    """合并调用方传入参数与策略声明的默认参数，返回有效参数 dict。

    策略在定义时声明了各参数的默认值（如 max_pe=15, max_pb=3.0）。调用方
    （前端）可能只传空 dict 或部分参数，若不合并默认值，依赖估值上限的退出
    逻辑（_entry_exit_mask）会因 params 中缺少 max_pe/max_pb 而静默失效，
    导致依赖估值条件的策略从不触发卖出（买入起点→卖出终点）。
    """
    effective: dict = {}
    for p in (strategy.get("params") or []):
        pid = p.get("id")
        if pid and "default" in p:
            effective[pid] = p["default"]
    if params:
        effective.update(params)
    return effective


def _entry_exit_mask(df: pd.DataFrame, strategy_id: str, params: dict):
    """返回 (entry_mask, exit_mask)：基于策略 filter 与退出信号。"""
    strategy = _get_strategy_map().get(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")

    # 用策略默认值合并调用方参数，确保估值上限等参数在未显式传入时仍生效
    effective = _effective_params(strategy, params)

    entry = run_strategy_filter(strategy_id, df, effective).fillna(False).astype(bool)

    exit_mask = pd.Series(False, index=df.index)

    # 策略声明的显式退出信号列
    exit_signals = strategy.get("exit_signals") or []
    if exit_signals:
        for sig in exit_signals:
            if sig in df.columns:
                exit_mask |= df[sig].fillna(False).astype(bool)

    # 估值条件退出：当策略配置了估值上限（max_pe/max_pb）且面板含每日估值列时，
    # 持仓股票 PE/PB 突破阈值即触发卖出，使"估值不再满足买入条件就卖出"得以生效。
    # 依赖 _enrich_panel_fundamentals 注入的每日历史估值（bug-020）。
    # 阈值取"合并默认值后的有效参数"，避免前端只传空 params 时估值退出被静默跳过。
    if "max_pe" in effective or "max_pb" in effective:
        max_pe = max_pb = None
        try:
            if "max_pe" in effective and "pe_ttm" in df.columns:
                max_pe = float(effective["max_pe"])
            if "max_pb" in effective and "pb" in df.columns:
                max_pb = float(effective["max_pb"])
        except (TypeError, ValueError):
            max_pe = max_pb = None
        if max_pe is not None or max_pb is not None:
            over = pd.Series(False, index=df.index)
            pe = pd.to_numeric(df.get("pe_ttm"), errors="coerce")
            pb = pd.to_numeric(df.get("pb"), errors="coerce")
            if max_pe is not None:
                over |= (pe > max_pe).fillna(False)
            if max_pb is not None:
                over |= (pb > max_pb).fillna(False)
            exit_mask |= over

    return entry, exit_mask


def _get_strategy_map():
    from app.strategy_system.strategies import _STRATEGY_MAP
    return _STRATEGY_MAP


# ──────────────────────────────────────────────────────────────
# 策略回测
# ──────────────────────────────────────────────────────────────

@dataclass
class StrategyBtConfig:
    strategy_id: str
    start: str
    end: str
    symbols: list[str] | None = None
    params: dict | None = None
    entry_fill: str = "open_t+1"   # close_t | open_t+1
    exit_fill: str = "open_t+1"    # close_t | open_t+1
    fees_pct: float = 0.0002
    slippage_bps: float = 5.0
    max_positions: int = 10
    max_exposure_pct: float = 1.0
    initial_capital: float = 1_000_000.0
    position_sizing: str = "equal"  # equal | score_weight
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_hold_days: int | None = None
    holding_days: int = 5
    as_dict: dict = None


def _pct_from_bps(bps: float) -> float:
    return bps / 10000.0


def run_strategy_backtest(db, config: StrategyBtConfig, panel: pd.DataFrame | None = None,
                          progress_cb: Callable[[float, str], None] | None = None) -> dict:
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:10]

    def _report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    def _err(msg: str) -> dict:
        return {
            "run_id": run_id,
            "success": False,
            "error": msg,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    try:
        if panel is None:
            # 按策略所需最小列集计算指标/信号，压缩全市场长区间面板内存，规避容器 OOM
            keep_columns = _strategy_required_columns(config.strategy_id)
            panel = _load_panel(db, config.as_dict or config.__dict__,
                                progress_cb=progress_cb, keep_columns=keep_columns,
                                enrich_fundamentals=_strategy_needs_fundamentals(config.strategy_id))
        # 传入的 panel 只读不复用拷贝，避免大内存下因深拷贝 OOM
    except Exception as e:
        return _err(f"数据加载失败: {e}")

    if panel.empty:
        return _err("无数据，请检查日期范围或先同步行情")

    _report(0.05, "正在计算指标与信号…")

    # 仅保留正式区间
    cfg = config.as_dict or config.__dict__
    start_s = _parse_date(cfg.get("start"))
    end_s = _parse_date(cfg.get("end"))
    formal = panel[(panel["date"] >= start_s) & (panel["date"] <= end_s)]
    if formal.empty:
        return _err("正式回测区间内无数据")

    try:
        entry, exit_mask = _entry_exit_mask(panel, config.strategy_id, config.params or {})
    except Exception as e:
        return _err(str(e))

    if not entry[formal.index].any():
        return _err("在指定区间内未产生买入信号")

    _report(0.10, "正在计算评分…")

    # 评分
    strategy = _get_strategy_map().get(config.strategy_id)
    scoring = strategy.get("scoring", {}) if strategy else {}
    scores = _score_series(panel, scoring)

    sim = _simulate_portfolio(
        panel, entry, exit_mask, scores, config,
        start_s, end_s, db,
        progress_cb=progress_cb,
    )
    if sim is None:
        return _err("回测模拟失败")

    _report(0.98, "正在生成报告…")

    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "run_id": run_id,
        "success": True,
        "config": {
            "strategy_id": config.strategy_id,
            "start": start_s,
            "end": end_s,
            "entry_fill": config.entry_fill,
            "exit_fill": config.exit_fill,
            "fees_pct": config.fees_pct,
            "slippage_bps": config.slippage_bps,
            "max_positions": config.max_positions,
            "initial_capital": config.initial_capital,
            "position_sizing": config.position_sizing,
        },
        "stats": sim["stats"],
        "equity_curve": sim["equity_curve"],
        "drawdown_curve": sim["drawdown_curve"],
        "benchmark_curve": sim["benchmark_curve"],
        "trades": sim["trades"],
        "per_symbol_stats": sim["per_symbol_stats"],
        "strategy_info": {
            "id": strategy["id"] if strategy else config.strategy_id,
            "name": strategy["name"] if strategy else config.strategy_id,
            "description": strategy["description"] if strategy else "",
            "entry_signals": strategy.get("entry_signals", []) if strategy else [],
            "exit_signals": strategy.get("exit_signals", []) if strategy else [],
        },
        "elapsed_ms": elapsed,
    }


def _score_series(df: pd.DataFrame, scoring: dict) -> pd.Series:
    scores = pd.Series(0.0, index=df.index)
    if not scoring:
        return scores
    executable = [(c, float(w)) for c, w in scoring.items() if w and c in df.columns]
    if not executable:
        return scores
    total = sum(w for _, w in executable)
    if total <= 0:
        return scores
    for col, w in executable:
        val = pd.to_numeric(df[col], errors="coerce")
        valid = val.notna()
        if valid.any():
            col_min, col_max = val[valid].min(), val[valid].max()
            rng = col_max - col_min
            norm = pd.Series(0.5, index=df.index)
            if rng > 0:
                norm = (val - col_min) / rng
            norm = norm.where(valid, 0.0)
        else:
            norm = pd.Series(0.0, index=df.index)
        scores += norm * (w / total)
    return scores * 100


def _build_name_map(panel: pd.DataFrame, db) -> dict[str, str]:
    """构建 symbol -> 股票名称 映射，供回测交易明细展示"名称"列。

    优先取面板自带 name 列（若存在）；否则回退从 stock_basic_info 按代码补齐。
    面板通常不含 name 列（data_adapter PANEL_COLUMNS 无 name），若不回退，
    交易明细的名称列会全部为空。
    """
    name_map: dict[str, str] = {}
    if "name" in panel.columns:
        for sym, g in panel.groupby("symbol", sort=False):
            nm = g["name"].dropna()
            if not nm.empty:
                name_map[str(sym)] = str(nm.iloc[0])
    if not name_map:
        try:
            name_map = screener._stock_name_map(db)
        except Exception:  # noqa: BLE001
            name_map = {}
    return name_map


def _shift_signal_to_execute(sig: pd.Series, panel: pd.DataFrame) -> pd.Series:
    """将"收盘信号"按每只股票的时间序列后移一个交易日，得到"执行日"信号。

    回测撮合在"当日开盘"成交。若直接用当日收盘产生的信号（如 RSI、MA 金叉、
    MA 死叉，均依赖当日 close）在当日开盘买入/卖出，属于未来函数——开盘时
    无法预知当日收盘，会系统性高估收益（超跌反弹等反转策略体现得最明显）。

    open_t+1 的正确语义：T 日收盘产生的信号，应在 T+1 日开盘执行。本函数把
    (symbol, T) 的信号平移到 (symbol, T 的下一个交易日)，使撮合循环在当日开盘
    用到的信号全部来自"前一个交易日"。
    """
    tmp = pd.DataFrame({
        "symbol": panel["symbol"].to_numpy(),
        "date": panel["date"].to_numpy(),
        "v": sig.to_numpy().astype(np.int8),
    })
    tmp.sort_values(["symbol", "date"], inplace=True)
    exec_v = tmp.groupby("symbol")["v"].shift(1).fillna(0).astype(bool)
    tmp["exec"] = exec_v.to_numpy()
    tmp.sort_index(inplace=True)  # 恢复与原面板一致的行序
    return pd.Series(tmp["exec"].to_numpy(), index=sig.index)


def _simulate_portfolio(panel, entry, exit_mask, scores, config, start_s, end_s, db,
                        progress_cb: Callable[[float, str], None] | None = None):
    """逐日组合模拟。返回 dict 含 stats/equity_curve/drawdown/trades/per_symbol."""
    df = panel
    dates = sorted(df["date"].unique())
    # 加入 warmup 数据但只从 start_s 开始撮合
    sim_dates = [d for d in dates if start_s <= d <= end_s]
    if not sim_dates:
        return None
    total_days = len(sim_dates)

    # open_t+1：T 日收盘信号 → T+1 日开盘执行。把信号后移一个交易日，
    # 消除"用当日收盘信号在当日开盘成交"的未来函数（见 _shift_signal_to_execute）。
    if config.entry_fill == "open_t+1":
        entry = _shift_signal_to_execute(entry, panel)
    if config.exit_fill == "open_t+1":
        exit_mask = _shift_signal_to_execute(exit_mask, panel)

    df = df.set_index(["symbol", "date"])
    entry = entry.set_axis(df.index)
    exit_mask = exit_mask.set_axis(df.index)
    scores = scores.set_axis(df.index)

    cash = float(config.initial_capital)
    positions: dict[str, dict] = {}  # symbol -> holding info
    trades: list[dict] = []
    equity_curve: list[dict] = []

    fees_pct = config.fees_pct
    slippage = _pct_from_bps(config.slippage_bps)
    max_positions = max(config.max_positions, 1)
    max_exposure = config.max_exposure_pct

    # 预计算 close / name 查找表，避免逐日全表扫描（大幅提速）
    close_series: dict[str, tuple] = {}
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date")
        close_series[sym] = (g["date"].to_numpy(), g["close"].to_numpy(dtype=float))
    name_map = _build_name_map(panel, db)

    def _fast_last_close(sym, d):
        """返回 sym 在 <= d 的最近收盘价（用二分加速）。"""
        if sym not in close_series:
            return None
        dates, closes = close_series[sym]
        i = bisect_right(dates, d) - 1
        if i < 0:
            return None
        c = closes[i]
        return float(c) if np.isfinite(c) else None

    def _fast_name(sym):
        return name_map.get(sym, "")

    def _price_for(row, kind, fill):
        px = row.get("open") if fill == "open_t+1" else row.get("close")
        if px is None or pd.isna(px) or px <= 0:
            return None
        if kind == "buy":
            return float(px) * (1 + slippage)
        return float(px) * (1 - slippage)

    for idx, d in enumerate(sim_dates):
        if progress_cb and (idx % 10 == 0 or idx == total_days - 1):
            progress_cb(0.10 + 0.85 * (idx + 1) / total_days, f"正在撮合回测（{idx + 1}/{total_days} 个交易日）…")
        day_syms = df.index.get_level_values(0)[df.index.get_level_values(1) == d]
        day_syms = list(dict.fromkeys(day_syms))
        day = df.xs(d, level="date") if d in df.index.get_level_values(1) else pd.DataFrame()

        # 1) 卖出：exit 信号 / 止损 / 止盈 / 最大持有
        for sym in list(positions.keys()):
            pos = positions[sym]
            if sym not in day.index:
                continue
            row = day.loc[sym]
            exit_reason = None
            if exit_mask.loc[(sym, d)]:
                exit_reason = "exit_signal"
            elif config.stop_loss_pct is not None and row.get("low") is not None and pd.notna(row["low"]):
                stop_price = pos["entry_price"] * (1 - config.stop_loss_pct)
                if float(row["low"]) <= stop_price:
                    exit_reason = "stop_loss"
            elif config.take_profit_pct is not None and row.get("high") is not None and pd.notna(row["high"]):
                tp_price = pos["entry_price"] * (1 + config.take_profit_pct)
                if float(row["high"]) >= tp_price:
                    exit_reason = "take_profit"
            elif config.max_hold_days is not None:
                hold_days = _trading_days_between(pos["entry_date"], d, dates)
                if hold_days >= config.max_hold_days:
                    exit_reason = "max_hold"

            if exit_reason is None:
                continue

            # 成交价：止损/止盈是盘中触发（用当日 low/high 判定），应在触发价位成交，
            # 而非当日开盘价——否则等于"已知当日最低/最高价后，用更早的开盘价成交"，
            # 同样是未来函数且对止损/止盈都系统性有利。
            # exit_signal / max_hold 则按配置口径：open_t+1 → 当日开盘（信号来自前一日）。
            if exit_reason == "stop_loss":
                px = stop_price * (1 - slippage)
            elif exit_reason == "take_profit":
                px = tp_price * (1 - slippage)
            else:
                px = _price_for(row, "sell", config.exit_fill)
            if px is None or px <= 0:
                continue
            proceeds = pos["shares"] * px * (1 - fees_pct)
            cash += proceeds
            pnl_amount = proceeds - pos["entry_value"]
            pnl_pct = pnl_amount / pos["entry_value"] if pos["entry_value"] else 0.0
            trades.append({
                "symbol": sym,
                "name": _fast_name(sym),
                "entry_date": pos["entry_date"],
                "exit_date": d,
                "entry_price": round(pos["entry_price"], 4),
                "exit_price": round(px, 4),
                "shares": pos["shares"],
                "entry_value": round(pos["entry_value"], 2),
                "exit_value": round(proceeds, 2),
                "pnl_amount": round(pnl_amount, 2),
                "pnl_pct": round(pnl_pct, 4),
                "duration": _trading_days_between(pos["entry_date"], d, dates),
                "exit_reason": exit_reason,
                "entry_score": pos.get("entry_score"),
                "position_pct": pos.get("position_pct"),
            })
            del positions[sym]

        # 2) 买入：entry 信号
        if len(positions) < max_positions:
            entry_syms = [s for s in day_syms if entry.loc[(s, d)] and s not in positions]
            if entry_syms:
                # 按 score 排序
                entry_syms_sorted = sorted(entry_syms, key=lambda s: -(scores.loc[(s, d)] if (s, d) in scores.index else 0))
                available = max_positions - len(positions)
                for sym in entry_syms_sorted[:available]:
                    row = day.loc[sym]
                    px = _price_for(row, "buy", config.entry_fill)
                    if px is None:
                        continue
                    equity_now = cash + sum(
                        pos["shares"] * _fast_last_close(s, d) for s, pos in positions.items()
                    )
                    slot_value = equity_now * max_exposure / max_positions
                    if config.position_sizing == "score_weight":
                        sc = scores.loc[(sym, d)] if (sym, d) in scores.index else 0.0
                        slot_value = slot_value * (0.5 + sc / 100.0)
                    slot_value = max(slot_value, 0.0)
                    shares = int(slot_value / px / 100) * 100
                    if shares <= 0:
                        continue
                    cost = shares * px * (1 + fees_pct)
                    if cost > cash:
                        continue
                    cash -= cost
                    positions[sym] = {
                        "shares": shares,
                        "entry_price": px,
                        "entry_value": cost,
                        "entry_date": d,
                        "entry_score": round(float(scores.loc[(sym, d)] if (sym, d) in scores.index else 0), 2),
                        "position_pct": round(min(slot_value / equity_now, 1.0), 4) if equity_now else 0.0,
                        "duration": 0,
                        "entry_sim_idx": len(sim_dates[:sim_dates.index(d) + 1]) - 1,
                    }

        # 3) 估值
        equity = cash
        for s, pos in positions.items():
            close = _fast_last_close(s, d)
            if close is not None:
                equity += pos["shares"] * close
        equity_curve.append({"date": d, "value": round(equity, 2), "positions": len(positions)})

    # 期末强制平仓：以最后交易日的收盘价为平仓成交价（含卖出滑点），
    # 与盘中卖出 _price_for(..., "sell", ...) 口径一致；若取不到最后收盘价则跳过该笔。
    last_d = sim_dates[-1]
    for sym in list(positions.keys()):
        pos = positions[sym]
        last_close = _fast_last_close(sym, last_d)
        if last_close is None:
            continue
        px = last_close * (1 - slippage)
        proceeds = pos["shares"] * px * (1 - fees_pct)
        cash += proceeds
        trades.append({
            "symbol": sym,
            "name": _fast_name(sym),
            "entry_date": pos["entry_date"],
            "exit_date": last_d,
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(px, 4),
            "shares": pos["shares"],
            "entry_value": round(pos["entry_value"], 2),
            "exit_value": round(proceeds, 2),
            "pnl_amount": round(proceeds - pos["entry_value"], 2),
            "pnl_pct": round((proceeds - pos["entry_value"]) / pos["entry_value"] if pos["entry_value"] else 0, 4),
            "duration": _trading_days_between(pos["entry_date"], last_d, dates),
            "exit_reason": "end",
            "entry_score": pos.get("entry_score"),
            "position_pct": pos.get("position_pct"),
        })
    del positions

    stats = _compute_stats(equity_curve, trades, config.initial_capital)
    benchmark_curve = _build_benchmark(db, start_s, end_s)
    dd_curve = _drawdown_curve(equity_curve)
    per_symbol = _per_symbol_stats(trades)
    return {
        "stats": stats,
        "equity_curve": equity_curve,
        "drawdown_curve": dd_curve,
        "benchmark_curve": benchmark_curve,
        "trades": trades,
        "per_symbol_stats": per_symbol,
    }


def _trading_days_between(start, end, all_dates):
    try:
        return all_dates.index(end) - all_dates.index(start)
    except ValueError:
        return 0


def _drawdown_curve(equity_curve):
    peak = -np.inf
    out = []
    for pt in equity_curve:
        peak = max(peak, pt["value"])
        dd = (pt["value"] - peak) / peak if peak > 0 else 0.0
        out.append({"date": pt["date"], "value": round(dd, 4)})
    return out


def _compute_stats(equity_curve, trades, initial_capital):
    if not equity_curve:
        return {}
    values = np.array([pt["value"] for pt in equity_curve], dtype=float)
    total_return = values[-1] / initial_capital - 1
    n_days = len(values)
    years = n_days / 252.0 if n_days else 0.0
    annual_return = (values[-1] / initial_capital) ** (1 / years) - 1 if years > 0 and values[-1] > 0 else 0.0
    daily_rets = np.diff(values) / values[:-1]
    sharpe = float(daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if daily_rets.size > 1 and daily_rets.std() > 0 else 0.0
    peak = np.maximum.accumulate(values)
    drawdown = (values - peak) / peak
    max_drawdown = float(drawdown.min()) if drawdown.size else 0.0

    pnl = np.array([t["pnl_amount"] for t in trades], dtype=float) if trades else np.array([])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    win_rate = float(wins.size / pnl.size) if pnl.size else 0.0
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = abs(float(losses.mean())) if losses.size else 0.0
    profit_factor = (avg_win / avg_loss) if avg_loss > 0 else (None if wins.size == 0 else float("inf"))

    return {
        "total_return": round(float(total_return), 4),
        "annual_return": round(float(annual_return), 4),
        "max_drawdown": round(max_drawdown, 4),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 4),
        "profit_factor": (round(profit_factor, 2) if profit_factor is not None and np.isfinite(profit_factor) else None),
        "n_trades": int(len(trades)),
        "n_days": int(n_days),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "best": round(float(pnl.max()), 2) if pnl.size else 0.0,
        "worst": round(float(pnl.min()), 2) if pnl.size else 0.0,
    }


def _per_symbol_stats(trades):
    by_sym: dict[str, list] = {}
    for t in trades:
        by_sym.setdefault(t["symbol"], []).append(t)
    out = []
    for sym, ts in by_sym.items():
        pnl = np.array([t["pnl_amount"] for t in ts], dtype=float)
        total = sum(t["pnl_amount"] for t in ts)
        wins = pnl[pnl > 0]
        out.append({
            "symbol": sym,
            "name": ts[0]["name"],
            "n_trades": len(ts),
            "win_rate": round(float(wins.size / pnl.size), 4) if pnl.size else 0.0,
            "total_pnl": round(float(total), 2),
            "avg_pnl": round(float(pnl.mean()), 2) if pnl.size else 0.0,
        })
    return sorted(out, key=lambda x: -x["total_pnl"])


def _build_benchmark(db, start_s, end_s):
    """以上证指数（000001.SH）作为基准。

    优先从 stock_daily_quotes 读取指数日线（须用带交易所后缀的指数代码）；
    若库中无指数历史数据，则回退到 AKShare 实时拉取上证指数日线后再按区间截取。

    注意：绝不能用裸代码 "000001" 查询——库中该代码对应的是平安银行（000001.SZ），
    会把个股价格误当成上证指数（历史上曾因此把基准画成 ~11 元而非 ~3900 点）。
    """
    # 库中指数代码候选（仅带交易所后缀，避免命中股票 000001.SZ）
    index_codes = ["000001.SH", "sh000001", "000001.XSHG"]
    try:
        collection = db["stock_daily_quotes"]
        query = {
            "period": "daily",
            "trade_date": {"$gte": start_s, "$lte": end_s},
            "$or": [
                {"code": {"$in": index_codes}},
                {"symbol": {"$in": index_codes}},
            ],
        }
        rows = list(collection.find(query, {"_id": 0, "trade_date": 1, "close": 1}).sort("trade_date", 1))
        out = []
        seen = set()
        for r in rows:
            close = r.get("close")
            if close is None:
                continue
            d = r.get("trade_date", "")
            # 同一交易日可能因指数以多种代码存储（000001.SH / sh000001 / 000001.XSHG）
            # 而命中多条记录，按日期去重，避免净值曲线出现重叠/双线
            if d in seen:
                continue
            seen.add(d)
            out.append({
                "date": d,
                "value": round(float(close), 4),
                "close": round(float(close), 4),
                "name": "上证指数",
                "symbol": "000001.SH",
            })
        if out:
            return out
    except Exception as e:
        logger.warning("加载基准失败: %s", e)

    # 库中无指数数据 → 回退 AKShare 拉取上证指数历史日线
    return _benchmark_from_akshare(start_s, end_s)


def _benchmark_from_akshare(start_s, end_s):
    """通过 AKShare 拉取上证指数历史日线并按回测区间截取。"""
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
            logger.warning("AKShare 上证指数数据为空")
            return []
        df = df[(df["date"].astype(str) >= start_s) & (df["date"].astype(str) <= end_s)]
        df = df.sort_values("date")
        out = []
        for _, row in df.iterrows():
            try:
                close = float(row["close"])
            except (TypeError, ValueError):
                continue
            out.append({
                "date": str(row["date"])[:10],
                "value": round(close, 4),
                "close": round(close, 4),
                "name": "上证指数",
                "symbol": "000001.SH",
            })
        return out
    except Exception as e:
        logger.warning("AKShare 拉取基准失败: %s", e)
        return []


# ──────────────────────────────────────────────────────────────
# 因子回测
# ──────────────────────────────────────────────────────────────

def run_factor_backtest(db, config: dict, progress_cb: Callable[[float, str], None] | None = None) -> dict:
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:10]
    factor_name = config.get("factor_name")
    start_s = _parse_date(config.get("start"))
    end_s = _parse_date(config.get("end"))
    n_groups = int(config.get("n_groups", 5))
    rebalance = config.get("rebalance", "monthly")

    def _report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    def _err(msg):
        return {"run_id": run_id, "success": False, "error": msg,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    try:
        panel = _load_panel(db, config)
    except Exception as e:
        return _err(f"数据加载失败: {e}")
    if panel.empty:
        return _err("无数据")

    formal = panel[(panel["date"] >= start_s) & (panel["date"] <= end_s)]
    if formal.empty:
        return _err("正式区间内无数据")
    if factor_name not in formal.columns:
        return _err(f"因子 {factor_name} 未在数据中（需先计算指标）")

    # 逐日因子分层
    _report(0.4, "正在计算分组收益…")
    group_returns = _compute_group_returns(formal, factor_name, n_groups, rebalance)
    _report(0.7, "正在计算 IC/IR…")
    ic, ir = _compute_ic_ir(formal, factor_name)
    long_short = _compute_long_short(formal, factor_name, n_groups, rebalance)

    _report(1.0, "完成")

    return {
        "run_id": run_id,
        "success": True,
        "config": {
            "factor_name": factor_name,
            "start": start_s,
            "end": end_s,
            "n_groups": n_groups,
            "rebalance": rebalance,
        },
        "stats": {
            "ic_mean": round(float(ic.mean()), 4) if len(ic) else 0.0,
            "ic_std": round(float(ic.std()), 4) if len(ic) else 0.0,
            "ic_ir": round(float(ir), 4) if ir is not None else 0.0,
            "ic_positive_ratio": round(float((ic > 0).mean()), 4) if len(ic) else 0.0,
            "n_days": int(len(ic)),
        },
        "ic_series": [{"date": d, "value": round(float(v), 4)} for d, v in ic.items()],
        "group_returns": group_returns,
        "long_short": long_short,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def _compute_ic_ir(df, factor_name):
    dates = sorted(df["date"].unique())
    sym_close_map = _build_sym_close(df)
    ic_series = []
    for d in dates:
        day = df[df["date"] == d]
        if len(day) < 5:
            continue
        f = pd.to_numeric(day[factor_name], errors="coerce")
        # 未来5日收益
        ret = _forward_return(sym_close_map, d, 5)
        m = f.notna() & ret.notna()
        if m.sum() < 5:
            continue
        corr = np.corrcoef(f[m], ret[m])
        if np.isfinite(corr[0, 1]):
            ic_series.append(corr[0, 1])
    ic = pd.Series(ic_series)
    if len(ic) == 0:
        return pd.Series(dtype=float), 0.0
    ir = float(ic.mean() / ic.std()) if ic.std() > 0 else 0.0
    return ic, ir


def _build_sym_close(df):
    """预计算 每symbol 的 (date升序, close) 数组，供快速前向收益计算。"""
    m: dict[str, tuple] = {}
    for sym, g in df.groupby("symbol", sort=False):
        g = g.sort_values("date")
        m[sym] = (g["date"].to_numpy(), g["close"].to_numpy(dtype=float))
    return m


def _forward_return(sym_close_map, d, horizon):
    """返回各 symbol 从 d 起往后 horizon 个交易日的收益率（用二分加速）。"""
    out = {}
    for sym, (dates, closes) in sym_close_map.items():
        i = bisect_right(dates, d) - 1
        if i < 0 or dates[i] != d:
            continue  # 该日无该 symbol 数据
        j = i + horizon
        if j >= len(closes):
            continue
        c0, c1 = closes[i], closes[j]
        if np.isfinite(c0) and np.isfinite(c1) and c0 > 0:
            out[sym] = c1 / c0 - 1
    return pd.Series(out)


def _compute_group_returns(df, factor_name, n_groups, rebalance):
    # 简化：按每期分组，计算各组的未来收益均值
    dates = sorted(df["date"].unique())
    sym_close_map = _build_sym_close(df)
    groups = {f"G{i+1}": [] for i in range(n_groups)}
    for d in dates:
        day = df[df["date"] == d]
        if len(day) < n_groups * 2:
            continue
        f = pd.to_numeric(day[factor_name], errors="coerce")
        valid = day[f.notna()]
        if valid.empty:
            continue
        rets = _forward_return(sym_close_map, d, 5)
        valid = valid[valid["symbol"].isin(rets.index)]
        if valid.empty:
            continue
        q = pd.qcut(valid[factor_name].rank(method="first"), n_groups, labels=False)
        for i in range(n_groups):
            syms = valid[q == i]["symbol"]
            g_ret = np.mean([rets[s] for s in syms if s in rets.index])
            if np.isfinite(g_ret):
                groups[f"G{i+1}"].append(g_ret)
    out = []
    for g, vals in groups.items():
        if not vals:
            continue
        arr = np.array(vals)
        out.append({
            "group": g,
            "avg_return": round(float(arr.mean()), 4),
            "cum_return": round(float(np.prod(1 + arr) - 1), 4),
            "n_days": int(len(arr)),
        })
    return out


def _compute_long_short(df, factor_name, n_groups, rebalance):
    group_returns = _compute_group_returns(df, factor_name, n_groups, rebalance)
    if len(group_returns) < 2:
        return {"avg_return": 0.0, "cum_return": 0.0, "n_days": 0}
    top = group_returns[0]["avg_return"]
    bottom = group_returns[-1]["avg_return"]
    ls = top - bottom
    return {"avg_return": round(ls, 4), "cum_return": round(ls, 4)}


# ──────────────────────────────────────────────────────────────
# 参数优化
# ──────────────────────────────────────────────────────────────

def run_optimizer(db, config: dict, panel: pd.DataFrame | None = None,
                  progress_cb: Callable[[float, str], None] | None = None) -> dict:
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:10]
    strategy_id = config.get("strategy_id")
    objective = config.get("objective", "total_return")
    param_grid = config.get("param_grid") or {}

    def _report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    def _err(msg):
        return {"run_id": run_id, "success": False, "error": msg,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    strategy = _get_strategy_map().get(strategy_id)
    if strategy is None:
        return _err(f"未知策略: {strategy_id}")

    # 只加载一次 panel，各参数组合复用，避免重复全市场指标计算
    if panel is None:
        try:
            panel = _load_panel(db, config)
        except Exception as e:
            return _err(f"数据加载失败: {e}")
        if panel.empty:
            return _err("无数据")

    _report(0.05, "正在构建参数组合…")

    # 构建参数组合
    keys = list(param_grid.keys())
    combos = []
    if keys:
        values = [param_grid[k] if isinstance(param_grid[k], list) else [param_grid[k]] for k in keys]
        for combo in itertools.product(*values):
            combos.append(dict(zip(keys, combo, strict=True)))
    else:
        combos.append({})

    if not combos:
        return _err("参数网格为空")

    n_combos = len(combos)
    results = []
    for i, params in enumerate(combos):
        def _inner(p: float, msg: str, _i: int = i) -> None:
            _report(0.05 + 0.90 * (_i + p) / n_combos, msg)
        bt = run_strategy_backtest(db, StrategyBtConfig(
            strategy_id=strategy_id,
            start=config.get("start"),
            end=config.get("end"),
            symbols=config.get("symbols"),
            params=params,
            entry_fill=config.get("entry_fill", "open_t+1"),
            exit_fill=config.get("exit_fill", "open_t+1"),
            fees_pct=float(config.get("fees_pct", 0.0002)),
            slippage_bps=float(config.get("slippage_bps", 5.0)),
            max_positions=int(config.get("max_positions", 10)),
            initial_capital=float(config.get("initial_capital", 1_000_000)),
            position_sizing=config.get("position_sizing", "equal"),
            stop_loss_pct=config.get("stop_loss_pct"),
            take_profit_pct=config.get("take_profit_pct"),
            max_hold_days=config.get("max_hold_days"),
            holding_days=int(config.get("holding_days", 5)),
            as_dict=config,
        ), panel=panel, progress_cb=_inner)
        _report(0.05 + 0.90 * (i + 1) / n_combos, f"已完成参数组合 {i + 1}/{n_combos}")
        if bt.get("success"):
            stats = bt["stats"]
            objective_value = stats.get(objective, 0.0)
            results.append({
                "params": params,
                "objective": objective,
                "value": objective_value if objective_value is not None else 0.0,
                "stats": stats,
            })

    results.sort(key=lambda x: -(x["value"] if isinstance(x["value"], (int, float)) else 0.0))
    return {
        "run_id": run_id,
        "success": True,
        "config": {
            "strategy_id": strategy_id,
            "objective": objective,
            "param_grid": param_grid,
            "start": config.get("start"),
            "end": config.get("end"),
        },
        "n_trials": len(results),
        "results": results,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


# ──────────────────────────────────────────────────────────────
# 步进优化
# ──────────────────────────────────────────────────────────────

def run_walkforward(db, config: dict,
                    progress_cb: Callable[[float, str], None] | None = None) -> dict:
    t0 = time.perf_counter()
    run_id = uuid.uuid4().hex[:10]
    strategy_id = config.get("strategy_id")
    start_s = _parse_date(config.get("start"))
    end_s = _parse_date(config.get("end"))
    train_days = int(config.get("train_days", 120))
    test_days = int(config.get("test_days", 30))
    param_grid = config.get("param_grid") or {}

    def _report(p: float, msg: str) -> None:
        if progress_cb:
            progress_cb(p, msg)

    def _err(msg):
        return {"run_id": run_id, "success": False, "error": msg,
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1)}

    strategy = _get_strategy_map().get(strategy_id)
    if strategy is None:
        return _err(f"未知策略: {strategy_id}")

    # 构建交易日序列
    try:
        panel = _load_panel(db, config)
    except Exception as e:
        return _err(f"数据加载失败: {e}")
    if panel.empty:
        return _err("无数据")
    all_dates = sorted(panel["date"].unique())
    formal_dates = [d for d in all_dates if start_s <= d <= end_s]
    if len(formal_dates) < train_days + test_days:
        return _err(f"交易日不足：需至少 {train_days + test_days} 天，当前 {len(formal_dates)} 天")

    folds = []
    for i in range(0, len(formal_dates) - train_days - test_days + 1, test_days):
        train_end = formal_dates[i + train_days - 1]
        test_start = formal_dates[i + train_days]
        test_end = formal_dates[min(i + train_days + test_days - 1, len(formal_dates) - 1)]
        folds.append({
            "train_start": formal_dates[i],
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

    n_folds = len(folds)
    fold_results = []
    for i, fold in enumerate(folds):
        def _inner(p: float, msg: str, _i: int = i) -> None:
            _report((_i + p) / n_folds, msg)
        # 训练期：选最优参数
        train_cfg = dict(config)
        train_cfg["start"] = fold["train_start"]
        train_cfg["end"] = fold["train_end"]
        opt = run_optimizer(db, train_cfg, panel=panel, progress_cb=_inner)
        best_params = None
        if opt.get("success") and opt.get("results"):
            best_params = opt["results"][0]["params"]
        # 测试期：用最优参数回测
        test_cfg = dict(config)
        test_cfg["start"] = fold["test_start"]
        test_cfg["end"] = fold["test_end"]
        bt = run_strategy_backtest(db, StrategyBtConfig(
            strategy_id=strategy_id,
            start=test_cfg["start"],
            end=test_cfg["end"],
            symbols=config.get("symbols"),
            params=best_params or {},
            entry_fill=config.get("entry_fill", "open_t+1"),
            exit_fill=config.get("exit_fill", "open_t+1"),
            fees_pct=float(config.get("fees_pct", 0.0002)),
            slippage_bps=float(config.get("slippage_bps", 5.0)),
            max_positions=int(config.get("max_positions", 10)),
            initial_capital=float(config.get("initial_capital", 1_000_000)),
            position_sizing=config.get("position_sizing", "equal"),
            max_hold_days=config.get("max_hold_days"),
            holding_days=int(config.get("holding_days", 5)),
            as_dict=test_cfg,
        ), panel=panel)
        _report((i + 1) / n_folds, f"已完成折叠 {i + 1}/{n_folds}")
        fold_results.append({
            "train": {"start": fold["train_start"], "end": fold["train_end"]},
            "test": {"start": fold["test_start"], "end": fold["test_end"]},
            "best_params": best_params,
            "stats": bt.get("stats", {}),
            "success": bt.get("success", False),
            "error": bt.get("error"),
        })

    _report(1.0, "完成")

    # 汇总测试期表现
    test_total_returns = [f["stats"].get("total_return", 0) for f in fold_results if f.get("success")]
    avg_test_return = float(np.mean(test_total_returns)) if test_total_returns else 0.0
    return {
        "run_id": run_id,
        "success": True,
        "config": {
            "strategy_id": strategy_id,
            "start": start_s,
            "end": end_s,
            "train_days": train_days,
            "test_days": test_days,
            "param_grid": param_grid,
        },
        "n_folds": len(fold_results),
        "avg_test_return": round(avg_test_return, 4),
        "folds": fold_results,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
    }