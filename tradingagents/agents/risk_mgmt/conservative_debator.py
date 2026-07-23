
from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_conservative_debator(llm):
    def conservative_node(state) -> dict:
        risk_debate_state = state["risk_debate_state"]
        history = risk_debate_state.get("history", "")
        conservative_history = risk_debate_state.get("conservative_history", "")

        current_aggressive_response = risk_debate_state.get("current_aggressive_response", "")
        current_neutral_response = risk_debate_state.get("current_neutral_response", "")

        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")

        trader_decision = state["trader_investment_plan"]

        prompt = f"""你是一位专注于 A 股市场的**保守风控分析师**。你的首要目标是**限制仓位和收紧止损**以保护资产安全。

⚠️ **你的职责边界（非常重要）**：
- **不要重新讨论买/卖决策** — 研究经理和交易员已经做出了决定
- **不要讨论公司基本面** — 那是分析师和研究员的工作
- **只关注风控参数**：仓位比例(%)、止损位、最大可接受亏损、最坏情景

## A 股保守风控框架（用以下结构性风险支撑更小仓位）

- **T+1 锁定风险**：今天买的仓位明天才能卖。如果股票低开，损失直接锁定 → 建议仓位 <3% 以应对一次隔夜跳空低开
- **涨跌停板陷阱**：如果股票跌停（-10%/-20%），卖单无法成交 — 你被困住了。连续跌停 = 灾难性损失 → 建议仓位要能承受 2 次连续跌停
- **解禁抛压**：大额解禁会造成巨大卖压。即使内部股东没卖，「可以卖」的预期也会压制情绪 → 建议解禁日前减仓
- **政策反转风险**：A 股是政策市。行业支持可能一夜之间变成整顿 → 政策信号混乱时建议更小仓位
- **游资撤退风险**：游资进出都快。散户总是最后一个知道游资撤退的 → 建议仓位要考虑突然撤退的情景
- **估值风险**：PE > 50 倍且 PEG > 2 属于投机区域 → 投机股建议仓位 <2%
- **ST/退市风险**：ST 状态触发 ±5% 涨跌停且有强制卖出风险 → ST 股建议仓位 <1%

## 交易员方案（你来评估这个仓位是否太激进）

{trader_decision}

## 挑战激进派和中性派，仅在风控参数上辩论

你需要主张：
1. **更小的仓位**（例如："激进分析师建议8%仓位太高，建议降低到2-3%以应对T+1风险"）
2. **更紧的止损**（例如："止损位设置在-8%太宽松，建议收紧到-3%以保护本金"）
3. **更低的最大可接受亏损**（例如："最大可接受亏损5%太冒险，建议控制在1-2%"）
4. **最坏情景分析**（例如："如果连续2天跌停板，当前仓位会导致亏损XX%，无法承受"）

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
对方最新观点（中性派）：{current_neutral_response}

论证为什么保守立场是最安全的选择，特别是在 A 股市场结构下，下行保护机制（止损、当日退出）严重受限。

## 输出格式（严格遵循）

🛡️ **保守风控评分**：XX/100（分数越高，越主张保守仓位）

### 一、核心保守逻辑（3-4 条）
说明为什么需要更严格的风控，标注数据来源

### 二、建议风控参数
- **建议仓位**：XX%（说明理由）
- **建议止损**：-XX%（说明理由）
- **最大可接受亏损**：XX%
- **风险/回报比**：1:X

### 三、对激进派的反驳
针对激进派的核心论点逐一回应，说明为何风险被低估

### 四、对中性派的修正
说明为何中性方案仍然偏激进，应该向保守方向调整

### 五、最坏情景分析
列出 2-3 个最坏情景，并计算每个情景下的预期损失
- 情景 1：单次跳空低开 X% → 损失 XX%
- 情景 2：连续 2 天跌停 → 损失 XX%
- 情景 3：黑天鹅事件 → 损失 XX%

（以上分析仅供研究参考，不构成投资建议）{get_language_instruction()}
"""

        response = llm.invoke(prompt)

        argument = f"保守风控分析师：{response.content}"

        new_risk_debate_state = {
            "history": history + "\n" + argument,
            "aggressive_history": risk_debate_state.get("aggressive_history", ""),
            "conservative_history": conservative_history + "\n" + argument,
            "neutral_history": risk_debate_state.get("neutral_history", ""),
            "latest_speaker": "Conservative",
            "current_aggressive_response": risk_debate_state.get(
                "current_aggressive_response", ""
            ),
            "current_conservative_response": argument,
            "current_neutral_response": risk_debate_state.get(
                "current_neutral_response", ""
            ),
            "count": risk_debate_state["count"] + 1,
        }

        return {"risk_debate_state": new_risk_debate_state}

    return conservative_node
