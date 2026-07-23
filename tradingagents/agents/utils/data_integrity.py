"""
分析师数据完整性检查模块

用于评估分析师执行过程中数据的完整性，确保分析结论建立在可靠的数据基础上。

主要功能：
1. 定义各分析师的核心工具依赖
2. 评估工具调用成功/失败情况
3. 生成数据完整性报告
4. 根据完整性级别决定是否继续分析流程
"""

import logging
from enum import Enum
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


class DataIntegrityLevel(Enum):
    """数据完整性级别"""
    COMPLETE = "complete"           # 完整：所有核心数据可用
    PARTIAL = "partial"            # 部分：部分核心数据可用
    CRITICAL_MISSING = "critical"  # 关键缺失：核心数据缺失超过阈值
    COMPLETE_FAILURE = "failure"  # 完全失败：分析师执行异常


class DataAvailability(Enum):
    """数据可用性状态"""
    AVAILABLE = "available"        # 数据可用
    UNAVAILABLE = "unavailable"    # 数据不可用（工具调用失败）
    EMPTY_RESULT = "empty_result"  # 工具调用成功但返回空结果
    TIMEOUT = "timeout"           # 数据获取超时
    ERROR = "error"               # 其他错误


@dataclass
class ToolCallResult:
    """单次工具调用结果"""
    tool_name: str
    status: DataAvailability
    error_message: Optional[str] = None
    result_preview: Optional[str] = None
    is_core_tool: bool = False

    @property
    def is_success(self) -> bool:
        return self.status == DataAvailability.AVAILABLE

    @property
    def is_core_failure(self) -> bool:
        """核心工具调用失败"""
        return self.is_core_tool and not self.is_success


@dataclass
class AnalystIntegrityReport:
    """分析师数据完整性报告"""
    analyst_type: str
    analyst_name: str
    integrity_level: DataIntegrityLevel
    total_calls: int
    successful_calls: int
    failed_calls: int
    core_tool_results: Dict[str, ToolCallResult]
    all_tool_results: Dict[str, ToolCallResult]
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.successful_calls / self.total_calls

    @property
    def core_success_rate(self) -> float:
        """核心工具成功率"""
        if not self.core_tool_results:
            return 1.0
        core_success = sum(1 for r in self.core_tool_results.values() if r.is_success)
        return core_success / len(self.core_tool_results)

    @property
    def can_proceed(self) -> bool:
        """是否可以继续分析流程"""
        return self.integrity_level in [
            DataIntegrityLevel.COMPLETE,
            DataIntegrityLevel.PARTIAL
        ]

    @property
    def quality_label(self) -> str:
        """质量标签"""
        labels = {
            DataIntegrityLevel.COMPLETE: "高质量",
            DataIntegrityLevel.PARTIAL: "中等质量",
            DataIntegrityLevel.CRITICAL_MISSING: "低质量",
            DataIntegrityLevel.COMPLETE_FAILURE: "分析失败"
        }
        return labels.get(self.integrity_level, "未知")

    def to_markdown(self) -> str:
        """生成 Markdown 格式的报告"""
        lines = [
            f"## 📊 {self.analyst_name} 数据完整性报告",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 完整性级别 | {self.quality_label} |",
            f"| 总调用次数 | {self.total_calls} |",
            f"| 成功调用 | {self.successful_calls} |",
            f"| 失败调用 | {self.failed_calls} |",
            f"| 成功率 | {self.success_rate:.1%} |",
            f"| 核心工具成功率 | {self.core_success_rate:.1%} |",
            "",
            "### 核心工具调用详情",
            ""
        ]

        if self.core_tool_results:
            lines.extend([
                "| 工具名称 | 状态 | 错误信息 |",
                "|----------|------|----------|"
            ])
            for tool_name, result in self.core_tool_results.items():
                status_icon = "✅" if result.is_success else "❌"
                error = result.error_message[:50] if result.error_message else "-"
                lines.append(f"| {tool_name} | {status_icon} {result.status.value} | {error} |")
        else:
            lines.append("*（无核心工具调用）*")

        if self.warnings:
            lines.extend(["", "### ⚠️ 警告", ""])
            for warning in self.warnings:
                lines.append(f"- {warning}")

        if self.recommendations:
            lines.extend(["", "### 💡 建议", ""])
            for rec in self.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)


# ============================================================================
# 分析师核心工具定义
# ============================================================================

