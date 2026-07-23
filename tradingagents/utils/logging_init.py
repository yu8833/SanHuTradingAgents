"""兼容层: 转发到 app.core.logging_config"""
import logging
from typing import Optional


def get_logger(name: str = "tradingagents") -> logging.Logger:
    """获取 logger"""
    return logging.getLogger(name)


def init_logging(log_level: str = "INFO", *args, **kwargs):
    """初始化日志（兼容 shim）"""
    try:
        from app.core.logging_config import setup_logging
        return setup_logging(log_level=log_level)
    except Exception:
        # 退回到基本 logging 配置
        logging.basicConfig(
            level=getattr(logging, log_level.upper(), logging.INFO),
            format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        )
        return None
