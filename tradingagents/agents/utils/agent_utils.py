from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.agents.utils.signal_data_tools import (
    get_profit_forecast,
    get_hot_stocks,
    get_northbound_flow,
    get_concept_blocks,
    get_fund_flow,
    get_dragon_tiger_board,
    get_lockup_expiry,
    get_industry_comparison,
    get_margin_trading,
    get_shareholder_concentration,
    get_risk_scan,
)


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


def get_quick_analysis_context(state: dict) -> str:
    """
    从 state 中提取速览分析结果并格式化为可读的上下文文本。

    速览分析结果可以注入到各分析师节点中作为背景参考，
    帮助分析师快速了解技术面基线，避免重复分析。

    Args:
        state: TradingAgents 的状态字典

    Returns:
        str: 格式化的速览分析上下文，如果不存在则返回空字符串
    """
    quick_result = state.get("quick_analysis_result", {})

    if not quick_result or not isinstance(quick_result, dict):
        return ""

    # 如果速览结果为空，返回空
    if not quick_result.get("buy_signal"):
        return ""

    try:
        # 提取关键数据
        trend_status = quick_result.get("trend_status", "N/A")
        buy_signal = quick_result.get("buy_signal", "N/A")
        signal_score = quick_result.get("signal_score", "N/A")
        confidence = quick_result.get("confidence", "N/A")
        summary = quick_result.get("summary", "N/A")

        # 关键价位
        support_levels = quick_result.get("support_levels", [])
        resistance_levels = quick_result.get("resistance_levels", [])
        stop_loss = quick_result.get("stop_loss", "N/A")
        target = quick_result.get("target", "N/A")

        # 技术指标
        ma5 = quick_result.get("ma5", "N/A")
        ma10 = quick_result.get("ma10", "N/A")
        ma20 = quick_result.get("ma20", "N/A")
        macd_status = quick_result.get("macd_status", "N/A")
        rsi_status = quick_result.get("rsi_status", "N/A")
        volume_ratio = quick_result.get("volume_ratio", "N/A")

        context = f"""
---

**📊 Quantitative Quick Scan (Technical Baseline Reference):**

| Indicator | Value |
|-----------|-------|
| Trend Status | {trend_status} |
| Trading Signal | **{buy_signal}** |
| Overall Score | {signal_score}/100 |
| Confidence | {confidence}% |

**Technical Indicators:**
- MA5: {ma5} | MA10: {ma10} | MA20: {ma20}
- MACD: {macd_status}
- RSI: {rsi_status}
- Volume Ratio: {volume_ratio}

**Key Price Levels:**
- Support Levels: {', '.join([str(s) for s in support_levels[:3]]) if support_levels else 'N/A'}
- Resistance Levels: {', '.join([str(r) for r in resistance_levels[:3]]) if resistance_levels else 'N/A'}
- Stop Loss: {stop_loss}
- Target Price: {target}

**Quick Summary:** {summary}

**Usage:** Please reference this quick scan as your technical baseline. 
You may confirm, supplement, or challenge these findings based on your specialized analysis.
"""

        return context
    except Exception as e:
        # 如果格式化失败，返回空字符串而不是崩溃
        return ""


def get_quick_scan_summary(state: dict) -> str:
    """
    获取速览分析的一行摘要，用于在节点间传递关键信息。

    Args:
        state: TradingAgents 的状态字典

    Returns:
        str: 速览分析的摘要字符串，如果无数据则返回空字符串
    """
    if not state:
        return ""

    quick_result = state.get("quick_analysis_result")

    if not quick_result or not isinstance(quick_result, dict):
        return ""

    buy_signal = quick_result.get("buy_signal")
    if not buy_signal:
        return ""

    signal = buy_signal or ""
    score = quick_result.get("signal_score", "")
    trend = quick_result.get("trend_status", "")

    return f"[QuickScan: {trend} | {signal} | Score: {score}/100]"



        
