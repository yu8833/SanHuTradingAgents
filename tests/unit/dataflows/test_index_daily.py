"""指数日线工具单测：Tushare 优先 / AKShare 兜底 / 空返回 / 缓存 / 市场分流。

运行：pytest -o addopts="" -m "not integration" tests/unit/dataflows/test_index_daily.py
"""

from __future__ import annotations

import sys
from unittest import mock

import pandas as pd

from tradingagents.dataflows import index_daily


def _clear_cache():
    index_daily._idf_cache.clear()


# ---------------------------------------------------------------------------
# get_index_daily_series：来源优先级与降级
# ---------------------------------------------------------------------------


def test_tushare_preferred_over_akshare():
    _clear_cache()
    with mock.patch.object(index_daily, "_tushare_index_rows", return_value=[("2024-01-02", 3500.0)]), \
         mock.patch.object(index_daily, "_akshare_index_rows", return_value=[("2024-01-02", 3400.0)]) as m_ak:
        rows = index_daily.get_index_daily_series("sh000300", "2024-01-01", "2024-01-31")
        assert rows == [("2024-01-02", 3500.0)]
        m_ak.assert_not_called()  # Tushare 成功时不应触达 AKShare


def test_fallback_to_akshare_when_tushare_empty():
    _clear_cache()
    with mock.patch.object(index_daily, "_tushare_index_rows", return_value=[]), \
         mock.patch.object(index_daily, "_akshare_index_rows", return_value=[("2024-01-02", 3400.0)]) as m_ak:
        rows = index_daily.get_index_daily_series("sh000300")
        assert rows == [("2024-01-02", 3400.0)]
        m_ak.assert_called_once()


def test_returns_empty_list_on_all_failures():
    _clear_cache()
    with mock.patch.object(index_daily, "_tushare_index_rows", return_value=[]), \
         mock.patch.object(index_daily, "_akshare_index_rows", return_value=[]):
        assert index_daily.get_index_daily_series("sh000300") == []


def test_range_filters_rows():
    _clear_cache()
    rows = [("2024-01-01", 3000.0), ("2024-01-15", 3100.0), ("2024-02-01", 3200.0)]
    with mock.patch.object(index_daily, "_tushare_index_rows", return_value=rows), \
         mock.patch.object(index_daily, "_akshare_index_rows", return_value=rows):
        got = index_daily.get_index_daily_series("sh000300", "2024-01-10", "2024-01-31")
        assert got == [("2024-01-15", 3100.0)]


def test_module_cache_hits_within_ttl():
    _clear_cache()
    with mock.patch.object(index_daily, "_tushare_index_rows", return_value=[("2024-01-02", 3500.0)]) as m_ts, \
         mock.patch.object(index_daily, "_akshare_index_rows", return_value=[]):
        index_daily.get_index_daily_series("sh000300", "2024-01-01", "2024-01-31")
        index_daily.get_index_daily_series("sh000300", "2024-01-01", "2024-01-31")
        # 第二次命中缓存，不再触发 Tushare / AKShare
        assert m_ts.call_count == 1


def test_ts_code_mapping():
    assert index_daily._index_code_to_ts_code("sh000300") == "000300.SH"
    assert index_daily._index_code_to_ts_code("sz399001") == "399001.SZ"
    assert index_daily._index_code_to_ts_code("not-a-code") is None


def test_tushare_rows_requires_token():
    with mock.patch.dict("sys.modules", {"tushare": mock.MagicMock()}):
        with mock.patch.dict("os.environ", {}, clear=False):
            token = __import__("os").environ.get("TUSHARE_TOKEN")
            # 无论 token 是否存在，调用不应抛异常；无 token 返回 []
            if not token:
                assert index_daily._tushare_index_rows("000300.SH", "20240101", "20240131") == []


# ---------------------------------------------------------------------------
# resolve_market / get_stock_daily_series
# ---------------------------------------------------------------------------


def test_resolve_market():
    assert index_daily.resolve_market("600000") == "A"
    assert index_daily.resolve_market("600000.SH") == "A"
    assert index_daily.resolve_market("AAPL.US") == "US"
    assert index_daily.resolve_market("0700.HK") == "HK"
    assert index_daily.resolve_market("BRK.B") == "OTHER"


def test_get_stock_daily_series_a_share():
    fake_ak = mock.MagicMock()
    fake_ak.stock_zh_a_hist.return_value = pd.DataFrame({
        "日期": ["2024-01-02", "2024-01-03"],
        "收盘": [100.0, 101.0],
    })
    with mock.patch.dict("sys.modules", {"akshare": fake_ak}):
        rows = index_daily.get_stock_daily_series("600000.SH", "2024-01-01", "2024-01-31")
    assert rows == [("2024-01-02", 100.0), ("2024-01-03", 101.0)]
    fake_ak.stock_zh_a_hist.assert_called_once()


def test_get_stock_daily_series_non_a_returns_empty():
    assert index_daily.get_stock_daily_series("AAPL.US", "2024-01-01", "2024-01-31") == []