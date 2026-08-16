"""流水线回测服务 — 复现系统默认三级链路：行业筛选 → 个股筛选 → 三买三卖择时。

按固定周期（默认每周）逐期重放：
  ① 行业层  get_industries(top_n, as_of=再平衡日) → 强势行业
  ② 个股层  get_industry_members + score_stocks(global_top_n, as_of) → 全局候选池
  ③ 择时层  复用 three_buys_three_sells_service.backtest，仅允许当前周期候选池内的
           股票产生新买入信号；已持仓股票不受候选池刷新影响（持仓保留，继续跑完三买三卖）。

输出：标准绩效（stats，分数口径）+ 完整净值曲线 + 交易明细 + 漏斗（全期累计）+ 再平衡排期。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger(__name__)

# 再平衡频率 → 交易日间隔
_FREQ_TRADING_DAYS = {"weekly": 5, "biweekly": 10, "monthly": 21}

# 流水线固定标识，用于「结果对比」持久化主键
PIPELINE_STRATEGY_ID = "pipeline"
PIPELINE_STRATEGY_NAME = "三买三卖回测"


def _prev_day(date_str: str) -> str:
    return (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def _build_schedule(db, start: str, end: str, freq: str, top_industries: int,
                    global_top_n: int, progress_cb: Callable[[float, str], None] | None = None):
    """逐周期计算候选池，返回再平衡排期（含每期 pool 与漏斗累计）。

    返回 (schedule, funnel)：
      schedule: [{start, end, industries, candidate_count, pool:[codes]}]
      funnel:   {industries: 去重行业数, candidates: 去重候选股数}
    """
    step = _FREQ_TRADING_DAYS.get(freq, 5)
    try:
        trading_dates = sorted([
            d for d in db["stock_daily_quotes"].distinct(
                "trade_date", {"period": "daily", "trade_date": {"$gte": start, "$lte": end}}
            ) if d
        ])
    except Exception as e:  # noqa: BLE001
        logger.warning("[pipeline] 获取回测区间交易日失败，回退为空: %s", e)
        trading_dates = []

    rebalance_dates = trading_dates[::step]
    if not rebalance_dates:
        return [], {"industries": 0, "candidates": 0}

    schedule: list[dict[str, Any]] = []
    seen_industries: set[str] = set()
    seen_codes: set[str] = set()
    total = len(rebalance_dates)

    for i, rd in enumerate(rebalance_dates):
        next_rd = rebalance_dates[i + 1] if i + 1 < len(rebalance_dates) else None
        period_end = _prev_day(next_rd) if next_rd else end

        # ① 行业层
        from app.services.candidate_pool.industry_layer import get_industries  # noqa: PLC0415
        ind_res = get_industries(top_n=top_industries, as_of=rd)
        industry_names = [x.get("industry") for x in ind_res.get("industries", []) if x.get("industry")]
        seen_industries.update(industry_names)

        # ② 个股层：收集强势行业成分 → 全局打分 Top N
        member_codes: set[str] = set()
        from app.services.candidate_pool.industry_layer import get_industry_members  # noqa: PLC0415
        for name in industry_names:
            try:
                mem = get_industry_members(name, as_of=rd)
                for it in mem.get("items", []):
                    if it.get("code"):
                        member_codes.add(str(it["code"]))
            except Exception as e:  # noqa: BLE001
                logger.warning("[pipeline] 获取行业成分失败 industry=%s as_of=%s: %s", name, rd, e)

        pool_codes: set[str] = set()
        if member_codes:
            from app.services.candidate_pool.stock_score_layer import score_stocks  # noqa: PLC0415
            try:
                scored = score_stocks(pool=sorted(member_codes), as_of=rd, limit=global_top_n)
                pool_codes = {str(it["code"]) for it in scored.get("items", []) if it.get("code")}
            except Exception as e:  # noqa: BLE001
                logger.warning("[pipeline] 全局个股打分失败 as_of=%s: %s", rd, e)
        seen_codes.update(pool_codes)

        schedule.append({
            "start": rd,
            "end": period_end,
            "industries": industry_names,
            "candidate_count": len(pool_codes),
            "pool": sorted(pool_codes),
        })

        if progress_cb:
            progress_cb(0.15 + 0.15 * (i + 1) / total, f"再平衡候选池 {i + 1}/{total}（{rd}）")

    funnel = {"industries": len(seen_industries), "candidates": len(seen_codes)}
    return schedule, funnel


async def run_pipeline_backtest(db, params: dict[str, Any] | None = None,
                                progress_cb: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    """执行流水线回测。params 见 _defaults()。"""
    start_time = time.time()
    p = dict(_defaults())
    if params:
        p.update(params)

    start = p["start"]
    end = p["end"]
    freq = p["rebalance_freq"]
    top_industries = int(p["top_industries"])
    global_top_n = int(p["global_top_n"])
    initial_capital = float(p["initial_capital"])
    max_positions = int(p["max_positions"])

    if progress_cb:
        progress_cb(0.05, "构建再平衡候选池…")

    # 构建候选池排期 + 漏斗累计
    schedule, funnel = _build_schedule(
        db, start, end, freq, top_industries, global_top_n, progress_cb=progress_cb
    )
    if not schedule:
        return {
            "success": False,
            "error": "回测区间内无候选行业/候选股，请检查数据或调整参数",
            "config": p,
            "elapsed_ms": int((time.time() - start_time) * 1000),
        }

    eligible_schedule = [
        {"start": seg["start"], "end": seg["end"], "pool": set(seg["pool"])}
        for seg in schedule
    ]

    # ③ 择时层：复用三买三卖回测，仅允许对应周期候选池建仓
    tbts_params = {
        "start_date": start,
        "end_date": end,
        "initial_capital": initial_capital,
        "top_n": global_top_n,
        "max_holdings": max_positions,
        "_eligible_schedule": eligible_schedule,
        "_full_output": True,
    }
    # 允许透传三买三卖内部参数微调（如 max_position_pct / min_score 等）
    for k, v in (p.get("tbts_overrides") or {}).items():
        tbts_params[k] = v

    if progress_cb:
        progress_cb(0.35, "运行三买三卖择时与组合模拟…")

    from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service
    svc = get_three_buys_three_sells_service()
    # 单例服务可能缓存了绑定到上一个事件循环的 Motor client（asyncio.run 每次新建/关闭 loop），
    # 重置后让其重新 get_mongo_db() 取当前 loop 的新连接，避免 "Event loop is closed"。
    svc.db = None
    raw = await svc.backtest(tbts_params)

    if progress_cb:
        progress_cb(0.95, "汇总绩效与漏斗…")

    # 汇总标准绩效（分数口径，兼容「结果对比」）
    stats = {
        "total_return": float(raw.get("total_return", 0) / 100),
        "annual_return": float(raw.get("annualized_return", 0) / 100),
        "max_drawdown": float(raw.get("max_drawdown", 0) / 100),
        "sharpe": float(raw.get("sharpe_ratio", 0)),
        "win_rate": float(raw.get("win_rate", 0) / 100),
        "profit_factor": float(raw["profit_loss_ratio"]) if raw.get("profit_loss_ratio") else None,
        "n_trades": int(raw.get("total_trades", 0)),
        "n_days": int(raw.get("backtest_days", 0)),
    }

    equity_curve = [
        {"date": d.get("date"), "value": d.get("total_value")}
        for d in raw.get("equity_curve", [])
    ]
    trades = raw.get("trades", [])
    total_signals = int(raw.get("total_signals", 0))

    # 漏斗：行业(去重) → 候选股(去重) → 买点信号(累计) → 成交(累计)
    funnel["signals"] = total_signals
    funnel["trades"] = int(stats["n_trades"])

    result = {
        "success": True,
        "config": {
            "strategy_id": PIPELINE_STRATEGY_ID,
            "strategy_name": PIPELINE_STRATEGY_NAME,
            "start": start,
            "end": end,
            "rebalance_freq": freq,
            "top_industries": top_industries,
            "global_top_n": global_top_n,
            "initial_capital": initial_capital,
            "max_positions": max_positions,
        },
        "stats": stats,
        "equity_curve": equity_curve,
        "trades": trades,
        "funnel": funnel,
        "rebalance_schedule": schedule,
        "signal_stats": raw.get("signal_stats", {}),
        "sell_reason_stats": raw.get("sell_reason_stats", {}),
        "data_contract_report": raw.get("data_contract_report", {}),
        "final_capital": raw.get("final_capital"),
        "elapsed_ms": int((time.time() - start_time) * 1000),
    }
    return result


def _defaults() -> dict[str, Any]:
    return {
        "start": None,
        "end": None,
        "rebalance_freq": "weekly",
        "top_industries": 10,
        "global_top_n": 20,
        "initial_capital": 1_000_000,
        "max_positions": 20,
        "tbts_overrides": {},
    }