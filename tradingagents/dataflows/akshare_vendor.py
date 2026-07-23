"""akshare 数据源 — A 股备用数据源

基于 akshare 库实现的 A 股数据接口，作为 a_stock 主数据源的 fallback 备用方案。

当 a_stock 主数据源失败时自动降级到本模块。

所有方法签名与 a_stock.py 保持一致，返回值均为格式化字符串。
"""
from __future__ import annotations

from typing import Annotated
from datetime import datetime, timedelta
import logging

import pandas as pd

logger = logging.getLogger(__name__)

_AKSHARE_AVAILABLE = None


def _ensure_akshare():
    """延迟导入 akshare，失败则标记为不可用。"""
    global _AKSHARE_AVAILABLE
    if _AKSHARE_AVAILABLE is None:
        try:
            import akshare as ak
            _AKSHARE_AVAILABLE = ak
        except ImportError as e:
            logger.warning(f"akshare 未安装: {e}")
            _AKSHARE_AVAILABLE = False
    if _AKSHARE_AVAILABLE is False:
        raise RuntimeError("akshare 未安装，请 pip install akshare")
    return _AKSHARE_AVAILABLE


def _normalize_code(symbol: str) -> str:
    """统一股票代码格式，返回纯 6 位数字。"""
    s = symbol.strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if s.startswith(("SH", "SZ", "BJ")):
        s = s[2:]
    return s


def _df_to_str(df: pd.DataFrame, max_rows: int = 50) -> str:
    """DataFrame 转字符串表示。"""
    if df is None or df.empty:
        return "（无数据）"
    if len(df) > max_rows:
        df = df.head(max_rows)
    return df.to_string(index=False)


# ===========================================================================
# 1. Core Stock Data
# ===========================================================================


