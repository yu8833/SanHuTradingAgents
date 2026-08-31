"""
分析相关数据模型
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.utils.timezone import now_tz, to_display_iso

from .user import PyObjectId


class AnalysisStatus(str, Enum):
    """分析状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BatchStatus(str, Enum):
    """批次状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisParameters(BaseModel):
    """分析参数模型"""
    market_type: str = "A股"
    analysis_date: datetime | None = None
    selected_analysts: list[str] = Field(default_factory=lambda: ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"])
    custom_prompt: str | None = None
    include_sentiment: bool = True
    include_risk: bool = True
    language: str = "zh-CN"
    # 分析模式：light=快评(精简链), full=尽调(完整链)
    # 兼容旧值：quick→light, deep→full
    mode: str = Field("full", description="分析模式: light=快评分析, full=尽调分析")
    # 速览分析结果（深度模式下复用）
    quick_result: dict[str, Any] | None = None
    # 模型配置
    quick_analysis_model: str | None = None
    deep_analysis_model: str | None = None


class AnalysisResult(BaseModel):
    """分析结果模型"""
    analysis_id: str | None = None
    summary: str | None = None
    recommendation: str | None = None
    confidence_score: float | None = None
    risk_level: str | None = None
    key_points: list[str] = Field(default_factory=list)
    detailed_analysis: dict[str, Any] | None = None
    charts: list[str] = Field(default_factory=list)
    tokens_used: int = 0
    execution_time: float = 0.0
    error_message: str | None = None
    model_info: str | None = None  # 🔥 添加模型信息字段


class AnalysisTask(BaseModel):
    """分析任务模型"""
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    task_id: str = Field(..., description="任务唯一标识")
    batch_id: str | None = None
    user_id: PyObjectId
    symbol: str = Field(..., description="6位股票代码")
    stock_code: str | None = Field(None, description="股票代码(已废弃,使用symbol)")
    stock_name: str | None = None
    status: AnalysisStatus = AnalysisStatus.PENDING

    progress: int = Field(default=0, ge=0, le=100, description="任务进度 0-100")

    # 时间戳
    created_at: datetime = Field(default_factory=now_tz)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # 执行信息
    worker_id: str | None = None
    parameters: AnalysisParameters = Field(default_factory=AnalysisParameters)
    result: AnalysisResult | None = None
    
    # 重试机制
    retry_count: int = 0
    max_retries: int = 3
    last_error: str | None = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )


class AnalysisBatch(BaseModel):
    """分析批次模型"""
    id: PyObjectId | None = Field(default_factory=PyObjectId, alias="_id")
    batch_id: str = Field(..., description="批次唯一标识")
    user_id: PyObjectId
    title: str = Field(..., description="批次标题")
    description: str | None = None
    status: BatchStatus = BatchStatus.PENDING
    
    # 任务统计
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    progress: int = Field(default=0, ge=0, le=100, description="整体进度 0-100")
    
    # 时间戳
    created_at: datetime = Field(default_factory=now_tz)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # 配置参数
    parameters: AnalysisParameters = Field(default_factory=AnalysisParameters)
    
    # 结果摘要
    results_summary: dict[str, Any] | None = None
    
    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True
    )


class StockInfo(BaseModel):
    """股票信息模型"""
    symbol: str = Field(..., description="6位股票代码")
    code: str | None = Field(None, description="股票代码(已废弃,使用symbol)")
    name: str = Field(..., description="股票名称")
    market: str = Field(..., description="市场类型")
    industry: str | None = None
    sector: str | None = None
    market_cap: float | None = None
    price: float | None = None
    change_percent: float | None = None


# API请求/响应模型

class SingleAnalysisRequest(BaseModel):
    """单股分析请求

    注意: stock_code 字段已废弃，请使用 symbol 字段
    """
    symbol: str | None = Field(None, description="股票代码 (6位代码，如: 000001)")
    stock_code: str | None = Field(None, description="⚠️ 已废弃，请使用 symbol 字段")
    parameters: AnalysisParameters | None = None

    def get_symbol(self) -> str:
        """获取股票代码(优先使用symbol，兼容旧字段stock_code)"""
        return self.symbol or self.stock_code or ""

    def __init__(self, **data):
        """初始化时自动处理废弃字段"""
        super().__init__(**data)
        # 如果只有 stock_code 而没有 symbol，自动迁移
        if not self.symbol and self.stock_code:
            import warnings
            warnings.warn(
                "stock_code 字段已废弃，请使用 symbol 字段",
                DeprecationWarning,
                stacklevel=2
            )
            self.symbol = self.stock_code


class BatchAnalysisRequest(BaseModel):
    """批量分析请求"""
    title: str = Field(..., description="批次标题")
    description: str | None = None
    symbols: list[str] | None = Field(None, min_items=1, max_items=10, description="股票代码列表（最多10个）")
    stock_codes: list[str] | None = Field(None, min_items=1, max_items=10, description="股票代码列表(已废弃,使用symbols，最多10个)")
    parameters: AnalysisParameters | None = None

    def get_symbols(self) -> list[str]:
        """获取股票代码列表(兼容旧字段)"""
        return self.symbols or self.stock_codes or []


class AnalysisTaskResponse(BaseModel):
    """分析任务响应"""
    task_id: str
    batch_id: str | None
    symbol: str
    stock_code: str | None = None  # 兼容字段
    stock_name: str | None
    status: AnalysisStatus
    progress: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: AnalysisResult | None

    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: datetime | None, _info) -> str | None:
        """序列化 datetime 为 ISO 8601 格式，保留时区信息"""
        if dt:
            return to_display_iso(dt)
        return None


class AnalysisBatchResponse(BaseModel):
    """分析批次响应"""
    batch_id: str
    title: str
    description: str | None
    status: BatchStatus
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    progress: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    parameters: AnalysisParameters

    @field_serializer('created_at', 'started_at', 'completed_at')
    def serialize_datetime(self, dt: datetime | None, _info) -> str | None:
        """序列化 datetime 为 ISO 8601 格式，保留时区信息"""
        if dt:
            return to_display_iso(dt)
        return None


class AnalysisHistoryQuery(BaseModel):
    """分析历史查询参数"""
    status: AnalysisStatus | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    symbol: str | None = None
    stock_code: str | None = None  # 兼容字段
    batch_id: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    def get_symbol(self) -> str | None:
        """获取股票代码(兼容旧字段)"""
        return self.symbol or self.stock_code
