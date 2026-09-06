"""MongoDB 集合名唯一登记表。

集中登记全部集合名，替代散落在各 service 里的硬编码字符串 `db["xxx"]`。
集合改名 / 迁移 / 加索引时只需修改本文件，是全项目集合名的单一事实来源。
"""
from __future__ import annotations

from app.core.database import get_mongo_db, get_mongo_db_sync


class Collections:
    """全部 MongoDB 集合名的集中登记。"""

    # 用户/权限
    users = "users"
    operations_logs = "operation_logs"
    notifications = "notifications"
    user_favorites = "user_favorites"
    user_tags = "user_tags"

    # 行情/数据
    stock_basic = "stock_basic"
    stock_basic_info = "stock_basic_info"
    stock_daily_quotes = "stock_daily_quotes"
    stock_daily_basic = "stock_daily_basic"
    stock_historical_data = "stock_historical_data"
    stock_news = "stock_news"
    stock_financial_data = "stock_financial_data"
    stock_dividend = "stock_dividend"
    market_quotes = "market_quotes"
    stock_screening_view = "stock_screening_view"

    # 分析/任务
    analysis_reports = "analysis_reports"
    analysis_tasks = "analysis_tasks"
    analysis_batches = "analysis_batches"
    token_usage = "token_usage"

    # 对话（Agent 问股）
    chat_sessions = "chat_sessions"

    # 零售/数据指标
    dg_prosperity = "dg_prosperity"
    data_metrics = "data_metrics"
    sync_status = "sync_status"
    success = "success"

    # 监控/信号/指令
    monitor_alerts = "monitor_alerts"
    monitor_tbs_orders = "monitor_tbs_orders"
    signal_tracking = "signal_tracking"
    stock_alerts = "stock_alerts"

    # 纸面交易/组合
    paper_accounts = "paper_accounts"
    paper_positions = "paper_positions"
    paper_trades = "paper_trades"
    paper_orders = "paper_orders"
    paper_market_rules = "paper_market_rules"
    trade_reviews = "trade_reviews"
    daily_plans = "daily_plans"
    research_notes = "research_notes"

    # 宏观/可视化
    macro_daily_snapshots = "macro_daily_snapshots"
    etf_radar_snapshot = "etf_radar_snapshot"
    weekly_reviews = "weekly_reviews"

    # 配置/任务
    system_configs = "system_configs"
    scheduler_executions = "scheduler_executions"
    strategy_backtest_results = "strategy_backtest_results"


def col(name: str):
    """按集合名取异步 MongoDB 集合。"""
    return get_mongo_db()[name]


def col_sync(name: str):
    """按集合名取同步 MongoDB 集合。"""
    return get_mongo_db_sync()[name]