"""交易驾驶舱 · 方法验证（最近 N 个交易日回放）

回答一个问题：这套「左侧观察（积累区）→ 右侧确认（放量突破）」的方法，
在最近 N 个交易日里实际表现如何？

口径说明（页面必须同步展示，避免误读）：
- 全部用日线收盘价回放。突破判定 = 前一日满足入池条件 且 当日收盘 ≥ 前一日触发价
  且 当日量比（成交额 ÷ 前 5 日均成交额）≥ 2.0。
- 实盘为盘中每 15 分钟检测、盘中价触发；回放用收盘价确认，偏保守（会漏掉
  盘中突破后回落收阴的情况，也会漏掉开盘即封板无法买入的情况）。
- 入场价取突破日收盘价，不计手续费、滑点、涨跌停无法成交。
- 后续收益按持有 1/3/5 个交易日的收盘价计算；假突破 = 突破后 5 个交易日内
  任一收盘跌破触发价 2%（与持仓区「假突破」口径一致）。

性能：只计算回放所需的两列指标（振幅、20 日年化波动），全部用 groupby.rolling
向量化，不做逐股票 Python 循环——全市场约 10 秒（加载日线约 50 秒为主）。
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from app.core.database import get_mongo_db_sync
from app.strategy_system.data_adapter import get_stock_list, load_daily_panel
from app.services.cockpit.accumulation_scanner import ACCUM_DEFAULTS, _ST_TOKENS

logger = logging.getLogger(__name__)

# 日线口径的突破量比阈值（无盘中时间进度归一，全日成交额直接比）
REPLAY_VOL_RATIO = 2.0
# 假突破缓冲（与 position_service 一致）
FALSE_BUFFER = 0.02
# 回放期最多返回的交易日数上限
MAX_DAYS = 10


def _pct(new: float | None, base: float | None) -> float | None:
    if new is None or base is None or not base or not np.isfinite(new):
        return None
    return round((new / base - 1) * 100, 2)


def _f(v) -> float | None:
    """numpy 标量 → JSON 安全 float（NaN/Inf 转 None）。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _latest_daily_date(db) -> str | None:
    """stock_daily_quotes 最新交易日 → YYYY-MM-DD（兼容 YYYYMMDD 存储）。"""
    doc = db["stock_daily_quotes"].find_one(
        {"period": "daily"}, {"trade_date": 1}, sort=[("trade_date", -1)]
    )
    raw = (doc or {}).get("trade_date")
    if not raw:
        return None
    s = str(raw).replace("-", "")[:8]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else str(raw)[:10]


def _groll(series: pd.Series, sym: pd.Series, window: int, agg: str) -> pd.Series:
    """按 symbol 分组的滚动聚合（C 层实现，避免逐股票 Python 循环）。"""
    roll = series.groupby(sym, sort=False).rolling(window)
    return getattr(roll, agg)().reset_index(level=0, drop=True)


def _empty_result(days: int, end_date: str | None, note: str) -> dict:
    return {
        "days": days,
        "end_date": end_date,
        "date_range": None,
        "panel_rows": 0,
        "trigger_count": 0,
        "pool_samples": 0,
        "daily": [],
        "trades": [],
        "vol_ratio_threshold": REPLAY_VOL_RATIO,
        "note": note,
    }


