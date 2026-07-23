"""
LLM客户端重试包装器

为现有的 LLM 客户端添加统一的重试机制。
通过装饰器或包装器方式集成 RetryableLLMCaller。

使用示例：

1. 使用装饰器方式：
```python
from tradingagents.llm_clients.retry_wrapper import with_llm_retry

class MyLLMClient:
    @with_llm_retry()
    async def invoke(self, prompt):
        return await self._llm.invoke(prompt)
```

2. 使用包装器方式：
```python
from tradingagents.llm_clients.retry_wrapper import RetryableLLMWrapper

llm = RetryableLLMWrapper(
    base_llm=original_llm,
    retry_config=get_retry_config("default")
)

result = await llm.invoke(prompt)
```

3. 在 LangChain 中使用：
```python
from tradingagents.llm_clients.retry_wrapper import wrap_llm_with_retry

retrying_llm = wrap_llm_with_retry(llm)
chain = LLMChain(llm=retrying_llm, prompt=prompt)
```

4. 直接在调用时指定配置：
```python
from tradingagents.llm_clients.retry_wrapper import RetryableLLMCaller

caller = RetryableLLMCaller(get_retry_config("fast"))
result = await caller.call(llm.invoke, prompt)
```
"""

import asyncio
import logging
from typing import Any, Callable, Optional, Awaitable
from functools import wraps

from .retry_strategy import (
    RetryConfig,
    RetryableLLMCaller,
    get_retry_config,
    RetryStrategy,
    RetryStats,
)

logger = logging.getLogger(__name__)


def with_llm_retry(
    config: Optional[RetryConfig] = None,
    mode: str = "default"
):
    """
    装饰器：为异步 LLM 调用添加重试逻辑

    Args:
        config: 直接传入 RetryConfig 对象
        mode: 预设模式 ("default", "fast", "conservative", "rate_limit_friendly")

    Returns:
        装饰后的函数

    示例：
    ```python
    class MyClient:
        @with_llm_retry(mode="fast")
        async def call_llm(self, prompt: str) -> str:
            return await self.llm.invoke(prompt)
    ```
    """
    retry_config = config or get_retry_config(mode)

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        caller = RetryableLLMCaller(retry_config)

        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            logger.debug(f"调用 {func.__name__} (重试配置: {mode})")
            return await caller.call(func, *args, **kwargs)

        # 添加统计信息属性
        wrapper.retry_stats = caller.stats

        return wrapper

    return decorator


class RetryableLLMWrapper:
    """
    可重试的 LLM 包装器

    将任何 LLM 实例包装为支持重试的版本。
    保持原 LLM 的所有接口不变，只在调用层面添加重试逻辑。
    """

    def __init__(
        self,
        base_llm: Any,
        retry_config: Optional[RetryConfig] = None,
        mode: str = "default"
    ):
        """
        初始化包装器

        Args:
            base_llm: 基础 LLM 实例（如 ChatOpenAI）
            retry_config: 自定义重试配置
            mode: 预设模式（当 retry_config 为 None 时生效）
        """
        self._base_llm = base_llm
        self._caller = RetryableLLMCaller(retry_config or get_retry_config(mode))

    @property
    def stats(self) -> RetryStats:
        """获取重试统计信息"""
        return self._caller.stats

    @property
    def config(self) -> RetryConfig:
        """获取重试配置"""
        return self._caller.config

    async def invoke(self, input: Any, **kwargs) -> Any:
        """带重试的 invoke 调用"""
        return await self._caller.call(self._base_llm.invoke, input, **kwargs)

    async def ainvoke(self, input: Any, **kwargs) -> Any:
        """带重试的 ainvoke 调用"""
        return await self._caller.call(self._base_llm.ainvoke, input, **kwargs)

    async def batch(self, inputs: list, **kwargs) -> list:
        """带重试的 batch 调用"""
        results = []
        for inp in inputs:
            result = await self.invoke(inp, **kwargs)
            results.append(result)
        return results

    def __getattr__(self, name: str) -> Any:
        """代理其他方法到基础 LLM"""
        return getattr(self._base_llm, name)

    def __repr__(self) -> str:
        return f"RetryableLLMWrapper(base={self._base_llm!r}, mode={self.config.strategy.value})"


