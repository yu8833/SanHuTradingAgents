"""回测 Worker 进程 — 消费回测任务队列，独立于后端进程执行长时回测。

与后端 web 进程解耦：后端重启/升级/崩溃不会杀掉正在运行的回测任务。
任务状态通过 TaskManager（Redis 持久化）跨进程共享，前端可正常轮询进度/结果。

当前实现为单进程单任务串行消费（一次一个回测，其余在队列中排队），
足以满足"全市场回测约 2~4 分钟"的常规负载。
"""
from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

# 保证项目根目录可导入
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.core.database import get_mongo_db_sync
from app.core.logging_config import setup_logging
from app.strategy_system import backtest as bt
from app.strategy_system.backtest_queue import dequeue
from app.strategy_system.task_manager import make_progress_cb, task_manager

logger = logging.getLogger("backtest_worker")


def _build_strategy_bt_config(request: dict) -> "bt.StrategyBtConfig":
    """从 JSON 请求字典重建策略回测配置（与后端路由保持一致）。"""
    return bt.StrategyBtConfig(
        strategy_id=request["strategy_id"],
        start=request["start"],
        end=request["end"],
        symbols=request.get("symbols"),
        params=request.get("params"),
        entry_fill=request.get("entry_fill", "open_t+1"),
        exit_fill=request.get("exit_fill", "open_t+1"),
        fees_pct=request.get("fees_pct", 0.0002),
        slippage_bps=request.get("slippage_bps", 5.0),
        max_positions=request.get("max_positions", 10),
        max_exposure_pct=request.get("max_exposure_pct", 1.0),
        initial_capital=request.get("initial_capital", 1_000_000.0),
        position_sizing=request.get("position_sizing", "equal"),
        stop_loss_pct=request.get("stop_loss_pct"),
        take_profit_pct=request.get("take_profit_pct"),
        max_hold_days=request.get("max_hold_days"),
        holding_days=request.get("holding_days", 5),
        as_dict=request,
    )


def _dispatch(kind: str, request: dict, db, task_id: str):
    """按任务类型分发到对应回测函数，返回回测结果。"""
    cb = make_progress_cb(task_id)
    if kind == "strategy":
        cfg = _build_strategy_bt_config(request)
        return bt.run_strategy_backtest(db, cfg, progress_cb=cb)
    if kind == "factor":
        return bt.run_factor_backtest(db, request, progress_cb=cb)
    if kind == "optimizer":
        return bt.run_optimizer(db, request, progress_cb=cb)
    if kind == "walkforward":
        return bt.run_walkforward(db, request, progress_cb=cb)
    raise ValueError(f"未知回测任务类型: {kind}")


def run() -> None:
    logger.info("🚀 启动回测 Worker")

    stopped = False

    def _stop(signum, frame):  # noqa: ARG001
        nonlocal stopped
        logger.info(f"收到信号 {signum}，当前回测结束后停止 Worker")
        stopped = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while not stopped:
        job = dequeue(timeout=5.0)
        if job is None:
            continue
        task_id = job["task_id"]
        kind = job["kind"]
        try:
            db = get_mongo_db_sync()
            result = _dispatch(kind, job["request"], db, task_id)
            task_manager.update(task_id, status="success", result=result, progress=1.0)
            logger.info(f"✅ 回测任务完成: task_id={task_id} kind={kind}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"回测任务执行异常: task_id={task_id} kind={kind}")
            task_manager.update(task_id, status="failure", error=str(e))

    logger.info("回测 Worker 已停止")


if __name__ == "__main__":
    setup_logging()
    run()