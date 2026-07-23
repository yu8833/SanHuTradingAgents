"""Pydantic schemas used by agents that produce structured output.

The framework's primary artifact is still prose: each agent's natural-language
reasoning is what users read in the saved markdown reports and what the
downstream agents read as context.  Structured output is layered onto the
three decision-making agents (Research Manager, Trader, Portfolio Manager)
so that:

- Their outputs follow consistent section headers across runs and providers
- Each provider's native structured-output mode is used (json_schema for
  OpenAI/xAI, response_schema for Gemini, tool-use for Anthropic)
- Schema field descriptions become the model's output instructions, freeing
  the prompt body to focus on context and the rating-scale guidance
- A render helper turns the parsed Pydantic instance back into the same
  markdown shape the rest of the system already consumes, so display,
  memory log, and saved reports keep working unchanged
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared rating types
# ---------------------------------------------------------------------------


class PortfolioRating(str, Enum):
    """5-tier rating used by the Research Manager and Portfolio Manager."""

    BUY = "Buy"
    OVERWEIGHT = "Overweight"
    HOLD = "Hold"
    UNDERWEIGHT = "Underweight"
    SELL = "Sell"


class TraderAction(str, Enum):
    """3-tier transaction direction used by the Trader.

    The Trader's job is to translate the Research Manager's investment plan
    into a concrete transaction proposal: should the desk execute a Buy, a
    Sell, or sit on Hold this round.  Position sizing and the nuanced
    Overweight / Underweight calls happen later at the Portfolio Manager.
    """

    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"


# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------


class ResearchPlan(BaseModel):
    """研究经理输出的结构化投资方案。

    作为多空辩论的裁判和综合者，研究经理需要给出明确的投资评级、
    多空双方核心观点的提炼、以及可执行的策略建议。
    """

    recommendation: PortfolioRating = Field(
        description=(
            "投资评级，从以下选项中选一个："
            "买入 / 增持 / 持有 / 减持 / 卖出。"
            "只有在双方证据真正均衡时才使用持有，"
            "否则应明确倾向于论证更充分的一方。"
        ),
    )
    conviction_score: int = Field(
        description=(
            "观点置信度评分，0-100 分的整数。"
            "分数越高表示对该评级的把握越大。"
            "80分以上表示高度确信，60-80表示中等确信，60以下表示低确信。"
        ),
    )
    bull_case_summary: str = Field(
        description=(
            "多方核心论点总结，2-3句话，提炼看涨方最有力的论据。"
        ),
    )
    bear_case_summary: str = Field(
        description=(
            "空方核心论点总结，2-3句话，提炼看跌方最有力的论据。"
        ),
    )
    key_debate_points: str = Field(
        description=(
            "辩论关键分歧点，列出3-5个多空双方争议最大的问题，"
            "以及哪一方在该点上更有说服力。"
        ),
    )
    investment_highlights: str = Field(
        description=(
            "投资亮点，3-5条分点列出，说明支持该评级的核心理由。"
        ),
    )
    risk_warnings: str = Field(
        description=(
            "风险提示，2-4条分点列出，说明主要的下行风险和需要关注的因素。"
        ),
    )
    applicable_scenarios: str = Field(
        description=(
            "适用场景，说明该投资建议适合什么样的投资者和市场环境。"
        ),
    )
    rationale: str = Field(
        description=(
            "综合判定理由，一段话总结为什么最终给出这个评级，"
            "解释多空因素如何权衡。"
        ),
    )
    strategic_actions: str = Field(
        description=(
            "策略行动建议，为交易员提供具体的执行指导，"
            "包括与评级一致的仓位建议、入场时机、操作方式等。"
        ),
    )


def render_research_plan(plan: ResearchPlan) -> str:
    """将研究经理的投资方案渲染为中文 Markdown 格式。"""
    rating_cn = {
        "Buy": "买入",
        "Overweight": "增持",
        "Hold": "持有",
        "Underweight": "减持",
        "Sell": "卖出",
    }.get(plan.recommendation.value, plan.recommendation.value)

    lines = [
        f"# 投资研究方案",
        "",
        f"## 🎯 投资评级：{rating_cn}",
        "",
        f"**观点置信度**：{plan.conviction_score}/100",
        "",
        "---",
        "",
        "## 📊 多空辩论摘要",
        "",
        "### 🐂 多方核心论点",
        plan.bull_case_summary,
        "",
        "### 🐻 空方核心论点",
        plan.bear_case_summary,
        "",
        "### ⚡ 关键分歧点",
        plan.key_debate_points,
        "",
        "---",
        "",
        "## 💡 投资亮点",
        plan.investment_highlights,
        "",
        "## ⚠️ 风险提示",
        plan.risk_warnings,
        "",
        "## 🎯 适用场景",
        plan.applicable_scenarios,
        "",
        "---",
        "",
        "## 📝 综合判定理由",
        plan.rationale,
        "",
        "## 📋 策略行动建议",
        plan.strategic_actions,
        "",
        "---",
        "",
        "> 以上分析仅供研究参考，不构成投资建议。投资有风险，入市需谨慎。",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trader
# ---------------------------------------------------------------------------


class TraderProposal(BaseModel):
    """交易员输出的结构化交易方案。

    交易员阅读研究经理的投资方案和分析师报告，
    然后将其转化为具体的交易方案：操作方向、核心理由、
    以及入场价、止损位、仓位等实操参数。
    """

    action: TraderAction = Field(
        description="交易方向，从以下选项中选一个：买入 / 持有 / 卖出。",
    )
    conviction_score: int = Field(
        description=(
            "交易置信度评分，0-100 分的整数。"
            "分数越高表示对该交易决策的把握越大。"
            "80分以上表示高度确信，60-80表示中等确信，60以下表示低确信。"
        ),
    )
    reasoning: str = Field(
        description=(
            "交易核心理由，4-6句话，基于分析师报告和研究方案，"
            "说明为什么做出这个交易决策。"
        ),
    )
    technical_analysis_summary: str = Field(
        description=(
            "技术面要点总结，2-3条，列出关键技术指标、支撑位、阻力位等。"
        ),
    )
    fundamental_analysis_summary: str = Field(
        description=(
            "基本面要点总结，2-3条，列出关键基本面因素、估值情况等。"
        ),
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="入场价格，以股票报价货币计价。",
    )
    target_price: Optional[float] = Field(
        default=None,
        description="目标价格，第一目标位，以股票报价货币计价。",
    )
    second_target_price: Optional[float] = Field(
        default=None,
        description="第二目标价格（可选），更高的目标位，以股票报价货币计价。",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="止损价格，以股票报价货币计价。",
    )
    position_sizing: Optional[str] = Field(
        default=None,
        description="仓位建议，例如『5% 组合仓位』或『分 3 批建仓，每批 2%』。",
    )
    entry_strategy: Optional[str] = Field(
        default=None,
        description="入场策略，说明如何建仓，例如『现价直接入场』『回调至XX元入场』『分3批建仓』等。",
    )
    risk_reward_ratio: Optional[str] = Field(
        default=None,
        description="风险/回报比，例如『1:2.5』。",
    )
    holding_period: Optional[str] = Field(
        default=None,
        description="预计持有周期，例如『1-2周』『1-3个月』『中长期』等。",
    )
    key_triggers: Optional[str] = Field(
        default=None,
        description="关键触发条件，列出 2-3 个会触发交易的事件或价位。",
    )
    risk_notes: Optional[str] = Field(
        default=None,
        description="交易风险提示，列出 2-3 个该交易需要注意的主要风险。",
    )


def render_trader_proposal(proposal: TraderProposal) -> str:
    """将交易员方案渲染为中文 Markdown 格式。"""
    action_cn = {
        "Buy": "买入",
        "Hold": "持有",
        "Sell": "卖出",
    }.get(proposal.action.value, proposal.action.value)

    lines = [
        f"# 交易员执行方案",
        "",
        f"## 🎯 交易决策：{action_cn}",
        "",
        f"**交易置信度**：{proposal.conviction_score}/100",
        "",
        "---",
        "",
        "## 📝 核心理由",
        proposal.reasoning,
        "",
        "---",
        "",
        "## 📊 分析要点",
        "",
        "### 技术面要点",
        proposal.technical_analysis_summary,
        "",
        "### 基本面要点",
        proposal.fundamental_analysis_summary,
        "",
        "---",
        "",
        "## 🎯 交易参数",
        "",
    ]

    if proposal.entry_price is not None:
        lines.append(f"- **入场价**：{proposal.entry_price} 元")
    if proposal.target_price is not None:
        lines.append(f"- **第一目标位**：{proposal.target_price} 元")
    if proposal.second_target_price is not None:
        lines.append(f"- **第二目标位**：{proposal.second_target_price} 元")
    if proposal.stop_loss is not None:
        lines.append(f"- **止损位**：{proposal.stop_loss} 元")
    if proposal.risk_reward_ratio:
        lines.append(f"- **风险/回报比**：{proposal.risk_reward_ratio}")
    if proposal.position_sizing:
        lines.append(f"- **建议仓位**：{proposal.position_sizing}")
    if proposal.holding_period:
        lines.append(f"- **预计持有周期**：{proposal.holding_period}")

    lines.extend(["", "---", ""])

    if proposal.entry_strategy:
        lines.extend([
            "## 📋 入场策略",
            proposal.entry_strategy,
            "",
            "---",
            "",
        ])

    if proposal.key_triggers:
        lines.extend([
            "## ⚡ 关键触发条件",
            proposal.key_triggers,
            "",
            "---",
            "",
        ])

    if proposal.risk_notes:
        lines.extend([
            "## ⚠️ 交易风险提示",
            proposal.risk_notes,
            "",
            "---",
            "",
        ])

    lines.extend([
        f"最终交易决策：**{action_cn}**",
        "",
        "> 以上分析仅供研究参考，不构成投资建议。投资有风险，入市需谨慎。",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Portfolio Manager
# ---------------------------------------------------------------------------


class RiskControlDecision(BaseModel):
    """风控经理输出的结构化风控评估。

    风控经理的职责是设定风险约束，而不是做出最终交易决策。
    本 schema 捕获仓位上限、止损水平、最坏情景等，
    组合经理必须尊重这些约束。
    """

    risk_overview: str = Field(
        description=(
            "风险概览，一段话总结整体风险状况，"
            "说明最主要的风险来源和风险等级。"
        ),
    )
    risk_score: int = Field(
        description=(
            "综合风险评分，0-100 分的整数。"
            "分数越高风险越大：0-30低风险，30-60中等风险，60-80较高风险，80-100高风险。"
        ),
    )
    risk_rating: PortfolioRating = Field(
        description=(
            "风险评级，从以下选项中选一个："
            "买入(低风险) / 增持(较低风险) / 持有(中等风险) / "
            "减持(较高风险) / 卖出(高风险)。"
            "基于风险状况评估，而不是上涨潜力。"
        ),
    )
    max_position_size: float = Field(
        description=(
            "最大仓位上限，占组合的百分比（例如 5.0 表示最高 5%）。"
            "这是组合经理必须遵守的硬性限制。"
        ),
    )
    recommended_position_size: float = Field(
        description=(
            "建议仓位，占组合的百分比，基于风险/回报比（例如 3.0 表示建议 3%）。"
            "这是软性指导，不是硬性限制。"
        ),
    )
    stop_loss_level: float = Field(
        description=(
            "建议止损位，从入场价下跌的百分比（例如 5.0 表示 -5% 止损）。"
            "用于防止灾难性损失。"
        ),
    )
    max_acceptable_loss: float = Field(
        description=(
            "最大可接受亏损，占组合的百分比（例如 0.5 表示最多 0.5%）。"
            "仓位大小必须遵守这个约束。"
        ),
    )
    key_risk_factors: str = Field(
        description=(
            "关键风险因素，3-5条分点列出，说明最主要的风险来源，"
            "包括政策风险、市场风险、流动性风险、个股风险等。"
        ),
    )
    worst_case_scenario: str = Field(
        description=(
            "最坏情景描述，说明可能发生的最糟糕情况，"
            "包括估计的损失幅度（例如『连续2日跌停板，损失约4%』）。"
        ),
    )
    risk_mitigation: str = Field(
        description=(
            "风险缓释策略，3-4条具体措施，"
            "例如『分批建仓，避免一次性all-in』『设置移动止损保护利润』等。"
        ),
    )
    position_management: str = Field(
        description=(
            "仓位管理建议，说明如何动态调整仓位，"
            "例如『盈利超过X%后加仓』『跌破XX元减仓』等。"
        ),
    )
    monitoring_points: str = Field(
        description=(
            "重点监控点，2-3条，说明持仓期间需要密切关注的信号或事件。"
        ),
    )


def render_risk_control_decision(decision: RiskControlDecision) -> str:
    """将风控决策渲染为中文 Markdown 格式。"""
    risk_rating_cn = {
        "Buy": "低风险（买入级）",
        "Overweight": "较低风险（增持级）",
        "Hold": "中等风险（持有级）",
        "Underweight": "较高风险（减持级）",
        "Sell": "高风险（卖出级）",
    }.get(decision.risk_rating.value, decision.risk_rating.value)

    lines = [
        f"# 风控约束报告",
        "",
        f"## ⚠️ 风险评级：{risk_rating_cn}",
        "",
        f"**综合风险评分**：{decision.risk_score}/100",
        "",
        f"**风险概览**：{decision.risk_overview}",
        "",
        "---",
        "",
        "## 📊 风控参数",
        "",
        f"- **最大仓位上限**：{decision.max_position_size}%（硬性限制）",
        f"- **建议仓位**：{decision.recommended_position_size}%",
        f"- **建议止损位**：-{decision.stop_loss_level}%",
        f"- **最大可接受亏损**：{decision.max_acceptable_loss}%",
        "",
        "---",
        "",
        "## 🔴 关键风险因素",
        decision.key_risk_factors,
        "",
        "---",
        "",
        "## 💀 最坏情景",
        decision.worst_case_scenario,
        "",
        "---",
        "",
        "## 🛡️ 风险缓释策略",
        decision.risk_mitigation,
        "",
        "---",
        "",
        "## 📈 仓位管理建议",
        decision.position_management,
        "",
        "---",
        "",
        "## 👁️ 重点监控点",
        decision.monitoring_points,
        "",
        "---",
        "",
        f"**风险等级（英文）**：{decision.risk_rating.value}",
        "",
        "> 以上分析仅供研究参考，不构成投资建议。投资有风险，入市需谨慎。",
    ]

    return "\n".join(lines)


class PortfolioDecision(BaseModel):
    """组合经理输出的最终投资决策。

    组合经理综合所有分析师报告、多空辩论、风控辩论的结果，
    给出最终的投资评级和完整的执行方案。
    """

    rating: PortfolioRating = Field(
        description=(
            "最终投资评级，从以下选项中选一个："
            "买入(Buy) / 增持(Overweight) / 持有(Hold) / "
            "减持(Underweight) / 卖出(Sell)。"
            "基于分析师辩论和风控评估综合得出。"
        ),
    )
    conviction_score: int = Field(
        description=(
            "投资置信度评分，0-100 分的整数。"
            "分数越高表示对该评级的把握越大。"
            "80分以上表示高度确信，60-80表示中等确信，60以下表示低确信。"
        ),
    )
    executive_summary: str = Field(
        description=(
            "执行摘要，简洁的行动计划，涵盖入场策略、仓位、"
            "关键风险水平、时间周期。3-5 句话。"
        ),
    )
    investment_thesis: str = Field(
        description=(
            "投资逻辑详述，基于分析师辩论中的具体证据进行深入推理。"
            "说明为什么做出这个最终决策。"
        ),
    )
    bull_case_key_points: str = Field(
        description=(
            "多方核心观点，2-3 条，提炼看涨方最有说服力的论点。"
        ),
    )
    bear_case_key_points: str = Field(
        description=(
            "空方核心观点，2-3 条，提炼看跌方最有说服力的论点。"
        ),
    )
    risk_assessment: str = Field(
        description=(
            "风险评估总结，说明主要风险因素以及风险可控程度。"
        ),
    )
    price_target: Optional[float] = Field(
        default=None,
        description="目标价格，以股票报价货币计价。",
    )
    stop_loss_price: Optional[float] = Field(
        default=None,
        description="止损价格，以股票报价货币计价。",
    )
    recommended_position: Optional[str] = Field(
        default=None,
        description="建议仓位，例如『3-5% 组合仓位』。",
    )
    time_horizon: Optional[str] = Field(
        default=None,
        description="建议持有周期，例如『3-6 个月』。",
    )
    entry_strategy: Optional[str] = Field(
        default=None,
        description="入场策略，说明如何建仓。",
    )
    key_catalysts: Optional[str] = Field(
        description="关键催化剂，2-3 个可能推动股价朝预期方向发展的事件。",
        default=None,
    )
    key_risks: Optional[str] = Field(
        description="关键风险，2-3 个可能导致投资失败的主要风险。",
        default=None,
    )
    monitoring_plan: Optional[str] = Field(
        description="跟踪计划，说明持仓期间需要重点关注哪些指标和事件。",
        default=None,
    )


def render_pm_decision(decision: PortfolioDecision) -> str:
    """将组合经理决策渲染为中文 Markdown 格式。"""
    rating_cn = {
        "Buy": "买入",
        "Overweight": "增持",
        "Hold": "持有",
        "Underweight": "减持",
        "Sell": "卖出",
    }.get(decision.rating.value, decision.rating.value)

    lines = [
        f"# 最终交易决策",
        "",
        f"## 🎯 投资评级：{rating_cn} ({decision.rating.value})",
        "",
        f"**投资置信度**：{decision.conviction_score}/100",
        "",
        "---",
        "",
        "## 📝 执行摘要",
        decision.executive_summary,
        "",
        "---",
        "",
        "## 💡 投资逻辑",
        decision.investment_thesis,
        "",
        "---",
        "",
        "## ⚖️ 多空权衡",
        "",
        "### 🐂 多方核心观点",
        decision.bull_case_key_points,
        "",
        "### 🐻 空方核心观点",
        decision.bear_case_key_points,
        "",
        "---",
        "",
        "## ⚠️ 风险评估",
        decision.risk_assessment,
        "",
        "---",
        "",
        "## 🎯 交易参数",
        "",
    ]

    if decision.price_target is not None:
        lines.append(f"- **目标价**：{decision.price_target} 元")
    if decision.stop_loss_price is not None:
        lines.append(f"- **止损价**：{decision.stop_loss_price} 元")
    if decision.recommended_position:
        lines.append(f"- **建议仓位**：{decision.recommended_position}")
    if decision.time_horizon:
        lines.append(f"- **持有周期**：{decision.time_horizon}")
    if decision.entry_strategy:
        lines.append(f"- **入场策略**：{decision.entry_strategy}")

    lines.extend(["", "---", ""])

    if decision.key_catalysts:
        lines.extend([
            "## ⚡ 关键催化剂",
            decision.key_catalysts,
            "",
            "---",
            "",
        ])

    if decision.key_risks:
        lines.extend([
            "## 🔴 关键风险",
            decision.key_risks,
            "",
            "---",
            "",
        ])

    if decision.monitoring_plan:
        lines.extend([
            "## 👁️ 跟踪计划",
            decision.monitoring_plan,
            "",
            "---",
            "",
        ])

    lines.extend([
        f"**最终定性评级**：{rating_cn}",
        "",
        f"**最终交易决策**：{rating_cn} ({decision.rating.value})",
        "",
        "> 以上分析仅供研究参考，不构成投资建议。投资有风险，入市需谨慎。",
    ])

    return "\n".join(lines)
