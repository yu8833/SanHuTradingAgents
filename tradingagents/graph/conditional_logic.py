# TradingAgents/graph/conditional_logic.py

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.utils.debate_convergence import (
    DebateConvergenceManager,
    DebatePhase,
    ConvergenceLevel,
)
import logging

logger = logging.getLogger(__name__)


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

        # 初始化辩论收敛管理器
        self._convergence_manager = DebateConvergenceManager(
            max_investment_rounds=max_debate_rounds,
            max_risk_rounds=max_risk_discuss_rounds,
            min_rounds=1,  # 至少辩论1轮
        )

    def should_continue_market(self, state: AgentState):
        """Determine if market analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state: AgentState):
        """Determine if social media analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state: AgentState):
        """Determine if news analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state: AgentState):
        """Determine if fundamentals analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_policy(self, state: AgentState):
        """Determine if policy analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_policy"
        return "Msg Clear Policy"

    def should_continue_hot_money(self, state: AgentState):
        """Determine if hot money tracking should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_hot_money"
        return "Msg Clear Hot_money"

    def should_continue_lockup(self, state: AgentState):
        """Determine if lockup/reduction analysis should continue."""
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_lockup"
        return "Msg Clear Lockup"

    def should_continue_debate(self, state: AgentState) -> str:
        """
        Determine if debate should continue.

        使用辩论收敛度判断来决定是否继续辩论，
        而不是简单的轮次计数。

        收敛判断逻辑：
        1. 检查是否达到最小轮次
        2. 评估观点收敛度
        3. 检测辩论疲劳
        4. 决定是否提前终止

        重要：确保 Bull 和 Bear 至少各发言一次，再进入 Research Manager
        """
        debate_state = state["investment_debate_state"]
        debate_count = debate_state.get("count", 0)
        has_bull_spoken = bool(debate_state.get("bull_history", "").strip())
        has_bear_spoken = bool(debate_state.get("bear_history", "").strip())

        # 使用收敛度判断
        should_continue, next_node, report = self._convergence_manager.should_continue_investment_debate(state)

        # 保存收敛报告到 state（供后续 Accuracy Guardian 使用）
        if report:
            logger.info(
                f"📊 投资辩论收敛度: {report.convergence_level.value}, "
                f"分数: {report.convergence_score:.2f}, "
                f"轮次: {report.total_rounds}"
            )

        # 确保双方至少各发言一次：如果 Bull 说了但 Bear 还没说，强制让 Bear 发言
        if has_bull_spoken and not has_bear_spoken:
            logger.info(f"🔄 投资辩论：确保看跌研究员至少发言一次")
            return "Bear Researcher"

        if not should_continue:
            # 达到终止条件
            logger.info(f"✅ 投资辩论终止: {report.stop_reason if report else '达到最大轮次'}")
            return "Research Manager"

        # 继续辩论，根据当前发言者决定下一个节点
        if debate_state.get("current_response", "").startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """
        Determine if risk analysis should continue.

        使用辩论收敛度判断来决定是否继续风控辩论。

        重要：确保 Aggressive、Conservative、Neutral 三方都至少发言一次，再进入 Portfolio Manager
        """
        risk_state = state["risk_debate_state"]
        debate_count = risk_state.get("count", 0)
        has_aggressive_spoken = bool(risk_state.get("aggressive_history", "").strip())
        has_conservative_spoken = bool(risk_state.get("conservative_history", "").strip())
        has_neutral_spoken = bool(risk_state.get("neutral_history", "").strip())
        latest_speaker = risk_state.get("latest_speaker", "")

        # 使用收敛度判断
        should_continue, next_node, report = self._convergence_manager.should_continue_risk_debate(state)

        # 记录收敛度信息
        if report:
            logger.info(
                f"📊 风控辩论收敛度: {report.convergence_level.value}, "
                f"分数: {report.convergence_score:.2f}, "
                f"轮次: {report.total_rounds}"
            )

        # 确保三方至少各发言一次
        if has_aggressive_spoken and not has_conservative_spoken:
            logger.info(f"🔄 风控辩论：确保保守风控至少发言一次")
            return "Conservative Analyst"
        if has_aggressive_spoken and has_conservative_spoken and not has_neutral_spoken:
            logger.info(f"🔄 风控辩论：确保中性风控至少发言一次")
            return "Neutral Analyst"

        if not should_continue:
            logger.info(f"✅ 风控辩论终止: {report.stop_reason if report else '达到最大轮次'}")
            return "Portfolio Manager"

        # 继续辩论
        if latest_speaker.startswith("Aggressive"):
            return "Conservative Analyst"
        if latest_speaker.startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"

    def get_convergence_manager(self) -> DebateConvergenceManager:
        """获取辩论收敛管理器（供外部访问报告）"""
        return self._convergence_manager
