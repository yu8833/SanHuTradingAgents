"""分析师目录 —— 唯一的分析师/报告字段/工具绑定注册源。

目的：新增一个分析师时不再散改 5 处（analysis_service 名单、simple_analysis_service
两处 report_fields、trading_graph 工具节点、state、前端）。改为只在本目录加一条
AnalystSpec + 在 state 补一个键，其余消费方全部从这里派生。

消费方：
- app/services/analysis_service.py          → ANALYST_KEYS / ANALYST_KEYS_SET
- app/services/simple_analysis_service.py   → REPORT_FIELDS（替换两处硬编码）
- tradingagents/graph/trading_graph.py      → ANALYSTS + load_tool
- 前端 report-schema（可选）                 → 序列化字段
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalystSpec:
    """一个分析师的注册信息。"""

    key: str                      # "market" —— state 键后缀 / 分析师 id
    report_field: str             # "market_report"
    zh_name: str                  # "市场分析"
    report_zh: str                # "市场报告"（前端页签用）
    tools: tuple[str, ...]        # 绑定的工具函数名
    order: int                    # 顺序
    enabled: bool = True


# ── 唯一注册源：新增分析师 = 在此加一条 ──
ANALYSTS: list[AnalystSpec] = [
    AnalystSpec("market", "market_report", "市场分析", "市场报告",
                ("get_stock_data", "get_indicators"), 1),
    AnalystSpec("social", "sentiment_report", "情绪分析", "情绪报告",
                ("get_news", "get_fund_flow", "get_margin_trading",
                 "get_shareholder_concentration", "get_dragon_tiger_board"), 2),
    AnalystSpec("news", "news_report", "新闻分析", "新闻报告",
                ("get_news", "get_global_news", "get_insider_transactions",
                 "get_risk_scan"), 3),
    AnalystSpec("fundamentals", "fundamentals_report", "基本面分析", "基本面报告",
                ("get_fundamentals", "get_balance_sheet", "get_cashflow",
                 "get_income_statement", "get_profit_forecast",
                 "get_industry_comparison", "get_risk_scan"), 4),
    AnalystSpec("policy", "policy_report", "政策分析", "政策报告",
                ("get_news", "get_global_news"), 5),
    AnalystSpec("hot_money", "hot_money_report", "游资追踪", "资金报告",
                ("get_stock_data", "get_news", "get_insider_transactions",
                 "get_hot_stocks", "get_northbound_flow", "get_concept_blocks",
                 "get_fund_flow", "get_dragon_tiger_board",
                 "get_industry_comparison", "get_margin_trading",
                 "get_shareholder_concentration", "get_risk_scan"), 6),
    AnalystSpec("lockup", "lockup_report", "解禁追踪", "解禁报告",
                ("get_insider_transactions", "get_news", "get_fundamentals",
                 "get_lockup_expiry", "get_risk_scan"), 7),
]


# 非分析师决策字段（round 队长/交易员/风控/经理产出）
DECISION_FIELDS: tuple[str, ...] = (
    "investment_plan",
    "trader_investment_plan",
    "risk_control_decision",
    "final_trade_decision",
)

# ── 派生常量：6 处消费方全部从这里取 ──
ANALYST_KEYS = [a.key for a in ANALYSTS if a.enabled]
ANALYST_KEYS_SET = set(ANALYST_KEYS)
REPORT_FIELDS = [a.report_field for a in ANALYSTS if a.enabled] + list(DECISION_FIELDS)
TOOLS_BY_ANALYST = {a.key: list(a.tools) for a in ANALYSTS}
ZH_BY_REPORT_FIELD = {a.report_field: a.report_zh for a in ANALYSTS}


# ── 工具名 → 实际函数的惰性定位器（延迟 import，避免启动期循环依赖） ──
_TOOL_LIB = None


def _ensure_tool_map() -> dict[str, object]:
    """延迟 import 所有工具模块，构建 工具名→函数 映射。"""
    global _TOOL_LIB
    if _TOOL_LIB is not None:
        return _TOOL_LIB
    from tradingagents.agents.utils.core_stock_tools import (  # noqa: F401
        get_stock_data,
    )
    from tradingagents.agents.utils.fundamental_data_tools import (  # noqa: F401
        get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement,
    )
    from tradingagents.agents.utils.technical_indicators_tools import (  # noqa: F401
        get_indicators,
    )
    from tradingagents.agents.utils.signal_data_tools import (  # noqa: F401
        get_profit_forecast, get_hot_stocks, get_northbound_flow,
        get_concept_blocks, get_fund_flow, get_dragon_tiger_board,
        get_lockup_expiry, get_industry_comparison, get_margin_trading,
        get_shareholder_concentration, get_risk_scan,
    )
    from tradingagents.agents.utils.news_data_tools import (  # noqa: F401
        get_news, get_global_news, get_insider_transactions,
    )
    _TOOL_LIB = {name: obj for name, obj in list(globals().items())
                 if callable(obj) and not name.startswith("_")}
    return _TOOL_LIB


def load_tool(name: str):
    """按工具名取实际函数；未找到返回 None（调用方自行跳过）。"""
    return _ensure_tool_map().get(name)


def analysts_json() -> list[dict]:
    """序列化分析师元数据（供前端 report-schema 使用）。"""
    return [
        {"key": a.key, "report_field": a.report_field,
         "zh_name": a.report_zh, "order": a.order}
        for a in ANALYSTS if a.enabled
    ]