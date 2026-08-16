"""
监控中心 API 路由 — 监控规则 CRUD + 触发记录查询/管理。

移植自 tickflow-stock-panel 监控中心，适配 SanHu 响应格式（{success, data, message}）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.monitor_service import (
    AUX_WARNING_FIELDS,
    SIGNAL_FIELDS,
    THRESHOLD_FIELDS,
    RuleModel,
    monitor_service,
)

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/monitor", tags=["监控中心"])


class StrategyMonitorRequest(BaseModel):
    enabled: bool
    name: str | None = None


class ExecuteTbsOrderRequest(BaseModel):
    """执行待确认指令时可选指定买入数量（股）。"""
    quantity: int | None = Field(default=None, gt=0, description="买入数量（股），不传则按建议仓位自动折算")


# ── 字段选项 ─────────────────────────────────────────────
@router.get("/options")
async def get_options(current_user: dict = Depends(get_current_user)):
    """返回可选字段、运算符、枚举，供前端表单使用。"""
    return ok({
        "threshold_fields": [{"key": k, "label": v} for k, v in THRESHOLD_FIELDS.items()],
        "signal_fields": [{"key": k, "label": v} for k, v in SIGNAL_FIELDS.items()],
        "aux_fields": [{"key": k, "label": v} for k, v in AUX_WARNING_FIELDS.items()],
        "operators": [">", ">=", "<", "<=", "==", "!="],
        "types": [
            {"key": "strategy", "label": "常用策略监控"},
            {"key": "signal", "label": "信号"},
            {"key": "price", "label": "价格/涨跌"},
            {"key": "market", "label": "市场异动"},
            {"key": "aux", "label": "辅助信号预警"},
        ],
        "scopes": [
            {"key": "symbols", "label": "指定标的"},
            {"key": "watchlist", "label": "自选股"},
            {"key": "all", "label": "全市场"},
            {"key": "positions", "label": "纸面持仓"},
        ],
        "tbs_dirs": [{"key": "buy", "label": "买入信号（左侧买点/突破买点/回踩买点）"},
                     {"key": "sell", "label": "卖出信号（加速卖点/跌破卖点/清仓卖出）"},
                     {"key": "both", "label": "买卖双向"}],
        "tbs_signals": [
            {"key": "B1", "label": "左侧买点"},
            {"key": "B2", "label": "突破买点"},
            {"key": "B3", "label": "回踩买点"},
            {"key": "S1", "label": "加速卖点"},
            {"key": "S2", "label": "跌破卖点"},
            {"key": "S3", "label": "清仓卖出"},
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
        rules = await monitor_service.list_rules(current_user["id"])
        return ok({"rules": rules})
    except Exception as e:
        logger.error(f"❌ 获取监控规则失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取监控规则失败: {str(e)}")


# ── 新建 / 更新规则 ─────────────────────────────────────
@router.post("/rules")
async def save_rule(req: RuleModel, current_user: dict = Depends(get_current_user)):
    """新建或更新监控规则。"""
    try:
        rule = req.model_dump()
        # 「自选股」/「持仓」/「三买三卖」作用域绑定创建/编辑用户，评估时动态解析并归属执行账户
        if rule.get("scope") in ("watchlist", "positions") or rule.get("type") == "tbs":
            rule["user_id"] = current_user["id"]
        else:
            rule.pop("user_id", None)
        rule = await monitor_service.save_rule(rule)
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
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 删除监控规则失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除监控规则失败: {str(e)}")


# ── 常用策略监控（type=strategy）启停/状态 ───────────────
@router.get("/strategies/status")
async def strategy_monitor_status(current_user: dict = Depends(get_current_user)):
    """返回当前用户各常用策略的监控开关状态。"""
    try:
        items = await monitor_service.get_strategy_monitoring(current_user["id"])
        return ok({"items": items})
    except Exception as e:
        logger.error(f"❌ 获取策略监控状态失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取策略监控状态失败: {str(e)}")


@router.post("/strategies/{strategy_id}/monitor")
async def strategy_monitor_toggle(strategy_id: str, req: StrategyMonitorRequest,
                                  current_user: dict = Depends(get_current_user)):
    """开启/关闭某常用策略的监控。"""
    try:
        rule = await monitor_service.set_strategy_monitoring(
            current_user["id"], strategy_id, req.enabled, req.name)
        return ok({"rule": rule}, "策略监控已开启" if req.enabled else "策略监控已关闭")
    except Exception as e:
        logger.error(f"❌ 切换策略监控失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"切换策略监控失败: {str(e)}")


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
        n = await monitor_service.run_evaluation(respect_trading_time=False)
        return ok({"triggered": n}, "评估完成")
    except Exception as e:
        logger.error(f"❌ 手动监控评估失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"手动监控评估失败: {str(e)}")


# ── 三买三卖待确认指令（type=tbs） ───────────────────────
@router.get("/tbs/orders")
async def list_tbs_orders(
    status: str | None = Query(default=None, description="pending/executed/cancelled/dismissed/all"),
    limit: int = Query(default=200, ge=1, le=1000),
    current_user: dict = Depends(get_current_user),
):
    """列出当前用户的待确认交易指令（时间倒序）。"""
    try:
        orders = await monitor_service.list_tbs_orders(
            user_id=current_user["id"], status=status, limit=limit)
        return ok({"orders": orders})
    except Exception as e:
        logger.error(f"❌ 获取待确认指令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取待确认指令失败: {str(e)}")


@router.post("/tbs/orders/{order_id}/execute")
async def execute_tbs_order(
    order_id: str,
    payload: ExecuteTbsOrderRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """确认执行待确认指令（走纸面交易成交入口）。

    买入时可选传 quantity 指定数量（股），不传则按建议仓位自动折算。
    """
    try:
        qty = (payload.quantity if payload else None)
        order = await monitor_service.execute_tbs_order(
            order_id, current_user["id"], quantity=qty
        )
        return ok({"order": order}, "指令已执行")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"❌ 执行待确认指令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行待确认指令失败: {str(e)}")


@router.post("/tbs/orders/{order_id}/cancel")
async def cancel_tbs_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """取消待确认指令（标记为已取消）。"""
    try:
        ok_flag = await monitor_service.cancel_tbs_order(order_id, current_user["id"])
        if not ok_flag:
            raise HTTPException(status_code=400, detail="指令不存在或已处理")
        return ok({"order_id": order_id}, "指令已取消")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 取消待确认指令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"取消待确认指令失败: {str(e)}")


@router.post("/tbs/orders/{order_id}/dismiss")
async def dismiss_tbs_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """忽略待确认指令（标记为已忽略，不执行）。"""
    try:
        ok_flag = await monitor_service.dismiss_tbs_order(order_id, current_user["id"])
        if not ok_flag:
            raise HTTPException(status_code=400, detail="指令不存在或已处理")
        return ok({"order_id": order_id}, "指令已忽略")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 忽略待确认指令失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"忽略待确认指令失败: {str(e)}")