# 各分析师的核心工具（缺少这些工具数据，分析质量会显著下降）
ANALYST_CORE_TOOLS: Dict[str, List[str]] = {
    "market": [
        "get_indicators",        # 技术指标 - 核心
        "get_stock_data",        # K线数据 - 核心
    ],
    "social": [
        "get_news",              # 新闻数据 - 核心
        "get_global_news",      # 全球新闻 - 辅助
        "get_fund_flow",        # 资金流向 - 辅助（散户行为分析）
        "get_margin_trading",   # 融资融券 - 辅助（散户杠杆情绪）
    ],
    "news": [
        "get_news",              # 新闻数据 - 核心
    ],
    "fundamentals": [
        "get_fundamentals",      # 基本面数据 - 核心
        "get_income_statement", # 利润表 - 重要
        "get_balance_sheet",    # 资产负债表 - 重要
    ],
    "policy": [
        "get_news",              # 政策新闻 - 核心（通过新闻接口获取）
        "get_global_news",      # 宏观政策新闻 - 辅助
    ],
    "hot_money": [
        "get_hot_stocks",        # 热门股票 - 核心
        "get_fund_flow",        # 资金流向 - 核心
        "get_dragon_tiger_board", # 龙虎榜 - 核心
        "get_northbound_flow",   # 北向资金 - 辅助
    ],
    "lockup": [
        "get_lockup_expiry",     # 解禁数据 - 核心（唯一来源）
    ],
}

# 分析师中文名称映射
ANALYST_NAMES_CN: Dict[str, str] = {
    "market": "技术分析师",
    "social": "市场情绪分析师",
    "news": "新闻分析师",
    "fundamentals": "基本面分析师",
    "policy": "政策分析师",
    "hot_money": "游资追踪师",
    "lockup": "解禁追踪师",
}

# 核心工具失败阈值（超过此比例认为关键数据缺失）
CORE_TOOL_FAILURE_THRESHOLD = 0.5  # 50%


# ============================================================================
# 数据完整性评估器
# ============================================================================

