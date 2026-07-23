"""
数据来源日志模块

用于记录所有工具调用的原始数据，确保分析师报告中引用的数字可以追溯到源头。
这有助于：
1. 验证报告中数据的准确性
2. 发现LLM幻觉（编造数据）
3. 审计数据来源

使用方式：
1. 在Agent初始化时创建 DataSourceLogger 实例
2. 将 logger 注入到工具函数或通过 context 传递
3. 工具调用时会自动记录到日志
4. 在prompt中引用日志生成数据来源对照表
"""

import logging
import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# 线程/异步安全的上下文变量
_data_source_logger: ContextVar[Optional['DataSourceLogger']] = ContextVar(
    'data_source_logger', default=None
)


@dataclass
class ToolCallRecord:
    """单次工具调用记录"""
    tool_name: str
    arguments: Dict[str, Any]
    result_preview: str  # 结果预览（前500字符，避免日志过大）
    result_hash: str  # 结果的哈希值，用于快速比对
    timestamp: str
    status: str = "success"  # success/error

    def to_markdown_table_row(self) -> str:
        """转换为 Markdown 表格行"""
        args_str = json.dumps(self.arguments, ensure_ascii=False)[:100]
        return f"| {self.tool_name} | {args_str}... | {self.status} | {self.timestamp} |"


@dataclass
class DataSourceLogger:
    """
    数据来源日志记录器

    线程安全，可在异步环境中使用
    """
    stock_code: str
    analyst_name: str
    call_records: List[ToolCallRecord] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def log_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Any,
        status: str = "success"
    ) -> None:
        """
        记录一次工具调用

        Args:
            tool_name: 工具名称（如 get_news, get_fundamentals）
            arguments: 工具调用参数
            result: 工具返回结果（会自动截断）
            status: 调用状态（success/error）
        """
        # 生成结果预览（限制长度）
        if isinstance(result, str):
            result_preview = result[:500] if len(result) > 500 else result
        else:
            result_preview = str(result)[:500] if result else ""

        # 生成简单哈希用于比对（不存储完整结果）
        import hashlib
        result_hash = hashlib.md5(str(result).encode()).hexdigest()[:8]

        record = ToolCallRecord(
            tool_name=tool_name,
            arguments=arguments,
            result_preview=result_preview,
            result_hash=result_hash,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            status=status
        )
        self.call_records.append(record)
        logger.debug(f"📊 [数据日志] {self.analyst_name} 调用 {tool_name}")

    def generate_source_table(self) -> str:
        """
        生成数据来源对照表（Markdown格式）

        Returns:
            Markdown 格式的数据来源表格
        """
        if not self.call_records:
            return "| 数据来源 | 调用参数 | 状态 | 时间 |\n|----------|----------|------|------|\n| *（无数据调用）* | - | - | - |"

        lines = [
            "| 工具名称 | 调用参数 | 状态 | 时间 |",
            "|----------|----------|------|------|"
        ]
        for record in self.call_records:
            lines.append(record.to_markdown_table_row())

        return "\n".join(lines)

    def generate_source_summary(self) -> str:
        """生成数据来源摘要"""
        tool_counts = {}
        for record in self.call_records:
            tool_counts[record.tool_name] = tool_counts.get(record.tool_name, 0) + 1

        summary_parts = [f"**数据来源摘要**（{self.stock_code} - {self.analyst_name}）"]
        summary_parts.append(f"- 调用工具数：{len(tool_counts)}")
        summary_parts.append(f"- 总调用次数：{len(self.call_records)}")
        for tool, count in sorted(tool_counts.items()):
            summary_parts.append(f"  - {tool}: {count}次")

        return "\n".join(summary_parts)

    def get_all_sources_markdown(self) -> str:
        """获取完整的数据来源信息（用于插入到prompt中）"""
        return f"""
---

## 📋 数据来源对照表

{self.generate_source_summary()}

### 详细调用记录

{self.generate_source_table()}

**注**：报告中引用的所有数字必须来自上述数据来源表中的一项或多项。
如发现报告中引用的数字无法在上述数据中找到，请标注 [数据待核实]。
"""

    def clear(self) -> None:
        """清空记录"""
        self.call_records.clear()


# ============================================================================
# 便捷函数
# ============================================================================

def get_current_logger() -> Optional[DataSourceLogger]:
    """获取当前上下文的数据日志器"""
    return _data_source_logger.get()


def set_current_logger(logger: Optional[DataSourceLogger]) -> None:
    """设置当前上下文的数据日志器"""
    _data_source_logger.set(logger)


def create_logger(stock_code: str, analyst_name: str) -> DataSourceLogger:
    """创建新的数据日志器并设置为当前上下文"""
    new_logger = DataSourceLogger(stock_code=stock_code, analyst_name=analyst_name)
    _data_source_logger.set(new_logger)
    return new_logger
