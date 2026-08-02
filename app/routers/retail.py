"""
散户策略路由

提供三个核心能力：
1. 仓位建议：POST /api/retail/position
2. 退出信号检查：POST /api/retail/exits
3. 市场环境检测：POST /api/retail/regime
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
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
    holdings: list[HoldingItem] = Field(default_factory=list)
    symbol: str = Field(..., description="目标股票代码")
    strategy: str = Field("default", description="策略类型")
    price: float = Field(..., gt=0, description="当前股价")
    win_rate: float = Field(0.55, ge=0, le=1, description="策略历史胜率")
    profit_loss_ratio: float = Field(1.5, gt=0, description="策略历史盈亏比")
    industry: str = Field("未知", description="行业")
    theme: str = Field("未知", description="主题")
    daily_volume_amount: float | None = Field(None, description="当日成交额（元）")


class ExitHoldingItem(BaseModel):
    symbol: str
    strategy: str = "default"
    buy_price: float
    buy_date: str  # ISO格式
    current_price: float
    current_ma: float | None = None
    thesis_invalid: bool = False
    thesis_invalid_reason: str = ""


class ExitRequest(BaseModel):
    holdings: list[ExitHoldingItem]


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


@router.get("/regime/auto")
async def detect_regime_auto(user=Depends(get_current_user)):
    """
    自动采集市场数据并检测环境

    自动获取沪深300行情/MA250/波动率分位/市场宽度/融资余额变化/换手率，
    无需手动传参。返回检测结果 + 原始采集数据。
    """
    try:
        regime, raw_data = await service.detect_regime_auto()
        return {
            **regime.to_dict(),
            "raw_data": raw_data,
            "data_source": "auto",
        }
    except Exception as e:
        logger.error(f"自动检测市场环境失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"自动检测市场环境失败: {str(e)}")


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


@router.get("/strategies/performance")
async def get_strategies_performance(user=Depends(get_current_user)):
    """
    获取所有策略的实际表现统计（基于已平仓持仓）

    返回每个策略的胜率、盈亏比、平均收益、交易次数，
    以及建议的 win_rate / profit_loss_ratio 参数（用于仓位计算器）。
    """
    from app.services.portfolio_service import portfolio_service

    strategies = ["extreme_reversal", "turnaround", "small_cap_value",
                  "convertible_arbitrage", "ma_crossover", "macd_divergence",
                  "volume_price", "default"]
    results = {}
    for s in strategies:
        try:
            perf = await portfolio_service.get_strategy_performance(user["id"], s)
            results[s] = perf
        except Exception as e:
            logger.warning(f"获取策略 {s} 表现失败: {e}")
            results[s] = {
                "strategy": s,
                "total_trades": 0,
                "win_rate": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "profit_loss_ratio": 0,
                "avg_return": 0,
            }

    # 汇总所有策略
    try:
        overall = await portfolio_service.get_strategy_performance(user["id"], None)
    except Exception:
        overall = {"strategy": "all", "total_trades": 0, "win_rate": 0,
                   "avg_win": 0, "avg_loss": 0, "profit_loss_ratio": 0, "avg_return": 0}

    return {
        "strategies": results,
        "overall": overall,
        # 建议参数：当交易次数>=5时使用实际值，否则使用默认值
        "suggested_params": {
            s: {
                "win_rate": results[s]["win_rate"] if results[s]["total_trades"] >= 5 else 0.55,
                "profit_loss_ratio": results[s]["profit_loss_ratio"] if results[s]["total_trades"] >= 5 else 1.5,
            }
            for s in strategies
        },
    }


# ============================================================
# 风险扫描
# ============================================================

class RiskScanRequest(BaseModel):
    code: str = Field(..., description="股票代码，如 600519.SH")
    name: str = Field("", description="股票名称")


class RiskScanResponse(BaseModel):
    code: str
    name: str
    risk_count: int
    has_high_risk: bool
    has_any_risk: bool
    risk_level: str
    risks: list[dict]


@router.post("/risk-scan")
async def scan_stock_risks(
    req: RiskScanRequest,
    user=Depends(get_current_user),
):
    """
    扫描单只股票的风险

    5类风险：财务造假 / 商誉减值 / 质押爆仓 / 退市 / 解禁减持
    高风险股票（ST/质押>50%/商誉>50%/财务造假）会被标记 has_high_risk=True
    """
    from app.services.retail.risk_scanner import get_risk_scanner

    scanner = get_risk_scanner()
    result = scanner.scan_stock_risks(req.code, req.name)
    return result


@router.post("/risk-scan/batch")
async def batch_scan_risks(
    stocks: list[dict],
    user=Depends(get_current_user),
):
    """
    批量扫描股票风险

    输入：[{"code": "600519.SH", "name": "贵州茅台"}, ...]
    返回：{"results": [...], "safe_count": N, "risky_count": M}
    """
    from app.services.retail.risk_scanner import get_risk_scanner

    scanner = get_risk_scanner()
    results = []
    safe_count = 0
    risky_count = 0

    for s in stocks[:50]:  # 最多50只，避免超时
        code = s.get("code", "")
        name = s.get("name", "")
        if not code:
            continue
        risk = scanner.scan_stock_risks(code, name)
        results.append(risk)
        if risk["has_high_risk"]:
            risky_count += 1
        else:
            safe_count += 1

    return {
        "total": len(results),
        "safe_count": safe_count,
        "risky_count": risky_count,
        "results": results,
    }
