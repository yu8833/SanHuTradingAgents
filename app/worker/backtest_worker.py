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
from app.strategy_system.backtest_queue import (
    clear_inflight,
    dequeue,
    drain_inflight,
    enqueue,
    mark_inflight,
)
from app.strategy_system.backtest_results_store import save_backtest_result
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
    if kind == "pipeline":
        import asyncio
        from app.core.database import init_database
        from app.services.pipeline_backtest_service import (
            PIPELINE_STRATEGY_ID,
            run_pipeline_backtest,
        )

        async def _run() -> dict:
            # 三买三卖服务依赖异步 get_mongo_db()，而 worker 进程未运行
            # FastAPI lifespan，需在此初始化异步数据库连接。
            await init_database()
            return await run_pipeline_backtest(db, request, progress_cb=cb)

        result = asyncio.run(_run())
        if result.get("success"):
            save_backtest_result(db, {
                **result,
                "strategy_info": {"id": PIPELINE_STRATEGY_ID, "name": "三买三卖回测"},
            })
        return result
    raise ValueError(f"未知回测任务类型: {kind}")


def run() -> None:
    logger.info("🚀 启动回测 Worker")

    # 启动时恢复上次被中断的在途任务：重新入队，确保不因 Worker 重启而丢失
    _recover_interrupted()

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
        # 取出即标记在途：若本进程在处理中被重启，启动时可据此恢复重入队
        mark_inflight(task_id, job)
        try:
            db = get_mongo_db_sync()
            result = _dispatch(kind, job["request"], db, task_id)
            clear_inflight()
            task_manager.update(task_id, status="success", result=result, progress=1.0)
            # 落库：供「结果对比」Tab 跨策略持久化对比，缓存失效后仍保留
            if kind == "strategy":
                save_backtest_result(db, result)
            logger.info(f"✅ 回测任务完成: task_id={task_id} kind={kind}")
        except Exception as e:  # noqa: BLE001
            clear_inflight()
            logger.exception(f"回测任务执行异常: task_id={task_id} kind={kind}")
            task_manager.update(task_id, status="failure", error=str(e))

    logger.info("回测 Worker 已停止")


def _recover_interrupted() -> None:
    """启动时把上次被中断的任务重新入队，避免任务永久丢失。

    Worker 用 BLPOP 阻塞取任务，取出时条目即从队列移除。若进程在任务执行中
    被重启（信号/PID 被杀/崩溃），该任务会残留 running 状态且无任何进程接管。
    通过读取在途标记，把被中断的任务重新投递到队列，由本进程继续执行。
    """
    try:
        payload = drain_inflight()
        if not payload:
            return
        task_id = payload["task_id"]
        kind = payload["kind"]
        request = payload.get("request") or {}
        ok = enqueue(kind, task_id, request)
        if ok:
            logger.info(f"♻️ 恢复被中断的回测任务并重新入队: task_id={task_id} kind={kind}")
        else:
            logger.warning(f"恢复被中断任务入队失败: task_id={task_id}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"恢复被中断任务异常: {e}")


if __name__ == "__main__":
    setup_logging()
    run()