def get_stock_data(
    symbol: Annotated[str, "A-stock code (e.g. 688017, SH688017)"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
) -> str:
    """Get OHLCV stock price data via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(symbol)
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start,
        end_date=end,
        adjust="qfq",
    )
    if df is None or df.empty:
        raise ValueError(f"akshare 无 K线数据: {code}")
    rename_map = {
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume",
    }
    df = df.rename(columns=rename_map)
    cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[cols]
    return f"=== {code} 日线行情 (akshare 前复权)\n" + _df_to_str(df, 80)


def get_indicators(
    symbol: Annotated[str, "A-stock code"],
    indicator: Annotated[str, "technical indicator (e.g. rsi, macd, close_50_sma)"],
    curr_date: Annotated[str, "Current trading date, YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"],
) -> str:
    """Get technical indicators using stockstats on akshare OHLCV data."""
    from stockstats import StockDataFrame

    ak = _ensure_akshare()
    code = _normalize_code(symbol)

    start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=look_back_days + 50)
    start = start_dt.strftime("%Y%m%d")
    end = curr_date.replace("-", "")

    df = ak.stock_zh_a_hist(
        symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq"
    )
    if df is None or df.empty:
        raise ValueError(f"akshare 无 K线数据: {code}")

    rename_map = {
        "日期": "date", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
    }
    df = df.rename(columns=rename_map)
    df = df[["date", "open", "high", "low", "close", "volume"]]

    stock = StockDataFrame.retype(df)

    indicator = indicator.lower()
    result_rows = []

    if indicator == "rsi":
        result = stock[["rsi_6", "rsi_12", "rsi_24"]].tail(look_back_days)
        result_rows.append(f"=== RSI 指标 ({code})\n" + _df_to_str(result, look_back_days))
    elif indicator == "macd":
        result = stock[["macd", "macds", "macdh"]].tail(look_back_days)
        result_rows.append(f"=== MACD 指标 ({code})\n" + _df_to_str(result, look_back_days))
    elif "sma" in indicator:
        periods = [int(p) for p in indicator.split("_") if p.isdigit()]
        if not periods:
            periods = [5, 10, 20, 50]
        cols = [f"close_{p}_sma" for p in periods]
        result = stock[cols].tail(look_back_days)
        result_rows.append(f"=== 均线指标 ({code})\n" + _df_to_str(result, look_back_days))
    elif indicator == "boll":
        result = stock[["boll", "boll_ub", "boll_lb"]].tail(look_back_days)
        result_rows.append(f"=== 布林带 ({code})\n" + _df_to_str(result, look_back_days))
    elif indicator == "kdj":
        result = stock[["kdjk", "kdjd", "kdjj"]].tail(look_back_days)
        result_rows.append(f"=== KDJ 指标 ({code})\n" + _df_to_str(result, look_back_days))
    else:
        result = stock.tail(look_back_days)
        result_rows.append(f"=== 行情数据 ({code})\n" + _df_to_str(result, look_back_days))

    return "\n\n".join(result_rows)


# ===========================================================================
# 2. Fundamentals
# ===========================================================================


def get_fundamentals(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date"] = None,
) -> str:
    """Get company fundamentals via akshare (东方财富 + 新浪)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    lines = []

    try:
        info = ak.stock_individual_info_em(symbol=code)
        if info is not None and not info.empty:
            lines.append("=== 公司基本信息 (东方财富)")
            for _, row in info.iterrows():
                lines.append(f"{row.iloc[0]}: {row.iloc[1]}")
    except Exception as e:
        lines.append(f"个股信息获取失败: {e}")

    try:
        df = ak.stock_a_ttm_lyr()
        if df is not None and not df.empty:
            target = df[df["code"].astype(str).str.zfill(6).str.endswith(code[-6:])]
            if not target.empty:
                lines.append("\n=== 估值指标 (TTM/LYR)")
                lines.append(_df_to_str(target.head(1), 1))
    except Exception:
        pass

    return "\n".join(lines) if lines else f"akshare 基本面数据不可用: {code}"


def get_balance_sheet(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get balance sheet via akshare (新浪财务报告)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_financial_report_sina(stock=code, symbol="资产负债表")
    if df is None or df.empty:
        raise ValueError(f"akshare 无资产负债表: {code}")
    return f"=== {code} 资产负债表 (akshare)\n" + _df_to_str(df, 60)


def get_cashflow(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get cash flow statement via akshare (新浪财务报告)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_financial_report_sina(stock=code, symbol="现金流量表")
    if df is None or df.empty:
        raise ValueError(f"akshare 无现金流量表: {code}")
    return f"=== {code} 现金流量表 (akshare)\n" + _df_to_str(df, 60)


def get_income_statement(
    ticker: Annotated[str, "A-stock code"],
    freq: Annotated[str, "frequency: 'annual' or 'quarterly'"] = "quarterly",
    curr_date: Annotated[str, "current date in YYYY-MM-DD format"] = None,
) -> str:
    """Get income statement via akshare (新浪财务报告)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_financial_report_sina(stock=code, symbol="利润表")
    if df is None or df.empty:
        raise ValueError(f"akshare 无利润表: {code}")
    return f"=== {code} 利润表 (akshare)\n" + _df_to_str(df, 60)


# ===========================================================================
# 3. News
# ===========================================================================


def get_news(
    ticker: Annotated[str, "A-stock code"],
    start_date: Annotated[str, "Start date yyyy-mm-dd"],
    end_date: Annotated[str, "End date yyyy-mm-dd"],
) -> str:
    """Get stock-specific news via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_news_em(symbol=code)
    if df is None or df.empty:
        raise ValueError(f"akshare 无新闻数据: {code}")

    if "发布时间" in df.columns:
        df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        df = df[(df["发布时间"] >= start_dt) & (df["发布时间"] <= end_dt)]

    return f"=== {code} 新闻 (akshare 东方财富)\n共 {len(df)} 条\n" + _df_to_str(df, 30)


def get_global_news(
    curr_date: Annotated[str, "Current date"],
    look_back_days: Annotated[int, "Days to look back"] = 3,
    limit: Annotated[int, "Max number of news items"] = 20,
) -> str:
    """Get global/market news via akshare (财联社电报)."""
    ak = _ensure_akshare()
    try:
        df = ak.stock_telegraph_cls()
        if df is not None and not df.empty:
            if "发布时间" in df.columns:
                df["发布时间"] = pd.to_datetime(df["发布时间"], errors="coerce")
                cutoff = pd.to_datetime(curr_date) - timedelta(days=look_back_days)
                df = df[df["发布时间"] >= cutoff]
            df = df.head(limit)
            return f"=== 全球财经新闻 (akshare 财联社)\n共 {len(df)} 条\n" + _df_to_str(df, limit)
    except Exception as e:
        raise ValueError(f"akshare 全球新闻获取失败: {e}")
    raise ValueError("akshare 无全球新闻数据")


def get_insider_transactions(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get insider / shareholder activity via akshare (股东增减持+主要股东+龙虎榜)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    lines = []

    # 1. 主要股东持股
    try:
        df = ak.stock_main_stock_holder(stock=code)
        if df is not None and not df.empty:
            # 只取前10大股东
            top10 = df.head(10)
            lines.append(f"# 主要股东持股 (akshare 东方财富)")
            lines.append(f"# 股票代码: {code}")
            lines.append(f"# 数据来源: 东方财富网")
            lines.append("")
            lines.append("## 前10大股东")
            lines.append(_df_to_str(top10, 10))
    except Exception:
        pass

    # 2. 股东增减持变动
    try:
        df = ak.stock_shareholder_change_ths(symbol=code)
        if df is not None and not df.empty:
            # 只取最近的10条
            recent = df.head(10)
            lines.append("")
            lines.append("## 股东增减持变动（近10条）")
            lines.append(_df_to_str(recent, 10))
    except Exception:
        pass

    # 3. 龙虎榜数据
    try:
        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        df = ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            target = df[df["代码"].astype(str).str.zfill(6) == code]
            if not target.empty:
                lines.append("")
                lines.append("## 龙虎榜上榜记录（近30日）")
                lines.append(_df_to_str(target, 10))
    except Exception:
        pass

    if not lines:
        raise ValueError(f"akshare 内部交易/股东数据不可用: {code}")

    return "\n".join(lines)


# ===========================================================================
# 4. Signal Data (A-stock specific)
# ===========================================================================


def get_profit_forecast(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "current date (unused, for interface compat)"] = None,
) -> str:
    """Get consensus EPS / profit forecast via akshare (东方财富一致预期)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_profit_forecast_em(symbol=code)
    if df is None or df.empty:
        raise ValueError(f"akshare 盈利预测数据: {code}")
    return f"=== {code} 盈利预测 (akshare)\n" + _df_to_str(df, 20)


def get_hot_stocks(
    curr_date: Annotated[str, "Date in YYYY-MM-DD format, empty for today"] = "",
) -> str:
    """Get today's hot / strong stocks with topic attribution via akshare (东方财富人气榜)."""
    ak = _ensure_akshare()
    df = ak.stock_hot_rank_em()
    if df is None or df.empty:
        raise ValueError("akshare 热门股数据")
    df = df.head(50)
    return f"=== 热门股排行 (akshare 东方财富人气榜)\n共 {len(df)} 只\n" + _df_to_str(df, 50)


def get_northbound_flow(
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    include_history: Annotated[bool, "Include historical data"] = False,
) -> str:
    """Get northbound capital flow (沪深股通) via akshare (东方财富)."""
    ak = _ensure_akshare()
    lines = []
    try:
        df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
        if df is not None and not df.empty:
            lines.append(f"=== 北向资金净流入 (akshare)\n" + _df_to_str(df.tail(20), 20))
    except Exception as e:
        raise ValueError(f"akshare 北向资金数据获取失败: {e}")

    try:
        south = ak.stock_hsgt_south_net_flow_in_em(symbol="南向")
        if south is not None and not south.empty:
            lines.append(f"\n=== 南向资金净流入 (akshare)\n" + _df_to_str(south.tail(10), 10))
    except Exception:
        pass

    return "\n".join(lines) if lines else "akshare 北向资金数据不可用"


def get_concept_blocks(
    ticker: Annotated[str, "A-stock code"],
) -> str:
    """Get concept / sector / region blocks via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_board_concept_name_em(symbol=code)
    if df is None or df.empty:
        raise ValueError(f"akshare 概念板块数据: {code}")
    return f"=== {code} 所属概念板块 (akshare)\n" + _df_to_str(df, 30)


def get_fund_flow(
    ticker: Annotated[str, "A-stock code"],
    curr_date: Annotated[str, "Date in YYYY-MM-DD format"],
    include_history: Annotated[bool, "Include historical data"] = True,
) -> str:
    """Get individual stock fund flow via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    df = ak.stock_fund_flow_individual(symbol=code)
    if df is None or df.empty:
        raise ValueError(f"akshare 资金流向数据: {code}")
    return f"=== {code} 资金流向 (akshare)\n" + _df_to_str(df, 30)


def get_dragon_tiger_board(
    ticker: Annotated[str, "A-stock code"],
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
    look_back_days: Annotated[int, "Days to look back"] = 30,
) -> str:
    """Get dragon-tiger board (龙虎榜) data via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    date_str = trade_date.replace("-", "")

    try:
        df = ak.stock_lhb_detail_em(date=date_str)
        if df is not None and not df.empty:
            target = df[df["代码"].astype(str).str.zfill(6) == code]
            if not target.empty:
                return f"=== {code} 龙虎榜 (akshare)\n" + _df_to_str(target, 20)
    except Exception:
        pass

    all_data = []
    for i in range(look_back_days):
        d = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y%m%d")
        try:
            df = ak.stock_lhb_detail_em(date=d)
            if df is not None and not df.empty:
                target = df[df["代码"].astype(str).str.zfill(6) == code]
                if not target.empty:
                    all_data.append(target)
        except Exception:
            continue

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        return f"=== {code} 龙虎榜 (akshare, 近 {look_back_days} 日)\n" + _df_to_str(combined, 20)

    raise ValueError(f"akshare 无龙虎榜数据: {code}")


def get_lockup_expiry(
    ticker: Annotated[str, "A-stock code"],
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
    forward_days: Annotated[int, "Days forward to check"] = 90,
) -> str:
    """Get lockup expiry (限售解禁) schedule via akshare (东方财富)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    try:
        df = ak.stock_restricted_release_queue_em()
        if df is not None and not df.empty:
            target = df[df["代码"].astype(str).str.zfill(6) == code]
            if not target.empty:
                return f"=== {code} 限售解禁 (akshare)\n" + _df_to_str(target, 30)
    except Exception:
        pass

    try:
        detail = ak.stock_restricted_release_detail_em(symbol=code)
        if detail is not None and not detail.empty:
            return f"=== {code} 限售解禁明细 (akshare)\n" + _df_to_str(detail, 30)
    except Exception as e:
        raise ValueError(f"akshare 限售解禁数据获取失败: {e}")

    raise ValueError(f"akshare 无解禁数据: {code}")


def get_industry_comparison(
    ticker: Annotated[str, "A-stock code"],
    trade_date: Annotated[str, "Date in YYYY-MM-DD format"],
    top_n: Annotated[int, "Number of top/bottom industries to show"] = 20,
) -> str:
    """Get industry sector comparison via akshare (东方财富行业板块)."""
    ak = _ensure_akshare()
    code = _normalize_code(ticker)
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            return f"=== 行业板块涨跌幅排行 (akshare)\n共 {len(df)} 个行业\n" + _df_to_str(df, top_n * 2)
    except Exception as e:
        raise ValueError(f"akshare 行业对比数据获取失败: {e}")
    raise ValueError("akshare 无行业对比数据")
