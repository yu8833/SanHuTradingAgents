"""
股票数据模型 - 基于现有集合扩展
采用方案B: 在现有集合基础上扩展字段，保持向后兼容
"""
import logging
from datetime import datetime
from typing import Any, Literal

from bson import ObjectId
from pydantic import BaseModel, ConfigDict, Field

_model_logger = logging.getLogger(__name__)


def to_str_id(v: Any) -> str:
    """ObjectId转字符串工具函数"""
    try:
        if isinstance(v, ObjectId):
            return str(v)
        return str(v)
    except Exception:
        return ""


# 枚举类型定义
MarketType = Literal["CN", "HK", "US"]  # 市场类型
ExchangeType = Literal["SZSE", "SSE", "SEHK", "NYSE", "NASDAQ"]  # 交易所
StockStatus = Literal["L", "D", "P"]  # 上市状态: L-上市 D-退市 P-暂停
CurrencyType = Literal["CNY", "HKD", "USD"]  # 货币类型


class MarketInfo(BaseModel):
    """市场信息结构 - 新增字段"""
    market: MarketType = Field(..., description="市场标识")
    exchange: ExchangeType = Field(..., description="交易所代码")
    exchange_name: str = Field(..., description="交易所名称")
    currency: CurrencyType = Field(..., description="交易货币")
    timezone: str = Field(..., description="时区")
    trading_hours: dict[str, Any] | None = Field(None, description="交易时间")


class TechnicalIndicators(BaseModel):
    """技术指标结构 - 分类扩展设计"""
    # 趋势指标
    trend: dict[str, float] | None = Field(None, description="趋势指标")
    # 震荡指标  
    oscillator: dict[str, float] | None = Field(None, description="震荡指标")
    # 通道指标
    channel: dict[str, float] | None = Field(None, description="通道指标")
    # 成交量指标
    volume: dict[str, float] | None = Field(None, description="成交量指标")
    # 波动率指标
    volatility: dict[str, float] | None = Field(None, description="波动率指标")
    # 自定义指标
    custom: dict[str, Any] | None = Field(None, description="自定义指标")


class StockBasicInfoExtended(BaseModel):
    """
    股票基础信息扩展模型 - 基于现有 stock_basic_info 集合
    统一使用 symbol 作为主要股票代码字段
    """
    # === 标准化字段 (主要字段) ===
    symbol: str = Field(..., description="6位股票代码", pattern=r"^\d{6}$")
    full_symbol: str = Field(..., description="完整标准化代码(如 000001.SZ)")
    name: str = Field(..., description="股票名称")

    # === 兼容字段 (保持向后兼容) ===
    code: str | None = Field(None, description="6位股票代码(已废弃,使用symbol)")

    # === 基础信息字段 ===
    area: str | None = Field(None, description="所在地区")
    industry: str | None = Field(None, description="行业")
    market: str | None = Field(None, description="交易所名称")
    list_date: str | None = Field(None, description="上市日期")
    sse: str | None = Field(None, description="板块")
    sec: str | None = Field(None, description="所属板块")
    source: str | None = Field(None, description="数据来源")
    updated_at: datetime | None = Field(None, description="更新时间")

    # 市值字段
    total_mv: float | None = Field(None, description="总市值(亿元)")
    circ_mv: float | None = Field(None, description="流通市值(亿元)")

    # 财务指标
    pe: float | None = Field(None, description="市盈率")
    pb: float | None = Field(None, description="市净率")
    pe_ttm: float | None = Field(None, description="滚动市盈率")
    pb_mrq: float | None = Field(None, description="最新市净率")
    roe: float | None = Field(None, description="净资产收益率")

    # 交易指标
    turnover_rate: float | None = Field(None, description="换手率%")
    volume_ratio: float | None = Field(None, description="量比")

    # === 扩展字段 ===
    name_en: str | None = Field(None, description="英文名称")
    
    # 新增市场信息
    market_info: MarketInfo | None = Field(None, description="市场信息")
    
    # 新增标准化字段
    board: str | None = Field(None, description="板块标准化")
    industry_code: str | None = Field(None, description="行业代码")
    sector: str | None = Field(None, description="所属板块标准化（GICS行业）")
    delist_date: str | None = Field(None, description="退市日期")
    status: StockStatus | None = Field(None, description="上市状态")
    is_hs: bool | None = Field(None, description="是否沪深港通标的")

    # 新增股本信息
    total_shares: float | None = Field(None, description="总股本")
    float_shares: float | None = Field(None, description="流通股本")

    # 港股特有字段
    lot_size: int | None = Field(None, description="每手股数（港股特有）")

    # 货币字段
    currency: CurrencyType | None = Field(None, description="交易货币")
    
    # 版本控制
    data_version: int | None = Field(None, description="数据版本")
    
    class Config:
        # 允许额外字段，保持向后兼容
        extra = "allow"
        # 示例数据
        json_schema_extra = {
            "example": {
                # 标准化字段
                "symbol": "000001",
                "full_symbol": "000001.SZ",
                "name": "平安银行",

                # 基础信息
                "area": "深圳",
                "industry": "银行",
                "market": "深圳证券交易所",
                "sse": "主板",
                "total_mv": 2500.0,
                "pe": 5.2,
                "pb": 0.8,

                # 扩展字段
                "market_info": {
                    "market": "CN",
                    "exchange": "SZSE",
                    "exchange_name": "深圳证券交易所",
                    "currency": "CNY",
                    "timezone": "Asia/Shanghai"
                },
                "status": "L",
                "data_version": 1
            }
        }


