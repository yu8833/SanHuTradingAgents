"""兼容层: 实时新闻聚合器占位"""
import logging

logger = logging.getLogger(__name__)


class RealtimeNewsAggregator:
    """实时新闻聚合器占位"""
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [RealtimeNewsAggregator] 占位类，未实现")

    def get_news(self, *args, **kwargs):
        return []
