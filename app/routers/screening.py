import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from app.routers.auth_db import get_current_user

from app.services.enhanced_screening_service import get_enhanced_screening_service
from app.models.screening import (
    ScreeningCondition, ScreeningRequest as NewScreeningRequest,
    ScreeningResponse as NewScreeningResponse, FieldInfo, BASIC_FIELDS_INFO
)

router = APIRouter(tags=["screening"])
logger = logging.getLogger("webapi")

# 筛选字段配置响应模型
class FieldConfigResponse(BaseModel):
    """筛选字段配置"""
    fields: Dict[str, FieldInfo]
    categories: Dict[str, List[str]]

class ScreeningResponse(BaseModel):
    total: int
    items: List[dict]

enhanced_svc = get_enhanced_screening_service()

# 前端字段名 → 数据库字段名 的映射
_FIELD_MAPPING = {
    "market_cap": "total_mv",
    "pe_ratio": "pe",
    "pb_ratio": "pb",
    "turnover": "turnover_rate",
    "change_percent": "pct_chg",
    "price": "close",
    # 直接用数据库字段名也支持（前端直接用）
    "pe": "pe",
    "pb": "pb",
    "total_mv": "total_mv",
    "circ_mv": "circ_mv",
    "turnover_rate": "turnover_rate",
    "pct_chg": "pct_chg",
    "amount": "amount",
    "volume": "volume",
    "close": "close",
    "market": "market",
}

# 前端操作符 → 数据库操作符 的映射
_OP_MAPPING = {
    "eq": "==", "ne": "!=",
    "gte": ">=", "lte": "<=",
    "gt": ">", "lt": "<",
}

# 数据库中可能全部为空的字段（数据尚未填充）——安全跳过
_FLAG_FIELDS = {
    "macd_golden_fork", "ma20_cross", "ma5_cross", "kdj_golden_fork",
    "volume_ratio", "pe_ttm", "pb_mrq",
    "ma20", "rsi14", "kdj_k", "kdj_d", "kdj_j", "dif", "dea", "macd_hist",
}


