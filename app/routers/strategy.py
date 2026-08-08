"""策略系统 API — 策略筛选 + 回测（策略/因子/参数优化/步进优化）。

数据操作使用同步 MongoDB 连接，并通过线程池执行以避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import get_mongo_db_sync
from app.core.response import fail, ok
from app.strategy_system import backtest as bt
from app.strategy_system import screener
from app.strategy_system.backtest_queue import enqueue as bt_enqueue
from app.strategy_system.task_manager import make_progress_cb, task_manager

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
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
        logger.exception("批量策略筛选失败")
        return fail(f"批量策略筛选失败: {e}")


@router.get("/api/strategy/trade-dates")
async def list_trade_dates(limit: int = 30):
    """获取最近 limit 个交易日（倒序），用于前端日期选择。"""
    try:
        db = get_mongo_db_sync()
        dates = await asyncio.to_thread(screener.get_trade_dates, db, limit)
        return ok({"dates": dates})
    except Exception as e:
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
    except Exception as e:
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
    except Exception as e:
        logger.exception("因子回测失败")
        return fail(f"因子回测失败: {e}")


@router.post("/api/strategy/optimize")
async def optimize(req: OptimizeRequest):
    """参数优化。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(bt.run_optimizer, db, req.model_dump())
        return ok(result)
    except Exception as e:
        logger.exception("参数优化失败")
        return fail(f"参数优化失败: {e}")


@router.post("/api/strategy/walkforward")
async def walkforward(req: WalkForwardRequest):
    """步进优化。"""
    try:
        db = get_mongo_db_sync()
        result = await asyncio.to_thread(bt.run_walkforward, db, req.model_dump())
        return ok(result)
    except Exception as e:
        logger.exception("步进优化失败")
        return fail(f"步进优化失败: {e}")


# ──────────────────────────────────────────────────────────────
# 异步回测任务（长时计算不阻塞请求，支持前端轮询进度/恢复结果）
# ──────────────────────────────────────────────────────────────

def _build_strategy_bt_config(req: BacktestRequest) -> bt.StrategyBtConfig:
    return bt.StrategyBtConfig(
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


@router.post("/api/strategy/backtest/start")
async def strategy_backtest_start(req: BacktestRequest):
    """发起异步策略回测，立即返回 task_id。"""
    try:
        task = task_manager.create("strategy")
        task_id = task.task_id
        # 序列化为 JSON 安全的字典，投递给独立回测 Worker 进程
        request_dict = req.model_dump(mode="json")

        def _run() -> None:
            try:
                db = get_mongo_db_sync()
                cfg = _build_strategy_bt_config(BacktestRequest(**request_dict))
                result = bt.run_strategy_backtest(db, cfg, progress_cb=make_progress_cb(task_id))
                task_manager.update(task_id, status="success", result=result, progress=1.0)
            except Exception as e:
                logger.exception("策略回测任务异常")
                task_manager.update(task_id, status="failure", error=str(e))

        # 优先投递到独立回测 Worker（后端重启不会杀掉任务）；
        # Redis 不可用时回退到本地守护线程，保证功能不失效。
        if not bt_enqueue("strategy", task_id, request_dict):
            threading.Thread(target=_run, daemon=True).start()
        return ok({"task_id": task_id, "status": "running", "kind": "strategy"})
    except Exception as e:
        logger.exception("创建策略回测任务失败")
        return fail(f"创建回测任务失败: {e}")


@router.post("/api/strategy/factor/backtest/start")
async def factor_backtest_start(req: FactorBacktestRequest):
    """发起异步因子回测，立即返回 task_id。"""
    try:
        task = task_manager.create("factor")
        task_id = task.task_id
        request_dict = req.model_dump(mode="json")

        def _run() -> None:
            try:
                db = get_mongo_db_sync()
                result = bt.run_factor_backtest(db, request_dict, progress_cb=make_progress_cb(task_id))
                task_manager.update(task_id, status="success", result=result, progress=1.0)
            except Exception as e:
                logger.exception("因子回测任务异常")
                task_manager.update(task_id, status="failure", error=str(e))

        if not bt_enqueue("factor", task_id, request_dict):
            threading.Thread(target=_run, daemon=True).start()
        return ok({"task_id": task_id, "status": "running", "kind": "factor"})
    except Exception as e:
        logger.exception("创建因子回测任务失败")
        return fail(f"创建回测任务失败: {e}")


@router.post("/api/strategy/optimize/start")
async def optimize_start(req: OptimizeRequest):
    """发起异步参数优化，立即返回 task_id。"""
    try:
        task = task_manager.create("optimizer")
        task_id = task.task_id
        request_dict = req.model_dump(mode="json")

        def _run() -> None:
            try:
                db = get_mongo_db_sync()
                result = bt.run_optimizer(db, request_dict, progress_cb=make_progress_cb(task_id))
                task_manager.update(task_id, status="success", result=result, progress=1.0)
            except Exception as e:
                logger.exception("参数优化任务异常")
                task_manager.update(task_id, status="failure", error=str(e))

        if not bt_enqueue("optimizer", task_id, request_dict):
            threading.Thread(target=_run, daemon=True).start()
        return ok({"task_id": task_id, "status": "running", "kind": "optimizer"})
    except Exception as e:
        logger.exception("创建参数优化任务失败")
        return fail(f"创建回测任务失败: {e}")


@router.post("/api/strategy/walkforward/start")
async def walkforward_start(req: WalkForwardRequest):
    """发起异步步进优化，立即返回 task_id。"""
    try:
        task = task_manager.create("walkforward")
        task_id = task.task_id
        request_dict = req.model_dump(mode="json")

        def _run() -> None:
            try:
                db = get_mongo_db_sync()
                result = bt.run_walkforward(db, request_dict, progress_cb=make_progress_cb(task_id))
                task_manager.update(task_id, status="success", result=result, progress=1.0)
            except Exception as e:
                logger.exception("步进优化任务异常")
                task_manager.update(task_id, status="failure", error=str(e))

        if not bt_enqueue("walkforward", task_id, request_dict):
            threading.Thread(target=_run, daemon=True).start()
        return ok({"task_id": task_id, "status": "running", "kind": "walkforward"})
    except Exception as e:
        logger.exception("创建步进优化任务失败")
        return fail(f"创建回测任务失败: {e}")


@router.get("/api/strategy/task/{task_id}")
async def strategy_task_status(task_id: str):
    """查询回测任务状态/进度/结果。"""
    task = task_manager.get(task_id)
    if task is None:
        return fail("任务不存在或已过期", code=404)
    data: dict[str, Any] = {
        "task_id": task.task_id,
        "kind": task.kind,
        "status": task.status,
        "progress": round(task.progress, 4),
        "message": task.message,
        "elapsed_ms": int((time.time() - task.started_at) * 1000),
    }
    if task.status == "success":
        data["result"] = task.result
    if task.status == "failure":
        data["error"] = task.error
    return ok(data)