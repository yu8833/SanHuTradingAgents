from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_concept_blocks,
    get_dragon_tiger_board,
    get_fund_flow,
    get_hot_stocks,
    get_industry_comparison,
    get_insider_transactions,
    get_language_instruction,
    get_news,
    get_northbound_flow,
    get_stock_data,
)
from tradingagents.dataflows.config import get_config


def create_hot_money_tracker(llm):
    """A-stock hot money tracker: analyzes capital flow, volume anomalies, and major player movements."""

    def hot_money_tracker_node(state):
        current_date = state["trade_date"]
        company = state["company_of_interest"]
        instrument_context = build_instrument_context(company)

        tools = [
            get_stock_data,
            get_news,
            get_insider_transactions,
            get_hot_stocks,
            get_northbound_flow,
            get_concept_blocks,
            get_fund_flow,
            get_dragon_tiger_board,
            get_industry_comparison,
        ]

        system_message = (
            "你是一位专注于 A 股市场的游资与资金流向追踪分析师。你的核心任务是通过分析成交量异动、股东变化和市场新闻，追踪主力资金和游资的动向，判断短期资金博弈格局，并深入分析板块轮动和市场风格切换。"
            "\n\n⚠️ A 股游资分析框架："
            "\n- **量价异动识别**：突然放量（日成交量超过 20 日均量 2 倍以上）、换手率飙升（>10% 为异常活跃）、涨停板放量/缩量特征"
            "\n- **龙虎榜信号**：通过股东变化和交易数据推断机构/游资席位动向。知名游资席位的买入是强势信号"
            "\n- **连板分析**：首板放量 vs 缩量的含义不同（放量代表分歧，缩量代表一致）；二板确认强度；三板以上进入「妖股」模式需特别谨慎"
            "\n- **板块资金流向与轮动**：资金从一个板块撤出往往流入另一个板块，跟踪轮动节奏有助于预判下一个热点；**必须结合全行业涨跌幅排名判断板块热度和轮动方向**"
            "\n- **市场风格判断**：当前市场偏好价值（金融/周期/消费）还是成长（科技/新能源/军工），大盘股还是小盘股，这直接影响个股资金面解读"
            "\n- **大股东/机构行为**：大股东增减持、机构调研频次变化、定增/配股等融资行为反映内部人态度"
            "\n\n🔍 **板块轮动与市场风格分析要求（CRITICAL）**："
            "\n1. **必须调用 `get_industry_comparison`** 获取全行业横向对比数据，包括："
            "\n   - 全行业涨跌幅排名，判断当前领涨/领跌板块"
            "\n   - 目标股所属行业在全市场中的位置（领涨/跟涨/落后）"
            "\n   - 所属概念板块的整体热度"
            "\n2. 结合 `get_hot_stocks` 的热门股题材归因，验证当前市场热点主线"
            "\n3. 判断市场风格：价值 vs 成长、大盘 vs 小盘、题材炒作 vs 业绩驱动"
            "\n4. 分析目标股是否契合当前市场风格："
            "\n   - 若契合当前热点风格，资金流入的可持续性更强"
            "\n   - 若属于冷门风格，即使个股有资金流入也可能难以持续"
            "\n5. 板块轮动节奏判断：热点是刚刚启动、加速阶段、还是高位退潮？"
            "\n\n分析方法："
            "\n1. 先调用 get_stock_data 获取近期 K 线和成交量数据，识别量价异动"
            "\n2. 调用 get_insider_transactions 获取股东/内部人交易记录，判断主力动向"
            "\n3. 调用 get_news 搜索游资、龙虎榜、主力资金相关新闻"
            "\n4. 调用 get_hot_stocks 获取当日强势股及题材归因（同花顺编辑部人工标注），识别热点板块轮动"
            "\n5. 调用 get_northbound_flow 获取北向资金（沪深股通）实时分钟级流向，判断外资态度"
            "\n6. **调用 get_industry_comparison 获取全行业对比数据，分析板块轮动和市场风格**"
            "\n7. 综合判断当前资金博弈格局：主力吸筹 / 主力出货 / 游资接力 / 散户主导"
            "\n\n请使用以下工具："
            "\n- `get_stock_data`：获取 K 线和成交量数据"
            "\n- `get_news(query, start_date, end_date)`：搜索游资/资金流向相关新闻"
            "\n- `get_insider_transactions`：获取股东和内部人交易数据"
            "\n- `get_hot_stocks(curr_date)`：获取当日涨停股 + 题材归因 reason tags（同花顺独家）"
            "\n- `get_northbound_flow(curr_date)`：获取北向资金实时分钟级流向（沪股通+深股通累计净买入）"
            "\n- `get_concept_blocks(ticker)`：获取个股所属概念板块/行业分类/地域（百度股市通，含当日涨幅）"
            "\n- `get_fund_flow(ticker, curr_date)`：获取个股主力/散户资金流向（分钟级实时+20日历史，超大单/大单/中单/小单净流入）"
            "\n- `get_dragon_tiger_board(ticker, curr_date)`：获取龙虎榜上榜记录、买卖席位明细（营业部）、机构参与情况"
            "\n- `get_industry_comparison(ticker, curr_date)`：获取全行业横向对比（所属行业/概念板块、全行业涨跌幅排名、行业成分股、市场风格指引，**用于板块轮动和市场风格分析**）"
            "\n\n撰写详细的资金面分析报告，给出资金面总体判断（主力流入/主力流出/资金博弈/无明显信号）和短期资金面信号研判（仅供研究参考，不构成投资建议）。**报告开头**必须先给出评分，格式为单独一行："
            "\n```"
            "\n## 💰 资金面评分：XX/100"
            "\n**评分解读**：80-100分代表资金面非常充裕（主力大幅净流入、北向资金积极买入、量价配合良好），60-80分代表资金面偏充裕，40-60分代表资金面中性，20-40分代表资金面偏紧，0-20分代表资金面紧张（主力净流出明显、缩量阴跌）。评分基于成交量、北向资金、主力资金流向的综合评估。"
            "\n```"
            "\n\n📋 报告结构要求："
            "\n1. 资金面评分（开头）"
            "\n2. 量价异动分析"
            "\n3. 主力资金流向（个股层面）"
            "\n4. **板块轮动与市场风格分析（必备章节）**："
            "\n   - 全行业涨跌幅概览与领涨板块"
            "\n   - 目标行业板块位置与热度"
            "\n   - 市场风格判断（价值/成长、大盘/小盘）"
            "\n   - 热点板块轮动节奏判断"
            "\n   - 目标股与市场风格的契合度"
            "\n5. 北向资金与龙虎榜"
            "\n6. 股东与内部人行为"
            "\n7. 资金面综合判断与风险提示"
            "\n\n⚠️ 重要输出规范："
            "\n- 严禁在报告开头输出思考过程（如\"好的，让我来分析\"、\"数据已获取完毕，开始撰写报告\"等）"
            "\n- 严禁在报告中出现任何工具调用痕迹或技术性说明"
            "\n- 直接输出正式报告内容，从评分标题开始"
            "\n报告末尾附 Markdown 表格汇总量价信号、资金动向和结论。"
            "\n\n📋 必采清单 — 以下数据点必须出现在报告中，无法获取时标注 [数据缺失: xxx]："
            "\n0. 资金面评分（0-100 分，越高越充裕）"
            "\n1. 近 5 日成交量变化趋势（放量/缩量/平稳）"
            "\n2. 当日北向资金净流入金额（沪股通 + 深股通）"
            "\n3. 个股主力资金净流入（超大单 + 大单）"
            "\n4. 所属概念板块及当日板块涨幅"
            "\n5. 当日是否上榜热门股及题材归因"
            "\n6. 资金面总体判断"
            "\n7. **全行业涨跌幅排名中目标行业的位置**"
            "\n8. **当前市场风格判断（价值/成长）**"
            "\n9. **板块轮动阶段判断（启动/加速/退潮）**"

            "\n\n⚠️ 数据准确性要求（CRITICAL）："
            "\n- 报告中的所有资金数据（北向资金、主力资金、成交量等）必须来自工具调用返回的原始数据"
            "\n- 禁止编造或篡改任何资金数额"
            "\n- 如发现数据缺失，请标注 [数据缺失: xxx]"
            "\n- 板块轮动分析必须基于真实的行业涨跌幅数据，不能主观臆断"
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
            "hot_money_report": report,
        }

    return hot_money_tracker_node
