"""
LLM调用统一重试策略模块

提供标准化的重试机制，包括：
1. 多种退避策略（指数退避、线性退避、常数延迟）
2. 抖动机制避免惊群效应
3. 细粒度的错误分类和重试判断
4. 限流专用处理
5. 统一的超时控制

使用方式：
1. 在 LLM 客户端中集成 RetryableLLMCaller
2. 配置 max_retries、base_delay 等参数
3. 调用 with_retry() 包装任意 LLM 请求
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Callable, TypeVar, Optional, Set, Any, Awaitable
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RetryStrategy(Enum):
    """重试策略类型"""
    EXPONENTIAL_BACKOFF = "exponential_backoff"  # 指数退避（推荐）
    LINEAR_BACKOFF = "linear_backoff"            # 线性退避
    CONSTANT = "constant"                        # 常数延迟


class ErrorSeverity(Enum):
    """错误严重程度"""
    TRANSIENT = "transient"      # 瞬时错误（网络抖动），可重试
    RATE_LIMIT = "rate_limit"   # 限流错误，需较长等待
    CLIENT_ERROR = "client_error"  # 客户端错误（参数错误等），不重试
    SERVER_ERROR = "server_error"  # 服务器错误（5xx），可重试
    UNKNOWN = "unknown"          # 未知错误，根据配置决定


@dataclass
class RetryConfig:
    """LLM调用重试配置"""
    # 重试次数
    max_retries: int = 3

    # 延迟配置
    base_delay: float = 1.0           # 基础延迟（秒）
    max_delay: float = 60.0           # 最大延迟（秒）

    # 退避策略
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF

    # 抖动配置
    jitter: bool = True               # 是否添加随机抖动
    jitter_factor: float = 0.5        # 抖动系数（0-1），实际延迟 = delay * (1 ± jitter_factor)

    # 超时配置
    request_timeout: float = 60.0    # 单次请求超时（秒）
    total_timeout: float = 300.0     # 总超时（秒）

    # 可重试的错误
    retryable_errors: Set[str] = field(default_factory=lambda: {
        "timeout", "ECONNABORTED", "timed out",
        "ConnectionError", "ConnectionResetError",
        "RemoteDisconnected",
    })

    # 可重试的HTTP状态码
    retryable_status_codes: Set[int] = field(default_factory=lambda: {
        408,  # Request Timeout
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    })

    # 限流错误码
    rate_limit_codes: Set[int] = field(default_factory=lambda: {
        429,  # Too Many Requests
    })

    def __post_init__(self):
        """参数校验"""
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if self.jitter_factor < 0 or self.jitter_factor > 1:
            raise ValueError("jitter_factor must be between 0 and 1")

    def calculate_delay(self, attempt: int, is_rate_limit: bool = False) -> float:
        """
        计算重试延迟时间

        Args:
            attempt: 当前尝试次数（从0开始）
            is_rate_limit: 是否为限流错误

        Returns:
            延迟时间（秒）
        """
        # 根据策略计算基础延迟
        if self.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = self.base_delay * (2 ** attempt)
        elif self.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = self.base_delay * (attempt + 1)
        else:  # CONSTANT
            delay = self.base_delay

        # 限流错误需要更长的等待时间
        if is_rate_limit:
            delay *= 2

        # 限制最大延迟
        delay = min(delay, self.max_delay)

        # 添加抖动
        if self.jitter:
            jitter_range = delay * self.jitter_factor
            delay = delay + random.uniform(-jitter_range, jitter_range)

        # 确保延迟为正数
        return max(0.1, delay)

    def is_retryable_error(self, error: Exception) -> tuple[bool, ErrorSeverity]:
        """
        判断错误是否可重试

        Args:
            error: 异常对象

        Returns:
            (is_retryable, severity)
        """
        error_str = str(error).lower()
        error_type = type(error).__name__

        # 检查是否为限流错误
        if "429" in error_str or "rate limit" in error_str or "too many requests" in error_str:
            return True, ErrorSeverity.RATE_LIMIT

        # 检查是否为超时错误
        if any(keyword in error_str for keyword in ["timeout", "timed out", "aborted"]):
            return True, ErrorSeverity.TRANSIENT

        # 检查是否为连接错误
        if any(keyword in error_str for keyword in [
            "connection", "refused", "reset", "disconnected", "network"
        ]):
            return True, ErrorSeverity.TRANSIENT

        # 检查是否为服务器错误
        if "500" in error_str or "internal server error" in error_str:
            return True, ErrorSeverity.SERVER_ERROR
        if "502" in error_str or "bad gateway" in error_str:
            return True, ErrorSeverity.SERVER_ERROR
        if "503" in error_str or "service unavailable" in error_str:
            return True, ErrorSeverity.SERVER_ERROR
        if "504" in error_str or "gateway timeout" in error_str:
            return True, ErrorSeverity.SERVER_ERROR

        # 检查是否在可重试错误列表中
        for retryable in self.retryable_errors:
            if retryable.lower() in error_str or retryable in error_type:
                return True, ErrorSeverity.TRANSIENT

        # 检查是否有 status_code 属性（HTTPError等）
        if hasattr(error, 'response') and hasattr(error.response, 'status_code'):
            status_code = error.response.status_code
            if status_code in self.retryable_status_codes:
                if status_code in self.rate_limit_codes:
                    return True, ErrorSeverity.RATE_LIMIT
                return True, ErrorSeverity.SERVER_ERROR

        return False, ErrorSeverity.UNKNOWN


@dataclass
class RetryStats:
    """重试统计信息"""
    total_attempts: int = 0
    successful_retries: int = 0
    failed_retries: int = 0
    rate_limit_waits: float = 0.0
    total_retry_time: float = 0.0
    errors_by_type: dict = field(default_factory=dict)

    def record_attempt(self, success: bool, retry_time: float, error_type: Optional[str] = None,
                       is_rate_limit: bool = False):
        """记录一次尝试"""
        self.total_attempts += 1
        if success:
            self.successful_retries += 1
        else:
            self.failed_retries += 1

        self.total_retry_time += retry_time

        if is_rate_limit:
            self.rate_limit_waits += retry_time

        if error_type:
            self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

    @property
    def success_rate(self) -> float:
        if self.total_attempts == 0:
            return 0.0
        return self.successful_retries / self.total_attempts

    @property
    def retry_rate(self) -> float:
        """重试率"""
        if self.total_attempts <= 1:
            return 0.0
        return (self.total_attempts - 1) / self.total_attempts

    def to_dict(self) -> dict:
        return {
            "total_attempts": self.total_attempts,
            "successful_retries": self.successful_retries,
            "failed_retries": self.failed_retries,
            "success_rate": f"{self.success_rate:.1%}",
            "retry_rate": f"{self.retry_rate:.1%}",
            "total_retry_time": f"{self.total_retry_time:.2f}s",
            "rate_limit_wait_time": f"{self.rate_limit_waits:.2f}s",
            "errors_by_type": self.errors_by_type,
        }


class RetryableLLMCaller:
    """
    可重试的 LLM 调用包装器

    使用示例：
    ```python
    config = RetryConfig(
        max_retries=3,
        base_delay=1.0,
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    )
    caller = RetryableLLMCaller(config)

    result = await caller.call(llm.invoke, prompt)
    ```
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()
        self.stats = RetryStats()

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args,
        **kwargs
    ) -> T:
        """
        执行带重试的异步调用

        Args:
            func: 异步函数（如 llm.invoke）
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回结果

        Raises:
            最后一次重试失败后抛出原始异常
        """
        last_error = None
        start_time = time.time()

        for attempt in range(self.config.max_retries + 1):
            attempt_start = time.time()

            try:
                # 添加请求超时
                if asyncio.iscoroutinefunction(func):
                    result = await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=self.config.request_timeout
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(func, *args, **kwargs),
                        timeout=self.config.request_timeout
                    )

                # 成功，记录统计
                attempt_time = time.time() - attempt_start
                self.stats.record_attempt(
                    success=True,
                    retry_time=attempt_time if attempt > 0 else 0,
                )

                if attempt > 0:
                    logger.info(
                        f"✅ LLM调用成功 (重试 {attempt} 次后)"
                    )

                return result

            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"LLM调用超时 (attempt {attempt + 1}/{self.config.max_retries + 1})"
                )
                is_retryable = True
                severity = ErrorSeverity.TRANSIENT

            except Exception as e:
                last_error = e
                is_retryable, severity = self.config.is_retryable_error(e)

            # 检查是否应该重试
            attempt_time = time.time() - attempt_start

            if not is_retryable:
                logger.warning(
                    f"❌ LLM调用失败且不可重试: {type(last_error).__name__}: {last_error}"
                )
                self.stats.record_attempt(
                    success=False,
                    retry_time=0,
                    error_type=type(last_error).__name__,
                )
                raise last_error

            # 检查是否达到最大重试次数
            if attempt >= self.config.max_retries:
                logger.error(
                    f"❌ LLM调用失败，已达到最大重试次数 ({self.config.max_retries})"
                )
                self.stats.record_attempt(
                    success=False,
                    retry_time=attempt_time,
                    error_type=type(last_error).__name__,
                    is_rate_limit=(severity == ErrorSeverity.RATE_LIMIT),
                )
                raise last_error

            # 计算等待时间
            is_rate_limit = severity == ErrorSeverity.RATE_LIMIT
            delay = self.config.calculate_delay(attempt, is_rate_limit=is_rate_limit)

            # 记录重试信息
            severity_icon = "⚠️" if severity == ErrorSeverity.RATE_LIMIT else "🔄"
            logger.warning(
                f"{severity_icon} LLM调用失败，"
                f"{delay:.2f}秒后重试 (attempt {attempt + 1}/{self.config.max_retries + 1}): "
                f"{type(last_error).__name__}: {str(last_error)[:100]}"
            )

            # 等待后再重试
            await asyncio.sleep(delay)

            # 记录限流等待时间
            if is_rate_limit:
                self.stats.record_attempt(
                    success=False,
                    retry_time=delay + attempt_time,
                    error_type="rate_limit",
                    is_rate_limit=True,
                )

        # 理论上不会到这里
        raise last_error

    def call_sync(
        self,
        func: Callable[..., T],
        *args,
        **kwargs
    ) -> T:
        """
        执行带重试的同步调用（包装为异步）

        这是 call() 的同步版本便利方法
        """
        return asyncio.get_event_loop().run_until_complete(
            self.call(func, *args, **kwargs)
        )


