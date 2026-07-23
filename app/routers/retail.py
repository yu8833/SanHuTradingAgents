"""
散户策略路由

提供三个核心能力：
1. 仓位建议：POST /api/retail/position
2. 退出信号检查：POST /api/retail/exits
3. 市场环境检测：POST /api/retail/regime
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user
from app.services.retail import StrategyType
from app.services.retail.retail_strategy_service import (
    get_retail_strategy_service,
)

router = APIRouter(tags=["retail"])
logger = logging.getLogger("webapi")
service = get_retail_strategy_service()


# ---- 请求/响应模型 ----

class HoldingItem(BaseModel):
    symbol: str
    industry: str = "未知"
    theme: str = "未知"
    market_value: float = 0.0
    position_ratio: float = 0.0


class PositionRequest(BaseModel):
    account_size: float = Field(..., gt=0, description="账户总资产（元）")
    holdings: List[HoldingItem] = Field(default_factory=list)
    symbol: str = Field(..., description="目标股票代码")
    strategy: str = Field("default", description="策略类型")
    price: float = Field(..., gt=0, description="当前股价")
    win_rate: float = Field(0.55, ge=0, le=1, description="策略历史胜率")
    profit_loss_ratio: float = Field(1.5, gt=0, description="策略历史盈亏比")
    industry: str = Field("未知", description="行业")
    theme: str = Field("未知", description="主题")
    daily_volume_amount: Optional[float] = Field(None, description="当日成交额（元）")


class ExitHoldingItem(BaseModel):
    symbol: str
    strategy: str = "default"
    buy_price: float
    buy_date: str  # ISO格式
    current_price: float
    current_ma: Optional[float] = None
    thesis_invalid: bool = False
    thesis_invalid_reason: str = ""


class ExitRequest(BaseModel):
    holdings: List[ExitHoldingItem]


class RegimeRequest(BaseModel):
    index_price: float
    index_ma250: float
    volatility_percentile: float = Field(..., ge=0, le=1)
    breadth_ratio: float = Field(..., ge=0, le=1)
    margin_balance_change_pct: float
    turnover_ratio: float
    turnover_ma20: float


# ---- 路由 ----

@router.post("/position")
async def calculate_position(
    req: PositionRequest,
    user=Depends(get_current_user),
):
    """仓位建议：根据策略、账户、持仓计算建议买入股数"""
    try:
        strategy = StrategyType(req.strategy)
    except ValueError:
        strategy = StrategyType.DEFAULT
    advice = service.calculate_position(
        account_size=req.account_size,
        holdings=[h.dict() for h in req.holdings],
        symbol=req.symbol,
        strategy=strategy,
        price=req.price,
        win_rate=req.win_rate,
        profit_loss_ratio=req.profit_loss_ratio,
        industry=req.industry,
        theme=req.theme,
        daily_volume_amount=req.daily_volume_amount,
    )
    return advice.to_dict()


@router.post("/exits")
async def check_exits(
    req: ExitRequest,
    user=Depends(get_current_user),
):
    """退出信号检查：批量评估持仓是否触发止盈/止损/时间止损"""
    signals = service.check_exits([h.dict() for h in req.holdings])
    return {
        "total": len(signals),
        "signals": [s.to_dict() for s in signals],
        "exits_count": sum(1 for s in signals if s.should_exit),
    }


@router.post("/regime")
async def detect_regime(
    req: RegimeRequest,
    user=Depends(get_current_user),
):
    """市场环境检测：判断牛熊/波动率/宽度/情绪，输出策略激活建议"""
    regime = service.detect_regime(
        index_price=req.index_price,
        index_ma250=req.index_ma250,
        volatility_percentile=req.volatility_percentile,
        breadth_ratio=req.breadth_ratio,
        margin_balance_change_pct=req.margin_balance_change_pct,
        turnover_ratio=req.turnover_ratio,
        turnover_ma20=req.turnover_ma20,
    )
    return regime.to_dict()


@router.get("/strategies")
async def list_strategies(user=Depends(get_current_user)):
    """列出所有支持的散户策略类型及风控参数"""
    from app.services.retail.position_sizer import STRATEGY_RISK_PARAMS

    strategy_info = {
        "extreme_reversal": {
            "name": "极端情绪反转",
            "edge": "行为优势（逆向买入）",
            "hold_days": "1-5天",
            "win_condition": "超跌反弹+基本面未恶化",
        },
        "turnaround": {
            "name": "困境反转",
            "edge": "认知优势（深度研究）",
            "hold_days": "30-90天",
            "win_condition": "业绩拐点验证",
        },
        "small_cap_value": {
            "name": "小盘价值",
            "edge": "流动性优势（机构不能买）",
            "hold_days": "60-180天",
            "win_condition": "价值回归+可能的并购重组",
        },
        "convertible_arbitrage": {
            "name": "转债下修博弈",
            "edge": "认知优势（条款理解）",
            "hold_days": "30-120天",
            "win_condition": "下修成功+转股价值提升",
        },
    }
    risk_params = {
        s.value: {
            "max_single_position": p["max_single_position"],
            "max_total_position": p["max_total_position"],
            "max_single_loss": p["max_single_loss"],
        }
        for s, p in STRATEGY_RISK_PARAMS.items()
    }
    return {
        "strategies": strategy_info,
        "risk_params": risk_params,
    }
