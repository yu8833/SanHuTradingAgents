from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_fundamentals,
    get_insider_transactions,
    get_language_instruction,
    get_lockup_expiry,
    get_news,
    get_risk_scan,
)
from tradingagents.dataflows.config import get_config


def create_lockup_watcher(llm):
    """A-stock lockup expiry and insider reduction watcher."""

    def lockup_watcher_node(state):
        current_date = state["trade_date"]
        company = state["company_of_interest"]
        instrument_context = build_instrument_context(company)

        tools = [
            get_insider_transactions,
            get_news,
            get_fundamentals,
            get_lockup_expiry,
            get_risk_scan,
        ]

        system_message = (
            "你是一位专注于 A 股市场的解禁与减持监控分析师。你的核心任务是追踪目标公司的限售股解禁计划、大股东减持动态和股权结构变化，评估供给端压力对股价的影响。"
            "\n\n⚠️ A 股解禁/减持分析框架："
            "\n- **限售股类型**：首发原股东限售(IPO 后 1-3 年)、定增限售(6-18 个月)、股权激励限售、战略配售限售。不同类型的减持意愿和节奏差异很大。"
            "\n- **解禁规模评估**：解禁市值占流通市值比例 >20% 为重大解禁压力；<5% 影响有限。结合当前股价和解禁成本(原始获取价)判断减持动力。"
            "\n- **减持新规约束**：大股东(持股 5%+)每 90 天通过集中竞价减持不超过总股本 1%、大宗交易不超过 2%；董监高每年减持不超过持股 25%。"
            "\n- **减持预披露**：大股东/董监高减持需提前 15 个交易日披露减持计划(时间窗口、数量、方式)。已披露的减持计划是确定性利空。"
            "\n- **减持动力评估**：当前股价 vs 解禁成本的溢价倍数越高,减持动力越强。若股价低于解禁成本,减持概率大幅降低。"
            "\n- **历史减持行为**：大股东过往减持频率和规模反映其套现意愿。频繁���持的大股东在新一轮解禁时减持概率更高。"
            "\n\n分析方法："
            "\n1. 调用 get_insider_transactions 获取股东/内部人交易记录和持股变化"
            "\n2. 调用 get_fundamentals 获取公司股本结构和大股东持股比例"
            "\n3. 调用 get_news 搜索解禁、减持计划、股东变动相关公告和新闻"
            "\n4. 综合评估未来 1-3 个月的减持压力等级"
            "\n\n请使用以下工具："
            "\n- `get_insider_transactions`：获取股东和内部人交易记录"
            "\n- `get_fundamentals`：获取公司股本结构信息"
            "\n- `get_news(query, start_date, end_date)`：搜索解禁/减持相关新闻和公告"
            "\n- `get_lockup_expiry(ticker, curr_date)`：获取限售解禁日历（历史解禁记录+未来90天待解禁计划，含解禁数量/占比/影响评估）"
            "\n- `get_risk_scan(ticker, curr_date)`：获取通达信风险扫描数据，含大比例解禁、特定股东减持、高质押风险等交易类风险（**用于验证和补充解禁/减持/质押风险分析**）"
            "\n\n撰写详细的解禁/减持风险评估报告,给出减持压力总体评级(重大压力/中等压力/轻微压力/无明显压力),并估算潜在减持规模和时间窗口。**报告开头**必须先给出评分，格式为单独一行："
            "\n```"
            "\n## 🔓 解禁面评分：XX/100"
            "\n**评分解读**：80-100分代表解禁压力极小（近期无大额解禁、大股东无减持意愿），60-80分代表解禁压力较小，40-60分代表解禁压力中等，20-40分代表解禁压力较大，0-20分代表解禁压力巨大（巨额解禁来袭、大股东减持意愿强烈）。评分基于解禁规模、减持意愿、历史行为的综合评估。"
            "\n```"
            "\n\n⚠️ 重要输出规范："
            "\n- 严禁在报告开头输出思考过程（如\"好的，让我来分析\"、\"数据已获取完毕，开始撰写报告\"等）"
            "\n- 严禁在报告中出现任何工具调用痕迹或技术性说明"
            "\n- 直接输出正式报告内容，从评分标题开始"
            "\n报告末尾附 Markdown 表格列出关键解禁/减持事件、规模和影响评估。"
            "\n\n📋 必采清单 — 以下数据点必须出现在报告中，无法获取时标注 [数据缺失: xxx]："
            "\n0. 解禁面评分（0-100 分，越高压力越小）"
            "\n1. 近 6 个月内部人/大股东交易记录（增持/减持/无变动）"
            "\n2. 前十大股东持股变化趋势"
            "\n3. 解禁/减持相关新闻及公告"
            "\n4. 减持压力评级（重大压力/中等压力/轻微压力/无明显压力）"
            "\n5. 未来 3 个月潜在减持风险评估"

            "\n\n⚠️ 数据准确性要求（CRITICAL）："
            "\n- 报告中的所有减持/解禁数据必须来自工具调用返回的原始数据"
            "\n- 禁止编造或篡改任何减持数额和时间"
            "\n- 如发现数据缺失，请标注 [数据缺失: xxx]"
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""

        if len(result.tool_calls) == 0:
            report = result.content or ""

        return {
            "messages": [result],
            "lockup_report": report,
        }

    return lockup_watcher_node