class DataIntegrityEvaluator:
    """
    数据完整性评估器

    使用方式：
    1. 在分析师开始执行时创建评估器
    2. 每次工具调用后记录结果
    3. 分析完成后生成完整性报告
    4. 根据报告决定后续流程
    """

    def __init__(self, analyst_type: str):
        self.analyst_type = analyst_type
        self.analyst_name = ANALYST_NAMES_CN.get(analyst_type, analyst_type)
        self._tool_results: List[ToolCallResult] = []
        self._core_tools = set(ANALYST_CORE_TOOLS.get(analyst_type, []))

    @property
    def core_tools(self) -> Set[str]:
        return self._core_tools

    def record_tool_call(
        self,
        tool_name: str,
        status: DataAvailability,
        error_message: Optional[str] = None,
        result_preview: Optional[str] = None,
    ) -> None:
        """记录一次工具调用结果"""
        is_core = tool_name in self._core_tools

        result = ToolCallResult(
            tool_name=tool_name,
            status=status,
            error_message=error_message,
            result_preview=result_preview,
            is_core_tool=is_core,
        )
        self._tool_results.append(result)

        # 记录日志
        status_icon = "✅" if status == DataAvailability.AVAILABLE else "❌"
        core_marker = "🔴" if is_core else "  "
        logger.debug(
            f"{core_marker} [{self.analyst_name}] {status_icon} {tool_name}: {status.value}"
        )

        if error_message and is_core:
            logger.warning(
                f"⚠️ [{self.analyst_name}] 核心工具 {tool_name} 调用失败: {error_message}"
            )

    def record_success(self, tool_name: str, result_preview: Optional[str] = None) -> None:
        """便捷方法：记录成功调用"""
        self.record_tool_call(tool_name, DataAvailability.AVAILABLE, result_preview=result_preview)

    def record_failure(
        self,
        tool_name: str,
        error_message: str,
        status: DataAvailability = DataAvailability.ERROR,
    ) -> None:
        """便捷方法：记录失败调用"""
        self.record_tool_call(tool_name, status, error_message=error_message)

    def record_timeout(self, tool_name: str, error_message: str) -> None:
        """便捷方法：记录超时"""
        self.record_tool_call(
            tool_name,
            DataAvailability.TIMEOUT,
            error_message=error_message
        )

    def record_empty_result(self, tool_name: str) -> None:
        """便捷方法：记录空结果"""
        self.record_tool_call(
            tool_name,
            DataAvailability.EMPTY_RESULT,
            error_message="工具返回空结果"
        )

    def assess_integrity(self) -> AnalystIntegrityReport:
        """评估数据完整性并生成报告"""
        # 分类工具调用结果
        all_results = {r.tool_name: r for r in self._tool_results}
        core_results = {
            name: result
            for name, result in all_results.items()
            if name in self._core_tools
        }

        # 统计
        total_calls = len(self._tool_results)
        successful_calls = sum(1 for r in self._tool_results if r.is_success)
        failed_calls = total_calls - successful_calls

        # 核心工具失败情况
        core_failed = [r for r in core_results.values() if not r.is_success]
        core_total = len(core_results)

        # 确定完整性级别
        if total_calls == 0:
            integrity_level = DataIntegrityLevel.COMPLETE_FAILURE
        elif failed_calls == total_calls:
            integrity_level = DataIntegrityLevel.COMPLETE_FAILURE
        elif core_total > 0 and len(core_failed) / core_total >= CORE_TOOL_FAILURE_THRESHOLD:
            integrity_level = DataIntegrityLevel.CRITICAL_MISSING
        elif failed_calls > 0:
            integrity_level = DataIntegrityLevel.PARTIAL
        else:
            integrity_level = DataIntegrityLevel.COMPLETE

        # 生成警告和建议
        warnings, recommendations = self._generate_feedback(
            integrity_level, core_failed, failed_calls, total_calls
        )

        return AnalystIntegrityReport(
            analyst_type=self.analyst_type,
            analyst_name=self.analyst_name,
            integrity_level=integrity_level,
            total_calls=total_calls,
            successful_calls=successful_calls,
            failed_calls=failed_calls,
            core_tool_results=core_results,
            all_tool_results=all_results,
            warnings=warnings,
            recommendations=recommendations,
        )

    def _generate_feedback(
        self,
        level: DataIntegrityLevel,
        core_failed: List[ToolCallResult],
        failed_calls: int,
        total_calls: int,
    ) -> Tuple[List[str], List[str]]:
        """生成警告和建议"""
        warnings = []
        recommendations = []

        if level == DataIntegrityLevel.COMPLETE_FAILURE:
            warnings.append("分析师执行完全失败，无有效数据")
            recommendations.append("建议检查网络连接和数据源可用性")
            recommendations.append("可能需要重试分析或降级使用缓存数据")

        elif level == DataIntegrityLevel.CRITICAL_MISSING:
            failed_tools = [r.tool_name for r in core_failed]
            warnings.append(f"核心工具调用失败: {', '.join(failed_tools)}")
            warnings.append("分析结论可靠性显著下降")

            recommendations.append("在分析报告中明确标注数据缺失情况")
            recommendations.append("结论应降低置信度，仅供参考")
            recommendations.append("建议手动补充关键数据后重新分析")

        elif level == DataIntegrityLevel.PARTIAL:
            if core_failed:
                failed_tools = [r.tool_name for r in core_failed]
                warnings.append(f"部分核心工具调用失败: {', '.join(failed_tools)}")

            failure_rate = failed_calls / total_calls if total_calls > 0 else 0
            if failure_rate > 0.3:
                warnings.append(f"工具调用失败率较高: {failure_rate:.1%}")

            recommendations.append("分析结论有一定参考价值")
            recommendations.append("建议关注报告中标注的数据缺失部分")

        else:  # COMPLETE
            recommendations.append("数据完整，分析结论可靠性较高")

        return warnings, recommendations

    def get_unavailable_core_tools(self) -> List[str]:
        """获取不可用的核心工具列表"""
        return [
            r.tool_name
            for r in self._tool_results
            if r.is_core_failure
        ]

    def should_abort_analysis(self) -> Tuple[bool, str]:
        """
        判断是否应该终止分析流程

        Returns:
            (should_abort, reason)
        """
        report = self.assess_integrity()

        if report.integrity_level == DataIntegrityLevel.COMPLETE_FAILURE:
            return True, "分析师执行完全失败"

        if report.integrity_level == DataIntegrityLevel.CRITICAL_MISSING:
            unavailable = self.get_unavailable_core_tools()
            return False, f"核心数据缺失但继续分析: {', '.join(unavailable)}"

        return False, ""


# ============================================================================
# 批量分析师完整性管理器
# ============================================================================