@router.get("/fields", response_model=FieldConfigResponse)
async def get_screening_fields(user: dict = Depends(get_current_user)):
    """
    获取筛选字段配置
    返回所有可用的筛选字段及其配置信息
    """
    try:
        # 字段分类
        categories = {
            "basic": ["code", "name", "industry", "area", "market"],
            "market_value": ["total_mv", "circ_mv"],
            "financial": ["pe", "pb", "pe_ttm", "pb_mrq", "roe"],
            "trading": ["turnover_rate", "volume_ratio"],
            "price": ["close", "pct_chg", "amount"],
            "technical": ["ma20", "rsi14", "kdj_k", "kdj_d", "kdj_j", "dif", "dea", "macd_hist"]
        }

        return FieldConfigResponse(
            fields=BASIC_FIELDS_INFO,
            categories=categories
        )

    except Exception as e:
        logger.error(f"[get_screening_fields] 获取字段配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def _convert_legacy_conditions_to_new_format(legacy_conditions: Dict[str, Any]) -> List[ScreeningCondition]:
    """向后兼容的辅助函数（当前已由 run_screening 直接处理）"""
    conditions = []
    if isinstance(legacy_conditions, dict):
        children = legacy_conditions.get("children", [])
        for child in children:
            if isinstance(child, dict):
                field = child.get("field")
                op = child.get("op")
                value = child.get("value")
                if field and op and value is not None:
                    mapped_field = _FIELD_MAPPING.get(field, field)
                    mapped_op = _OP_MAPPING.get(op, op)
                    conditions.append(ScreeningCondition(
                        field=mapped_field, operator=mapped_op, value=value
                    ))
    return conditions


# 传统筛选接口（保持向后兼容，但使用增强服务）
@router.post("/run", response_model=ScreeningResponse)
async def run_screening(request: Request, user: dict = Depends(get_current_user)):
    try:
        # 直接从原始 JSON body 中提取条件，绕过 Pydantic 模型验证
        raw_body = await request.json()

        # 从 raw_body 中提取条件列表（支持多种格式）
        raw_conditions: list = []
        if "conditions" in raw_body:
            cond = raw_body["conditions"]
            if isinstance(cond, list):
                raw_conditions = cond
            elif isinstance(cond, dict) and "children" in cond:
                raw_conditions = cond.get("children", [])
        elif "children" in raw_body and isinstance(raw_body["children"], list):
            raw_conditions = raw_body["children"]

        # 映射字段名和操作符
        conditions: List[Dict[str, Any]] = []
        for c in raw_conditions:
            if not isinstance(c, dict):
                continue
            op_raw = c.get("op", "==")
            op = _OP_MAPPING.get(str(op_raw).strip().lower(), op_raw)
            fld = _FIELD_MAPPING.get(str(c.get("field", "")), c.get("field", ""))
            value = c.get("value")
            if not fld or value is None:
                continue

            conditions.append({"field": fld, "operator": op, "value": value})

        logger.info(f"[screening] 筛选请求: limit={raw_body.get('limit')}, parsed_conditions={conditions}")

        # 执行筛选
        result = await enhanced_svc.screen_stocks(
            conditions=conditions,
            market=raw_body.get("market", "CN"),
            date=raw_body.get("date"),
            adj=raw_body.get("adj", "qfq"),
            limit=min(int(raw_body.get("limit", 50)), 500),
            offset=max(int(raw_body.get("offset", 0)), 0),
            order_by=[],
            use_database_optimization=True
        )

        logger.info(f"[screening] 完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        return ScreeningResponse(total=result["total"], items=result["items"])

    except Exception as e:
        logger.error(f"[screening] 处理失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# 新的优化筛选接口
@router.post("/enhanced", response_model=NewScreeningResponse)
async def enhanced_screening(req: NewScreeningRequest, user: dict = Depends(get_current_user)):
    """
    增强的股票筛选接口
    - 支持更丰富的筛选条件格式
    - 自动选择最优的筛选策略（数据库优化 vs 传统方法）
    - 提供详细的性能统计信息
    """
    try:
        logger.info(f"[enhanced_screening] 筛选条件: {len(req.conditions)}个")
        logger.info(f"[enhanced_screening] 排序与分页: order_by={req.order_by}, limit={req.limit}, offset={req.offset}")

        # 执行增强筛选
        result = await enhanced_svc.screen_stocks(
            conditions=req.conditions,
            market=req.market,
            date=req.date,
            adj=req.adj,
            limit=req.limit,
            offset=req.offset,
            order_by=req.order_by,
            use_database_optimization=req.use_database_optimization
        )

        logger.info(f"[enhanced_screening] 筛选完成: total={result.get('total')}, "
                   f"took={result.get('took_ms')}ms, optimization={result.get('optimization_used')}")

        return NewScreeningResponse(
            total=result["total"],
            items=result["items"],
            took_ms=result.get("took_ms"),
            optimization_used=result.get("optimization_used"),
            source=result.get("source")
        )

    except Exception as e:
        logger.error(f"[enhanced_screening] 筛选失败: {e}")
        raise HTTPException(status_code=500, detail=f"增强筛选失败: {str(e)}")


# 获取单个字段的详细信息
@router.get("/fields/{field_name}", response_model=Dict[str, Any])
async def get_field_info(field_name: str, user: dict = Depends(get_current_user)):
    """获取指定字段的详细信息"""
    try:
        field_info = await enhanced_svc.get_field_info(field_name)
        if not field_info:
            raise HTTPException(status_code=404, detail=f"字段 '{field_name}' 不存在")
        return field_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[screening] 获取字段信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取字段信息失败: {str(e)}")


# 验证筛选条件
@router.post("/validate", response_model=Dict[str, Any])
async def validate_conditions(conditions: List[ScreeningCondition], user: dict = Depends(get_current_user)):
    """验证筛选条件的有效性"""
    try:
        validation_result = await enhanced_svc.validate_conditions(conditions)
        return validation_result
    except Exception as e:
        logger.error(f"[screening] 验证条件失败: {e}")
        raise HTTPException(status_code=500, detail=f"验证条件失败: {str(e)}")

# 重复定义的旧端点移除（保留带日志的版本）


@router.get("/industries")
async def get_industries(user: dict = Depends(get_current_user)):
    """
    获取数据库中所有可用的行业列表
    从所有数据源中聚合行业分类数据，返回按股票数量排序的行业列表
    """
    try:
        from app.core.database import get_mongo_db

        db = get_mongo_db()
        collection = db["stock_basic_info"]

        # 🔥 从所有有行业数据的数据源中聚合行业信息
        # 先查询有哪些数据源有非空的 industry 字段
        sources_with_data = []
        try:
            source_pipeline = [
                {"$match": {"industry": {"$exists": True, "$nin": [None, "", "未知"]}}},
                {"$group": {"_id": "$source", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}}
            ]
            async for doc in collection.aggregate(source_pipeline):
                sources_with_data.append({"source": doc.get("_id"), "count": doc.get("count", 0)})
        except Exception as e:
            logger.warning(f"[get_industries] 查询数据源分布失败: {e}")

        logger.info(f"[get_industries] 有行业数据的数据源: {sources_with_data}")

        # 聚合查询：按行业分组并统计股票数量（从所有数据源查询）
        pipeline = [
            {
                "$match": {
                    "industry": {"$exists": True, "$nin": [None, "", "未知"]}
                }
            },
            {
                "$group": {
                    "_id": "$industry",
                    "count": {"$sum": 1}
                }
            },
            {"$sort": {"count": -1}},  # 按股票数量降序排序
            {
                "$project": {
                    "industry": "$_id",
                    "count": 1,
                    "_id": 0
                }
            }
        ]

        industries = []
        async for doc in collection.aggregate(pipeline):
            raw_industry = doc.get("industry")
            safe_industry = ""
            try:
                if raw_industry is None:
                    safe_industry = ""
                elif isinstance(raw_industry, float):
                    if raw_industry != raw_industry or raw_industry in (float("inf"), float("-inf")):
                        safe_industry = ""
                    else:
                        safe_industry = str(raw_industry)
                else:
                    safe_industry = str(raw_industry)
            except Exception:
                safe_industry = ""

            raw_count = doc.get("count", 0)
            safe_count = 0
            try:
                if isinstance(raw_count, float):
                    if raw_count != raw_count or raw_count in (float("inf"), float("-inf")):
                        safe_count = 0
                    else:
                        safe_count = int(raw_count)
                else:
                    safe_count = int(raw_count)
            except Exception:
                safe_count = 0

            if safe_industry and safe_count > 0:
                industries.append({
                    "value": safe_industry,
                    "label": safe_industry,
                    "count": safe_count,
                })

        # 确定主要数据源
        primary_source = sources_with_data[0]["source"] if sources_with_data else "unknown"

        logger.info(f"[get_industries] 返回 {len(industries)} 个行业，主要数据源: {primary_source}")

        return {
            "industries": industries,
            "total": len(industries),
            "source": primary_source,
            "sources": sources_with_data
        }

    except Exception as e:
        logger.error(f"[get_industries] 获取行业列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== 涨停回调策略 ==========

class LimitUpPullbackRequest(BaseModel):
    """涨停回调策略请求参数（精简版：4个核心参数）"""
    min_score: int = Field(40, ge=0, le=100, description="最低评分阈值")
    top_n: int = Field(10, ge=1, le=50, description="回测时每次最多选股数")
    hold_days: int = Field(20, ge=5, le=30, description="最大持有天数")
    initial_capital: float = Field(1000000, ge=100000, description="初始资金")
    limit: int = Field(50, ge=1, le=200, description="扫描返回数量限制")


class LimitUpPullbackResponse(BaseModel):
    """涨停回调策略响应"""
    total: int = Field(..., description="符合条件的股票总数")
    items: List[dict] = Field(..., description="股票列表")
    took_ms: Optional[int] = Field(None, description="耗时(毫秒)")
    scanned_count: Optional[int] = Field(None, description="扫描的股票总数")
    params: Optional[dict] = Field(None, description="使用的参数")


@router.post("/limit-up-pullback/scan", response_model=LimitUpPullbackResponse)
async def scan_limit_up_pullback(
    req: LimitUpPullbackRequest,
    user: dict = Depends(get_current_user)
):
    """
    涨停回调（龙回头/N字反包）策略选股
    
    策略逻辑：
    1. 筛选最近N天内出现过涨停的股票
    2. 涨停后出现缩量回调（3-5天）
    3. 回调期间出现地量+下影线（左侧买点）
    4. 放量突破5日线（右侧确认买点）
    5. 回调期间不破10日线（生命线）
    """
    try:
        from app.services.limit_up_pullback_service import get_limit_up_pullback_service
        
        service = get_limit_up_pullback_service()
        params = req.model_dump()
        
        logger.info(f"[limit_up_pullback] 扫描请求: {params}")
        
        result = await service.scan_limit_up_pullback(params)
        
        logger.info(f"[limit_up_pullback] 扫描完成: 找到 {result['total']} 只股票, "
                   f"耗时 {result.get('took_ms')}ms")
        
        return LimitUpPullbackResponse(
            total=result["total"],
            items=result["items"],
            took_ms=result.get("took_ms"),
            scanned_count=result.get("scanned_count"),
            params=result.get("params")
        )
        
    except Exception as e:
        logger.error(f"[limit_up_pullback] 扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"涨停回调扫描失败: {str(e)}")


class LimitUpPullbackBacktestRequest(LimitUpPullbackRequest):
    """涨停回调策略回测请求参数"""
    start_date: Optional[str] = Field(None, description="回测开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="回测结束日期 YYYY-MM-DD")


class LimitUpPullbackBacktestResponse(BaseModel):
    """涨停回调策略回测响应"""
    total_trades: int = Field(..., description="总交易次数")
    win_rate: float = Field(..., description="胜率(%)")
    avg_return: float = Field(..., description="平均收益(%)")
    avg_win: float = Field(..., description="平均盈利(%)")
    avg_loss: float = Field(..., description="平均亏损(%)")
    profit_loss_ratio: float = Field(0.0, description="盈亏比")
    max_drawdown: float = Field(..., description="最大回撤(%)")
    sharpe_ratio: float = Field(0.0, description="夏普比率")
    calmar_ratio: float = Field(0.0, description="卡玛比率")
    annualized_return: float = Field(0.0, description="年化收益率(%)")
    max_consecutive_losses: int = Field(0, description="最大连续亏损次数")
    total_fees_est: float = Field(0.0, description="估算总手续费")
    total_return: float = Field(..., description="总收益(%)")
    final_capital: float = Field(..., description="最终资金")
    initial_capital: float = Field(..., description="初始资金")
    backtest_days: int = Field(..., description="回测天数")
    signal_stats: dict = Field(default_factory=dict, description="按信号类型统计")
    sell_reason_stats: dict = Field(default_factory=dict, description="按卖出原因统计")
    daily_results: List[dict] = Field(default_factory=list, description="每日结果(前50天)")
    top_trades: List[dict] = Field(default_factory=list, description="盈利最多的20笔")
    worst_trades: List[dict] = Field(default_factory=list, description="亏损最多的20笔")
    params: Optional[dict] = Field(None, description="使用的参数")
    took_ms: Optional[int] = Field(None, description="耗时(毫秒)")


@router.post("/limit-up-pullback/backtest", response_model=LimitUpPullbackBacktestResponse)
async def backtest_limit_up_pullback(
    req: LimitUpPullbackBacktestRequest,
    user: dict = Depends(get_current_user)
):
    """
    涨停回调策略回测
    """
    try:
        from app.services.limit_up_pullback_service import get_limit_up_pullback_service
        
        service = get_limit_up_pullback_service()
        params = req.model_dump()
        
        logger.info(f"[limit_up_pullback_backtest] 回测请求: {params}")
        
        result = await service.backtest(params)
        
        logger.info(f"[limit_up_pullback_backtest] 回测完成: {result['total_trades']} 笔交易, "
                   f"胜率 {result['win_rate']}%, 平均收益 {result['avg_return']}%, "
                   f"耗时 {result.get('took_ms')}ms")
        
        return LimitUpPullbackBacktestResponse(**result)
        
    except Exception as e:
        logger.error(f"[limit_up_pullback_backtest] 回测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"涨停回调回测失败: {str(e)}")


# ========== 三买三卖策略 ==========

class ThreeBuysThreeSellsRequest(BaseModel):
    """三买三卖策略请求参数（精简版：5个核心参数）"""
    min_score: int = Field(50, ge=0, le=100, description="最低信号评分(100分制)")
    top_n: int = Field(10, ge=1, le=50, description="回测时每次最多选股数")
    hold_days: int = Field(60, ge=5, le=120, description="最大持有天数")
    initial_capital: float = Field(1000000, ge=100000, description="初始资金")
    max_position_pct: float = Field(0.15, ge=0.01, le=0.5, description="单股最大仓位比例")
    limit: int = Field(50, ge=1, le=200, description="扫描返回数量限制")


class ThreeBuysThreeSellsResponse(BaseModel):
    """三买三卖策略响应"""
    total: int = Field(..., description="符合条件的股票总数")
    items: List[dict] = Field(..., description="股票列表")
    took_ms: Optional[int] = Field(None, description="耗时(毫秒)")
    scanned_count: Optional[int] = Field(None, description="扫描的股票总数")
    params: Optional[dict] = Field(None, description="使用的参数")
    market_trend: Optional[str] = Field(None, description="大盘趋势")


@router.post("/three-buys-three-sells/scan", response_model=ThreeBuysThreeSellsResponse)
async def scan_three_buys_three_sells(
    req: ThreeBuysThreeSellsRequest,
    user: dict = Depends(get_current_user)
):
    """
    三买三卖交易策略扫描

    三类买点：
    - B1 左侧买点: BIAS(60) ∈ [-30%, -20%]
    - B2 突破买点: 放量 + 中阳 + 站上MA55&MA60
    - B3 回踩买点: 回调至MA60附近 + 放量中阳支撑

    三类卖点：
    - S1 减仓预警: BIAS超阈值 或 GMMA慢组压缩>30%
    - S2 主减仓: 连续2日跌破短期均线组
    - S3 清仓卖出: 跌破MA55&MA60且MA60拐头向下

    安全网: 单日跌幅 > ATR×3 → 强制减仓
    """
    try:
        from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service

        service = get_three_buys_three_sells_service()
        params = req.model_dump()

        logger.info(f"[three_buys_three_sells] 扫描请求: {params}")

        result = await service.scan_three_buys_three_sells(params)

        logger.info(f"[three_buys_three_sells] 扫描完成: 找到 {result['total']} 只股票, "
                   f"耗时 {result.get('took_ms')}ms")

        return ThreeBuysThreeSellsResponse(
            total=result["total"],
            items=result["items"],
            took_ms=result.get("took_ms"),
            scanned_count=result.get("scanned_count"),
            params=result.get("params"),
            market_trend=result.get("market_trend")
        )

    except Exception as e:
        logger.error(f"[three_buys_three_sells] 扫描失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"三买三卖扫描失败: {str(e)}")


class ThreeBuysThreeSellsBacktestRequest(ThreeBuysThreeSellsRequest):
    """三买三卖策略回测请求参数"""
    start_date: Optional[str] = Field(None, description="回测开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="回测结束日期 YYYY-MM-DD")


class ThreeBuysThreeSellsBacktestResponse(BaseModel):
    """三买三卖策略回测响应"""
    total_trades: int = Field(..., description="总交易次数")
    win_rate: float = Field(..., description="胜率(%)")
    avg_return: float = Field(..., description="平均收益(%)")
    avg_win: float = Field(..., description="平均盈利(%)")
    avg_loss: float = Field(..., description="平均亏损(%)")
    profit_loss_ratio: float = Field(0.0, description="盈亏比")
    max_drawdown: float = Field(..., description="最大回撤(%)")
    sharpe_ratio: float = Field(0.0, description="夏普比率")
    calmar_ratio: float = Field(0.0, description="卡玛比率")
    annualized_return: float = Field(0.0, description="年化收益率(%)")
    max_consecutive_losses: int = Field(0, description="最大连续亏损次数")
    total_fees_est: float = Field(0.0, description="估算总手续费")
    total_return: float = Field(..., description="总收益(%)")
    final_capital: float = Field(..., description="最终资金")
    initial_capital: float = Field(..., description="初始资金")
    backtest_days: int = Field(..., description="回测天数")
    signal_stats: dict = Field(default_factory=dict, description="按信号类型统计")
    sell_reason_stats: dict = Field(default_factory=dict, description="按卖出原因统计")
    daily_results: List[dict] = Field(default_factory=list, description="每日结果(前50天)")
    top_trades: List[dict] = Field(default_factory=list, description="盈利最多的20笔")
    worst_trades: List[dict] = Field(default_factory=list, description="亏损最多的20笔")
    params: Optional[dict] = Field(None, description="使用的参数")
    took_ms: Optional[int] = Field(None, description="耗时(毫秒)")


@router.post("/three-buys-three-sells/backtest", response_model=ThreeBuysThreeSellsBacktestResponse)
async def backtest_three_buys_three_sells(
    req: ThreeBuysThreeSellsBacktestRequest,
    user: dict = Depends(get_current_user)
):
    """
    三买三卖策略回测
    """
    try:
        from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service

        service = get_three_buys_three_sells_service()
        params = req.model_dump()

        logger.info(f"[three_buys_three_sells_backtest] 回测请求: {params}")

        result = await service.backtest(params)

        logger.info(f"[three_buys_three_sells_backtest] 回测完成: {result['total_trades']} 笔交易, "
                   f"胜率 {result['win_rate']}%, 平均收益 {result['avg_return']}%, "
                   f"耗时 {result.get('took_ms')}ms")

        return ThreeBuysThreeSellsBacktestResponse(**result)

    except Exception as e:
        logger.error(f"[three_buys_three_sells_backtest] 回测失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"三买三卖回测失败: {str(e)}")


# ============================================================
# 散户策略：极端反转 / 困境反转 / 小盘价值 / 转债博弈
# ============================================================

class RetailStrategyRequest(BaseModel):
    """散户策略通用请求"""
    min_score: int = Field(40, ge=0, le=100, description="最低评分阈值")
    top_n: int = Field(10, ge=1, le=50, description="回测时每次最多选股数")
    hold_days: int = Field(20, ge=5, le=120, description="最大持有天数")
    initial_capital: float = Field(1000000, ge=100000, description="初始资金")
    limit: int = Field(50, ge=1, le=200, description="扫描返回数量限制")
    max_position_pct: float = Field(0.1, ge=0.01, le=0.5, description="单股最大仓位比例")
    # 转债下修博弈专用参数（其他策略忽略）
    max_bond_price: Optional[float] = Field(None, description="转债价格上限")
    max_stock_vs_conversion: Optional[float] = Field(None, description="正股/转股价最大比值")
    min_issue_size: Optional[float] = Field(None, description="最小发行规模（亿元）")


class RetailStrategyScanResponse(BaseModel):
    """散户策略扫描响应"""
    total: int
    items: List[dict]
    took_ms: Optional[int] = None
    params: Optional[dict] = None
    scanned_count: Optional[int] = None
    message: Optional[str] = None


class RetailStrategyBacktestRequest(RetailStrategyRequest):
    """散户策略回测请求"""
    start_date: Optional[str] = Field(None, description="回测开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(None, description="回测结束日期 YYYY-MM-DD")


class RetailStrategyBacktestResponse(BaseModel):
    """散户策略回测响应"""
    strategy: Optional[str] = None
    total_trades: int = 0
    win_rate: float = 0
    avg_return: float = 0
    avg_win: float = 0
    avg_loss: float = 0
    profit_loss_ratio: float = 0
    max_drawdown: float = 0
    sharpe_ratio: float = 0
    calmar_ratio: float = 0
    annualized_return: float = 0
    max_consecutive_losses: int = 0
    total_fees_est: float = 0
    total_return: float = 0
    final_capital: float = 0
    initial_capital: float = 0
    backtest_days: int = 0
    sell_reason_stats: Optional[Dict[str, Any]] = None
    daily_results: Optional[List[dict]] = None
    top_trades: Optional[List[dict]] = None
    worst_trades: Optional[List[dict]] = None
    params: Optional[dict] = None
    took_ms: Optional[int] = None
    message: Optional[str] = None


# ---- 极端反转 ----

@router.post("/extreme-reversal/scan", response_model=RetailStrategyScanResponse)
async def scan_extreme_reversal(req: RetailStrategyRequest):
    """极端情绪反转策略 - 扫描选股"""
    try:
        from app.services.retail.extreme_reversal_service import get_extreme_reversal_service
        service = get_extreme_reversal_service()
        params = req.model_dump()
        result = await service.scan_extreme_reversal(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[extreme_reversal_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"极端反转扫描失败: {str(e)}")


@router.post("/extreme-reversal/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_extreme_reversal(req: RetailStrategyBacktestRequest):
    """极端情绪反转策略 - 回测分析"""
    try:
        from app.services.retail.extreme_reversal_service import get_extreme_reversal_service
        service = get_extreme_reversal_service()
        params = req.model_dump()
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[extreme_reversal_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"极端反转回测失败: {str(e)}")


# ---- 困境反转 ----

@router.post("/turnaround/scan", response_model=RetailStrategyScanResponse)
async def scan_turnaround(req: RetailStrategyRequest):
    """困境反转策略 - 扫描选股"""
    try:
        from app.services.retail.turnaround_service import get_turnaround_service
        service = get_turnaround_service()
        params = req.model_dump()
        result = await service.scan_turnaround(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[turnaround_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"困境反转扫描失败: {str(e)}")


@router.post("/turnaround/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_turnaround(req: RetailStrategyBacktestRequest):
    """困境反转策略 - 回测分析"""
    try:
        from app.services.retail.turnaround_service import get_turnaround_service
        service = get_turnaround_service()
        params = req.model_dump()
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[turnaround_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"困境反转回测失败: {str(e)}")


# ---- 小盘价值 ----

@router.post("/small-cap-value/scan", response_model=RetailStrategyScanResponse)
async def scan_small_cap_value(req: RetailStrategyRequest):
    """小盘价值策略 - 扫描选股"""
    try:
        from app.services.retail.small_cap_value_service import get_small_cap_value_service
        service = get_small_cap_value_service()
        params = req.model_dump()
        result = await service.scan_small_cap_value(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[small_cap_value_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"小盘价值扫描失败: {str(e)}")


@router.post("/small-cap-value/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_small_cap_value(req: RetailStrategyBacktestRequest):
    """小盘价值策略 - 回测分析"""
    try:
        from app.services.retail.small_cap_value_service import get_small_cap_value_service
        service = get_small_cap_value_service()
        params = req.model_dump()
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[small_cap_value_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"小盘价值回测失败: {str(e)}")


# ---- 转债博弈 ----

@router.post("/convertible-arbitrage/scan", response_model=RetailStrategyScanResponse)
async def scan_convertible_arbitrage(req: RetailStrategyRequest):
    """转债下修博弈策略 - 扫描选股"""
    try:
        from app.services.retail.convertible_arbitrage_service import get_convertible_arbitrage_service
        service = get_convertible_arbitrage_service()
        params = req.model_dump()
        result = await service.scan_convertible_arbitrage(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[convertible_arbitrage_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"转债博弈扫描失败: {str(e)}")


@router.post("/convertible-arbitrage/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_convertible_arbitrage(req: RetailStrategyBacktestRequest):
    """转债下修博弈策略 - 回测分析"""
    try:
        from app.services.retail.convertible_arbitrage_service import get_convertible_arbitrage_service
        service = get_convertible_arbitrage_service()
        params = req.model_dump()
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[convertible_arbitrage_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"转债博弈回测失败: {str(e)}")


# ========== 新策略：技术分析 ==========

@router.post("/ma-crossover/scan", response_model=RetailStrategyScanResponse)
async def scan_ma_crossover(req: RetailStrategyRequest):
    """均线交叉策略扫描"""
    try:
        from app.services.retail.moving_average_crossover_service import get_moving_average_crossover_service
        service = get_moving_average_crossover_service()
        params = req.dict(exclude_none=True)
        result = await service.scan_moving_average_crossover(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[ma_crossover_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"均线交叉扫描失败: {str(e)}")


@router.post("/ma-crossover/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_ma_crossover(req: RetailStrategyBacktestRequest):
    """均线交叉策略回测"""
    try:
        from app.services.retail.moving_average_crossover_service import get_moving_average_crossover_service
        service = get_moving_average_crossover_service()
        params = req.dict(exclude_none=True)
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[ma_crossover_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"均线交叉回测失败: {str(e)}")


@router.post("/macd-divergence/scan", response_model=RetailStrategyScanResponse)
async def scan_macd_divergence(req: RetailStrategyRequest):
    """MACD背离策略扫描"""
    try:
        from app.services.retail.macd_divergence_service import get_macd_divergence_service
        service = get_macd_divergence_service()
        params = req.dict(exclude_none=True)
        result = await service.scan_macd_divergence(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[macd_divergence_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MACD背离扫描失败: {str(e)}")


@router.post("/macd-divergence/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_macd_divergence(req: RetailStrategyBacktestRequest):
    """MACD背离策略回测"""
    try:
        from app.services.retail.macd_divergence_service import get_macd_divergence_service
        service = get_macd_divergence_service()
        params = req.dict(exclude_none=True)
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[macd_divergence_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"MACD背离回测失败: {str(e)}")


@router.post("/volume-price/scan", response_model=RetailStrategyScanResponse)
async def scan_volume_price(req: RetailStrategyRequest):
    """量价配合策略扫描"""
    try:
        from app.services.retail.volume_price_service import get_volume_price_service
        service = get_volume_price_service()
        params = req.dict(exclude_none=True)
        result = await service.scan_volume_price(params)
        return RetailStrategyScanResponse(**result)
    except Exception as e:
        logger.error(f"[volume_price_scan] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"量价配合扫描失败: {str(e)}")


@router.post("/volume-price/backtest", response_model=RetailStrategyBacktestResponse)
async def backtest_volume_price(req: RetailStrategyBacktestRequest):
    """量价配合策略回测"""
    try:
        from app.services.retail.volume_price_service import get_volume_price_service
        service = get_volume_price_service()
        params = req.dict(exclude_none=True)
        result = await service.backtest(params)
        return RetailStrategyBacktestResponse(**result)
    except Exception as e:
        logger.error(f"[volume_price_backtest] 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"量价配合回测失败: {str(e)}")


# ==================== 数据新鲜度检查 ====================

@router.get("/data-freshness")
async def check_data_freshness(user: dict = Depends(get_current_user)):
    """
    检查系统中所有需要及时更新的数据的新鲜度

    返回多维度数据新鲜度信息：
    - basics: 股票基础信息（stock_basic_info）
    - quotes: 历史K线数据（stock_daily_quotes）
    - financial: 财务数据（stock_financial_data）
    - news: 新闻数据（stock_news）
    - overall: 整体新鲜度（任一数据不新鲜则整体不新鲜）
    """
    try:
        from app.core.database import get_mongo_db
        from datetime import datetime, timedelta

        db = get_mongo_db()
        today = datetime.now()

        def is_trade_day(date):
            if date.weekday() >= 5:
                return False
            try:
                import chinese_calendar
                return chinese_calendar.is_workday(date)
            except ImportError:
                return True
            except Exception:
                return True

        expected_date = today
        while not is_trade_day(expected_date):
            expected_date -= timedelta(days=1)
        expected_date_str = expected_date.strftime("%Y-%m-%d")
        is_trading_day = is_trade_day(today)
        current_hour = today.hour

        # --- 1. 股票基础信息 ---
        basics_filter = {
            "$or": [
                {"category": "stock_cn"},
                {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}},
            ]
        }
        basics_count = len(await db.stock_basic_info.distinct("code", basics_filter))
        latest_basic_doc = await db.stock_basic_info.find().sort("updated_at", -1).limit(1).to_list(length=1)
        basics_updated_at = latest_basic_doc[0].get("updated_at") if latest_basic_doc else None
        # 基础信息只要今天更新过就算新鲜
        basics_is_fresh = False
        basics_stale_days = 999
        if basics_updated_at:
            if isinstance(basics_updated_at, str):
                basics_dt = datetime.strptime(basics_updated_at[:19], "%Y-%m-%d %H:%M:%S")
            else:
                basics_dt = basics_updated_at
            basics_stale_days = (today - basics_dt).days
            # 当天更新过就算新鲜
            basics_is_fresh = basics_stale_days <= 0
            basics_updated_at_str = basics_dt.strftime("%Y-%m-%d %H:%M")
        else:
            basics_updated_at_str = None

        # --- 2. 历史K线数据 ---
        latest_pipeline = [
            {"$match": {"period": "daily"}},
            {"$group": {"_id": "$trade_date"}},
            {"$sort": {"_id": -1}},
            {"$limit": 1},
        ]
        latest_docs = await db.stock_daily_quotes.aggregate(latest_pipeline).to_list(length=1)
        if latest_docs:
            quotes_latest_date = latest_docs[0]["_id"]
            quotes_total = len(await db.stock_daily_quotes.distinct("code", {"trade_date": quotes_latest_date, "period": "daily"}))
        else:
            quotes_latest_date = None
            quotes_total = 0

        quotes_is_fresh = False
        quotes_stale_days = 999
        if quotes_latest_date:
            try:
                quotes_dt = datetime.strptime(quotes_latest_date, "%Y-%m-%d")
                quotes_stale_days = (expected_date - quotes_dt).days
                if is_trading_day and current_hour < 16:
                    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
                    quotes_is_fresh = quotes_dt >= datetime.strptime(yesterday, "%Y-%m-%d")
                else:
                    quotes_is_fresh = quotes_stale_days <= 0
            except Exception:
                pass

        # --- 3. 财务数据 ---
        latest_fin_doc = await db.stock_financial_data.find().sort("updated_at", -1).limit(1).to_list(length=1)
        fin_updated_at = latest_fin_doc[0].get("updated_at") if latest_fin_doc else None
        fin_count = await db.stock_financial_data.count_documents({})
        fin_is_fresh = False
        fin_stale_days = 999
        if fin_updated_at:
            if isinstance(fin_updated_at, str):
                fin_dt = datetime.strptime(fin_updated_at[:19], "%Y-%m-%d %H:%M:%S")
            else:
                fin_dt = fin_updated_at
            fin_stale_days = (today - fin_dt).days
            # 财务数据每季度更新，30天内算新鲜
            fin_is_fresh = fin_stale_days <= 30
            fin_updated_at_str = fin_dt.strftime("%Y-%m-%d %H:%M")
        else:
            fin_updated_at_str = None

        # --- 4. 新闻数据 ---
        latest_news_doc = await db.stock_news.find().sort("published_at", -1).limit(1).to_list(length=1)
        if not latest_news_doc:
            latest_news_doc = await db.stock_news.find().sort("updated_at", -1).limit(1).to_list(length=1)
        news_updated_at = None
        if latest_news_doc:
            news_updated_at = latest_news_doc[0].get("published_at") or latest_news_doc[0].get("updated_at")
        news_count = await db.stock_news.count_documents({})
        news_is_fresh = False
        news_stale_days = 999
        if news_updated_at:
            if isinstance(news_updated_at, str):
                news_dt = datetime.strptime(str(news_updated_at)[:19], "%Y-%m-%d %H:%M:%S")
            else:
                news_dt = news_updated_at
            news_stale_days = (today - news_dt).days
            # 新闻数据每天更新，1天内算新鲜
            news_is_fresh = news_stale_days <= 1
            news_updated_at_str = news_dt.strftime("%Y-%m-%d %H:%M")
        else:
            news_updated_at_str = None

        # --- 整体新鲜度 ---
        overall_is_fresh = basics_is_fresh and quotes_is_fresh and fin_is_fresh and news_is_fresh
        overall_stale_days = max(basics_stale_days, quotes_stale_days, fin_stale_days, news_stale_days)

        data_items = [
            {
                "key": "basics",
                "label": "股票基础信息",
                "is_fresh": basics_is_fresh,
                "stale_days": basics_stale_days,
                "latest": basics_updated_at_str or "无数据",
                "count": basics_count,
                "threshold": "每日更新",
            },
            {
                "key": "quotes",
                "label": "历史K线数据",
                "is_fresh": quotes_is_fresh,
                "stale_days": quotes_stale_days,
                "latest": quotes_latest_date or "无数据",
                "count": quotes_total,
                "threshold": "每个交易日更新",
            },
            {
                "key": "financial",
                "label": "财务数据",
                "is_fresh": fin_is_fresh,
                "stale_days": fin_stale_days,
                "latest": fin_updated_at_str or "无数据",
                "count": fin_count,
                "threshold": "每季度更新（30天内有效）",
            },
            {
                "key": "news",
                "label": "新闻数据",
                "is_fresh": news_is_fresh,
                "stale_days": news_stale_days,
                "latest": news_updated_at_str or "无数据",
                "count": news_count,
                "threshold": "每日更新",
            },
        ]

        if overall_is_fresh:
            message = "所有数据均为最新"
        else:
            stale_items = [item["label"] for item in data_items if not item["is_fresh"]]
            message = f"{', '.join(stale_items)} 需要更新"

        return {
            "success": True,
            "data": {
                "overall_is_fresh": overall_is_fresh,
                "overall_stale_days": overall_stale_days,
                "expected_date": expected_date_str,
                "message": message,
                "items": data_items,
                # 兼容旧字段
                "latest_data_date": quotes_latest_date,
                "is_fresh": overall_is_fresh,
                "stale_days": overall_stale_days,
                "total_stocks": quotes_total,
                "expected_total": basics_count,
            }
        }
    except Exception as e:
        logger.error(f"数据新鲜度检查失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")