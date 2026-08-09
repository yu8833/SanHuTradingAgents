"""
Bug-021 防回归测试：回测交易明细的名称列不应为空

根因：回测面板经 `data_adapter.load_daily_panel` 加载，输出列 PANEL_COLUMNS 不含
      `name`，`_simulate_portfolio` 此前仅从面板的 name 列构建 symbol->名称映射，
      导致交易明细的"名称"列全部为空（只有代码）。

修复：新增 `_build_name_map`，优先取面板 name 列，缺失时回退从 stock_basic_info
      按代码补齐名称。
"""
import pytest

from app.strategy_system.backtest import _build_name_map

import pandas as pd

pytestmark = [pytest.mark.regression, pytest.mark.unit]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)

    def __iter__(self):
        return iter(self._docs)

    def limit(self, n):
        return _FakeCursor(self._docs[:n])


class _FakeCollection:
    """微型假集合，支持 get_stock_list 用到的 find(query, projection).limit()。"""

    def __init__(self, docs):
        self._docs = docs

    def find(self, query, projection=None):
        out = []
        for doc in self._docs:
            if projection:
                keep = {k: v for k, v in doc.items()
                        if k in projection or k == "_id"}
                out.append(keep)
            else:
                out.append(doc)
        return _FakeCursor(out)


class _FakeDb:
    def __init__(self, basic):
        self.stock_basic_info = _FakeCollection(basic)

    def __getitem__(self, name):
        return getattr(self, name)


def _build_panel(dates, with_name=False):
    rows = [{
        "symbol": "000001", "date": d,
        "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0,
        "volume": 1000, "amount": 10000, "pct_chg": 0.0,
    } for d in dates]
    df = pd.DataFrame(rows)
    if with_name:
        df["name"] = "平安银行"
    return df


def test_name_map_falls_back_to_stock_basic_info():
    """面板无 name 列时，应从 stock_basic_info 补齐名称。"""
    basic = [
        {"symbol": "000001", "name": "平安银行", "code": "000001", "industry": "银行"},
        {"symbol": "000338", "name": "潍柴动力", "code": "000338", "industry": "汽车"},
    ]
    db = _FakeDb(basic)
    panel = _build_panel(["2026-01-05", "2026-01-06"], with_name=False)
    names = _build_name_map(panel, db)
    assert names.get("000001") == "平安银行", "面板无 name 时应回退 stock_basic_info"
    assert names.get("000338") == "潍柴动力"


def test_name_map_uses_panel_name_column_when_present():
    """面板自带 name 列时，应优先使用面板名称。"""
    basic = [{"symbol": "000001", "name": "旧名称", "code": "000001", "industry": "银行"}]
    db = _FakeDb(basic)
    panel = _build_panel(["2026-01-05"], with_name=True)
    names = _build_name_map(panel, db)
    assert names.get("000001") == "平安银行", "面板自带 name 列应优先使用"