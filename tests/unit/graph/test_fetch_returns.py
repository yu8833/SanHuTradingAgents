"""_fetch_returns 单测：A 股走 akshare 基准、非 A 股保留 yfinance、数据不足返回 None。

运行：pytest -o addopts="" -m "not integration" tests/unit/graph/test_fetch_returns.py
"""

from __future__ import annotations

from unittest import mock

import pandas as pd

from tradingagents.graph.trading_graph import TradingAgentsGraph


def _graph_instance() -> TradingAgentsGraph:
    """用 __new__ 避开 __init__ 的 LLM/配置初始化，仅测试方法本身。"""
    return TradingAgentsGraph.__new__(TradingAgentsGraph)


A_STOCK_ROWS = [("2024-01-02", 100.0), ("2024-01-03", 110.0), ("2024-01-04", 99.0)]
A_BENCH_ROWS = [("2024-01-02", 3000.0), ("2024-01-03", 3100.0), ("2024-01-04", 3050.0)]


def test_a_share_uses_akshare_series_and_hs300_benchmark():
    g = _graph_instance()
    with mock.patch("tradingagents.graph.trading_graph.get_stock_daily_series", return_value=A_STOCK_ROWS) as m_stock, \
         mock.patch("tradingagents.graph.trading_graph.get_index_daily_series", return_value=A_BENCH_ROWS) as m_bench, \
         mock.patch("tradingagents.graph.trading_graph.yf.Ticker") as m_yf:
        raw, alpha, days = g._fetch_returns("600000.SH", "2024-01-02", holding_days=5)

    m_stock.assert_called_once()
    m_bench.assert_called_once()
    m_yf.assert_not_called()  # A 股彻底脱离 yfinance

    assert days == 2  # min(5, 2, 2)
    # raw = (99 - 100)/100 = -0.01；bench = (3050 - 3000)/3000 = 0.0166667
    assert abs(raw - (-0.01)) < 1e-9
    bench_ret = A_BENCH_ROWS[2][1] / A_BENCH_ROWS[0][1] - 1
    assert abs(alpha - (raw - bench_ret)) < 1e-9


def test_us_share_still_uses_yfinance_with_mapped_benchmark():
    g = _graph_instance()
    idx = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    stock_df = pd.DataFrame({"Close": [100.0, 110.0, 99.0]}, index=idx)
    bench_df = pd.DataFrame({"Close": [2000.0, 2100.0, 2050.0]}, index=idx)

    class _FakeTicker:
        def __init__(self, df):
            self._df = df

        def history(self, **kwargs):
            return self._df

    with mock.patch("tradingagents.graph.trading_graph.yf.Ticker") as m_yf:
        def _side_effect(sym):
            assert sym in ("AAPL.US", "^GSPC")
            return _FakeTicker(stock_df if sym == "AAPL.US" else bench_df)

        m_yf.side_effect = _side_effect
        raw, alpha, days = g._fetch_returns("AAPL.US", "2024-01-02", holding_days=5)

    assert m_yf.call_count == 2
    assert days == 2
    assert abs(raw - (-0.01)) < 1e-9
    bench_ret = 2050.0 / 2000.0 - 1
    assert abs(alpha - (raw - bench_ret)) < 1e-9


def test_insufficient_data_returns_none():
    g = _graph_instance()
    with mock.patch("tradingagents.graph.trading_graph.get_stock_daily_series", return_value=[("2024-01-02", 100.0)]), \
         mock.patch("tradingagents.graph.trading_graph.get_index_daily_series", return_value=A_BENCH_ROWS):
        assert g._fetch_returns("600000.SH", "2024-01-02", holding_days=5) == (None, None, None)


def test_data_source_exception_returns_none():
    g = _graph_instance()
    with mock.patch("tradingagents.graph.trading_graph.get_stock_daily_series", side_effect=RuntimeError("boom")):
        assert g._fetch_returns("600000.SH", "2024-01-02", holding_days=5) == (None, None, None)