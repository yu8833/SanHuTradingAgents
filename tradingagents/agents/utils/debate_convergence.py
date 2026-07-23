"""
辩论收敛度判断模块

用于评估多空辩论和风控辩论过程中的观点收敛情况，
避免无意义的过长辩论，提高分析效率和结论稳定性。

主要功能：
1. 追踪辩论历史中的关键论点
2. 计算观点收敛度（对立程度是否降低）
3. 检测辩论疲劳（为了反驳而反驳）
4. 生成辩论质量报告
5. 决定是否应该提前终止辩论

使用方式：
- 在 ConditionalLogic.should_continue_debate 中集成
- 在 ConditionalLogic.should_continue_risk_analysis 中集成
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class ConvergenceLevel(Enum):
    """收敛级别"""
    CONVERGED = "converged"        # 观点已收敛，双方接近一致
    NARROWING = "narrowing"        # 观点差异正在缩小
    STABLE = "stable"             # 观点差异稳定，无明显变化
    DIVERGING = "diverging"        # 观点差异扩大
    FATIGUE = "fatigue"           # 辩论疲劳，开始为了反驳而反驳


class DebatePhase(Enum):
    """辩论阶段"""
    INVESTMENT_DEBATE = "investment"    # 投资辩论（多空）
    RISK_DEBATE = "risk"                # 风控辩论


@dataclass
class ArgumentPoint:
    """单个论点"""
    speaker: str              # 发言者（Bull/Bear/Aggressive/Conservative/Neutral）
    content: str              # 论点内容
    round: int                # 辩论轮次
    stance: str               # 立场（bullish/bearish/neutral/aggressive/conservative）
    key_points: List[str] = field(default_factory=list)  # 关键论点关键词
    confidence: float = 0.0   # 论点的置信度（0-1）


@dataclass
class RoundAnalysis:
    """单轮辩论分析结果"""
    round_number: int
    bull_arguments: List[ArgumentPoint]
    bear_arguments: List[ArgumentPoint]
    disagreement_score: float    # 本轮对立程度（0-1，越高越对立）
    new_points_raised: int       # 新提出的论点数量
    repeated_points: int         # 重复论点数量
    argument_quality: float      # 论点质量（0-1）


@dataclass
class DebateConvergenceReport:
    """辩论收敛度报告"""
    phase: DebatePhase
    total_rounds: int
    convergence_level: ConvergenceLevel
    convergence_score: float         # 收敛分数（0-1，越高越收敛）
    disagreement_trend: List[float]  # 对立程度变化趋势
    key_agreements: List[str]        # 双方一致的观点
    key_disagreements: List[str]     # 双方核心分歧
    fatigue_detected: bool           # 是否检测到疲劳
    fatigue_round: Optional[int]     # 疲劳开始的轮次
    recommendation: str              # 建议操作
    should_stop: bool                # 是否应该停止辩论
    stop_reason: str                 # 停止原因

    @property
    def quality_grade(self) -> str:
        """质量等级"""
        grades = {
            ConvergenceLevel.CONVERGED: "A",
            ConvergenceLevel.NARROWING: "B",
            ConvergenceLevel.STABLE: "C",
            ConvergenceLevel.DIVERGING: "D",
            ConvergenceLevel.FATIGUE: "F",
        }
        return grades.get(self.convergence_level, "C")

    @property
    def rating_bias_towards_hold(self) -> float:
        """
        评级向「持有」偏移的建议系数（0-1）。
        
        返回值越大，说明辩论越不收敛，评级越应该向持有偏移。
        - 0.0: 完全收敛，不需要偏移
        - 0.3: 略有分歧，轻微向持有偏移
        - 0.5: 分歧较大，明显向持有偏移
        - 0.8: 严重分歧或疲劳，强烈建议持有
        """
        bias_map = {
            ConvergenceLevel.CONVERGED: 0.0,
            ConvergenceLevel.NARROWING: 0.15,
            ConvergenceLevel.STABLE: 0.35,
            ConvergenceLevel.DIVERGING: 0.6,
            ConvergenceLevel.FATIGUE: 0.8,
        }
        return bias_map.get(self.convergence_level, 0.3)

    @property
    def should_default_to_hold(self) -> bool:
        """
        是否应该默认选择持有。
        
        当辩论未充分收敛（STABLE/DIVERGING/FATIGUE）时，
        在A股高不确定性环境下应优先选择持有。
        """
        return self.convergence_level in [
            ConvergenceLevel.STABLE,
            ConvergenceLevel.DIVERGING,
            ConvergenceLevel.FATIGUE,
        ]

    def to_summary(self) -> str:
        """生成简短摘要"""
        status_icon = {
            ConvergenceLevel.CONVERGED: "✅",
            ConvergenceLevel.NARROWING: "📉",
            ConvergenceLevel.STABLE: "➡️",
            ConvergenceLevel.DIVERGING: "📈",
            ConvergenceLevel.FATIGUE: "⚠️",
        }.get(self.convergence_level, "❓")

        return (
            f"{status_icon} 辩论收敛度: {self.convergence_level.value} "
            f"(分数: {self.convergence_score:.2f}, 轮次: {self.total_rounds})"
        )


# ============================================================================
# 关键论点关键词（用于识别论点类型）
# ============================================================================

# 看涨论点关键词
BULL_KEYWORDS = [
    "growth", "增长", "upside", "上涨空间", "potential", "潜力",
    "advantage", "优势", "opportunity", "机会", "bullish", "看涨",
    "buy", "买入", "overweight", "增持", "strong", "强劲",
    "positive", "正面", "利好", "support", "支撑", "momentum", "动能",
    "北向", "northbound", "流入", "inflow", "政策支持", "policy support",
]

# 看跌论点关键词
BEAR_KEYWORDS = [
    "risk", "风险", "downside", "下跌风险", "challenge", "挑战",
    "weakness", "劣势", "threat", "威胁", "bearish", "看跌",
    "sell", "卖出", "underweight", "减持", "weak", "疲软",
    "negative", "负面", "利空", "resistance", "阻力", "concern", "担忧",
    "流出", "outflow", "监管", "regulation", "解禁", "lockup",
]

# 风控激进论点关键词
AGGRESSIVE_KEYWORDS = [
    "aggressive", "激进", "opportunity", "机会", "risk-tolerant", "风险容忍",
    "higher position", "更大仓位", "growth potential", "增长潜力",
]

# 风控保守论点关键词
CONSERVATIVE_KEYWORDS = [
    "conservative", "保守", "caution", "谨慎", "risk-averse", "风险厌恶",
    "smaller position", "较小仓位", "safety", "安全", "protection", "保护",
]

# 中性论点关键词
NEUTRAL_KEYWORDS = [
    "neutral", "中性", "balanced", "平衡", "moderate", "适度",
    "hold", "持有", "wait", "等待", "observe", "观察",
]


# ============================================================================
# 辩论收敛度评估器
# ============================================================================

class DebateConvergenceEvaluator:
    """
    辩论收敛度评估器

    追踪辩论过程，分析观点收敛情况，判断是否应该提前终止。
    """

    def __init__(
        self,
        phase: DebatePhase,
        max_rounds: int = 5,
        min_rounds: int = 2,
        convergence_threshold: float = 0.7,
        fatigue_threshold: float = 0.85,
    ):
        """
        初始化评估器

        Args:
            phase: 辩论阶段（投资辩论/风控辩论）
            max_rounds: 最大辩论轮次
            min_rounds: 最小辩论轮次（至少辩论几轮）
            convergence_threshold: 收敛阈值（达到此分数认为已收敛）
            fatigue_threshold: 疲劳阈值（对立程度持续高于此值认为疲劳）
        """
        self.phase = phase
        self.max_rounds = max_rounds
        self.min_rounds = min_rounds
        self.convergence_threshold = convergence_threshold
        self.fatigue_threshold = fatigue_threshold

        self._round_analyses: List[RoundAnalysis] = []
        self._argument_history: List[ArgumentPoint] = []
        self._disagreement_trend: List[float] = []

    def analyze_round(
        self,
        state: Dict[str, Any],
        round_number: int,
    ) -> RoundAnalysis:
        """
        分析单轮辩论

        Args:
            state: AgentState 状态
            round_number: 当前轮次

        Returns:
            RoundAnalysis 分析结果
        """
        if self.phase == DebatePhase.INVESTMENT_DEBATE:
            debate_state = state.get("investment_debate_state", {})
            bull_history = debate_state.get("bull_history", "")
            bear_history = debate_state.get("bear_history", "")
        else:
            debate_state = state.get("risk_debate_state", {})
            # 风控辩论使用三个分析师的历史
            bull_history = debate_state.get("aggressive_history", "")
            bear_history = debate_state.get("conservative_history", "")

        # 提取本轮论点
        bull_args = self._extract_arguments(bull_history, round_number, "bullish")
        bear_args = self._extract_arguments(bear_history, round_number, "bearish")

        # 计算对立程度
        disagreement = self._calculate_disagreement(bull_args, bear_args)

        # 计算新论点和重复论点
        new_points, repeated = self._count_new_and_repeated(bull_args + bear_args)

        # 计算论点质量
        quality = self._assess_argument_quality(bull_args + bear_args)

        analysis = RoundAnalysis(
            round_number=round_number,
            bull_arguments=bull_args,
            bear_arguments=bear_args,
            disagreement_score=disagreement,
            new_points_raised=new_points,
            repeated_points=repeated,
            argument_quality=quality,
        )

        self._round_analyses.append(analysis)
        self._disagreement_trend.append(disagreement)
        self._argument_history.extend(bull_args + bear_args)

        return analysis

    def _extract_arguments(
        self,
        history: str,
        round_number: int,
        stance: str,
    ) -> List[ArgumentPoint]:
        """从历史记录中提取论点"""
        if not history:
            return []

        # 按发言者分段
        segments = re.split(r'\n(?=[A-Z][a-z]+ (Analyst|Researcher):)', history)

        arguments = []
        for i, segment in enumerate(segments):
            if not segment.strip():
                continue

            # 提取发言者
            speaker_match = re.match(r'([A-Z][a-z]+ (Analyst|Researcher)):', segment)
            speaker = speaker_match.group(1) if speaker_match else "Unknown"

            # 提取关键论点
            key_points = self._extract_key_points(segment, stance)

            # 估算置信度（基于论点数量和质量）
            confidence = min(1.0, len(key_points) / 5 + 0.3)

            arg = ArgumentPoint(
                speaker=speaker,
                content=segment.strip()[:500],  # 截断过长内容
                round=round_number,
                stance=stance,
                key_points=key_points,
                confidence=confidence,
            )
            arguments.append(arg)

        return arguments

    def _extract_key_points(self, text: str, stance: str) -> List[str]:
        """提取关键论点关键词"""
        keywords = []
        text_lower = text.lower()

        if stance in ["bullish", "aggressive"]:
            keyword_set = BULL_KEYWORDS + AGGRESSIVE_KEYWORDS
        elif stance in ["bearish", "conservative"]:
            keyword_set = BEAR_KEYWORDS + CONSERVATIVE_KEYWORDS
        else:
            keyword_set = NEUTRAL_KEYWORDS

        for keyword in keyword_set:
            if keyword.lower() in text_lower:
                keywords.append(keyword)

        return keywords[:10]  # 最多返回10个

    def _calculate_disagreement(
        self,
        bull_args: List[ArgumentPoint],
        bear_args: List[ArgumentPoint],
    ) -> float:
        """
        计算对立程度

        基于双方论点关键词的交集和差集计算。
        """
        if not bull_args or not bear_args:
            return 0.5

        bull_keywords = set()
        bear_keywords = set()

        for arg in bull_args:
            bull_keywords.update(arg.key_points)

        for arg in bear_args:
            bear_keywords.update(arg.key_points)

        if not bull_keywords or not bear_keywords:
            return 0.5

        # 计算关键词重叠度
        overlap = bull_keywords & bear_keywords
        total = bull_keywords | bear_keywords

        # 重叠度低 = 对立程度高
        overlap_ratio = len(overlap) / len(total) if total else 0

        # 对立程度 = 1 - 重叠度
        disagreement = 1 - overlap_ratio

        return disagreement

    def _count_new_and_repeated(
        self,
        current_args: List[ArgumentPoint],
    ) -> Tuple[int, int]:
        """计算新论点和重复论点数量"""
        current_keywords = set()
        for arg in current_args:
            current_keywords.update(arg.key_points)

        historical_keywords = set()
        for arg in self._argument_history:
            historical_keywords.update(arg.key_points)

        new_keywords = current_keywords - historical_keywords
        repeated_keywords = current_keywords & historical_keywords

        return len(new_keywords), len(repeated_keywords)

    def _assess_argument_quality(self, arguments: List[ArgumentPoint]) -> float:
        """评估论点质量"""
        if not arguments:
            return 0.0

        # 质量因子：
        # 1. 关键论点数量
        # 2. 置信度
        # 3. 内容长度（太短可能质量低）

        total_quality = 0.0
        for arg in arguments:
            # 关键论点数量得分
            key_points_score = min(1.0, len(arg.key_points) / 5)

            # 内容长度得分
            length_score = min(1.0, len(arg.content) / 300)

            # 综合得分
            quality = (key_points_score * 0.6 + length_score * 0.4) * arg.confidence
            total_quality += quality

        return total_quality / len(arguments)

    def assess_convergence(self) -> DebateConvergenceReport:
        """
        评估辩论收敛度

        Returns:
            DebateConvergenceReport 收敛度报告
        """
        total_rounds = len(self._round_analyses)

        if total_rounds < self.min_rounds:
            return DebateConvergenceReport(
                phase=self.phase,
                total_rounds=total_rounds,
                convergence_level=ConvergenceLevel.STABLE,
                convergence_score=0.0,
                disagreement_trend=self._disagreement_trend,
                key_agreements=self._find_agreements(),
                key_disagreements=self._find_disagreements(),
                fatigue_detected=False,
                fatigue_round=None,
                recommendation="继续辩论，尚未达到最小轮次",
                should_stop=False,
                stop_reason="",
            )

        # 分析对立程度趋势
        convergence_level = self._determine_convergence_level()
        convergence_score = self._calculate_convergence_score()

        # 检测疲劳
        fatigue_detected, fatigue_round = self._detect_fatigue()

        # 确定是否应该停止
        should_stop, stop_reason = self._should_stop_debate(
            convergence_level,
            convergence_score,
            fatigue_detected,
            fatigue_round,
        )

        return DebateConvergenceReport(
            phase=self.phase,
            total_rounds=total_rounds,
            convergence_level=convergence_level,
            convergence_score=convergence_score,
            disagreement_trend=self._disagreement_trend,
            key_agreements=self._find_agreements(),
            key_disagreements=self._find_disagreements(),
            fatigue_detected=fatigue_detected,
            fatigue_round=fatigue_round,
            recommendation=self._generate_recommendation(convergence_level, should_stop),
            should_stop=should_stop,
            stop_reason=stop_reason,
        )

    def _determine_convergence_level(self) -> ConvergenceLevel:
        """确定收敛级别"""
        if len(self._disagreement_trend) < 2:
            return ConvergenceLevel.STABLE

        # 计算趋势
        recent_trend = self._disagreement_trend[-3:] if len(self._disagreement_trend) >= 3 else self._disagreement_trend

        # 计算变化率
        if len(recent_trend) >= 2:
            delta = recent_trend[-1] - recent_trend[0]

            if delta < -0.1:  # 对立程度下降
                if recent_trend[-1] < 0.3:
                    return ConvergenceLevel.CONVERGED
                return ConvergenceLevel.NARROWING
            elif delta > 0.1:  # 对立程度上升
                return ConvergenceLevel.DIVERGING

        # 检测疲劳
        if self._is_fatigue_pattern():
            return ConvergenceLevel.FATIGUE

        return ConvergenceLevel.STABLE

    def _calculate_convergence_score(self) -> float:
        """计算收敛分数"""
        if not self._disagreement_trend:
            return 0.0

        # 收敛分数 = 1 - 平均对立程度
        avg_disagreement = sum(self._disagreement_trend) / len(self._disagreement_trend)

        # 加上趋势因子（正在收敛加分）
        if len(self._disagreement_trend) >= 2:
            trend = self._disagreement_trend[-1] - self._disagreement_trend[0]
            trend_factor = -trend * 0.2  # 趋势下降加分
        else:
            trend_factor = 0

        convergence_score = 1 - avg_disagreement + trend_factor

        return max(0.0, min(1.0, convergence_score))

    def _detect_fatigue(self) -> Tuple[bool, Optional[int]]:
        """检测辩论疲劳"""
        if len(self._disagreement_trend) < 3:
            return False, None

        # 疲劳模式：
        # 1. 对立程度持续高位（> fatigue_threshold）
        # 2. 新论点数量减少
        # 3. 重复论点数量增加

        recent_disagreement = self._disagreement_trend[-3:]

        # 对立程度持续高位
        if all(d > self.fatigue_threshold for d in recent_disagreement):
            # 检查新论点趋势
            recent_analyses = self._round_analyses[-3:]
            new_points_trend = [a.new_points_raised for a in recent_analyses]

            # 新论点持续减少
            if all(new_points_trend[i] <= new_points_trend[i-1] for i in range(1, len(new_points_trend))):
                return True, len(self._round_analyses) - 3

        return False, None

    def _is_fatigue_pattern(self) -> bool:
        """检查是否为疲劳模式"""
        fatigue_detected, _ = self._detect_fatigue()
        return fatigue_detected

    def _should_stop_debate(
        self,
        level: ConvergenceLevel,
        score: float,
        fatigue: bool,
        fatigue_round: Optional[int],
    ) -> Tuple[bool, str]:
        """判断是否应该停止辩论"""
        total_rounds = len(self._round_analyses)

        # 已收敛，停止
        if level == ConvergenceLevel.CONVERGED:
            return True, f"观点已收敛（收敛分数: {score:.2f}）"

        # 疲劳，立即停止
        if level == ConvergenceLevel.FATIGUE:
            return True, f"检测到辩论疲劳（轮次 {fatigue_round}）"

        # 达到最大轮次
        if total_rounds >= self.max_rounds:
            return True, f"达到最大轮次 ({self.max_rounds})"

        # 收敛分数高，提前停止
        if score >= self.convergence_threshold and total_rounds >= self.min_rounds:
            return True, f"收敛分数达标 ({score:.2f} >= {self.convergence_threshold})"

        return False, ""

    def _find_agreements(self) -> List[str]:
        """找到双方一致的观点"""
        agreements = []

        # 提取双方都提到的关键词
        bull_keywords = set()
        bear_keywords = set()

        for arg in self._argument_history:
            if arg.stance in ["bullish", "aggressive"]:
                bull_keywords.update(arg.key_points)
            else:
                bear_keywords.update(arg.key_points)

        overlap = bull_keywords & bear_keywords

        # 筛选可能的一致观点（非对立关键词）
        neutral_overlap = [k for k in overlap if k.lower() in [n.lower() for n in NEUTRAL_KEYWORDS]]

        return neutral_overlap[:5]

    def _find_disagreements(self) -> List[str]:
        """找到核心分歧"""
        disagreements = []

        # 对立关键词（一方有另一方没有）
        bull_only = []
        bear_only = []

        for arg in self._argument_history:
            if arg.stance in ["bullish", "aggressive"]:
                for kp in arg.key_points:
                    if kp.lower() in [b.lower() for b in BULL_KEYWORDS + AGGRESSIVE_KEYWORDS]:
                        bull_only.append(kp)
            else:
                for kp in arg.key_points:
                    if kp.lower() in [b.lower() for b in BEAR_KEYWORDS + CONSERVATIVE_KEYWORDS]:
                        bear_only.append(kp)

        # 取交集作为核心分歧
        disagreements = list(set(bull_only[:3] + bear_only[:3]))

        return disagreements[:5]

    def _generate_recommendation(
        self,
        level: ConvergenceLevel,
        should_stop: bool,
    ) -> str:
        """生成建议"""
        if should_stop:
            if level == ConvergenceLevel.CONVERGED:
                return "辩论质量良好，双方观点接近一致，建议进入下一阶段"
            elif level == ConvergenceLevel.FATIGUE:
                return "辩论出现疲劳迹象，建议提前终止以避免结论漂移"
            else:
                return "辩论已达到终止条件，建议进入下一阶段"
        else:
            if level == ConvergenceLevel.NARROWING:
                return "观点正在收敛，继续辩论可能达成一致"
            elif level == ConvergenceLevel.DIVERGING:
                return "观点分歧扩大，可能需要更多论据支持"
            else:
                return "继续辩论，等待收敛或达到最大轮次"


# ============================================================================
# 辩论收敛管理器（整合到 ConditionalLogic）
# ============================================================================

class DebateConvergenceManager:
    """
    辩论收敛管理器

    管理两个辩论阶段的收敛评估：
    1. 投资辩论（多空）
    2. 风控辩论（激进/保守/中性）
    """

    def __init__(
        self,
        max_investment_rounds: int = 5,
        max_risk_rounds: int = 5,
        min_rounds: int = 2,
    ):
        self._investment_evaluator = DebateConvergenceEvaluator(
            phase=DebatePhase.INVESTMENT_DEBATE,
            max_rounds=max_investment_rounds,
            min_rounds=min_rounds,
        )
        self._risk_evaluator = DebateConvergenceEvaluator(
            phase=DebatePhase.RISK_DEBATE,
            max_rounds=max_risk_rounds,
            min_rounds=min_rounds,
        )

        self._reports: Dict[str, DebateConvergenceReport] = {}

    def get_evaluator(self, phase: DebatePhase) -> DebateConvergenceEvaluator:
        """获取指定阶段的评估器"""
        if phase == DebatePhase.INVESTMENT_DEBATE:
            return self._investment_evaluator
        return self._risk_evaluator

    def analyze_investment_round(self, state: Dict[str, Any]) -> RoundAnalysis:
        """分析投资辩论轮次"""
        count = state.get("investment_debate_state", {}).get("count", 0)
        round_number = (count // 2) + 1  # Bull+Bear = 1 round

        return self._investment_evaluator.analyze_round(state, round_number)

    def analyze_risk_round(self, state: Dict[str, Any]) -> RoundAnalysis:
        """分析风控辩论轮次"""
        count = state.get("risk_debate_state", {}).get("count", 0)
        round_number = (count // 3) + 1  # Aggressive+Conservative+Neutral = 1 round

        return self._risk_evaluator.analyze_round(state, round_number)

    def should_continue_investment_debate(
        self,
        state: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[DebateConvergenceReport]]:
        """
        判断是否继续投资辩论

        Returns:
            (should_continue, next_node, report)
        """
        # 分析当前轮次
        self.analyze_investment_round(state)

        # 评估收敛度
        report = self._investment_evaluator.assess_convergence()
        self._reports["investment"] = report

        # 记录日志
        logger.info(f"📊 投资辩论收敛度: {report.to_summary()}")

        if report.should_stop:
            # 根据当前发言者决定下一个节点
            current_response = state.get("investment_debate_state", {}).get("current_response", "")
            if current_response.startswith("Bull"):
                return False, "Bear Researcher", report  # Bull说完，轮到Bear（但实际要停止）
            return False, "Research Manager", report

        # 继续辩论
        current_response = state.get("investment_debate_state", {}).get("current_response", "")
        if current_response.startswith("Bull"):
            return True, "Bear Researcher", report
        return True, "Bull Researcher", report

    def should_continue_risk_debate(
        self,
        state: Dict[str, Any],
    ) -> Tuple[bool, str, Optional[DebateConvergenceReport]]:
        """
        判断是否继续风控辩论

        Returns:
            (should_continue, next_node, report)
        """
        # 分析当前轮次
        self.analyze_risk_round(state)

        # 评估收敛度
        report = self._risk_evaluator.assess_convergence()
        self._reports["risk"] = report

        # 记录日志
        logger.info(f"📊 风控辩论收敛度: {report.to_summary()}")

        if report.should_stop:
            return False, "Portfolio Manager", report

        # 继续辩论
        latest_speaker = state.get("risk_debate_state", {}).get("latest_speaker", "")
        if latest_speaker.startswith("Aggressive"):
            return True, "Conservative Analyst", report
        if latest_speaker.startswith("Conservative"):
            return True, "Neutral Analyst", report
        return True, "Aggressive Analyst", report

    def get_investment_report(self) -> Optional[DebateConvergenceReport]:
        """获取投资辩论报告"""
        return self._reports.get("investment")

    def get_risk_report(self) -> Optional[DebateConvergenceReport]:
        """获取风控辩论报告"""
        return self._reports.get("risk")

    def generate_summary(self) -> str:
        """生成辩论收敛度摘要"""
        lines = ["## 📊 辩论收敛度摘要"]

        if "investment" in self._reports:
            inv_report = self._reports["investment"]
            lines.extend([
                "",
                "### 投资辩论（多空）",
                f"- 总轮次: {inv_report.total_rounds}",
                f"- 收敛级别: {inv_report.convergence_level.value}",
                f"- 收敛分数: {inv_report.convergence_score:.2f}",
                f"- 疲劳检测: {'是' if inv_report.fatigue_detected else '否'}",
                f"- 建议: {inv_report.recommendation}",
            ])

        if "risk" in self._reports:
            risk_report = self._reports["risk"]
            lines.extend([
                "",
                "### 风控辩论",
                f"- 总轮次: {risk_report.total_rounds}",
                f"- 收敛级别: {risk_report.convergence_level.value}",
                f"- 收敛分数: {risk_report.convergence_score:.2f}",
                f"- 疲劳检测: {'是' if risk_report.fatigue_detected else '否'}",
                f"- 建议: {risk_report.recommendation}",
            ])

        return "\n".join(lines)