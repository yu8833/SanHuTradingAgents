"""兼容层: A股 fundamentals_snapshot 占位"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


def fundamentals_snapshot(*args, **kwargs) -> Dict[str, Any]:
    """占位 - 返回空 dict"""
    return {}


def fetch_fundamentals_snapshot(*args, **kwargs) -> Dict[str, Any]:
    """占位 - 返回空 dict"""
    return {}


def get_cn_fund_snapshot(*args, **kwargs) -> Dict[str, Any]:
    """占位 - 返回空 dict"""
    return {}
