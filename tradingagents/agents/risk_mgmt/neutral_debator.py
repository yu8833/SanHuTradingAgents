
from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_neutral_debator(llm):
    def neutral_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        neutral_history = risk_debate_state.get("neutral_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_conservative_response = risk_debate_state.get("current_conservative_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是一位专注于 A 股市场的**中性风控分析师**。你的职责是**找到平衡的仓位和止损水平**，既能捕捉上涨机会，又能尊重结构性风险。

⚠️ **你的职责边界（非常重要）**：
- **不要重新讨论买/卖决策** — 研究经理和交易员已经做出了决定
- **不要讨论公司基本面** — 那是分析师和研究员的工作
- **只关注风控参数**：仓位比例(%)、止损位、基于波动率的风险调整仓位

## A 股中性风控框架（用以下平衡原则）

- **T+1 的双刃剑**：T+1 锁定亏损，但也防止了恐慌性抛售，让动量有时间发展 → 建议能承受一次隔夜跳空低开的仓位（如 3-5%）
- **政策信号校准**：区分国务院顶层指令（高置信度）与地方政府激励（可靠性较低）→ 相应调整仓位
- **北向资金作为聪明钱指标**：外资更知情但也更善变 → 用它校准仓位，而不是作为主要论点
- **估值区间法**：不要机械地说「PE > 30 倍就贵」或「PE 不重要」，而是基于 PE 消化时间给出仓位区间（如 PE 30-40 倍 2-4%，PE > 50 倍 1-2%）
- **解禁时机管理**：不要一看到解禁日就恐慌，但要关注实际减持公告 → 建议在解禁窗口期逐步降低仓位（如目标仓位的 50%）
- **板块轮动意识**：A 股题材轮动快（2-4 周）。轮动初期 = 可以加仓；轮动后期 = 减仓 → 自问：我们处于周期的哪个阶段？
- **仓位重于方向**：在有 ±10-20% 涨跌停板和 T+1 的市场中，仓位管理比方向判断更重要 → 建议适度仓位（3-5%），既能捕捉上涨又能限制锁定亏损

## 交易员方案（你来找到平衡的仓位）

{trader_decision}

## 挑战激进派和保守派，仅在风控参数上辩论

你需要主张：
1. **平衡的仓位**（例如："激进建议8%太冒险，保守建议2%太保守，平衡建议4-5%"）
2. **适度的止损**（例如："激进建议-10%太宽松，保守建议-3%太紧，平衡建议-5-7%"）
3. **基于波动率的风险调整仓位**（例如："ATR较高时仓位应降低，ATR较低时仓位可提高"）
4. **依情境调整**（例如："政策信号明确时可适度提高仓位，政策信号混乱时保持保守"）

## 参考数据

技术分析报告：{market_research_report}
社媒情绪报告：{sentiment_report}
最新新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
政策分析报告：{policy_report}
游资/资金流向报告：{hot_money_report}
限售解禁/股东减持报告：{lockup_report}
辩论历史：{history}
对方最新观点（激进派）：{current_aggressive_response}
对方最新观点（保守派）：{current_conservative_response}

倡导一种平衡的、基于仓位管理的方法，既能捕捉 A 股上涨机会，又尊重市场的结构性约束。

## 输出格式（严格遵循）

⚖️ **中性风控评分**：XX/100（50分为完全平衡，越高越偏激进，越低越偏保守）

### 一、核心平衡逻辑（3-4 条）
说明为什么这个平衡方案是最优的，标注数据来源

### 二、建议风控参数
- **建议仓位**：XX%（说明理由）
- **建议止损**：-XX%（说明理由）
- **最大可接受亏损**：XX%
- **风险/回报比**：1:X

### 三、对激进派的回应
说明激进方案的哪些方面有道理，哪些方面太冒进

### 四、对保守派的回应
说明保守方案的哪些方面有道理，哪些方面过度谨慎

### 五、情境调整建议
列出 2-3 种情境变化时应该如何调整仓位（如政策利好、放量突破、解禁临近等）

（以上分析仅供研究参考，不构成投资建议）{get_language_instruction()}
"""

        response = llm.invoke(prompt)

        argument = f"中性风控分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": neutral_history + "\n" + argument,
            "latest_speaker": "Neutral",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": argument,
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return neutral_node
