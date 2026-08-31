"""周度复盘 API 路由（P3）。

设计文档《第六章·交易工具与日常流程》§4 缺口3 + 附录A Tab4：
- GET  /api/weekly-review/latest    最近一期周度复盘（定量统计/沪深300对比/信号有效性）
- GET  /api/weekly-review/history   历史周度复盘列表
- POST /api/weekly-review/generate  手动生成本周复盘（周五盘后定时任务之外的手动触发）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services import weekly_review_service

router = APIRouter(prefix="/api/weekly-review", tags=["weekly-review"])
logger = logging.getLogger("webapi")


@router.get("/latest")
async def get_latest(user: dict = Depends(get_current_user)):
    """最近一期周度复盘。"""
    try:
        review = await weekly_review_service.get_latest_review(user["id"])
        if not review:
            return ok(None, message="暂无周度复盘，可在周五盘后自动生成或手动触发")
        return ok(review)
    except Exception as e:
        logger.error(f"周度复盘读取失败: {e}", exc_info=True)
        return ok(None, message="周度复盘读取失败")


@router.get("/history")
async def list_history(
    limit: int = Query(default=12, ge=1, le=50, description="返回期数"),
    user: dict = Depends(get_current_user),
):
    """历史周度复盘列表（按周倒序）。"""
    try:
        items = await weekly_review_service.list_reviews(user["id"], limit=limit)
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"周度复盘历史读取失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="周度复盘历史读取失败")


@router.post("/generate")
async def generate(user: dict = Depends(get_current_user)):
    """手动生成本周复盘。"""
    try:
        review = await weekly_review_service.generate_weekly_review(user["id"])
        return ok(review)
    except Exception as e:
        logger.error(f"周度复盘生成失败: {e}", exc_info=True)
        return ok(None, message="周度复盘生成失败")
