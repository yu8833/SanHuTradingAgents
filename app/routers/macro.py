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

    读取语义：
    - refresh=True：同步强制重新生成（100-200s，用户点「立即刷新」时接受等待）。
    - refresh=False（默认）：纯读取。若快照缺失，**不再让前端空态等点击**——
      自动在后台补生成一次（交易日、当日仅一次、并发单飞），立即返回 None 并携带
      auto_generating=true，前端据此展示"自动生成中…"并轻轮询取回；快照就绪后
      正常返回数据。这样作战室打开即"要么有货、要么正在自动生成"，无需手动触发。
    """
    try:
        if refresh:
            snap = await macro_service.refresh_macro_snapshot()
            return ok(snap)
        snap = await macro_service.get_macro_snapshot(date)
        if snap is None:
            auto_gen = await macro_service._ensure_snapshot_auto_generated()
            if auto_gen:
                # 快照缺失且已在后台自动补生成：返回 None + auto_generating=true，
                # 前端据此展示"自动生成中…"并轻轮询取回，而非空态催促点击。
                base = ok(None)
                base["data"] = {"snapshot": None, "auto_generating": True}
                return base
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


@router.get("/reference")
async def macro_reference(
    refresh: bool = Query(default=False, description="是否强制重建指数/快讯缓存"),
    current_user: dict = Depends(get_optional_current_user),
):
    """参考 Tab 独立实时数据（外围指数 / 财经日历 / 重要快讯）。

    不依赖宏观快照是否生成、不落库、不跑 LLM 逐条解读；
    三块数据各自带短 TTL 缓存，秒回。refresh=True 时强制重建外围指数缓存。
    """
    try:
        data = await macro_service.get_macro_reference(refresh=refresh)
        return ok(data)
    except Exception as e:
        logger.error(f"参考数据获取失败: {e}", exc_info=True)
        return ok(None, message="参考数据获取失败，请稍后重试")
