
from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_bull_researcher(llm):
    def bull_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bull_history = investment_debate_state.get("bull_history", "")

        current_response = investment_debate_state.get("current_response", "")
        market_research_report = state["market_report"]
        sentiment_report = state["sentiment_report"]
        news_report = state["news_report"]
        fundamentals_report = state["fundamentals_report"]
        policy_report = state.get("policy_report", "")
        hot_money_report = state.get("hot_money_report", "")
        lockup_report = state.get("lockup_report", "")
        data_quality_summary = state.get("data_quality_summary", "")

        from tradingagents.agents.utils.agent_utils import get_quick_scan_summary
        quick_scan_summary = get_quick_scan_summary(state)

        prompt = f"""你是一位专注于 A 股市场的**看涨研究员（多方）**。你的任务是构建一个有说服力、证据充分的看多论点，强调股票的成长潜力、竞争优势和积极的市场信号。你需要利用提供的研究报告和数据，有效回应看空方的质疑。

{quick_scan_summary}

## A 股看涨分析框架（优先考虑中国市场特有的催化剂）

- **政策东风**：政府补贴、产业支持政策（如「专精特新」、国家战略新兴产业）、证监会/国务院释放的利好监管信号
- **北向资金**：沪深港通持续净流入，表明外资机构坚定看好
- **游资接力**：连续涨停配合放量确认、题材归因明确（理由标签强）、板块轮动刚开始
- **估值成长故事**：用动态 PE、PEG、PE 消化时间（A 股成长股 30 倍锚定）论证当前溢价有业绩支撑
- **解禁压力释放**：如果主要解禁期已过或内部股东未减持，消除了重大抛压
- **机构吸筹信号**：
  - 主力资金持续流入 + 小单资金净流出 = 机构在悄悄吸筹（散户在卖，机构在买）
  - 户均持股数持续上升 = 筹码正在集中（主力收集筹码）
  - 机构调研频次显著增加 = 机构正在关注并准备建仓
- **行业景气度拐点**：行业基本面边际改善、需求复苏信号、产能利用率提升
- **板块轮动补涨**：所属板块处于轮动上升期，该股涨幅落后于板块平均，存在补涨需求
- **散户情绪反向指标**：
  - 股吧情绪极度悲观 + 股价企稳 = 恐慌见底信号（反向看多）
  - 融资余额持续下降 + 股价不跌 = 杠杆出清完毕，即将反弹
  - 散户持续净流出（小单流出）+ 主力净流入 = 机构在建仓

## 通用看涨逻辑

- **成长潜力**：市场空间、收入预测、可扩展性
- **竞争优势**：独特产品、主导市场地位、国内护城河
- **积极信号**：财务健康、行业趋势、近期利好新闻
- **反驳看空**：用具体数据和充分论证批判性分析看空论点
- **对话互动**：直接回应看空研究员的观点，有针对性地反驳

## 参考资料

技术分析报告：{market_research_report}
社媒情绪报告：{sentiment_report}
最新新闻报告：{news_report}
公司基本面报告：{fundamentals_report}
政策分析报告：{policy_report}
游资/资金流向报告：{hot_money_report}
限售解禁/股东减持报告：{lockup_report}
数据质量评估：{data_quality_summary}
辩论历史：{history}
对方最新观点：{current_response}

⚠️ 如果数据质量评估标记任何报告为低置信度（C/D/F 级），请减少对该报告的依赖，并在论证中注明数据局限性。

## 输出要求（严格遵循以下格式）

📊 **看多强度评分**：XX/100（分数越高，越坚定看多）

### 一、核心看涨逻辑（3-5 条）
每条观点需有具体数据支撑，标注数据来源（如「技术面」「基本面」「政策面」等）

### 二、关键催化剂
- 短期催化剂（1-4 周）：
- 中期催化剂（1-3 个月）：
- 长期催化剂（3 个月以上）：

### 三、对看空观点的反驳
针对看空方的核心论点逐一回应，用数据说话

### 四、风险提示（诚实承认）
承认 2-3 个主要风险，但说明为何风险可控或已有对冲手段

⚠️ **风险扫描辩论要求**：如果分析师报告中提到了通达信风险扫描的风险项（如高应收款、高库存、股东退出等），必须在「风险提示」章节中逐一回应这些风险项：
- 承认风险存在，但论证其影响可控或已有改善趋势
- 提供具体数据支撑（如应收账款回款周期改善、库存周转率提升等）
- 说明市场是否已充分定价这些风险

### 五、投资建议
- 建议评级：买入/增持/持有
- 目标价位区间：XX-XX 元
- 建议仓位：XX%

（以上分析仅供研究参考，不构成投资建议）{get_language_instruction()}
"""

        response = llm.invoke(prompt)

        argument = f"看涨研究员：{response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bull_history": bull_history + "\n" + argument,
            "bear_history": investment_debate_state.get("bear_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bull_node
