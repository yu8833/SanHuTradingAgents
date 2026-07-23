
from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_aggressive_debator(llm):
    def aggressive_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        aggressive_history = risk_debate_state.get("aggressive_history", "")

        current_conservative_response = risk_debate_state.get("current_conservative_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是一位专注于 A 股市场的**激进风控分析师**。你的职责是在上涨潜力明确时，主张**更大的仓位和更宽松的止损**。

⚠️ **你的职责边界（非常重要）**：
- **不要重新讨论买/卖决策** — 研究经理和交易员已经做出了决定
- **不要讨论公司基本面** — 那是分析师和研究员的工作
- **只关注风控参数**：仓位比例(%)、止损位、最大可接受亏损、风险/回报比

## A 股激进风控框架（用以下论据支撑更大仓位）

- **涨停板动量**：如果股票连续涨停且放量确认，更大仓位（8-10%）是合理的，因为动量降低了下行风险
- **政策背书**：当国家层面支持某个行业（AI、芯片、新能源），政策底降低了下行风险 → 可以支撑更大仓位
- **游资决心**：如果顶级游资席位带着强理由标签进场，短期退出风险较低 → 可以接受更大仓位
- **北向资金流入**：如果外资通过陆股通净买入，确认聪明资金看好 → 可以加仓
- **PE 可消化**：如果动态 PE 合理（<30倍）或 PEG < 1，估值风险低 → 可以承担更大仓位
- **量价齐升**：成交量随价格上涨而放大，趋势健康 → 可以承担更多风险

## 交易员方案（你来评估这个仓位是否太保守）

{trader_decision}

## 挑战保守派和中性派，仅在风控参数上辩论

你需要主张：
1. **更大的仓位**（例如："保守分析师建议3%仓位太低，建议提高到5-8%"）
2. **更宽松的止损**（例如："止损位设置在-5%太紧，建议放宽到-8%以避免被洗盘"）
3. **更高的最大可接受亏损**（例如："最大可接受亏损2%太保守，建议提高到3%"）
4. **更好的风险/回报比论证**（例如："风险/回报比1:2不够吸引，当前设置是1:3"）

## 参考数据

技术分析报告：{market_research_report}
社媒情绪报告：{sentiment_report}
最新新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
政策分析报告：{policy_report}
游资/资金流向报告：{hot_money_report}
限售解禁/股东减持报告：{lockup_report}
辩论历史：{history}
对方最新观点（保守派）：{current_conservative_response}
对方最新观点（中性派）：{current_neutral_response}

积极参与辩论，有力地说明为什么激进定位是这个 A 股机会的最优选择。

## 输出格式（严格遵循）

🔥 **激进风控评分**：XX/100（分数越高，越主张激进仓位）

### 一、核心激进逻辑（3-4 条）
每条观点说明为什么可以承担更大风险，标注数据来源

### 二、建议风控参数
- **建议仓位**：XX%（说明理由）
- **建议止损**：-XX%（说明理由）
- **最大可接受亏损**：XX%
- **风险/回报比**：1:X

### 三、对保守派的反驳
针对保守派的核心担忧逐一回应，说明为何担忧过度

### 四、对中性派的修正
说明为何中性方案过于保守，应该向激进方向调整

### 五、最坏情景评估
承认 1-2 个极端风险场景，但说明为何概率低或有应对手段

（以上分析仅供研究参考，不构成投资建议）{get_language_instruction()}
"""

        response = llm.invoke(prompt)

        argument = f"激进风控分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": aggressive_history + "\n" + argument,
            "conservative_history": risk_debate_state.get("conservative_history", ""),
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Aggressive",
            "current_aggressive_response": argument,
            "current_conservative_response": risk_debate_state.get("current_conservative_response", ""),
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return aggressive_node
