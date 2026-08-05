"""
监控中心 API 路由 — 监控规则 CRUD + 触发记录查询/管理。

移植自 tickflow-stock-panel 监控中心，适配 SanHu 响应格式（{success, data, message}）。
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.monitor_service import (
    SIGNAL_FIELDS,
    THRESHOLD_FIELDS,
    RuleModel,
    monitor_service,
)

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/monitor", tags=["监控中心"])


# ── 字段选项 ─────────────────────────────────────────────
@router.get("/options")
async def get_options(current_user: dict = Depends(get_current_user)):
    """返回可选字段、运算符、枚举，供前端表单使用。"""
    return ok({
        "threshold_fields": [{"key": k, "label": v} for k, v in THRESHOLD_FIELDS.items()],
        "signal_fields": [{"key": k, "label": v} for k, v in SIGNAL_FIELDS.items()],
        "operators": [">", ">=", "<", "<=", "==", "!="],
        "types": [
            {"key": "signal", "label": "信号"},
            {"key": "price", "label": "价格/涨跌"},
            {"key": "market", "label": "市场异动"},
        ],
        "scopes": [
            {"key": "symbols", "label": "指定标的"},
            {"key": "all", "label": "全市场"},
        ],
        "logics": [
            {"key": "and", "label": "全部满足 (AND)"},
            {"key": "or", "label": "任一满足 (OR)"},
        ],
        "severities": [
            {"key": "info", "label": "普通"},
            {"key": "warn", "label": "警告"},
            {"key": "critical", "label": "重要"},
        ],
    })


# ── 规则列表 ─────────────────────────────────────────────
@router.get("/rules")
async def list_rules(current_user: dict = Depends(get_current_user)):
    """监控规则列表。"""
    try:
        rules = await monitor_service.list_rules()
        return ok({"rules": rules})
    except Exception as e:
        logger.error(f"❌ 获取监控规则失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取监控规则失败: {str(e)}")


# ── 新建 / 更新规则 ─────────────────────────────────────
@router.post("/rules")
async def save_rule(req: RuleModel, current_user: dict = Depends(get_current_user)):
    """新建或更新监控规则。"""
    try:
        rule = await monitor_service.save_rule(req.model_dump())
        return ok({"rule": rule}, "规则保存成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 保存监控规则失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存监控规则失败: {str(e)}")


# ── 删除规则 ─────────────────────────────────────────────
@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, current_user: dict = Depends(get_current_user)):
    """删除监控规则。"""
    try:
        deleted = await monitor_service.delete_rule(rule_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="规则不存在")
        return ok({"rule_id": rule_id}, "规则已删除")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除监控规则失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除监控规则失败: {str(e)}")


# ── 触发记录 ─────────────────────────────────────────────
@router.get("/alerts")
async def list_alerts(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=500, ge=1, le=2000),
    source: str | None = Query(default=None),
    current_user: dict = Depends(get_current_user),
):
    """查询触发记录（时间倒序）。"""
    try:
        alerts, total = await monitor_service.list_alerts(days=days, limit=limit, source=source)
        return ok({"alerts": alerts, "total": total})
    except Exception as e:
        logger.error(f"❌ 获取触发记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取触发记录失败: {str(e)}")


@router.delete("/alerts")
async def clear_alerts(current_user: dict = Depends(get_current_user)):
    """清空全部触发记录。"""
    try:
        n = await monitor_service.clear_alerts()
        return ok({"cleared": n}, "记录已清空")
    except Exception as e:
        logger.error(f"❌ 清空触发记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清空触发记录失败: {str(e)}")


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str, current_user: dict = Depends(get_current_user)):
    """删除单条触发记录。"""
    try:
        deleted = await monitor_service.delete_alert(alert_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="记录不存在")
        return ok({"alert_id": alert_id}, "记录已删除")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除触发记录失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除触发记录失败: {str(e)}")


# ── 手动触发评估 ─────────────────────────────────────────
@router.post("/check")
async def manual_check(current_user: dict = Depends(get_current_user)):
    """手动触发一次监控评估（用于调试/立即生效）。"""
    try:
        n = await monitor_service.run_evaluation()
        return ok({"triggered": n}, "评估完成")
    except Exception as e:
        logger.error(f"❌ 手动监控评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"手动监控评估失败: {str(e)}")