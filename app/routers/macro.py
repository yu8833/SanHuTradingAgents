"""宏观快扫（盘前）API 路由。

设计文档《第六章·交易工具与日常流程》§5.5：
- GET  /api/macro/daily-overview  今日（或指定日期）宏观快照
- POST /api/macro/refresh         手动触发生成今日快照并落库（绕过 8:15 定时任务）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, Query

from app.core.response import ok
from app.services.macro import macro_service

router = APIRouter(prefix="/api/macro", tags=["macro"])
logger = logging.getLogger("webapi")


async def get_optional_current_user(authorization: str | None = Header(default=None)) -> dict:
    """可选鉴权：无 token 视为 guest。"""
    if not authorization:
        return {"user_id": "guest", "username": "guest", "is_guest": True}
    try:
        from app.routers.auth_db import get_current_user
        user = await get_current_user(authorization)
        user["is_guest"] = False
        return user
    except Exception:
        return {"user_id": "guest", "username": "guest", "is_guest": True}


@router.get("/daily-overview")
async def daily_overview(
    date: str | None = Query(default=None, description="日期 YYYY-MM-DD，默认今日"),
    refresh: bool = Query(default=False, description="是否强制重新生成"),
    current_user: dict = Depends(get_optional_current_user),
):
    """今日（或指定日期）宏观快照：方向结论 + 依据明细 + LLM 解读 + 外围/日历/快讯。

    纯读取语义：快照缺失返回 None，**绝不请求内现场生成**（现场生成需拉外围指数 +
    LLM 解读，实测 100-200s，会让盘前 Tab 打开即冻结 2 分钟）。
    需要生成时走 POST /api/macro/refresh（用户点「立即生成」，前台等待可接受）。
    """
    try:
        if refresh:
            snap = await macro_service.refresh_macro_snapshot()
            return ok(snap)
        snap = await macro_service.get_macro_snapshot(date)
        return ok(snap)
    except Exception as e:
        logger.error(f"宏观快照读取失败: {e}", exc_info=True)
        return ok(None, message="宏观快照读取失败，请稍后重试")


@router.post("/refresh")
async def refresh(current_user: dict = Depends(get_optional_current_user)):
    """手动触发生成今日宏观快照（落库）。"""
    try:
        snap = await macro_service.refresh_macro_snapshot()
        return ok(snap)
    except Exception as e:
        logger.error(f"宏观快照刷新失败: {e}", exc_info=True)
        return ok(None, message="宏观快照刷新失败，请稍后重试")