class MarketQuotesExtended(BaseModel):
    """
    实时行情扩展模型 - 基于现有 market_quotes 集合
    统一使用 symbol 作为主要股票代码字段
    """
    # === 标准化字段 (主要字段) ===
    symbol: str = Field(..., description="6位股票代码", pattern=r"^\d{6}$")
    full_symbol: str | None = Field(None, description="完整标准化代码")
    market: MarketType | None = Field(None, description="市场标识")

    # === 兼容字段 (保持向后兼容) ===
    code: str | None = Field(None, description="6位股票代码(已废弃,使用symbol)")

    # === 行情字段 ===
    close: float | None = Field(None, description="收盘价")
    pct_chg: float | None = Field(None, description="涨跌幅%")
    amount: float | None = Field(None, description="成交额")
    open: float | None = Field(None, description="开盘价")
    high: float | None = Field(None, description="最高价")
    low: float | None = Field(None, description="最低价")
    pre_close: float | None = Field(None, description="前收盘价")
    trade_date: str | None = Field(None, description="交易日期")
    updated_at: datetime | None = Field(None, description="更新时间")
    
    # 新增行情字段
    current_price: float | None = Field(None, description="当前价格(与close相同)")
    change: float | None = Field(None, description="涨跌额")
    volume: float | None = Field(None, description="成交量")
    turnover_rate: float | None = Field(None, description="换手率")
    volume_ratio: float | None = Field(None, description="量比")
    
    # 五档行情
    bid_prices: list[float] | None = Field(None, description="买1-5价")
    bid_volumes: list[float] | None = Field(None, description="买1-5量")
    ask_prices: list[float] | None = Field(None, description="卖1-5价")
    ask_volumes: list[float] | None = Field(None, description="卖1-5量")
    
    # 时间戳
    timestamp: datetime | None = Field(None, description="行情时间戳")
    
    # 数据源和版本
    data_source: str | None = Field(None, description="数据来源")
    data_version: int | None = Field(None, description="数据版本")
    
    class Config:
        extra = "allow"
        json_schema_extra = {
            "example": {
                # 标准化字段
                "symbol": "000001",
                "full_symbol": "000001.SZ",
                "market": "CN",

                # 行情字段
                "close": 12.65,
                "pct_chg": 1.61,
                "amount": 1580000000,
                "open": 12.50,
                "high": 12.80,
                "low": 12.30,
                "trade_date": "2024-01-15",

                # 扩展字段
                "current_price": 12.65,
                "change": 0.20,
                "volume": 125000000
            }
        }


# ==================== P4-11：DB 写入白名单模型（extra=forbid） ====================
# 对外/读取模型（StockBasicInfoExtended / MarketQuotesExtended）保持 extra="allow" 兼容；
# 下面两个模型以 extra="forbid" 定义"允许写入 DB 的字段白名单"，用于在同步写入口
# 暴露字段漂移（写入新增/拼错字段不再被静默落库）。运行时仅做比对告警，不阻断、不删字段，
# 避免上游数据源新字段导致写入中断或数据丢失。

class StockBasicInfoDB(BaseModel):
    """stock_basic_info 写入白名单模型（P4-11）"""
    code: str | None = None
    symbol: str | None = None
    name: str | None = None
    area: str | None = None
    industry: str | None = None
    market: str | None = None
    list_date: str | None = None
    sse: str | None = None
    sec: str | None = None
    source: str | None = None
    updated_at: datetime | None = None
    full_symbol: str | None = None
    category: str | None = None
    total_mv: float | None = None
    circ_mv: float | None = None
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    pe_ttm: float | None = None
    pb_mrq: float | None = None
    ps_ttm: float | None = None
    roe: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    total_share: float | None = None
    float_share: float | None = None
    board: str | None = None
    industry_code: str | None = None
    sector: str | None = None
    status: str | None = None
    is_hs: bool | None = None
    delist_date: str | None = None

    model_config = ConfigDict(extra="forbid")


