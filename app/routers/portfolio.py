"""
持仓追踪API路由
提供持仓的增删改查、批量导入和汇总统计功能
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
import logging

from app.routers.auth_db import get_current_user
from app.services.portfolio_service import portfolio_service, Position, PositionUpdate
from app.core.response import ok

logger = logging.getLogger("webapi")

router = APIRouter(tags=["持仓追踪"])


class AddPositionRequest(BaseModel):
    """添加持仓请求"""
    symbol: str                      # 股票代码，如 "600519.SH"
    stock_name: str                  # 股票名称，如 "贵州茅台"
    quantity: int                    # 持股数量
    cost_price: float                # 成本价
    position_ratio: float            # 仓位占比 (0-1)
    buy_date: str                    # 买入日期，格式 "YYYY-MM-DD"
    notes: Optional[str] = None      # 备注
    strategy: Optional[str] = "default"  # 策略类型
    stop_loss_price: Optional[float] = None   # 止损价
    take_profit_price: Optional[float] = None  # 止盈价
    thesis: Optional[str] = None     # 投资逻辑


class UpdatePositionRequest(BaseModel):
    """更新持仓请求"""
    quantity: Optional[int] = None
    cost_price: Optional[float] = None
    position_ratio: Optional[float] = None
    notes: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    thesis: Optional[str] = None


class ImportPositionsRequest(BaseModel):
    """批量导入持仓请求"""
    positions: List[AddPositionRequest]


class PositionResponse(BaseModel):
    """持仓响应"""
    id: str
    symbol: str
    stock_name: str
    quantity: int
    cost_price: float
    position_ratio: float
    buy_date: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    # 汇总时包含的实时数据
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_rate: Optional[float] = None


@router.get("/positions", response_model=dict)
async def get_positions(
    current_user: dict = Depends(get_current_user)
):
    """获取当前用户所有持仓"""
    try:
        logger.info(f"📊 获取持仓列表: user_id={current_user['id']}")
        positions = await portfolio_service.get_positions(current_user["id"])
        logger.info(f"✅ 获取持仓成功: 共 {len(positions)} 条")
        return ok(positions)
    except Exception as e:
        logger.error(f"❌ 获取持仓列表失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取持仓列表失败: {str(e)}"
        )


@router.post("/positions", response_model=dict)
async def add_position(
    request: AddPositionRequest,
    current_user: dict = Depends(get_current_user)
):
    """添加单个持仓"""
    try:
        logger.info(f"📝 添加持仓请求: user_id={current_user['id']}, symbol={request.symbol}, stock_name={request.stock_name}")

        # 构建持仓对象
        position = Position(
            user_id=current_user["id"],
            symbol=request.symbol,
            stock_name=request.stock_name,
            quantity=request.quantity,
            cost_price=request.cost_price,
            position_ratio=request.position_ratio,
            buy_date=request.buy_date,
            notes=request.notes
        )

        # 创建持仓
        result = await portfolio_service.create_position(position)

        logger.info(f"✅ 添加持仓成功: position_id={result.get('id')}")
        return ok(result, "添加成功")

    except Exception as e:
        logger.error(f"❌ 添加持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加持仓失败: {str(e)}"
        )


@router.put("/positions/{position_id}", response_model=dict)
async def update_position(
    position_id: str,
    request: UpdatePositionRequest,
    current_user: dict = Depends(get_current_user)
):
    """更新持仓信息"""
    try:
        logger.info(f"📝 更新持仓: position_id={position_id}")

        # 构建更新字段
        updates = {}
        if request.quantity is not None:
            updates["quantity"] = request.quantity
        if request.cost_price is not None:
            updates["cost_price"] = request.cost_price
        if request.position_ratio is not None:
            updates["position_ratio"] = request.position_ratio
        if request.notes is not None:
            updates["notes"] = request.notes

        if not updates:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="没有提供需要更新的字段"
            )

        result = await portfolio_service.update_position(position_id, updates)

        if result:
            logger.info(f"✅ 更新持仓成功: position_id={position_id}")
            return ok(result, "更新成功")
        else:
            logger.warning(f"⚠️ 持仓不存在: position_id={position_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="持仓不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 更新持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新持仓失败: {str(e)}"
        )


@router.delete("/positions/{position_id}", response_model=dict)
async def delete_position(
    position_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除持仓"""
    try:
        logger.info(f"🗑️ 删除持仓: position_id={position_id}")

        success = await portfolio_service.delete_position(position_id)

        if success:
            logger.info(f"✅ 删除持仓成功: position_id={position_id}")
            return ok({"position_id": position_id}, "删除成功")
        else:
            logger.warning(f"⚠️ 持仓不存在: position_id={position_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="持仓不存在"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 删除持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除持仓失败: {str(e)}"
        )


