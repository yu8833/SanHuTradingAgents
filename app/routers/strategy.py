"""策略系统 API — 策略筛选 + 回测（策略/因子/参数优化/步进优化）。

数据操作使用同步 MongoDB 连接，并通过线程池执行以避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import get_mongo_db_sync
from app.core.response import ok, fail
from app.strategy_system import backtest as bt
from app.strategy_system import screener

logger = logging.getLogger(__name__)
router = APIRouter(tags=["strategy"])


# ──────────────────────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────────────────────

class StrategyRunRequest(BaseModel):
    strategy_id: str
    as_of: str | None = None
    params: dict | None = None
    limit: int = 100
    pool: list[str] | None = None


class StrategyRunAllRequest(BaseModel):
    as_of: str | None = None
    limit: int = 30
    pool: list[str] | None = None
    refresh: bool = False


class BacktestRequest(BaseModel):
    strategy_id: str
    start: str
    end: str
    symbols: list[str] | None = None
    params: dict | None = None
    entry_fill: str = "open_t+1"
    exit_fill: str = "open_t+1"
    fees_pct: float = 0.0002
    slippage_bps: float = 5.0
    max_positions: int = 10
    max_exposure_pct: float = 1.0
    initial_capital: float = 1_000_000.0
    position_sizing: str = "equal"
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_hold_days: int | None = None
    holding_days: int = 5


class FactorBacktestRequest(BaseModel):
    factor_name: str
    start: str
    end: str
    symbols: list[str] | None = None
    n_groups: int = 5
    rebalance: str = "monthly"


class OptimizeRequest(BaseModel):
    strategy_id: str
    start: str
    end: str
    symbols: list[str] | None = None
    objective: str = "total_return"
    param_grid: dict[str, list[Any]] | None = None
    entry_fill: str = "open_t+1"
    exit_fill: str = "open_t+1"
    fees_pct: float = 0.0002
    slippage_bps: float = 5.0
    max_positions: int = 10
    initial_capital: float = 1_000_000.0
    position_sizing: str = "equal"
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    max_hold_days: int | None = None
    holding_days: int = 5


class WalkForwardRequest(BaseModel):
    strategy_id: str
    start: str
    end: str
    symbols: list[str] | None = None
    train_days: int = 120
    test_days: int = 30
    param_grid: dict[str, list[Any]] | None = None
    entry_fill: str = "open_t+1"
    exit_fill: str = "open_t+1"
    fees_pct: float = 0.0002
    slippage_bps: float = 5.0
    max_positions: int = 10
    initial_capital: float = 1_000_000.0
    position_sizing: str = "equal"
    max_hold_days: int | None = None
    holding_days: int = 5


# ──────────────────────────────────────────────────────────────
# 端点
# ──────────────────────────────────────────────────────────────

@router.get("/api/strategy/list")
async def list_strategies():
    """获取策略列表（元信息）。"""
    try:
        return ok(screener.list_strategies())
    except Exception as e:  # noqa: BLE001
        logger.exception("获取策略列表失败")
        return fail(f"获取策略列表失败: {e}")


@router.post("/api/strategy/run")
async def run_strategy(req: StrategyRunRequest):
    """运行单个策略筛选。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(
            screener.run_strategy, db, req.strategy_id, req.as_of, req.params, req.limit, req.pool
        )
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("策略筛选失败")
        return fail(f"策略筛选失败: {e}")


@router.post("/api/strategy/run-all")
async def run_all_strategies(req: StrategyRunAllRequest):
    """批量运行全部策略。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(
            screener.run_all_strategies, db, req.as_of, req.limit, req.pool, req.refresh
        )
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("批量策略筛选失败")
        return fail(f"批量策略筛选失败: {e}")


@router.get("/api/strategy/trade-dates")
async def list_trade_dates(limit: int = 30):
    """获取最近 limit 个交易日（倒序），用于前端日期选择。"""
    try:
        db = get_mongo_db_sync()
        dates = await asyncio.to_thread(screener.get_trade_dates, db, limit)
        return ok({"dates": dates})
    except Exception as e:  # noqa: BLE001
        logger.exception("获取交易日列表失败")
        return fail(f"获取交易日列表失败: {e}")


@router.post("/api/strategy/backtest")
async def strategy_backtest(req: BacktestRequest):
    """策略回测。"""
    try:
        db = get_mongo_db_sync()
        cfg = bt.StrategyBtConfig(
            strategy_id=req.strategy_id,
            start=req.start,
            end=req.end,
            symbols=req.symbols,
            params=req.params,
            entry_fill=req.entry_fill,
            exit_fill=req.exit_fill,
            fees_pct=req.fees_pct,
            slippage_bps=req.slippage_bps,
            max_positions=req.max_positions,
            max_exposure_pct=req.max_exposure_pct,
            initial_capital=req.initial_capital,
            position_sizing=req.position_sizing,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
            max_hold_days=req.max_hold_days,
            holding_days=req.holding_days,
            as_dict=req.model_dump(),
        )
        result = await asyncio.to_thread(bt.run_strategy_backtest, db, cfg)
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("策略回测失败")
        return fail(f"策略回测失败: {e}")


@router.post("/api/strategy/factor/backtest")
async def factor_backtest(req: FactorBacktestRequest):
    """因子回测。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(
            bt.run_factor_backtest, db, req.model_dump()
        )
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("因子回测失败")
        return fail(f"因子回测失败: {e}")


@router.post("/api/strategy/optimize")
async def optimize(req: OptimizeRequest):
    """参数优化。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(bt.run_optimizer, db, req.model_dump())
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("参数优化失败")
        return fail(f"参数优化失败: {e}")


@router.post("/api/strategy/walkforward")
async def walkforward(req: WalkForwardRequest):
    """步进优化。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(bt.run_walkforward, db, req.model_dump())
        return ok(result)
    except Exception as e:  # noqa: BLE001
        logger.exception("步进优化失败")
        return fail(f"步进优化失败: {e}")