class MarketQuotesDB(BaseModel):
    """market_quotes 写入白名单模型（P4-11）"""
    code: str | None = None
    symbol: str | None = None
    trade_date: str | None = None
    updated_at: datetime | None = None
    close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    pre_close: float | None = None
    pct_chg: float | None = None
    turnover_rate: float | None = None
    vol_ratio: float | None = None
    name: str | None = None
    amount: float | None = None
    volume: float | None = None
    data_source: str | None = None

    model_config = ConfigDict(extra="forbid")


def detect_db_extra_fields(model_cls, data: dict, context: str = "") -> list[str]:
    """
    比对写入字段与白名单模型，返回不在白名单（疑似漂移）的字段名列表。
    仅记录 warning，不阻断、不删除数据——字段漂移检测是 P4-11 的核心价值。
    """
    if not data:
        return []
    allowed = set(getattr(model_cls, "model_fields", {}).keys())
    extra = [k for k in data if k not in allowed]
    if extra:
        _model_logger.warning(
            "DB 写入字段漂移 %s: 非白名单字段 %s%s",
            getattr(model_cls, "__name__", str(model_cls)),
            extra,
            f"（context: {context}）" if context else "",
        )
    return extra


# 数据库操作相关的响应模型
class StockBasicInfoResponse(BaseModel):
    """股票基础信息API响应模型"""
    success: bool = True
    data: StockBasicInfoExtended | None = None
    message: str = ""


class MarketQuotesResponse(BaseModel):
    """实时行情API响应模型"""
    success: bool = True
    data: MarketQuotesExtended | None = None
    message: str = ""


class StockListResponse(BaseModel):
    """股票列表API响应模型"""
    success: bool = True
    data: list[StockBasicInfoExtended] | None = None
    total: int = 0
    page: int = 1
    page_size: int = 20
    message: str = ""


class ScheduledTask(BaseModel):
    """
    定时任务数据模型
    用于存储定时任务的配置和状态信息
    """
    # 任务标识
    job_id: str = Field(..., description="任务ID")
    
    # 任务配置
    name: str = Field(..., description="任务名称")
    task_type: str = Field(..., description="任务类型，如 analysis, sync, report 等")
    cron_expression: str | None = Field(None, description="Cron 表达式")
    
    # 任务参数
    symbols: list[str] | None = Field(None, description="股票代码列表")
    params: dict[str, Any] | None = Field(None, description="任务参数")
    
    # 状态信息
    enabled: bool = Field(True, description="是否启用")
    consecutive_failures: int = Field(0, description="连续失败次数")
    max_consecutive_failures: int = Field(3, description="最大连续失败次数，达到后自动禁用")
    last_success_at: datetime | None = Field(None, description="上次成功执行时间")
    last_failure_at: datetime | None = Field(None, description="上次失败执行时间")
    
    # 持仓上下文
    portfolio_context: dict[str, Any] | None = Field(None, description="持仓上下文（股票、成本价、仓位等）")
    
    # 用户关联
    user_id: str | None = Field(None, description="用户ID")
    
    # 元数据
    display_name: str | None = Field(None, description="显示名称")
    description: str | None = Field(None, description="任务描述")
    
    # 时间戳
    created_at: datetime | None = Field(None, description="创建时间")
    updated_at: datetime | None = Field(None, description="更新时间")
    
    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "job_id": "stock_analysis_000001",
                "name": "股票分析任务",
                "task_type": "analysis",
                "cron_expression": "0 9 * * 1-5",
                "symbols": ["000001.SZ"],
                "enabled": True,
                "consecutive_failures": 0,
                "max_consecutive_failures": 3,
                "portfolio_context": {
                    "positions": [
                        {"symbol": "000001.SZ", "stock_name": "平安银行", "quantity": 1000, "cost_price": 12.50}
                    ]
                },
                "user_id": "user123"
            }
        }


class BatchJobUpdateRequest(BaseModel):
    """批量更新任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1)
    enabled: bool | None = Field(None, description="是否启用")
    cron_expression: str | None = Field(None, description="Cron 表达式")
    consecutive_failures: int | None = Field(None, description="重置连续失败计数")


class BatchJobDeleteRequest(BaseModel):
    """批量删除任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1)


class BatchJobTriggerRequest(BaseModel):
    """批量触发任务请求"""
    job_ids: list[str] = Field(..., description="任务ID列表", min_length=1)
    force: bool = Field(False, description="是否强制执行")


class CreateScheduledTaskFromFavoritesRequest(BaseModel):
    """从自选股创建定时任务请求"""
    task_type: str = Field("analysis", description="任务类型")
    cron_expression: str = Field(..., description="Cron 表达式")
    analysis_type: str | None = Field("comprehensive", description="分析类型")
    tags: list[str] | None = Field(None, description="自选股标签过滤")
    include_portfolio_context: bool = Field(True, description="是否包含持仓上下文")
