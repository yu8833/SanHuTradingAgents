"""研究经理：将多空辩论转化为结构化的投资方案，交付给交易员执行。"""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import build_instrument_context, get_language_instruction
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "研究经理")

    def research_manager_node(state) -> dict:
        instrument_context = build_instrument_context(state["company_of_interest"])
        history = state["investment_debate_state"].get("history", "")

        investment_debate_state = state["investment_debate_state"]
        
        quick_result = state.get("quick_analysis_result", {})
        quick_context_text = ""
        if quick_result and isinstance(quick_result, dict) and quick_result.get("buy_signal"):
            quick_context_text = f"""
---

**量化速览结果（基准参考）：**
- 趋势：{quick_result.get('trend_status', 'N/A')}
- 信号：{quick_result.get('buy_signal', 'N/A')}
- 评分：{quick_result.get('signal_score', 'N/A')}/100
- 置信度：{quick_result.get('confidence', 'N/A')}%
- 摘要：{quick_result.get('summary', 'N/A')}
- 关键价位：支撑 {quick_result.get('support_levels', ['N/A'])[0] if quick_result.get('support_levels') else 'N/A'} | 阻力 {quick_result.get('resistance_levels', ['N/A'])[0] if quick_result.get('resistance_levels') else 'N/A'} | 止损 {quick_result.get('stop_loss', 'N/A')} | 目标 {quick_result.get('target', 'N/A')}

**你的职责：**
1. 在分析中明确提及量化速览的结论
2. 明确说明你「同意」「修正」还是「不同意」速览结果
3. 如果修正或不同意，必须提供辩论中有力的证据支撑
4. 除非辩论中出现重大新证据改变了整体判断，否则最终决策应大致与速览方向一致
"""

        prompt = f"""你是研究经理，同时也是多空辩论的主持人和裁判。你的职责是批判性地评估本轮辩论，为交易员输出一份清晰、可执行的投资方案。

{instrument_context}

注意：这是 A 股（中国大陆）股票。在综合辩论结论时，必须考虑监管政策影响、游资/资金流向动态、以及限售解禁/内部减持风险。
{quick_context_text}
---

## 评级标准（严格选择一个）

- **买入**：高度确信多方论点成立，多方论据显著强于空方（差距>30%），且市场环境配合
- **增持**：建设性看多，多方论据明显占优，风险可控
- **持有**：多空平衡或论据强度相近，或辩论未充分收敛，建议维持现有仓位
- **减持**：谨慎偏空，空方论据明显占优，建议降低仓位
- **卖出**：高度确信空方论点成立，空方论据显著强于多方，且有明确下行催化剂

### A 股评级调整原则（必须遵守）：

1. **优先中性原则**：在 A 股高不确定性环境下，当多空双方论据强度相差不大时，默认选择中性立场（持有），而非强制站队。
2. **辩论收敛度影响**：
   - 如果辩论充分收敛（双方观点接近一致），可以根据胜出方给出明确评级
   - 如果辩论未收敛或出现疲劳，应向「持有」方向偏移，避免在分歧大时做出极端决策
3. **市场环境校准**：
   - 牛市/强势市场：可适当提高乐观评级的权重
   - 熊市/弱势市场：可适当提高谨慎评级的权重
   - 震荡市：优先选择持有，等待方向明确
4. **散户情绪反向参考**：
   - 散户情绪极度乐观时，即使多方论据占优也应谨慎，适当向持有/减持偏移
   - 散户情绪极度悲观时，即使空方论据占优也不应过度看空，适当向持有/增持偏移
5. **风险收益比优先**：评级应基于风险收益比，而非单纯的多空胜负。即使看多，如果上涨空间有限但下跌风险大，也应谨慎。

---

## 输出格式（严格遵循，所有标题使用纯中文）

# 投资研究方案

## 1. 投资评级
**买入/增持/持有/减持/卖出**

## 2. 观点置信度
**XX** / 100

## 3. 多方核心论点
（2-3句话提炼多方最有力论据）

## 4. 空方核心论点
（2-3句话提炼空方最有力论据）

## 5. 关键分歧点
| 争议焦点 | 多方观点 | 空方观点 | 裁判倾向 |
|----------|----------|----------|----------|
| 问题1 | ... | ... | 多方/空方胜出 |

## 6. 投资亮点
- 亮点1
- 亮点2
- ...

## 7. 风险提示
- 风险1
- 风险2
- ...

## 8. 适用场景
（适合什么样的投资者和市场环境）

## 9. 综合判定理由
（一段话总结为什么给出这个评级）

## 10. 策略行动建议
（给交易员的具体执行指导）

---

## 辩论历史：
{history}
{get_language_instruction()}"""

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "研究经理",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node
