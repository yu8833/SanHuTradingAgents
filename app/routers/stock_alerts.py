"""
个股预警 API 路由

支持创建/查询/更新/删除价格预警和涨跌幅预警规则。
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
import logging

from app.routers.auth_db import get_current_user
from app.services.stock_alert_service import (
    stock_alert_service,
    AlertRuleCreate,
    AlertRuleUpdate,
)
from app.core.response import ok

logger = logging.getLogger("webapi")

router = APIRouter(tags=["个股预警"])


@router.get("/alerts", response_model=dict)
async def get_alerts(
    code: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """获取用户的预警规则列表"""
    try:
        alerts = await stock_alert_service.get_alerts(current_user["id"], code)
        return ok(alerts)
    except Exception as e:
        logger.error(f"❌ 获取预警列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取预警列表失败: {str(e)}")


@router.post("/alerts", response_model=dict)
async def create_alert(
    req: AlertRuleCreate,
    current_user: dict = Depends(get_current_user),
):
    """创建预警规则"""
    try:
        valid_types = {"price_above", "price_below", "pct_up", "pct_down"}
        if req.alert_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"alert_type 必须为: {valid_types}")
        if req.threshold <= 0:
            raise HTTPException(status_code=400, detail="threshold 必须大于0")

        result = await stock_alert_service.create_alert(current_user["id"], req)
        return ok(result, "预警规则创建成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 创建预警失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建预警失败: {str(e)}")


@router.put("/alerts/{alert_id}", response_model=dict)
async def update_alert(
    alert_id: str,
    req: AlertRuleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新预警规则（可用于重置触发状态）"""
    try:
        result = await stock_alert_service.update_alert(alert_id, req)
        if not result:
            raise HTTPException(status_code=404, detail="预警规则不存在")
        return ok(result, "更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新预警失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"更新预警失败: {str(e)}")


@router.delete("/alerts/{alert_id}", response_model=dict)
async def delete_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除预警规则"""
    try:
        success = await stock_alert_service.delete_alert(alert_id)
        if not success:
            raise HTTPException(status_code=404, detail="预警规则不存在")
        return ok({"alert_id": alert_id}, "删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除预警失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除预警失败: {str(e)}")
