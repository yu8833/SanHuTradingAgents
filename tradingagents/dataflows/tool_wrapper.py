"""
工具调用包装器

包装现有工具，自动记录调用数据到 DataSourceLogger。
用于确保报告中引用的所有数字都可以追溯到源头。

使用方式：
1. 创建 DataSourceLogger 实例
2. 用 wrap_tool() 包装需要监控的工具
3. 包装后的工具调用会自动记录到 logger
"""

import logging
from typing import Any, Callable, Dict, Optional, Type
from functools import wraps

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from tradingagents.dataflows.data_source_logger import (
    DataSourceLogger,
    get_current_logger,
    create_logger
)

logger = logging.getLogger(__name__)


def wrap_tool(tool: BaseTool, data_logger: Optional[DataSourceLogger] = None) -> BaseTool:
    """
    包装 LangChain 工具，自动记录调用数据

    Args:
        tool: 要包装的 LangChain 工具
        data_logger: 数据日志器（如果不传则使用当前上下文的 logger）

    Returns:
        包装后的工具，调用时会自动记录
    """
    original_func = tool.func
    original_name = tool.name
    original_description = tool.description
    original_args_schema = tool.args_schema

    def wrapped_func(*args, **kwargs):
        _logger = data_logger or get_current_logger()

        arguments = kwargs.copy()
        if args:
            arguments["args"] = list(args)

        try:
            result = original_func(*args, **kwargs)

            if _logger:
                _logger.log_tool_call(
                    tool_name=original_name,
                    arguments=arguments,
                    result=result,
                    status="success"
                )

            return result
        except Exception as e:
            if _logger:
                _logger.log_tool_call(
                    tool_name=original_name,
                    arguments=arguments,
                    result=str(e),
                    status="error"
                )
            raise

    if hasattr(tool, 'coroutine') and tool.coroutine:
        original_coroutine = tool.coroutine

        async def wrapped_coroutine(*args, **kwargs):
            _logger = data_logger or get_current_logger()

            arguments = kwargs.copy()
            if args:
                arguments["args"] = list(args)

            try:
                result = await original_coroutine(*args, **kwargs)

                if _logger:
                    _logger.log_tool_call(
                        tool_name=original_name,
                        arguments=arguments,
                        result=result,
                        status="success"
                    )

                return result
            except Exception as e:
                if _logger:
                    _logger.log_tool_call(
                        tool_name=original_name,
                        arguments=arguments,
                        result=str(e),
                        status="error"
                    )
                raise

        return StructuredTool.from_function(
            func=wrapped_func,
            coroutine=wrapped_coroutine,
            name=original_name,
            description=original_description,
            args_schema=original_args_schema,
        )
    else:
        return StructuredTool.from_function(
            func=wrapped_func,
            name=original_name,
            description=original_description,
            args_schema=original_args_schema,
        )


def wrap_tools(tools: list, data_logger: Optional[DataSourceLogger] = None) -> list:
    """
    批量包装工具

    Args:
        tools: 工具列表
        data_logger: 数据日志器

    Returns:
        包装后的工具列表
    """
    return [wrap_tool(tool, data_logger) for tool in tools]


# ============================================================================
# 便捷函数：创建带日志的分析师环境
# ============================================================================

def create_analyst_environment(
    stock_code: str,
    analyst_name: str,
    tools: list
) -> tuple:
    """
    创建带数据日志的分析师环境

    Args:
        stock_code: 股票代码
        analyst_name: 分析师名称
        tools: 工具列表

    Returns:
        (logger, wrapped_tools) 元组
    """
    data_logger = create_logger(stock_code, analyst_name)
    wrapped_tools = wrap_tools(tools, data_logger)
    return data_logger, wrapped_tools
