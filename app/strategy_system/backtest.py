"""回测引擎 — 移植自 tickflow-stock-panel 的 backtest 模块（pandas/numpy 实现）。

包含四个模块：
- 策略回测 (strategy)：按策略信号构建组合逐日撮合，输出净值/回撤/交易/指标。
- 因子回测 (factor)：IC/IR、分层收益、多空组合。
- 参数优化 (optimizer)：网格搜索参数组合，以目标函数排序。
- 步进优化 (walkforward)：滚动训练/测试窗口，评估参数稳健性。

数据来源：MongoDB stock_daily_quotes（经 data_adapter 加载）。
"""
from __future__ import annotations

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
from app.strategy_system.indicators import compute_all
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


def _load_panel(db, config, end_extra_days: int = 0) -> pd.DataFrame:
    """加载回测区间 + warmup 历史，并计算指标/信号。"""
    start = _parse_date(config.get("start"))
    end = _parse_date(config.get("end"))
    end_dt = pd.to_datetime(end)
    start_dt = pd.to_datetime(start) - pd.Timedelta(days=WARMUP_DAYS)
    load_end = end_dt + pd.Timedelta(days=end_extra_days)

    symbols = config.get("symbols")
    df = data_adapter.load_daily_panel(
        db, symbols, start_dt, load_end.strftime("%Y-%m-%d")
    )
    if df.empty:
        return df
    df = compute_all(df)
    # compute_all 会把 date 转为 datetime64，统一转回字符串便于下游字符串比较
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df


def _entry_exit_mask(df: pd.DataFrame, strategy_id: str, params: dict):
    """返回 (entry_mask, exit_mask)：基于策略 filter 与退出信号。"""
    strategy = _get_strategy_map().get(strategy_id)
    if strategy is None:
        raise ValueError(f"未知策略: {strategy_id}")

    entry = run_strategy_filter(strategy_id, df, params).fillna(False).astype(bool)

    exit_signals = strategy.get("exit_signals") or []
    exit_mask = pd.Series(False, index=df.index)
    if exit_signals:
        for sig in exit_signals:
            if sig in df.columns:
                exit_mask |= df[sig].fillna(False).astype(bool)

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
            panel = _load_panel(db, config.as_dict or config.__dict__)
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


def _simulate_portfolio(panel, entry, exit_mask, scores, config, start_s, end_s, db,
                        progress_cb: Callable[[float, str], None] | None = None):
    """逐日组合模拟。返回 dict 含 stats/equity_curve/drawdown/trades/per_symbol。"""
    df = panel
    dates = sorted(df["date"].unique())
    # 加入 warmup 数据但只从 start_s 开始撮合
    sim_dates = [d for d in dates if start_s <= d <= end_s]
    if not sim_dates:
        return None
    total_days = len(sim_dates)

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
    name_map: dict[str, str] = {}
    for sym, g in panel.groupby("symbol", sort=False):
        g = g.sort_values("date")
        close_series[sym] = (g["date"].to_numpy(), g["close"].to_numpy(dtype=float))
        if "name" in g.columns:
            nm = g["name"].dropna()
            if not nm.empty:
                name_map[sym] = str(nm.iloc[0])

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

            px = _price_for(row, "sell", config.exit_fill)
            if px is None:
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

    # 期末强制平仓
    for sym in list(positions.keys()):
        pos = positions[sym]
        day = df.xs(pos["entry_date"], level="date") if pos["entry_date"] in df.index.get_level_values(1) else None
        px = pos["entry_price"]
        proceeds = pos["shares"] * px * (1 - fees_pct)
        cash += proceeds
        trades.append({
            "symbol": sym,
            "name": _fast_name(sym),
            "entry_date": pos["entry_date"],
            "exit_date": sim_dates[-1],
            "entry_price": round(pos["entry_price"], 4),
            "exit_price": round(px, 4),
            "shares": pos["shares"],
            "entry_value": round(pos["entry_value"], 2),
            "exit_value": round(proceeds, 2),
            "pnl_amount": round(proceeds - pos["entry_value"], 2),
            "pnl_pct": round((proceeds - pos["entry_value"]) / pos["entry_value"] if pos["entry_value"] else 0, 4),
            "duration": _trading_days_between(pos["entry_date"], sim_dates[-1], dates),
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
    """以上证指数（000001.SH）作为基准。若数据不可用返回空。"""
    try:
        # 从 stock_daily_quotes 读取上证指数（兼容 code/symbol 两种存储）
        collection = db["stock_daily_quotes"]
        query = {
            "period": "daily",
            "trade_date": {"$gte": start_s, "$lte": end_s},
            "$or": [
                {"code": {"$in": ["000001.SH", "000001", "sh000001", "000001.XSHG"]}},
                {"symbol": {"$in": ["000001.SH", "000001", "sh000001", "000001.XSHG"]}},
            ],
        }
        rows = collection.find(
            query,
            {"_id": 0, "trade_date": 1, "close": 1},
        ).sort("trade_date", 1)
        out = []
        for r in rows:
            close = r.get("close")
            if close is None:
                continue
            out.append({
                "date": r.get("trade_date", ""),
                "value": round(float(close), 4),
                "close": round(float(close), 4),
                "name": "上证指数",
                "symbol": "000001.SH",
            })
        return out
    except Exception as e:
        logger.warning("加载基准失败: %s", e)
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