class BatchIntegrityManager:
    """
    批量分析师完整性管理器

    用于管理多个分析师的完整性状态，
    生成整体数据质量报告。
    """

    def __init__(self):
        self._evaluators: Dict[str, DataIntegrityEvaluator] = {}
        self._reports: Dict[str, AnalystIntegrityReport] = {}

    def get_evaluator(self, analyst_type: str) -> DataIntegrityEvaluator:
        """获取指定分析师的评估器"""
        if analyst_type not in self._evaluators:
            self._evaluators[analyst_type] = DataIntegrityEvaluator(analyst_type)
        return self._evaluators[analyst_type]

    def assess_all(self) -> Dict[str, AnalystIntegrityReport]:
        """评估所有分析师的完整性"""
        self._reports = {
            analyst_type: evaluator.assess_integrity()
            for analyst_type, evaluator in self._evaluators.items()
        }
        return self._reports

    def get_overall_quality(self) -> Tuple[float, str]:
        """
        获取整体数据质量评分

        Returns:
            (quality_score, quality_label)
            - quality_score: 0.0-1.0 的评分
            - quality_label: 质量等级描述
        """
        if not self._reports:
            return 0.0, "未评估"

        # 计算加权分数（核心分析师权重更高）
        analyst_weights = {
            "market": 1.5,        # 技术分析权重最高
            "fundamentals": 1.3,  # 基本面次之
            "news": 1.0,
            "social": 0.8,
            "policy": 0.7,
            "hot_money": 0.6,
            "lockup": 0.5,
        }

        total_weight = 0.0
        weighted_score = 0.0

        for analyst_type, report in self._reports.items():
            weight = analyst_weights.get(analyst_type, 1.0)

            # 根据完整性级别计算得分
            level_scores = {
                DataIntegrityLevel.COMPLETE: 1.0,
                DataIntegrityLevel.PARTIAL: 0.6,
                DataIntegrityLevel.CRITICAL_MISSING: 0.3,
                DataIntegrityLevel.COMPLETE_FAILURE: 0.0,
            }
            score = level_scores.get(report.integrity_level, 0.5)

            weighted_score += score * weight
            total_weight += weight

        overall_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # 确定质量标签
        if overall_score >= 0.85:
            label = "优秀"
        elif overall_score >= 0.70:
            label = "良好"
        elif overall_score >= 0.50:
            label = "一般"
        elif overall_score >= 0.30:
            label = "较差"
        else:
            label = "很差"

        return overall_score, label

    def should_proceed_to_debate(self) -> Tuple[bool, str]:
        """
        判断是否应该进入辩论阶段

        只有核心分析师（market, fundamentals, news）的数据质量达标，
        才进入辩论流程。
        """
        core_analysts = ["market", "fundamentals", "news"]
        critical_failures = []

        for analyst_type in core_analysts:
            if analyst_type in self._reports:
                report = self._reports[analyst_type]
                if report.integrity_level in [
                    DataIntegrityLevel.COMPLETE_FAILURE,
                    DataIntegrityLevel.CRITICAL_MISSING,
                ]:
                    critical_failures.append(f"{report.analyst_name}: {report.quality_label}")

        if critical_failures:
            return False, f"关键分析师数据不足: {', '.join(critical_failures)}"

        return True, ""

    def generate_summary_report(self) -> str:
        """生成整体质量摘要报告"""
        if not self._reports:
            return "## 📋 数据质量摘要\n\n*（暂无评估数据）*"

        overall_score, overall_label = self.get_overall_quality()
        can_proceed, proceed_reason = self.should_proceed_to_debate()

        lines = [
            "## 📋 分析师数据质量摘要",
            "",
            f"| 整体评分 | {overall_score:.0%} ({overall_label}) |",
            f"| 进入辩论 | {'✅ 是' if can_proceed else '❌ 否'} |",
        ]

        if proceed_reason:
            lines.append(f"| 原因 | {proceed_reason} |")

        lines.extend(["", "### 各分析师详情", ""])
        lines.extend([
            "| 分析师 | 完整性 | 核心成功率 | 状态 |",
            "|--------|--------|-----------|------|"
        ])

        for analyst_type in ["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"]:
            if analyst_type in self._reports:
                report = self._reports[analyst_type]
                icon = "✅" if report.can_proceed else "❌"
                lines.append(
                    f"| {report.analyst_name} | {report.quality_label} | "
                    f"{report.core_success_rate:.0%} | {icon} |"
                )

        return "\n".join(lines)
