"""策略回测结果持久化 — 供「结果对比」Tab 跨策略对比使用。

回测任务可能由后端进程（回退线程）或独立回测 Worker 进程执行，
两端共用此模块将结果按 strategy_id 落库到 MongoDB，保证缓存失效后结果仍保留。
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

BACKTEST_RESULTS_COLLECTION = "strategy_backtest_results"


def save_backtest_result(db, result: dict) -> None:
    """将策略回测结果精炼后持久化到 MongoDB，供「结果对比」跨策略对比使用。

    每次回测都新增一条记录（不对同一策略做覆盖），以支持同一策略多次回测、
    不同区间/参数的结果并存对比。仅保存对比所需字段（stats / equity_curve / config / strategy_info）。
    """
    try:
        info = result.get("strategy_info") or {}
        cfg = result.get("config") or {}
        record = {
            "strategy_id": info.get("id") or cfg.get("strategy_id"),
            "strategy_name": info.get("name") or cfg.get("strategy_id"),
            "config": {"start": cfg.get("start"), "end": cfg.get("end")},
            "stats": result.get("stats") or {},
            "equity_curve": result.get("equity_curve") or [],
            "saved_at": time.time(),
        }
        if not record["strategy_id"]:
            return
        db[BACKTEST_RESULTS_COLLECTION].insert_one(record)
    except Exception as e:  # noqa: BLE001
        logger.warning("保存回测结果到MongoDB失败: %s", e)