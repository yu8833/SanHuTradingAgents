"""组合经理：综合风控辩论，做出最终投资决策。

两阶段流程：
1. 风控经理阶段：生成结构化的风控约束（仓位上限、止损位等）
2. 组合经理阶段：做出最终交易决策，必须尊重阶段1设定的风险约束

使用 LangChain 的结构化输出，让 LLM 直接生成 typed schema，分两次调用。
结果渲染回 markdown 格式，保存在 risk_control_decision 和 final_trade_decision 中。
"""

from __future__ import annotations

from tradingagents.agents.schemas import (
    PortfolioDecision,
    RiskControlDecision,
    render_pm_decision,
    render_risk_control_decision,
)
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    risk_llm = bind_structured(llm, RiskControlDecision, "风控经理")
    portfolio_llm = bind_structured(llm, PortfolioDecision, "组合经理")

    def portfolio_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])

        history = state["risk_debate_state"]["history"]
        risk_debate_state = state["risk_debate_state"]
        research_plan = state["investment_plan"]
        trader_plan = state["trader_investment_plan"]

        past_context = state.get("past_context", "")
        lessons_line = (
            f"- 历史决策和经验教训：\n{past_context}\n"
            if past_context
            else ""
        )

        # ============================================================
        # 阶段1：风控经理 — 设定风险约束（不是最终决策）
        # ============================================================
        risk_judge_prompt = f"""你是风控经理，你的职责是设定**风险约束**，而不是做出最终交易决策。

你的角色是纯粹的风险控制：
- 设定最大仓位上限（硬性约束）
- 建议基于风险/回报比的仓位（软性指导）
- 定义止损水平（防止灾难性损失）
- 计算最大可接受亏损（占组合的百分比）
- 识别最坏情景并估计损失幅度
- 提供风险缓释策略
- 给出关键风险因素
- 提供仓位管理建议
- 列出重点监控点

⚠️ 你不决定买/卖 — 那是组合经理的工作。
⚠️ 你不分析上涨潜力 — 那是研究员的工作。
⚠️ 你只设定组合经理必须遵守的风险参数。

{instrument_context}

---

**A 股交易约束**（必须纳入风险评估）：
- T+1 交割：当日买入的股票次日才能卖出
- 涨跌幅限制：主板 ±10%，科创板/创业板 ±20%，ST 股 ±5%
- 最小交易单位：主板 100 股（1 手），科创板/创业板 200 股
- 交易时间：北京时间 09:30-11:30，13:00-15:00
- ST/退市风险：ST 或 *ST 状态表示监管警告，需纳入仓位评估
- 融资融券资格：并非所有 A 股都可融资融券，默认只能现金交易

---

**风险评级标准**（基于风险状况，而非上涨潜力）：
- **买入（低风险）**：风险状况低（基本面稳定、低波动、无重大悬而未决的问题）
- **增持（较低风险）**：风险可控（有一些担忧但整体安全）
- **持有（中等风险）**：风险/回报平衡，谨慎持有
- **减持（较高风险）**：存在多个风险因素
- **卖出（高风险）**：结构性风险（如连续跌停风险、重大政策反转、ST 状态）

**参考资料：**
- 研究经理投资方案：**{research_plan}**
- 交易员交易方案：**{trader_plan}**
{lessons_line}
**风控分析师辩论历史：**
{history}

---

请输出结构化的风控决策，包含具体的数字（仓位%、止损%、最大亏损%）。
每个约束都必须基于辩论中的具体证据。
{get_language_instruction()}"""

        risk_control_decision = invoke_structured_or_freetext(
            risk_llm,
            llm,
            risk_judge_prompt,
            render_risk_control_decision,
            "风控经理",
        )

        # ============================================================
        # 阶段2：组合经理 — 做出最终决策（遵守风险约束）
        # ============================================================
        final_decision_prompt = f"""你是组合经理，你的职责是做出**最终交易决策**，必须遵守风控经理设定的风险约束。

⚠️ 你必须遵守风控经理的以下硬性约束：
- 最大仓位上限：绝对不能超过
- 止损水平：可以更紧，但不能更松
- 最大可接受亏损：仓位设置必须遵守

你可以：
- 选择比风控经理建议更保守的策略
- 将止损设置得比风控经理建议更紧
- 如果你不认同上涨潜力，可以降低仓位

你不可以：
- 超过最大仓位上限（这是硬性限制）
- 放松止损水平（这是安全约束）
- 忽视最坏情景分析

{instrument_context}

---

**A 股交易约束**（必须纳入决策）：
- T+1 交割：当日买入的股票次日才能卖出
- 涨跌幅限制：主板 ±10%，科创板/创业板 ±20%，ST 股 ±5%
- 最小交易单位：主板 100 股（1 手），科创板/创业板 200 股
- 交易时间：北京时间 09:30-11:30，13:00-15:00
- ST/退市风险：ST 或 *ST 状态表示监管警告，需纳入仓位评估
- 融资融券资格：并非所有 A 股都可融资融券，默认只能现金交易

---

**评级标准**（基于上涨/下跌的平衡）：
- **买入**：高度确信上涨，风险约束允许较大仓位
- **增持**：上涨有利，可以采用建议仓位
- **持有**：上涨/下跌平衡，维持适度仓位
- **减持**：上涨有限或下跌风险升高，降低敞口
- **卖出**：下跌主导或风险约束禁止有意义的仓位

**参考资料：**
- 研究经理投资方案：**{research_plan}**
- 交易员交易方案：**{trader_plan}**
- **风控经理约束（必须遵守）：** **{risk_control_decision}**
{lessons_line}
**风控分析师辩论历史：**
{history}

---

请做出最终决策。你的仓位必须 ≤ 风控经理的最大仓位上限。
你的止损必须 ≥ 风控经理的止损水平（即更紧或相等）。
{get_language_instruction()}"""

        final_trade_decision = invoke_structured_or_freetext(
            portfolio_llm,
            llm,
            final_decision_prompt,
            render_pm_decision,
            "组合经理",
        )

        new_risk_debate_state = {
            "judge_decision": risk_control_decision,
            "history": risk_debate_state["history"],
            "aggressive_history": risk_debate_state["aggressive_history"],
            "conservative_history": risk_debate_state["conservative_history"],
            "neutral_history": risk_debate_state["neutral_history"],
            "latest_speaker": "Judge",
            "current_aggressive_response": risk_debate_state["current_aggressive_response"],
            "current_conservative_response": risk_debate_state["current_conservative_response"],
            "current_neutral_response": risk_debate_state["current_neutral_response"],
            "count": risk_debate_state["count"],
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "risk_control_decision": risk_control_decision,
            "final_trade_decision": final_trade_decision,
        }

    return portfolio_manager_node