@router.post("/positions/import", response_model=dict)
async def import_positions(
    request: ImportPositionsRequest,
    current_user: dict = Depends(get_current_user)
):
    """批量导入持仓"""
    try:
        logger.info(f"📥 批量导入持仓: user_id={current_user['id']}, 数量={len(request.positions)}")

        if not request.positions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="导入列表为空"
            )

        # 构建持仓对象列表
        positions = []
        for pos_req in request.positions:
            positions.append(Position(
                user_id=current_user["id"],
                symbol=pos_req.symbol,
                stock_name=pos_req.stock_name,
                quantity=pos_req.quantity,
                cost_price=pos_req.cost_price,
                position_ratio=pos_req.position_ratio,
                buy_date=pos_req.buy_date,
                notes=pos_req.notes
            ))

        # 批量导入
        success_count = await portfolio_service.import_positions(positions)

        logger.info(f"✅ 批量导入成功: 成功 {success_count} 条")
        return ok({
            "total": len(request.positions),
            "success_count": success_count
        }, f"成功导入 {success_count} 条持仓")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 批量导入持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量导入持仓失败: {str(e)}"
        )


@router.get("/summary", response_model=dict)
async def get_portfolio_summary(
    current_user: dict = Depends(get_current_user)
):
    """获取持仓汇总（总市值、总盈亏、持仓数等）"""
    try:
        logger.info(f"📊 获取持仓汇总: user_id={current_user['id']}")

        summary = await portfolio_service.get_position_summary(current_user["id"])

        logger.info(f"✅ 获取持仓汇总成功: "
                   f"持仓数={summary.get('total_positions')}, "
                   f"总成本={summary.get('total_cost')}, "
                   f"总市值={summary.get('total_market_value')}, "
                   f"总盈亏={summary.get('total_profit_loss')}")

        return ok(summary)

    except Exception as e:
        logger.error(f"❌ 获取持仓汇总失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取持仓汇总失败: {str(e)}"
        )


# ============================================================
# 散户策略持仓扩展：平仓 / 未平仓 / 策略表现
# ============================================================

class ClosePositionRequest(BaseModel):
    """平仓请求"""
    exit_price: float                    # 平仓价
    exit_date: Optional[str] = None      # 平仓日期（默认今天）
    exit_reason: str = ""                # 平仓原因


@router.post("/{position_id}/close")
async def close_position(
    position_id: str,
    req: ClosePositionRequest,
    user=Depends(get_current_user)
):
    """平仓（保留记录用于策略表现统计）"""
    try:
        result = await portfolio_service.close_position(
            position_id=position_id,
            exit_price=req.exit_price,
            exit_date=req.exit_date,
            exit_reason=req.exit_reason
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="持仓不存在或已平仓"
            )
        return ok(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 平仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"平仓失败: {str(e)}"
        )


@router.get("/open/list")
async def get_open_positions(user=Depends(get_current_user)):
    """获取所有未平仓持仓"""
    try:
        positions = await portfolio_service.get_open_positions(user["id"])
        return ok(positions)
    except Exception as e:
        logger.error(f"❌ 获取未平仓持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取未平仓持仓失败: {str(e)}"
        )


@router.get("/strategy/{strategy}/positions")
async def get_positions_by_strategy(
    strategy: str,
    user=Depends(get_current_user)
):
    """按策略获取未平仓持仓"""
    try:
        positions = await portfolio_service.get_positions_by_strategy(
            user["id"], strategy
        )
        return ok(positions)
    except Exception as e:
        logger.error(f"❌ 按策略获取持仓失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"按策略获取持仓失败: {str(e)}"
        )


@router.get("/strategy/performance")
async def get_strategy_performance(
    strategy: Optional[str] = None,
    user=Depends(get_current_user)
):
    """获取策略表现统计（胜率/盈亏比/平均收益）"""
    try:
        perf = await portfolio_service.get_strategy_performance(
            user["id"], strategy
        )
        return ok(perf)
    except Exception as e:
        logger.error(f"❌ 获取策略表现失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取策略表现失败: {str(e)}"
        )
