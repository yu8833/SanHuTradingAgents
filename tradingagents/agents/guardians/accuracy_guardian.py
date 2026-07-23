"""
准确性守护者节点 (Accuracy Guardian Node)

在最终交易决策生成前进行质量把关，
评估数据完整性、辩论质量、风控一致性，
生成置信度标签和警告信息。

主要功能：
1. 评估分析师报告的数据完整性
2. 评估辩论收敛度和质量
3. 检查风控辩论的一致性
4. 生成综合质量分数和置信度标签
5. 提供决策建议和警告信息

使用方式：
- 在 Portfolio Manager 生成最终决策后调用
- 将质量报告添加到最终决策中
- 作为报告展示的一部分

位置：tradingagents/agents/guardians/accuracy_guardian.py
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import re

from tradingagents.agents.utils.data_integrity import (
    DataIntegrityLevel,
    AnalystIntegrityReport,
)
from tradingagents.agents.utils.debate_convergence import (
    ConvergenceLevel,
    DebateConvergenceReport,
)

logger = logging.getLogger(__name__)


class QualityGrade(Enum):
    """质量等级"""
    A = "优秀"      # 高数据质量、辩论收敛、风控一致
    B = "良好"      # 数据质量较好、辩论部分收敛
    C = "一般"      # 有一些数据缺失或辩论疲劳
    D = "较差"      # 关键数据缺失或辩论未收敛
    F = "很差"      # 严重问题，结论不可靠


class ConfidenceLevel(Enum):
    """置信度级别"""
    HIGH = "高置信度"        # 可作为决策参考
    MEDIUM = "中等置信度"    # 可参考但需关注风险
    LOW = "低置信度"         # 仅供参考，需验证
    VERY_LOW = "谨慎参考"    # 结论可靠性低，需谨慎决策
    UNRELIABLE = "不可靠"    # 数据质量太差，不建议参考


@dataclass
class ComponentQuality:
    """单个组件的质量评估"""
    component_name: str
    quality_score: float      # 0-1
    issues: List[str]         # 发现的问题
    weight: float             # 权重
    recommendations: List[str]  # 建议


@dataclass
class AccuracyGuardianReport:
    """准确性守护者报告"""
    # 整体评估
    overall_quality_score: float
    quality_grade: QualityGrade
    confidence_level: ConfidenceLevel

    # 各组件评估
    data_quality: ComponentQuality           # 数据质量
    debate_quality: ComponentQuality         # 辩论质量
    risk_consistency: ComponentQuality       # 风控一致性

    # 关键信息
    missing_analysts: List[str]              # 缺失的分析师报告
    low_quality_reports: List[str]           # 低质量报告列表
    debate_fatigue: bool                     # 是否检测到辩论疲劳
    risk_conflicts: List[str]                # 风控冲突

    # 建议
    warnings: List[str]                      # 警告信息
    recommendations: List[str]               # 建议
    decision_guidance: str                   # 决策指导

    # 是否应该信任结论
    should_trust: bool                       # 是否应该信任此结论
    trust_reason: str                        # 原因说明

    def to_summary(self) -> str:
        """生成简短摘要"""
        grade_icon = {
            QualityGrade.A: "🌟",
            QualityGrade.B: "✅",
            QualityGrade.C: "🔶",
            QualityGrade.D: "⚠️",
            QualityGrade.F: "❌",
        }.get(self.quality_grade, "❓")

        return (
            f"{grade_icon} 整体质量: {self.quality_grade.value} "
            f"(分数: {self.overall_quality_score:.0%}, 置信度: {self.confidence_level.value})"
        )

    def to_markdown(self) -> str:
        """生成 Markdown 格式的完整报告"""
        lines = [
            "# 🔍 准确性守护者报告",
            "",
            "## 整体评估",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 整体质量分数 | {self.overall_quality_score:.0%} |",
            f"| 质量等级 | {self.quality_grade.value} |",
            f"| 置信度 | {self.confidence_level.value} |",
            f"| 是否建议参考 | {'✅ 是' if self.should_trust else '❌ 否'} |",
            "",
            "## 各组件质量",
            "",
        ]

        # 数据质量
        lines.extend([
            "### 📊 数据质量",
            f"- 分数: {self.data_quality.quality_score:.0%}",
            f"- 权重: {self.data_quality.weight:.1f}",
        ])
        if self.data_quality.issues:
            lines.append("- 问题:")
            for issue in self.data_quality.issues:
                lines.append(f"  - {issue}")
        if self.data_quality.recommendations:
            lines.append("- 建议:")
            for rec in self.data_quality.recommendations:
                lines.append(f"  - {rec}")

        lines.append("")
        lines.extend([
            "### 🗣️ 辩论质量",
            f"- 分数: {self.debate_quality.quality_score:.0%}",
            f"- 权重: {self.debate_quality.weight:.1f}",
        ])
        if self.debate_quality.issues:
            lines.append("- 问题:")
            for issue in self.debate_quality.issues:
                lines.append(f"  - {issue}")
        if self.debate_quality.recommendations:
            lines.append("- 建议:")
            for rec in self.debate_quality.recommendations:
                lines.append(f"  - {rec}")

        lines.append("")
        lines.extend([
            "### 🛡️ 风控一致性",
            f"- 分数: {self.risk_consistency.quality_score:.0%}",
            f"- 权重: {self.risk_consistency.weight:.1f}",
        ])
        if self.risk_consistency.issues:
            lines.append("- 问题:")
            for issue in self.risk_consistency.issues:
                lines.append(f"  - {issue}")
        if self.risk_consistency.recommendations:
            lines.append("- 建议:")
            for rec in self.risk_consistency.recommendations:
                lines.append(f"  - {rec}")

        # 关键信息
        lines.extend([
            "",
            "## 🔑 关键信息",
            "",
        ])

        if self.missing_analysts:
            lines.append(f"- 缺失分析师: {', '.join(self.missing_analysts)}")

        if self.low_quality_reports:
            lines.append(f"- 低质量报告: {', '.join(self.low_quality_reports)}")

        if self.debate_fatigue:
            lines.append("- ⚠️ 检测到辩论疲劳")

        if self.risk_conflicts:
            lines.append("- 风控冲突:")
            for conflict in self.risk_conflicts:
                lines.append(f"  - {conflict}")

        # 警告和建议
        lines.extend([
            "",
            "## ⚠️ 警告",
            "",
        ])

        if self.warnings:
            for warning in self.warnings:
                lines.append(f"- {warning}")
        else:
            lines.append("*（无警告）*")

        lines.extend([
            "",
            "## 💡 建议",
            "",
        ])

        if self.recommendations:
            for rec in self.recommendations:
                lines.append(f"- {rec}")
        else:
            lines.append("*（无特殊建议）*")

        lines.extend([
            "",
            "## 📋 决策指导",
            "",
            self.decision_guidance,
        ])

        return "\n".join(lines)


# ============================================================================
# 各分析师报告的权重定义
# ============================================================================

ANALYST_REPORT_WEIGHTS = {
    "market_report": 1.5,           # 技术分析权重最高
    "fundamentals_report": 1.3,     # 基本面次之
    "news_report": 1.0,             # 新闻分析
    "sentiment_report": 0.8,        # 情绪分析（波动大）
    "policy_report": 0.7,           # 政策分析（A股特有）
    "hot_money_report": 0.6,        # 游资追踪
    "lockup_report": 0.5,           # 解禁追踪
}

# 分析师报告字段到分析师类型的映射
REPORT_FIELD_TO_ANALYST = {
    "market_report": "market",
    "fundamentals_report": "fundamentals",
    "news_report": "news",
    "sentiment_report": "social",
    "policy_report": "policy",
    "hot_money_report": "hot_money",
    "lockup_report": "lockup",
}

# 分析师名称
REPORT_ANALYST_NAMES = {
    "market": "技术分析师",
    "fundamentals": "基本面分析师",
    "news": "新闻分析师",
    "social": "市场情绪分析师",
    "policy": "政策分析师",
    "hot_money": "游资追踪师",
    "lockup": "解禁追踪师",
}


# ============================================================================
# 准确性守护者
# ============================================================================

class AccuracyGuardian:
    """
    准确性守护者

    在最终决策生成前进行质量把关。
    """

    def __init__(
        self,
        data_quality_weight: float = 0.4,
        debate_quality_weight: float = 0.3,
        risk_consistency_weight: float = 0.3,
    ):
        """
        初始化守护者

        Args:
            data_quality_weight: 数据质量权重
            debate_quality_weight: 辩论质量权重
            risk_consistency_weight: 风控一致性权重
        """
        self.data_quality_weight = data_quality_weight
        self.debate_quality_weight = debate_quality_weight
        self.risk_consistency_weight = risk_consistency_weight

    def assess_conclusion_quality(
        self,
        state: Dict[str, Any],
        integrity_reports: Optional[Dict[str, AnalystIntegrityReport]] = None,
        debate_reports: Optional[Dict[str, DebateConvergenceReport]] = None,
    ) -> AccuracyGuardianReport:
        """
        评估最终结论质量

        Args:
            state: AgentState 状态
            integrity_reports: 数据完整性报告（来自 BatchIntegrityManager）
            debate_reports: 辩论收敛度报告（来自 DebateConvergenceManager）

        Returns:
            AccuracyGuardianReport 完整的质量报告
        """
        # 1. 评估数据质量
        data_quality = self._assess_data_quality(state, integrity_reports)

        # 2. 评估辩论质量
        debate_quality = self._assess_debate_quality(state, debate_reports)

        # 3. 评估风控一致性
        risk_consistency = self._assess_risk_consistency(state)

        # 4. 计算综合质量分数
        overall_score = self._calculate_overall_score(
            data_quality,
            debate_quality,
            risk_consistency,
        )

        # 5. 确定质量等级和置信度
        quality_grade = self._determine_quality_grade(overall_score, data_quality)
        confidence_level = self._determine_confidence_level(overall_score, data_quality)

        # 6. 收集关键信息
        missing_analysts = self._find_missing_analysts(state)
        low_quality_reports = self._find_low_quality_reports(state)
        debate_fatigue = self._check_debate_fatigue(debate_reports)
        risk_conflicts = self._find_risk_conflicts(state)

        # 7. 生成警告和建议
        warnings = self._generate_warnings(
            data_quality, debate_quality, risk_consistency,
            missing_analysts, low_quality_reports, debate_fatigue, risk_conflicts,
        )
        recommendations = self._generate_recommendations(
            data_quality, debate_quality, risk_consistency,
            missing_analysts, low_quality_reports,
        )

        # 8. 决策指导
        decision_guidance = self._generate_decision_guidance(
            quality_grade, confidence_level, warnings,
        )

        # 9. 是否应该信任结论
        should_trust, trust_reason = self._should_trust_conclusion(
            quality_grade, confidence_level, data_quality, debate_quality,
        )

        return AccuracyGuardianReport(
            overall_quality_score=overall_score,
            quality_grade=quality_grade,
            confidence_level=confidence_level,
            data_quality=data_quality,
            debate_quality=debate_quality,
            risk_consistency=risk_consistency,
            missing_analysts=missing_analysts,
            low_quality_reports=low_quality_reports,
            debate_fatigue=debate_fatigue,
            risk_conflicts=risk_conflicts,
            warnings=warnings,
            recommendations=recommendations,
            decision_guidance=decision_guidance,
            should_trust=should_trust,
            trust_reason=trust_reason,
        )

    def _assess_data_quality(
        self,
        state: Dict[str, Any],
        integrity_reports: Optional[Dict[str, AnalystIntegrityReport]] = None,
    ) -> ComponentQuality:
        """评估数据质量"""
        issues = []
        recommendations = []
        total_weight = 0.0
        weighted_score = 0.0

        # 从完整性报告中获取分数（如果有）
        if integrity_reports:
            for report_field, weight in ANALYST_REPORT_WEIGHTS.items():
                analyst_type = REPORT_FIELD_TO_ANALYST.get(report_field, "")
                if analyst_type in integrity_reports:
                    report = integrity_reports[analyst_type]
                    level_scores = {
                        DataIntegrityLevel.COMPLETE: 1.0,
                        DataIntegrityLevel.PARTIAL: 0.6,
                        DataIntegrityLevel.CRITICAL_MISSING: 0.3,
                        DataIntegrityLevel.COMPLETE_FAILURE: 0.0,
                    }
                    score = level_scores.get(report.integrity_level, 0.5)
                    weighted_score += score * weight
                    total_weight += weight

                    # 收集问题
                    if report.integrity_level == DataIntegrityLevel.CRITICAL_MISSING:
                        issues.append(f"{REPORT_ANALYST_NAMES.get(analyst_type, analyst_type)}: 关键数据缺失")
                    elif report.integrity_level == DataIntegrityLevel.COMPLETE_FAILURE:
                        issues.append(f"{REPORT_ANALYST_NAMES.get(analyst_type, analyst_type)}: 分析失败")
        else:
            # 从 state 中直接检查报告
            for report_field, weight in ANALYST_REPORT_WEIGHTS.items():
                report_content = state.get(report_field, "")

                if not report_content:
                    score = 0.0
                    issues.append(f"{report_field} 缺失")
                elif "[分析失败]" in report_content or "[❌ 分析失败]" in report_content:
                    score = 0.0
                    issues.append(f"{report_field} 分析失败")
                elif "[关键数据缺失]" in report_content or "[⚠️ 关键数据缺失]" in report_content:
                    score = 0.3
                    issues.append(f"{report_field} 关键数据缺失")
                elif "[数据不完整]" in report_content or "[🔶 部分数据缺失]" in report_content:
                    score = 0.6
                    issues.append(f"{report_field} 部分数据缺失")
                else:
                    score = 1.0

                weighted_score += score * weight
                total_weight += weight

        final_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # 生成建议
        if final_score < 0.5:
            recommendations.append("建议重新执行分析，补充缺失数据")
        elif final_score < 0.7:
            recommendations.append("建议关注报告中标注的数据缺失部分")

        return ComponentQuality(
            component_name="数据质量",
            quality_score=final_score,
            issues=issues,
            weight=self.data_quality_weight,
            recommendations=recommendations,
        )

    def _assess_debate_quality(
        self,
        state: Dict[str, Any],
        debate_reports: Optional[Dict[str, DebateConvergenceReport]] = None,
    ) -> ComponentQuality:
        """评估辩论质量"""
        issues = []
        recommendations = []
        score = 0.0

        if debate_reports:
            inv_report = debate_reports.get("investment")
            risk_report = debate_reports.get("risk")

            if inv_report:
                level_scores = {
                    ConvergenceLevel.CONVERGED: 1.0,
                    ConvergenceLevel.NARROWING: 0.8,
                    ConvergenceLevel.STABLE: 0.6,
                    ConvergenceLevel.DIVERGING: 0.4,
                    ConvergenceLevel.FATIGUE: 0.2,
                }
                inv_score = level_scores.get(inv_report.convergence_level, 0.5)

                if inv_report.fatigue_detected:
                    issues.append("投资辩论出现疲劳迹象")
                    recommendations.append("多空观点未收敛，结论可能存在偏差")

                score += inv_score * 0.5  # 投资辩论权重 50%
            else:
                score += 0.5 * 0.5  # 默认中等分数
                issues.append("缺少投资辩论收敛度报告")

            if risk_report:
                level_scores = {
                    ConvergenceLevel.CONVERGED: 1.0,
                    ConvergenceLevel.NARROWING: 0.8,
                    ConvergenceLevel.STABLE: 0.6,
                    ConvergenceLevel.DIVERGING: 0.4,
                    ConvergenceLevel.FATIGUE: 0.2,
                }
                risk_score = level_scores.get(risk_report.convergence_level, 0.5)

                if risk_report.fatigue_detected:
                    issues.append("风控辩论出现疲劳迹象")

                score += risk_score * 0.5  # 风控辩论权重 50%
            else:
                score += 0.5 * 0.5  # 默认中等分数
                issues.append("缺少风控辩论收敛度报告")
        else:
            # 从辩论历史中直接评估
            investment_history = state.get("investment_debate_state", {}).get("history", "")
            risk_history = state.get("risk_debate_state", {}).get("history", "")

            # 简化评估：基于辩论长度和轮次
            inv_rounds = state.get("investment_debate_state", {}).get("count", 0)
            risk_rounds = state.get("risk_debate_state", {}).get("count", 0)

            if inv_rounds >= 4:
                issues.append(f"投资辩论轮次较多 ({inv_rounds//2}轮)，可能存在疲劳")
                score += 0.4 * 0.5
            elif inv_rounds >= 2:
                score += 0.7 * 0.5
            else:
                score += 0.6 * 0.5

            if risk_rounds >= 6:
                issues.append(f"风控辩论轮次较多 ({risk_rounds//3}轮)，可能存在疲劳")
                score += 0.4 * 0.5
            elif risk_rounds >= 3:
                score += 0.7 * 0.5
            else:
                score += 0.6 * 0.5

        return ComponentQuality(
            component_name="辩论质量",
            quality_score=score,
            issues=issues,
            weight=self.debate_quality_weight,
            recommendations=recommendations,
        )

    def _assess_risk_consistency(self, state: Dict[str, Any]) -> ComponentQuality:
        """评估风控一致性"""
        issues = []
        recommendations = []
        score = 1.0  # 默认一致

        # 检查 Research Manager 和 Trader 的结论一致性
        investment_plan = state.get("investment_plan", "")
        trader_plan = state.get("trader_investment_plan", "")

        # 检查风险控制决策和最终决策的一致性
        risk_control = state.get("risk_control_decision", "")
        final_decision = state.get("final_trade_decision", "")

        # 提取评级
        investment_rating = self._extract_rating(investment_plan)
        trader_rating = self._extract_rating(trader_plan)
        final_rating = self._extract_rating(final_decision)

        # 检查冲突
        if investment_rating and trader_rating:
            if investment_rating != trader_rating:
                issues.append(
                    f"Research Manager ({investment_rating}) 和 Trader ({trader_rating}) 评级不一致"
                )
                score *= 0.8

        if investment_rating and final_rating:
            # 评级方向应该一致（Buy/Overweight vs Sell/Underweight）
            bullish_ratings = {"Buy", "Overweight", "买入", "增持"}
            bearish_ratings = {"Sell", "Underweight", "卖出", "减持"}
            neutral_ratings = {"Hold", "持有"}

            if investment_rating in bullish_ratings and final_rating in bearish_ratings:
                issues.append(f"投资建议 ({investment_rating}) 和最终决策 ({final_rating}) 方向相反")
                score *= 0.5
                recommendations.append("最终决策与投资建议方向相反，需仔细确认风险因素")
            elif investment_rating in bearish_ratings and final_rating in bullish_ratings:
                issues.append(f"投资建议 ({investment_rating}) 和最终决策 ({final_rating}) 方向相反")
                score *= 0.5
                recommendations.append("最终决策与投资建议方向相反，需仔细确认投资逻辑")

        # 检查风险控制是否被违反
        if risk_control and final_decision:
            # 检查仓位限制是否被遵守
            max_position = self._extract_max_position(risk_control)
            final_position = self._extract_position(final_decision)

            if max_position and final_position:
                if final_position > max_position:
                    issues.append(f"最终仓位 ({final_position}%) 超过风险控制上限 ({max_position}%)")
                    score *= 0.6
                    recommendations.append("最终决策违反风险控制约束，需重新评估")

        return ComponentQuality(
            component_name="风控一致性",
            quality_score=max(0.0, score),
            issues=issues,
            weight=self.risk_consistency_weight,
            recommendations=recommendations,
        )

    def _extract_rating(self, text: str) -> Optional[str]:
        """从文本中提取评级（更准确的匹配逻辑）"""
        if not text:
            return None

        # 优先匹配标题行附近的评级（更准确）
        # 匹配模式：评级关键词出现在"投资评级"、"最终决策"、"交易方向"等标题附近
        title_patterns = [
            r'(?:投资评级|最终交易决策|交易方向|交易决策|核心建议)[^：\n]*[：:]\s*[\*_]*\s*(\S+?)\s*[\*_]*(?:\s|/|$)',
            r'^#+\s*.*?(买入|增持|持有|减持|卖出)',
            r'\*\*(投资评级|最终决策|交易方向|交易决策)\*\*[^：\n]*[：:]\s*[\*_]*\s*(\S+?)[\*_]*',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                raw = match.group(1) if match.lastindex == 1 else match.group(2)
                if not raw:
                    raw = match.group(1)
                raw = raw.strip()
                # 标准化
                if '买入' in raw:
                    return '买入'
                elif '增持' in raw:
                    return '增持'
                elif '持有' in raw or '观望' in raw:
                    return '持有'
                elif '减持' in raw:
                    return '减持'
                elif '卖出' in raw or '做空' in raw or '规避' in raw:
                    return '卖出'

        # 降级方案：找第一个出现在开头部分的评级关键词（前500字符内）
        first_500 = text[:500]
        cn_ratings = ["卖出", "减持", "持有", "增持", "买入"]  # 按长度排序，优先匹配长词
        for rating in cn_ratings:
            if rating in first_500:
                # 检查是否在标题或重要位置（前后有**、#、：等标记）
                idx = first_500.find(rating)
                context = first_500[max(0, idx-10):idx+len(rating)+10]
                if any(marker in context for marker in ['**', '#', '：', ':', '🎯', '📊']):
                    return rating

        # 英文评级（作为兜底）
        en_ratings = ["Sell", "Underweight", "Hold", "Overweight", "Buy"]
        for rating in en_ratings:
            if rating in first_500:
                return rating

        return None

    def _extract_max_position(self, text: str) -> Optional[float]:
        """从风险控制文本中提取最大仓位"""
        if not text:
            return None

        # 搜索类似 "最大仓位 10%" 或 "max_position_size: 10" 的模式
        patterns = [
            r"最大仓位[:\s]*(\d+)[%]?",
            r"max[_\s]?position[:\s]*(\d+)",
            r"仓位上限[:\s]*(\d+)[%]?",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))

        return None

    def _extract_position(self, text: str) -> Optional[float]:
        """从最终决策文本中提取仓位"""
        if not text:
            return None

        patterns = [
            r"建议仓位[:\s]*(\d+)[%]?",
            r"position[_\s]?size[:\s]*(\d+)",
            r"仓位[:\s]*(\d+)[%]?",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return float(match.group(1))

        return None

    def _calculate_overall_score(
        self,
        data_quality: ComponentQuality,
        debate_quality: ComponentQuality,
        risk_consistency: ComponentQuality,
    ) -> float:
        """计算综合质量分数"""
        weighted_sum = (
            data_quality.quality_score * data_quality.weight +
            debate_quality.quality_score * debate_quality.weight +
            risk_consistency.quality_score * risk_consistency.weight
        )

        total_weight = (
            data_quality.weight +
            debate_quality.weight +
            risk_consistency.weight
        )

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    def _determine_quality_grade(
        self,
        overall_score: float,
        data_quality: ComponentQuality,
    ) -> QualityGrade:
        """确定质量等级"""
        # 数据质量是最关键的因素
        if data_quality.quality_score < 0.3:
            return QualityGrade.F

        if overall_score >= 0.85:
            return QualityGrade.A
        elif overall_score >= 0.70:
            return QualityGrade.B
        elif overall_score >= 0.50:
            return QualityGrade.C
        elif overall_score >= 0.30:
            return QualityGrade.D
        else:
            return QualityGrade.F

    def _determine_confidence_level(
        self,
        overall_score: float,
        data_quality: ComponentQuality,
    ) -> ConfidenceLevel:
        """确定置信度级别"""
        # 数据质量决定置信度上限
        if data_quality.quality_score < 0.3:
            return ConfidenceLevel.UNRELIABLE

        if overall_score >= 0.85:
            return ConfidenceLevel.HIGH
        elif overall_score >= 0.70:
            return ConfidenceLevel.MEDIUM
        elif overall_score >= 0.50:
            return ConfidenceLevel.LOW
        elif overall_score >= 0.30:
            return ConfidenceLevel.VERY_LOW
        else:
            return ConfidenceLevel.UNRELIABLE

    def _find_missing_analysts(self, state: Dict[str, Any]) -> List[str]:
        """找出缺失的分析师报告"""
        missing = []

        for report_field, analyst_type in REPORT_FIELD_TO_ANALYST.items():
            content = state.get(report_field, "")
            if not content or "[分析失败]" in content or "[未初始化]" in content:
                missing.append(REPORT_ANALYST_NAMES.get(analyst_type, analyst_type))

        return missing

    def _find_low_quality_reports(self, state: Dict[str, Any]) -> List[str]:
        """找出低质量的报告"""
        low_quality = []

        for report_field, analyst_type in REPORT_FIELD_TO_ANALYST.items():
            content = state.get(report_field, "")
            if content and (
                "[关键数据缺失]" in content or
                "[⚠️ 关键数据缺失]" in content or
                "[数据不完整]" in content or
                "[🔶 部分数据缺失]" in content
            ):
                low_quality.append(REPORT_ANALYST_NAMES.get(analyst_type, analyst_type))

        return low_quality

    def _check_debate_fatigue(
        self,
        debate_reports: Optional[Dict[str, DebateConvergenceReport]] = None,
    ) -> bool:
        """检查是否有辩论疲劳"""
        if not debate_reports:
            return False

        inv_report = debate_reports.get("investment")
        risk_report = debate_reports.get("risk")

        fatigue = False

        if inv_report and inv_report.fatigue_detected:
            fatigue = True

        if risk_report and risk_report.fatigue_detected:
            fatigue = True

        return fatigue

    def _find_risk_conflicts(self, state: Dict[str, Any]) -> List[str]:
        """找出风控冲突"""
        conflicts = []

        # 从风控一致性评估中获取
        risk_consistency = self._assess_risk_consistency(state)
        conflicts.extend(risk_consistency.issues)

        return conflicts

    def _generate_warnings(
        self,
        data_quality: ComponentQuality,
        debate_quality: ComponentQuality,
        risk_consistency: ComponentQuality,
        missing_analysts: List[str],
        low_quality_reports: List[str],
        debate_fatigue: bool,
        risk_conflicts: List[str],
    ) -> List[str]:
        """生成警告信息"""
        warnings = []

        # 数据质量警告
        if data_quality.quality_score < 0.5:
            warnings.append("⚠️ 数据质量较差，分析结论可能不准确")
        elif data_quality.quality_score < 0.7:
            warnings.append("⚠️ 存在数据缺失，需关注报告中的标注")

        if missing_analysts:
            warnings.append(f"⚠️ 缺少分析师报告: {', '.join(missing_analysts)}")

        if low_quality_reports:
            warnings.append(f"⚠️ 低质量报告: {', '.join(low_quality_reports)}")

        # 辩论质量警告
        if debate_fatigue:
            warnings.append("⚠️ 辩论出现疲劳，观点可能未收敛")

        if debate_quality.quality_score < 0.5:
            warnings.append("⚠️ 辩论质量较差，结论可能存在偏差")

        # 风控一致性警告
        if risk_conflicts:
            for conflict in risk_conflicts[:2]:  # 最多显示2个
                warnings.append(f"⚠️ {conflict}")

        if risk_consistency.quality_score < 0.5:
            warnings.append("⚠️ 风控一致性较差，建议重新审核决策")

        return warnings

    def _generate_recommendations(
        self,
        data_quality: ComponentQuality,
        debate_quality: ComponentQuality,
        risk_consistency: ComponentQuality,
        missing_analysts: List[str],
        low_quality_reports: List[str],
    ) -> List[str]:
        """生成建议"""
        recommendations = []

        # 数据建议
        recommendations.extend(data_quality.recommendations)

        # 辩论建议
        recommendations.extend(debate_quality.recommendations)

        # 风控建议
        recommendations.extend(risk_consistency.recommendations)

        # 针对缺失的建议
        if missing_analysts:
            recommendations.append(
                f"建议补充 {', '.join(missing_analysts)} 的分析报告"
            )

        # 针对低质量的建议
        if low_quality_reports:
            recommendations.append(
                f"建议验证 {', '.join(low_quality_reports)} 的数据来源"
            )

        # 去重
        return list(set(recommendations))

    def _generate_decision_guidance(
        self,
        quality_grade: QualityGrade,
        confidence_level: ConfidenceLevel,
        warnings: List[str],
    ) -> str:
        """生成决策指导"""
        guidance_lines = []

        # 基于质量等级的指导
        grade_guidance = {
            QualityGrade.A: "分析结论可靠性较高，可作为决策参考。但仍需结合个人判断和市场实际情况。",
            QualityGrade.B: "分析有一定参考价值，建议关注报告中标注的风险点和数据缺失情况。",
            QualityGrade.C: "分析存在一些问题，建议结合其他信息源验证，谨慎决策。",
            QualityGrade.D: "分析质量较差，结论仅供参考，不建议直接用于决策。",
            QualityGrade.F: "分析存在严重问题，结论可靠性低，建议重新执行分析或使用其他信息源。",
        }
        guidance_lines.append(grade_guidance.get(quality_grade, ""))

        # 基于置信度的补充
        confidence_guidance = {
            ConfidenceLevel.HIGH: "置信度较高，结论经过多轮辩论和风控验证。",
            ConfidenceLevel.MEDIUM: "置信度中等，建议关注报告中的数据缺失和风险提示。",
            ConfidenceLevel.LOW: "置信度较低，建议结合其他分析方法验证。",
            ConfidenceLevel.VERY_LOW: "置信度很低，结论仅供参考，请谨慎决策。",
            ConfidenceLevel.UNRELIABLE: "结论不可靠，不建议作为决策依据。",
        }
        guidance_lines.append(confidence_guidance.get(confidence_level, ""))

        # 警告补充
        if warnings:
            guidance_lines.append("")
            guidance_lines.append("⚠️ 注意事项:")
            for warning in warnings[:3]:  # 最多显示3个警告
                guidance_lines.append(f"  {warning}")

        return "\n".join(guidance_lines)

    def _should_trust_conclusion(
        self,
        quality_grade: QualityGrade,
        confidence_level: ConfidenceLevel,
        data_quality: ComponentQuality,
        debate_quality: ComponentQuality,
    ) -> Tuple[bool, str]:
        """判断是否应该信任此结论"""
        # 不信任的条件
        if quality_grade == QualityGrade.F:
            return False, "分析存在严重问题，结论不可靠"

        if confidence_level == ConfidenceLevel.UNRELIABLE:
            return False, "置信度过低，结论不可靠"

        if data_quality.quality_score < 0.3:
            return False, "数据质量太差，结论不可靠"

        # 信任但有条件
        if quality_grade == QualityGrade.D:
            return False, "分析质量较差，不建议作为决策依据"

        if quality_grade == QualityGrade.C:
            return True, "可参考但需谨慎验证"

        if quality_grade == QualityGrade.B:
            return True, "有一定参考价值，建议关注风险提示"

        # 高质量，信任
        return True, "分析质量良好，可作为决策参考"


# ============================================================================
# 创建 Accuracy Guardian Node（用于 LangGraph）
# ============================================================================

def create_accuracy_guardian_node(guardian: AccuracyGuardian = None):
    """
    创建准确性守护者节点

    用于在 Portfolio Manager 之后插入，
    生成质量报告并添加到 state。

    节点内部会：
    1. 自行计算辩论收敛度（不依赖外部传入）
    2. 评估整体质量
    3. 将质量摘要融入最终决策文本
    """
    if guardian is None:
        guardian = AccuracyGuardian()

    def accuracy_guardian_node(state) -> dict:
        """准确性守护者节点函数"""
        from tradingagents.agents.utils.debate_convergence import (
            DebateConvergenceEvaluator,
            DebatePhase,
        )

        logger.info("🔍 Accuracy Guardian 正在评估结论质量...")

        # 自行计算辩论收敛度
        debate_reports = {}

        # 计算投资辩论收敛度
        investment_history = state.get("investment_debate_state", {}).get("history", "")
        if investment_history:
            inv_evaluator = DebateConvergenceEvaluator(
                phase=DebatePhase.INVESTMENT_DEBATE,
                max_rounds=10,
                min_rounds=1,
            )
            # 估算轮次（每2条发言为1轮）
            count = state.get("investment_debate_state", {}).get("count", 0)
            for i in range(1, max(count, 1) + 1):
                try:
                    inv_evaluator.analyze_round(state, i)
                except Exception:
                    pass
            debate_reports["investment"] = inv_evaluator.assess_convergence()

        # 计算风控辩论收敛度
        risk_history = state.get("risk_debate_state", {}).get("history", "")
        if risk_history:
            risk_evaluator = DebateConvergenceEvaluator(
                phase=DebatePhase.RISK_DEBATE,
                max_rounds=10,
                min_rounds=1,
            )
            count = state.get("risk_debate_state", {}).get("count", 0)
            for i in range(1, max(count, 1) + 1):
                try:
                    risk_evaluator.analyze_round(state, i)
                except Exception:
                    pass
            debate_reports["risk"] = risk_evaluator.assess_convergence()

        # 从 state 中获取完整性报告
        integrity_reports = state.get("_integrity_reports", {})

        # 评估质量
        report = guardian.assess_conclusion_quality(
            state,
            integrity_reports,
            debate_reports,
        )

        # 记录日志
        logger.info(f"📊 质量评估完成: {report.to_summary()}")

        if report.warnings:
            for warning in report.warnings:
                logger.warning(warning)

        # 将质量报告融入最终决策文本
        final_decision = state.get("final_trade_decision", "")
        if final_decision:
            enhanced_decision = enhance_final_decision_with_quality(
                final_decision, report
            )
        else:
            enhanced_decision = final_decision

        # 将报告添加到 state
        return {
            "_accuracy_guardian_report": report,
            "_quality_grade": report.quality_grade.value,
            "_confidence_level": report.confidence_level.value,
            "_overall_quality_score": report.overall_quality_score,
            "_should_trust": report.should_trust,
            "_trust_reason": report.trust_reason,
            "_debate_reports": debate_reports,
            "final_trade_decision": enhanced_decision,
        }

    return accuracy_guardian_node


# ============================================================================
# 将质量报告融入最终决策文本
# ============================================================================

def enhance_final_decision_with_quality(
    final_decision: str,
    guardian_report: AccuracyGuardianReport,
) -> str:
    """
    将质量报告融入最终决策文本

    在最终决策前添加质量评估摘要。
    """
    quality_summary = f"""
---

## 📊 质量评估摘要

| 指标 | 值 |
|------|-----|
| 整体质量 | {guardian_report.quality_grade.value} |
| 置信度 | {guardian_report.confidence_level.value} |
| 建议参考 | {'✅ 是' if guardian_report.should_trust else '❌ 否'} |

{guardian_report.trust_reason}

---
"""

    if guardian_report.warnings:
        quality_summary += "\n⚠️ **注意事项:**\n"
        for warning in guardian_report.warnings[:3]:
            quality_summary += f"- {warning}\n"
        quality_summary += "\n---\n"

    # 将质量摘要插入到决策文本中
    return quality_summary + "\n" + final_decision