def wrap_llm_with_retry(
    llm: Any,
    retry_config: Optional[RetryConfig] = None,
    mode: str = "default"
) -> RetryableLLMWrapper:
    """
    便捷函数：包装 LLM 实例为支持重试的版本

    Args:
        llm: 基础 LLM 实例
        retry_config: 自定义重试配置
        mode: 预设模式

    Returns:
        RetryableLLMWrapper 实例

    示例：
    ```python
    from tradingagents.llm_clients import create_llm_client
    from tradingagents.llm_clients.retry_wrapper import wrap_llm_with_retry

    # 创建基础 LLM
    base_llm = create_llm_client(...).get_llm()

    # 包装为支持重试的版本
    retrying_llm = wrap_llm_with_retry(base_llm, mode="conservative")

    # 使用方式与原 LLM 完全相同
    result = await retrying_llm.invoke(prompt)
    ```
    """
    return RetryableLLMWrapper(llm, retry_config, mode)


# ============================================================================
# LangChain 兼容层
# ============================================================================

class RetryableLLM(RetryableLLMWrapper):
    """
    LangChain 兼容的 Retryable LLM

    继承自 RetryableLLMWrapper，添加 LangChain 所需的标准方法。
    """

    def invoke(self, input: Any, config: Any = None, **kwargs) -> Any:
        """同步调用（LangChain 标准接口）"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果已经在事件循环中，创建一个任务
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._caller.call(self._base_llm.invoke, input, **kwargs)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(
                    self._caller.call(self._base_llm.invoke, input, **kwargs)
                )
        except RuntimeError:
            # 没有事件循环，创建一个新的
            return asyncio.run(
                self._caller.call(self._base_llm.invoke, input, **kwargs)
            )

    async def ainvoke(self, input: Any, config: Any = None, **kwargs) -> Any:
        """异步调用（LangChain AsyncLLM 接口）"""
        return await self._caller.call(self._base_llm.ainvoke, input, **kwargs)


def create_retrying_llm(
    llm: Any,
    retry_config: Optional[RetryConfig] = None,
    mode: str = "default"
) -> RetryableLLM:
    """
    创建 LangChain 兼容的 Retryable LLM

    Args:
        llm: 基础 LLM 实例
        retry_config: 自定义重试配置
        mode: 预设模式

    Returns:
        RetryableLLM 实例（继承自 base_llm 的类型）

    示例：
    ```python
    base_llm = ChatOpenAI(model="gpt-4")
    retrying_llm = create_retrying_llm(base_llm, mode="rate_limit_friendly")

    # 在 LangChain Chain 中使用
    chain = LLMChain(llm=retrying_llm, prompt=prompt)
    ```
    """
    # 创建一个继承自 base_llm 类型的新类
    class ConfigurableRetryLLM(RetryableLLM):
        pass

    wrapper = RetryableLLMWrapper(llm, retry_config, mode)

    # 复制类型信息
    ConfigurableRetryLLM.__name__ = f"Retryable{llm.__class__.__name__}"
    ConfigurableRetryLLM.__qualname__ = f"Retryable{llm.__class__.__qualname__}"

    return ConfigurableRetryLLM(wrapper._base_llm, wrapper.config)


# ============================================================================
# 配置集成
# ============================================================================

def update_llm_config_with_retry(
    config_dict: dict,
    retry_mode: str = "default"
) -> dict:
    """
    在 LLM 配置中添加重试参数

    用于从配置文件或数据库读取配置后，添加重试相关参数。

    Args:
        config_dict: 原始配置字典
        retry_mode: 重试模式

    Returns:
        更新后的配置字典
    """
    retry_config = get_retry_config(retry_mode)

    return {
        **config_dict,
        "max_retries": retry_config.max_retries,
        "request_timeout": retry_config.request_timeout,
    }