def _replay_sync(end_date: str, days: int) -> dict:
    """同步重活：加载面板 → 全向量化逐日判定 → 拍平触发事件。"""
    p = ACCUM_DEFAULTS
    db = get_mongo_db_sync()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    # 250 日波动分位 + 60 日窗口 + 回放期，留足冗余
    start_dt = end_dt - timedelta(days=p["warmup_days"] + days * 2 + 40)

    df = load_daily_panel(db, symbols=None, start_dt=start_dt, end_dt=end_dt, adjust="hfq")
    if df.empty:
        return _empty_result(days, end_date, "日线数据为空，无法回放")
    df = df.reset_index(drop=True)

    sym = df["symbol"]
    close = df["close"].astype("float64")
    high = df["high"].astype("float64")
    low = df["low"].astype("float64")
    amount = df["amount"].astype("float64")
    g_close = close.groupby(sym, sort=False)
    g_high = high.groupby(sym, sort=False)

    # 只算回放所需指标（与 indicators 口径一致，省掉全量指标计算约 45s）
    prev_close = g_close.shift(1)
    amp = ((high - low) / prev_close).where(prev_close > 0)
    vol20 = (
        g_close.pct_change()
        .groupby(sym, sort=False)
        .rolling(20)
        .std()
        .reset_index(level=0, drop=True)
        * np.sqrt(252)
    )

    # ---- 入池四条件（截至当日收盘，与 accumulation_scanner 同口径） ----
    c_short_min = _groll(close, sym, p["no_new_low_short"], "min")
    c_prior_min = _groll(
        g_close.shift(p["no_new_low_short"]),
        sym,
        p["no_new_low_long"] - p["no_new_low_short"],
        "min",
    )
    ok1 = c_short_min >= c_prior_min * p["no_new_low_tolerance"]

    v_pct = (
        vol20.groupby(sym, sort=False)
        .rolling(p["vol_pctile_window"], min_periods=60)
        .rank(pct=True)
        .reset_index(level=0, drop=True)
    )
    ok2 = v_pct < p["vol_pctile_max"]

    amp_short = _groll(amp, sym, p["converge_days"], "mean")
    amp_base = _groll(amp, sym, p["converge_base_days"], "mean")
    ok3 = (amp_short / amp_base) <= p["converge_ratio_max"]

    ok4 = _groll(amount, sym, 20, "mean") >= p["min_avg_amount"]

    in_pool = (ok1 & ok2 & ok3 & ok4).fillna(False).astype(bool)

    # ---- 触发价：近 20 日高点 与 前段 40 日高点取更紧者 ----
    h_short = _groll(high, sym, p["trigger_short"], "max")
    h_prior = _groll(
        g_high.shift(p["trigger_short"]),
        sym,
        p["trigger_long"] - p["trigger_short"],
        "max",
    )
    trigger = pd.concat([h_short, h_prior], axis=1).min(axis=1)
    trigger = trigger.where(h_short.notna() & h_prior.notna())

    # ---- 当日量比（成交额 ÷ 前 5 日均额） ----
    amt5_prev = _groll(amount, sym, 5, "mean").groupby(sym, sort=False).shift(1)
    vol_ratio = amount / amt5_prev

    # ---- 前一日状态（避免未来函数） ----
    in_pool_prev = in_pool.groupby(sym, sort=False).shift(1, fill_value=False).astype(bool)
    trigger_prev = trigger.groupby(sym, sort=False).shift(1)

    # ---- 后续 1/3/5 日收益与 5 日内极值 ----
    fwd1 = g_close.shift(-1)
    fwd3 = g_close.shift(-3)
    fwd5 = g_close.shift(-5)
    future = pd.concat([g_close.shift(-k) for k in range(1, 6)], axis=1)
    fut_max = future.max(axis=1)
    fut_min = future.min(axis=1)
    bars_after = future.notna().sum(axis=1)

    # ---- 回放窗口内：池内计数 ----
    all_dates = sorted(df["date"].astype(str).unique())
    if len(all_dates) < days + 2:
        days = max(1, len(all_dates) - 2)
    replay_dates = all_dates[-days:]
    replay_set = set(replay_dates)
    in_window = df["date"].astype(str).isin(replay_set)

    # ---- 剔除 ST/退市 与 上市不足的次新（与扫描器一致） ----
    stock_list = get_stock_list(db)
    info_map = {
        str(s.get("symbol")): {
            "name": s.get("name", ""),
            "industry": s.get("ths_industry") or s.get("industry", ""),
        }
        for s in stock_list
        if s.get("symbol")
    }
    eligible = sym.map(sym.value_counts()) >= p["min_panel_rows"]
    st_codes = {
        c for c, info in info_map.items() if any(tok in (info.get("name") or "") for tok in _ST_TOKENS)
    }
    if st_codes:
        eligible &= ~sym.isin(st_codes)
    eligible_np = eligible.to_numpy(dtype=bool)

    pool_mask = (in_pool.to_numpy() & eligible_np & in_window.to_numpy())
    pool_by_date = df.loc[pool_mask, "date"].astype(str).value_counts().to_dict()

    # ---- 突破命中（收盘口径） ----
    hit = (
        in_pool_prev.to_numpy()
        & eligible_np
        & in_window.to_numpy()
        & trigger_prev.notna().to_numpy()
        & (trigger_prev.fillna(0).to_numpy() > 0)
        & (close.to_numpy() >= trigger_prev.fillna(np.inf).to_numpy())
        & vol_ratio.notna().to_numpy()
        & (vol_ratio.fillna(0).to_numpy() >= REPLAY_VOL_RATIO)
    )

    codes_np = sym.astype(str).to_numpy()
    dates_np = df["date"].astype(str).to_numpy()
    close_np = close.to_numpy()
    tp_np = trigger_prev.to_numpy()
    vr_np = vol_ratio.to_numpy()
    f1_np, f3_np, f5_np = fwd1.to_numpy(), fwd3.to_numpy(), fwd5.to_numpy()
    fmax_np, fmin_np, bars_np = fut_max.to_numpy(), fut_min.to_numpy(), bars_after.to_numpy()

    trades: list[dict] = []
    for i in np.where(hit)[0]:
        entry = float(close_np[i])
        tp = float(tp_np[i])
        fmin = fmin_np[i]
        info = info_map.get(codes_np[i]) or {}
        trades.append(
            {
                "date": dates_np[i],
                "code": codes_np[i],
                "name": info.get("name", ""),
                "industry": info.get("industry", "") or "",
                "trigger_price": round(tp, 3),
                "entry_close": round(entry, 3),
                "vol_ratio": round(float(vr_np[i]), 2),
                "ret_1d": _pct(_f(f1_np[i]), entry),
                "ret_3d": _pct(_f(f3_np[i]), entry),
                "ret_5d": _pct(_f(f5_np[i]), entry),
                "max_gain_5d": _pct(_f(fmax_np[i]), entry),
                "max_drawdown_5d": _pct(_f(fmin_np[i]), entry),
                "false_breakout": bool(np.isfinite(fmin) and fmin < tp * (1 - FALSE_BUFFER)),
                "bars_after": int(bars_np[i]),
            }
        )

    # ---- 汇总 ----
    def _avg(vals: list[float]) -> float | None:
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _win(vals: list[float]) -> float | None:
        vals = [v for v in vals if v is not None]
        return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None

    # 参照组：「只要在池就买」的假想结果（对照组，用于说明「等右侧确认」是否值得）
    pool_entry = close_np[pool_mask]
    pool_rets: dict[str, list[float | None]] = {}
    for key, fut_np in (("1d", f1_np), ("3d", f3_np), ("5d", f5_np)):
        fut = fut_np[pool_mask]
        valid = np.isfinite(fut) & np.isfinite(pool_entry) & (pool_entry > 0)
        pool_rets[key] = [round(float(r) * 100, 2) for r in (fut[valid] / pool_entry[valid] - 1)]

    r1 = [t["ret_1d"] for t in trades]
    r3 = [t["ret_3d"] for t in trades]
    r5 = [t["ret_5d"] for t in trades]
    trades.sort(key=lambda t: (t["date"], t["code"]), reverse=True)

    return {
        "days": days,
        "end_date": end_date,
        "date_range": [replay_dates[0], replay_dates[-1]] if replay_dates else None,
        "panel_rows": int(len(df)),
        "trigger_count": len(trades),
        "avg_ret_1d": _avg(r1),
        "avg_ret_3d": _avg(r3),
        "avg_ret_5d": _avg(r5),
        "win_rate_1d": _win(r1),
        "win_rate_3d": _win(r3),
        "win_rate_5d": _win(r5),
        "false_breakout_count": sum(1 for t in trades if t["false_breakout"]),
        "false_breakout_rate": round(
            sum(1 for t in trades if t["false_breakout"]) / len(trades) * 100, 1
        ) if trades else None,
        "best_5d": max((t["ret_5d"] for t in trades if t["ret_5d"] is not None), default=None),
        "worst_5d": min((t["ret_5d"] for t in trades if t["ret_5d"] is not None), default=None),
        # 参照组：池内样本（每个「日期×股票」记一条，等权），回答「不等突破直接买」会怎样
        "pool_samples": len(pool_rets["5d"]),
        "pool_avg_ret_1d": _avg(pool_rets["1d"]),
        "pool_avg_ret_3d": _avg(pool_rets["3d"]),
        "pool_avg_ret_5d": _avg(pool_rets["5d"]),
        "pool_win_rate_1d": _win(pool_rets["1d"]),
        "pool_win_rate_3d": _win(pool_rets["3d"]),
        "pool_win_rate_5d": _win(pool_rets["5d"]),
        "daily": [
            {
                "date": d,
                "pool_count": int(pool_by_date.get(d, 0)),
                "trigger_count": sum(1 for t in trades if t["date"] == d),
            }
            for d in replay_dates
        ],
        "trades": trades[:200],
        "vol_ratio_threshold": REPLAY_VOL_RATIO,
        "note": "日线收盘口径回放（收盘突破确认），实盘为盘中触发；不计手续费/滑点/涨跌停无法成交",
    }


def replay_recent(days: int = MAX_DAYS) -> dict:
    """同步入口：以日线最新交易日为终点，回放最近 days 个交易日（供线程池调用）。"""
    days = max(1, min(int(days or MAX_DAYS), MAX_DAYS))
    db = get_mongo_db_sync()
    end_date = _latest_daily_date(db)
    if not end_date:
        return _empty_result(days, None, "日线数据为空，无法回放")
    started = datetime.now()
    result = _replay_sync(end_date, days)
    result["elapsed_ms"] = int((datetime.now() - started).total_seconds() * 1000)
    return result
