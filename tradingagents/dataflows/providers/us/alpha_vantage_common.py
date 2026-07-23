"""兼容层: Alpha Vantage 公共模块占位"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AlphaVantageRateLimitError(Exception):
    """Alpha Vantage 速率限制错误"""
    pass


def get_api_key() -> Optional[str]:
    """获取 Alpha Vantage API Key"""
    return os.getenv("ALPHA_VANTAGE_API_KEY")


def _make_api_request(*args, **kwargs):
    """占位 - API 请求"""
    raise NotImplementedError("Alpha Vantage 适配器尚未迁移到新架构")
