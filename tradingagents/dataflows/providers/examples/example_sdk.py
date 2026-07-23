"""兼容层: 示例 SDK 占位"""
import logging

logger = logging.getLogger(__name__)


class ExampleSDKProvider:
    def __init__(self, *args, **kwargs):
        logger.warning("⚠️ [ExampleSDKProvider] 占位类，未实现")

    def get_data(self, *args, **kwargs):
        return []


def example_sdk(*args, **kwargs):
    """占位"""
    return ExampleSDKProvider()
