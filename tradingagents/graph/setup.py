# TradingAgents/graph/setup.py

from typing import Any, Dict, List
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.agents.guardians.accuracy_guardian import create_accuracy_guardian_node

from .conditional_logic import ConditionalLogic
from .parallel_analysts import create_parallel_analysts_node


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def setup_graph(
        self,
        selected_analysts=["market", "social", "news", "fundamentals", "policy", "hot_money", "lockup"],
        mode="full",
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst (technical analysis)
                - "social": Social media / sentiment analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
                - "policy": Policy analyst (A-stock specific)
                - "hot_money": Hot money / capital flow tracker (A-stock specific)
                - "lockup": Lockup expiry / reduction watcher (A-stock specific)
            mode (str): 分析模式，控制论证链长短：
                - "full": 完整链（含多空辩论 + 风险辩论 + 组合经理二审）
                - "light": 精简链（跳过辩论与风控二审，更快出结论）
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # 归一化模式：兼容旧值 quick/deep
        mode = "light" if mode in ("light", "quick") else "full"

        analyst_tool_nodes = {}

        for analyst_type in selected_analysts:
            analyst_tool_nodes[analyst_type] = self.tool_nodes[analyst_type]

        # Create quality gate node
        quality_gate_node = create_quality_gate(self.quick_thinking_llm)

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create accuracy guardian node
        accuracy_guardian_node = create_accuracy_guardian_node()

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add parallel analysts node
        parallel_node = create_parallel_analysts_node(
            self.quick_thinking_llm,
            analyst_tool_nodes,
            selected_analysts,
        )
        workflow.add_node("Parallel Analysts", parallel_node)

        # Add quality gate + other nodes
        workflow.add_node("Quality Gate", quality_gate_node)
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)
        workflow.add_node("Accuracy Guardian", accuracy_guardian_node)  # 新增节点

        # Define edges
        # Start with parallel analysts
        workflow.add_edge(START, "Parallel Analysts")
        workflow.add_edge("Parallel Analysts", "Quality Gate")

        # ── 分析模式路由 ─────────────────────────────────────
        # full（尽调）：完整论证链，含多空辩论 + 风险辩论 + 组合经理二审
        # light（快评）：精简论证链，跳过辩论与风控二审，更快出结论
        if mode == "light":
            workflow.add_edge("Quality Gate", "Research Manager")
            workflow.add_edge("Research Manager", "Trader")
            workflow.add_edge("Trader", "Accuracy Guardian")
        else:
            workflow.add_edge("Quality Gate", "Bull Researcher")

            # 多空研究辩论
            workflow.add_conditional_edges(
                "Bull Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bear Researcher": "Bear Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_conditional_edges(
                "Bear Researcher",
                self.conditional_logic.should_continue_debate,
                {
                    "Bull Researcher": "Bull Researcher",
                    "Research Manager": "Research Manager",
                },
            )
            workflow.add_edge("Research Manager", "Trader")

            # 风险辩论三人组 + 组合经理二审
            workflow.add_edge("Trader", "Aggressive Analyst")
            workflow.add_conditional_edges(
                "Aggressive Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Conservative Analyst": "Conservative Analyst",
                    "Portfolio Manager": "Portfolio Manager",
                },
            )
            workflow.add_conditional_edges(
                "Conservative Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Neutral Analyst": "Neutral Analyst",
                    "Portfolio Manager": "Portfolio Manager",
                },
            )
            workflow.add_conditional_edges(
                "Neutral Analyst",
                self.conditional_logic.should_continue_risk_analysis,
                {
                    "Aggressive Analyst": "Aggressive Analyst",
                    "Portfolio Manager": "Portfolio Manager",
                },
            )
            workflow.add_edge("Portfolio Manager", "Accuracy Guardian")

        # Portfolio Manager -> Accuracy Guardian/END
        workflow.add_edge("Accuracy Guardian", END)

        return workflow
