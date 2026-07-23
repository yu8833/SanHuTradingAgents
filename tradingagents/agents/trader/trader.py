"""交易员：将研究经理的投资方案转化为具体的交易执行方案。"""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "交易员")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]

        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")

        astock_context_parts = []
        if policy_report:
            astock_context_parts.append(f"政策分析报告：\n{policy_report}")
        if hot_money_report:
            astock_context_parts.append(f"游资/资金流向报告：\n{hot_money_report}")
        if lockup_report:
            astock_context_parts.append(f"限售解禁/股东减持报告：\n{lockup_report}")
        astock_context = "\n\n".join(astock_context_parts)

        extra_context = ""
        if astock_context:
            extra_context = f"**额外的 A 股分析师参考：**\n{astock_context}\n"

        prompt = f"""你是一位专注于 A 股市场的交易员。你的任务是将研究经理的投资方案转化为一份具体、可执行的交易方案。

你必须考虑 A 股的交易规则：
- T+1 交割：当天买入的股票次日才能卖出
- 涨跌幅限制：主板 ±10%，科创板/创业板 ±20%，ST 股 ±5%
- 最小交易单位：主板 100 股（1 手），科创板/创业板 200 股
- 交易时间：北京时间 09:30-11:30，13:00-15:00

你的交易决策必须基于分析师报告和研究方案。入场价、止损位、仓位等参数必须具体明确。
（以上参数仅供技术研究参考，不构成投资建议）

---

基于研究团队（包括技术面、情绪面、新闻、基本面、政策、资金流向、限售解禁等专家）的综合分析，以下是 {company_name} 的投资方案。

{instrument_context}

**研究经理投资方案：**
{investment_plan}

{extra_context}
---

## 输出格式（严格遵循）

请按以下结构输出，**所有标题和标签使用纯中文，不要出现任何英文标签**：

# 交易员执行方案

## 🎯 交易决策：买入/持有/卖出

**交易置信度**：XX/100

---

## 📝 核心理由

（4-6句话，基于分析师报告和研究方案说明为什么做出这个决策）

---

## 📊 分析要点

### 技术面要点

（2-3条关键技术指标、支撑位、阻力位）

### 基本面要点

（2-3条关键基本面因素、估值情况）

---

## 🎯 交易参数

- **入场价**：XXX 元
- **第一目标位**：XXX 元
- **第二目标位**：XXX 元（可选）
- **止损位**：XXX 元
- **风险/回报比**：例如 1:2.5
- **建议仓位**：仓位比例和建仓方式
- **预计持有周期**：例如 1-2周、1-3个月

---

## 📋 入场策略

（如何建仓：现价入场/回调入场/分批建仓等）

---

## ⚡ 关键触发条件

（2-3个会触发交易的事件或价位）

---

## ⚠️ 交易风险提示

（2-3个主要风险）

最终交易决策：**买入/持有/卖出**

> 以上分析仅供研究参考，不构成投资建议。投资有风险，入市需谨慎。

请基于这些洞察，制定一份精确的交易执行方案。
{get_language_instruction()}
"""

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_trader_proposal,
            "交易员",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
