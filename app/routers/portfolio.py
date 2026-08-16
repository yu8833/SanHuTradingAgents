"""
持仓追踪API路由
提供持仓的增删改查、批量导入和汇总统计功能。
支持CSV导入实盘交易记录。
"""

import csv
import io
import logging
from datetime import datetime
from app.utils.timezone import now_tz

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.portfolio_service import Position, portfolio_service

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
    notes: str | None = None      # 备注
    strategy: str | None = "default"  # 策略类型
    stop_loss_price: float | None = None   # 止损价
    take_profit_price: float | None = None  # 止盈价
    thesis: str | None = None     # 投资逻辑


class UpdatePositionRequest(BaseModel):
    """更新持仓请求"""
    quantity: int | None = None
    cost_price: float | None = None
    position_ratio: float | None = None
    notes: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    thesis: str | None = None


class ImportPositionsRequest(BaseModel):
    """批量导入持仓请求"""
    positions: list[AddPositionRequest]


class PositionResponse(BaseModel):
    """持仓响应"""
    id: str
    symbol: str
    stock_name: str
    quantity: int
    cost_price: float
    position_ratio: float
    buy_date: str
    notes: str | None
    created_at: str
    updated_at: str
    # 汇总时包含的实时数据
    current_price: float | None = None
    market_value: float | None = None
    profit_loss: float | None = None
    profit_loss_rate: float | None = None


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

        # 构建持仓对象（含策略元数据）
        position = Position(
            user_id=current_user["id"],
            symbol=request.symbol,
            stock_name=request.stock_name,
            quantity=request.quantity,
            cost_price=request.cost_price,
            position_ratio=request.position_ratio,
            buy_date=request.buy_date,
            notes=request.notes,
            strategy=request.strategy,
            stop_loss_price=request.stop_loss_price,
            take_profit_price=request.take_profit_price,
            thesis=request.thesis,
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

        # 构建更新字段（含策略元数据）
        updates = {}
        if request.quantity is not None:
            updates["quantity"] = request.quantity
        if request.cost_price is not None:
            updates["cost_price"] = request.cost_price
        if request.position_ratio is not None:
            updates["position_ratio"] = request.position_ratio
        if request.notes is not None:
            updates["notes"] = request.notes
        if request.stop_loss_price is not None:
            updates["stop_loss_price"] = request.stop_loss_price
        if request.take_profit_price is not None:
            updates["take_profit_price"] = request.take_profit_price
        if request.thesis is not None:
            updates["thesis"] = request.thesis

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

        # 构建持仓对象列表（含策略元数据）
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
                notes=pos_req.notes,
                strategy=pos_req.strategy,
                stop_loss_price=pos_req.stop_loss_price,
                take_profit_price=pos_req.take_profit_price,
                thesis=pos_req.thesis,
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


@router.post("/positions/import-csv", response_model=dict)
async def import_positions_csv(
    file: UploadFile = File(...),
    strategy: str = Form("default"),
    current_user: dict = Depends(get_current_user),
):
    """
    从CSV文件导入实盘交易记录

    支持的CSV列名（不区分大小写，支持中英文）：
    - 代码/symbol/code: 股票代码
    - 名称/name/stock_name: 股票名称
    - 数量/quantity/qty: 持股数量
    - 成本价/cost_price/avg_cost: 成本价
    - 买入日期/buy_date/date: 买入日期（YYYY-MM-DD）
    - 止损价/stop_loss: 止损价（可选）
    - 止盈价/take_profit: 止盈价（可选）

    CSV第一行必须为表头。strategy 参数为统一策略标签，应用于本次导入的所有记录。
    """
    try:
        if not file.filename or not file.filename.lower().endswith('.csv'):
            raise HTTPException(status_code=400, detail="请上传CSV格式文件")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="文件为空")

        # 尝试多种编码（券商导出常为GBK）
        text = None
        for enc in ('utf-8-sig', 'utf-8', 'gbk', 'gb18030'):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise HTTPException(status_code=400, detail="无法解码文件，请使用UTF-8或GBK编码")

        reader = csv.DictReader(io.StringIO(text))
        raw_rows = list(reader)
        if not raw_rows:
            raise HTTPException(status_code=400, detail="CSV文件无数据行")

        # 字段别名映射
        def _pick(row, *keys):
            for k in keys:
                for actual_key in row:
                    if actual_key.strip().lower() == k.lower():
                        val = row[actual_key]
                        return val.strip() if isinstance(val, str) else val
            return None

        positions = []
        skipped = 0
        for row in raw_rows:
            code = _pick(row, '代码', 'symbol', 'code', '股票代码')
            name = _pick(row, '名称', 'name', 'stock_name', '股票名称') or ''
            qty_str = _pick(row, '数量', 'quantity', 'qty', '持股数量')
            cost_str = _pick(row, '成本价', 'cost_price', 'avg_cost', '买入价')
            date_str = _pick(row, '买入日期', 'buy_date', 'date', '日期')
            stop_str = _pick(row, '止损价', 'stop_loss', 'stop_loss_price')
            tp_str = _pick(row, '止盈价', 'take_profit', 'take_profit_price')

            if not code or not qty_str:
                skipped += 1
                continue

            try:
                qty = int(float(str(qty_str).replace(',', '')))
                cost = float(str(cost_str).replace(',', '')) if cost_str else 0.0
            except (ValueError, TypeError):
                skipped += 1
                continue

            # 日期格式归一化
            buy_date = now_tz().strftime("%Y-%m-%d")
            if date_str:
                try:
                    # 尝试 YYYY-MM-DD 或 YYYY/MM/DD
                    ds = str(date_str).replace('/', '-').strip()
                    if len(ds) >= 10:
                        buy_date = ds[:10]
                except Exception:
                    pass

            try:
                stop_loss = float(str(stop_str).replace(',', '')) if stop_str else None
            except (ValueError, TypeError):
                stop_loss = None
            try:
                take_profit = float(str(tp_str).replace(',', '')) if tp_str else None
            except (ValueError, TypeError):
                take_profit = None

            positions.append(Position(
                user_id=current_user["id"],
                symbol=str(code),
                stock_name=str(name),
                quantity=qty,
                cost_price=cost,
                position_ratio=0.0,
                buy_date=buy_date,
                strategy=strategy,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                thesis=None,
                created_at=now_tz(),
                updated_at=now_tz(),
            ))

        if not positions:
            raise HTTPException(status_code=400, detail=f"CSV中无有效记录（跳过{skipped}行）")

        success_count = await portfolio_service.import_positions(positions)
        logger.info(f"✅ CSV导入成功: user={current_user['id']}, 成功{success_count}条, 跳过{skipped}条")

        return ok({
            "total": len(raw_rows),
            "success_count": success_count,
            "skipped": skipped,
            "strategy": strategy,
        }, f"成功导入 {success_count} 条持仓（跳过 {skipped} 行无效记录）")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ CSV导入失败: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CSV导入失败: {str(e)}"
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
    exit_date: str | None = None      # 平仓日期（默认今天）
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
    strategy: str | None = None,
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