def with_retry(config: Optional[RetryConfig] = None):
    """
    装饰器：为异步函数添加重试逻辑

    使用示例：
    ```python
    @with_retry(RetryConfig(max_retries=3))
    async def call_llm(prompt: str) -> str:
        return await llm.invoke(prompt)
    ```
    """
    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        caller = RetryableLLMCaller(config)

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await caller.call(func, *args, **kwargs)

        return wrapper
    return decorator


# ============================================================================
# 预配置的重试配置
# ============================================================================

# 默认配置（适合大多数场景）
DEFAULT_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=60.0,
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    jitter=True,
    jitter_factor=0.5,
    request_timeout=60.0,
)

# 快速模式（少重试，快失败）
FAST_RETRY_CONFIG = RetryConfig(
    max_retries=1,
    base_delay=0.5,
    max_delay=10.0,
    strategy=RetryStrategy.CONSTANT,
    jitter=True,
    jitter_factor=0.3,
    request_timeout=30.0,
)

# 保守模式（多重试，长等待）
CONSERVATIVE_RETRY_CONFIG = RetryConfig(
    max_retries=5,
    base_delay=2.0,
    max_delay=120.0,
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    jitter=True,
    jitter_factor=0.4,
    request_timeout=120.0,
)

# 限流友好模式（专门处理429错误）
RATE_LIMIT_FRIENDLY_CONFIG = RetryConfig(
    max_retries=4,
    base_delay=5.0,  # 更长的基础延迟
    max_delay=180.0,  # 更长的最大延迟
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    jitter=True,
    jitter_factor=0.6,  # 更大的抖动
    request_timeout=90.0,
)


def get_retry_config(mode: str = "default") -> RetryConfig:
    """
    获取预配置的重试配置

    Args:
        mode: 配置模式
            - "default": 默认配置
            - "fast": 快速模式
            - "conservative": 保守模式
            - "rate_limit_friendly": 限流友好模式

    Returns:
        RetryConfig 实例
    """
    configs = {
        "default": DEFAULT_RETRY_CONFIG,
        "fast": FAST_RETRY_CONFIG,
        "conservative": CONSERVATIVE_RETRY_CONFIG,
        "rate_limit_friendly": RATE_LIMIT_FRIENDLY_CONFIG,
    }
    return configs.get(mode, DEFAULT_RETRY_CONFIG)
