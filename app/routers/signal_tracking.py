"""信号跟踪 + 有效性回填 API 路由（P1）。

设计文档《第六章·交易工具与日常流程》§4 缺口1 + 附录A Tab3 ②：
- GET  /api/signal-tracking          信号跟踪列表（按触发日倒序）
- GET  /api/signal-tracking/stats    按信号类型聚合的胜率/盈亏比/触止损率
- POST /api/signal-tracking/backfill 手动触发回填到期信号的实际表现
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services import signal_tracking_service

router = APIRouter(prefix="/api/signal-tracking", tags=["signal-tracking"])
logger = logging.getLogger("webapi")


@router.get("")
async def list_signals(
    signal_type: str | None = Query(default=None, description="信号类型 B1/B2/B3/B2G"),
    status: str | None = Query(default=None, description="状态 pending/filled"),
    code: str | None = Query(default=None, description="股票代码"),
    limit: int = Query(default=100, ge=1, le=500, description="返回条数"),
    user: dict = Depends(get_current_user),
):
    """信号跟踪列表。"""
    try:
        items = await signal_tracking_service.list_signals(
            signal_type=signal_type, status=status, code=code, limit=limit
        )
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"信号跟踪列表失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="信号跟踪列表读取失败")


@router.get("/stats")
async def get_stats(user: dict = Depends(get_current_user)):
    """按信号类型聚合的胜率/盈亏比/触止损率统计。"""
    try:
        stats = await signal_tracking_service.get_signal_stats()
        return ok(stats)
    except Exception as e:
        logger.error(f"信号统计失败: {e}", exc_info=True)
        return ok({"by_type": [], "total": {}, "pending_count": 0}, message="信号统计失败")


@router.post("/backfill")
async def backfill(
    n_trading_days: int = Query(default=signal_tracking_service.BACKFILL_DAYS,
                                ge=1, le=30, description="回填观察期（交易日数）"),
    user: dict = Depends(get_current_user),
):
    """手动触发回填到期信号的实际表现。"""
    try:
        filled = await signal_tracking_service.backfill_due_signals(n_trading_days=n_trading_days)
        return ok({"filled": filled, "n_trading_days": n_trading_days})
    except Exception as e:
        logger.error(f"信号回填失败: {e}", exc_info=True)
        return ok({"filled": 0}, message="信号回填失败")
