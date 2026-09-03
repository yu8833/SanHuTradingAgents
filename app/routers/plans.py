"""当日交易计划 API 路由（P2）。

设计文档《第六章·交易工具与日常流程》§4 缺口2 + 附录A：
- GET   /api/plans           当日/指定日期计划列表
- GET   /api/plans/summary   当日计划摘要（待执行/已执行/取消 计数，供引导条）
- POST  /api/plans           创建计划（buy 自动仓位反算）
- PATCH /api/plans/{id}      更新状态（待执行→已执行/已取消，可关联成交）
- POST  /api/plans/evaluate  对照实时行情评估触发价（SSE 触发提醒）
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services import plan_service

router = APIRouter(prefix="/api/plans", tags=["plans"])
logger = logging.getLogger("webapi")


class PlanCreateRequest(BaseModel):
    code: str = Field(..., description="标的代码，如 600519")
    name: str | None = Field(None, description="标的名称")
    direction: str = Field("buy", description="buy=买入 / sell=卖出")
    trigger_price: float | None = Field(None, description="触发价")
    stop_loss: float | None = Field(None, description="止损位")
    sell_condition: str | None = Field(None, description="卖出条件")
    position: dict | None = Field(None, description="仓位反算结果（可选，缺省时买入自动反算）")
    strategy: str | None = Field("default", description="仓位反算策略")
    notes: str | None = Field(None, description="备注")
    date: str | None = Field(None, description="计划日期 YYYY-MM-DD，默认当日")
    source: dict | None = Field(None, description="5.4 来源标签 {type, ref, label}")
    confirmed: bool | None = Field(None, description="三态确认：False=待确认 / True=已确认（手动添加/已拍板为 True，候选写库为 False）")


class PlanDetailUpdateRequest(BaseModel):
    trigger_price: float | None = Field(None, description="触发价")
    stop_loss: float | None = Field(None, description="止损位")
    sell_condition: str | None = Field(None, description="卖出条件")
    name: str | None = Field(None, description="标的名称")
    notes: str | None = Field(None, description="备注")
    confirmed: bool | None = Field(None, description="人工确认：False=待确认 / True=已确认（进入盘中提醒）")


class PlanStatusRequest(BaseModel):
    status: str = Field(..., description="executed=已执行 / cancelled=已取消")
    executed_trade_id: str | None = Field(None, description="关联的 paper_trades 成交记录 id")


class EvaluatePlansRequest(BaseModel):
    quotes: dict[str, float] = Field(..., description="{code: 最新价}")


@router.get("")
async def list_plans(
    date: str | None = Query(default=None, description="计划日期 YYYY-MM-DD，默认当日"),
    status: str | None = Query(default=None, description="pending/executed/cancelled"),
    user: dict = Depends(get_current_user),
):
    try:
        items = await plan_service.list_plans(user["id"], plan_date=date, status=status)
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"计划列表失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="计划列表读取失败")


@router.get("/summary")
async def plan_summary(user: dict = Depends(get_current_user)):
    try:
        return ok(await plan_service.get_today_summary(user["id"]))
    except Exception as e:
        logger.error(f"计划摘要失败: {e}", exc_info=True)
        return ok({"pending": 0, "executed": 0, "cancelled": 0}, message="计划摘要失败")


@router.post("")
async def create_plan(req: PlanCreateRequest, user: dict = Depends(get_current_user)):
    try:
        plan = await plan_service.create_plan(user["id"], req.model_dump())
        return ok(plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        logger.error(f"创建计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建计划失败: {e}") from None


@router.patch("/{plan_id}")
async def update_plan(plan_id: str, req: PlanStatusRequest, user: dict = Depends(get_current_user)):
    try:
        plan = await plan_service.update_plan_status(
            user["id"], plan_id, req.status, executed_trade_id=req.executed_trade_id
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="计划不存在或无权访问")
        return ok(plan)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新计划失败: {e}") from None


@router.put("/{plan_id}")
async def update_plan_detail(plan_id: str, req: PlanDetailUpdateRequest,
                             user: dict = Depends(get_current_user)):
    """5.4 人工可改：改价 / 改止损 / 改卖出条件（改触发价后自动重算仓位）。"""
    try:
        plan = await plan_service.update_plan_detail(
            user["id"], plan_id, req.model_dump(exclude_unset=True)
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="计划不存在或无权访问")
        return ok(plan)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修改计划失败: {e}") from None


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str, user: dict = Depends(get_current_user)):
    """5.4 人工删除：仅允许删除未执行(pending)的计划。"""
    try:
        deleted = await plan_service.delete_plan(user["id"], plan_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="计划不存在、已执行或无权访问")
        return ok({"deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除计划失败: {e}") from None


@router.post("/evaluate")
async def evaluate_plans(
    req: EvaluatePlansRequest,
    user: dict = Depends(get_current_user),
):
    """对照实时行情评估当日待执行计划：价格触达触发价 → triggered=True。"""
    try:
        items = await plan_service.evaluate_plans(user["id"], req.quotes)
        return ok({"total": len(items), "items": items})
    except Exception as e:
        logger.error(f"计划触发评估失败: {e}", exc_info=True)
        return ok({"total": 0, "items": []}, message="计划触发评估失败")
