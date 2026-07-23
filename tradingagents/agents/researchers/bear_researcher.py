
from tradingagents.agents.utils.agent_utils import get_language_instruction


def create_bear_researcher(llm):
    def bear_node(state) -> dict:
        investment_debate_state = state["investment_debate_state"]
        history = investment_debate_state.get("history", "")
        bear_history = investment_debate_state.get("bear_history", "")

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

        prompt = f"""你是一位专注于 A 股市场的**看跌研究员（空方）**。你的任务是提出一个有理有据的看空论点，强调股票的风险、挑战和中国市场特有的负面信号。你需要利用提供的研究报告和数据，突出潜在下行风险，有效反驳多方观点。

{quick_scan_summary}

## A 股看空分析框架（优先考虑中国市场特有的风险因素）

- **政策逆风**：突发监管整顿（如行业整改、反垄断）、证监会窗口指导、全行业交易限制、政治风险信号
- **解禁与内部抛售**：即将到来的大额解禁日、控股股东处于减持预披露期、股权质押平仓风险
- **游资撤退**：涨停后量价背离（放量滞涨）、连板断裂、板块轮动离开该题材
- **估值泡沫**：PE 远高于 A 股成长股 30 倍锚定且 3 年内 EPS 无法消化、PEG > 2 表明成长性透支、散户驱动的投机溢价
- **T+1 陷阱**：大涨后当日买入次日才能卖出 — 如果情绪隔夜反转或低开，损失被锁定
- **北向撤离**：陆股通净流出表明外资机构正在减仓
- **散户接盘风险**：
  - 主力资金持续流出 + 小单资金净流入 = 机构在出货，散户在接盘
  - 户均持股数持续下降 = 筹码正在分散（主力派发筹码给散户）
  - 龙虎榜散户席位（东财拉萨营业部）频繁上榜且净买入 = 散户在追高
  - 融资余额快速上升 + 股价滞涨 = 杠杆资金拥挤，随时可能回调
- **散户情绪顶背离**：
  - 股吧情绪极度乐观 + 股价不再创新高 = 情绪见顶信号
  - 换手率持续>20% + 量价背离 = 散户投机过热，见顶风险高
  - 新增散户开户暴增（滞后信号）= 市场阶段性顶部

## 通用看空逻辑

- **风险与挑战**：市场饱和、财务不稳定、宏观经济威胁
- **竞争劣势**：市场地位下滑、创新能力下降、竞争对手威胁
- **负面信号**：财务数据、市场趋势、不利消息中的证据
- **反驳多方**：用具体数据揭露多方过于乐观的假设
- **对话互动**：直接回应看涨研究员的观点，有针对性地反驳

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

⚠️ **看空风险评分**：XX/100（分数越高，风险越大，越坚定看空）

### 一、核心看空逻辑（3-5 条）
每条观点需有具体数据支撑，标注数据来源（如「技术面」「基本面」「政策面」等）

⚠️ **风险扫描辩论要求**：如果分析师报告中提到了通达信风险扫描的风险项（如高应收款、高库存、股东退出等），必须将这些风险项作为核心看空逻辑之一：
- 逐一分析每个风险项的严重性和潜在影响
- 量化风险可能带来的损失（如应收账款坏账比例、库存跌价金额等）
- 说明这些风险尚未被市场充分定价的理由

### 二、关键风险催化剂
- 短期风险（1-4 周）：
- 中期风险（1-3 个月）：
- 长期风险（3 个月以上）：

### 三、对看涨观点的反驳
针对看涨方的核心论点逐一回应，用数据说话

### 四、可能的多头反击（诚实承认）
承认 2-3 个可能的多头反击点，但说明为何这些点不足以改变整体判断

### 五、投资建议
- 建议评级：卖出/减持/持有
- 下行目标价位：XX 元
- 建议操作：减仓/观望/规避

（以上分析仅供研究参考，不构成投资建议）{get_language_instruction()}
"""

        response = llm.invoke(prompt)

        argument = f"看跌研究员：{response.content}"

        new_investment_debate_state = {
            "history": history + "\n" + argument,
            "bear_history": bear_history + "\n" + argument,
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": argument,
            "count": investment_debate_state["count"] + 1,
        }

        return {"investment_debate_state": new_investment_debate_state}

    return bear_node
