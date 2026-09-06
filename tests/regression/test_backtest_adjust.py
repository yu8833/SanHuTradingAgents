"""
回测复权治理（B3/B4）回归测试：hfq 复权链重建 + adjust 口径标注

背景（三项改造之 B）：
  - B3 复权：`data_adapter.load_daily_panel(adjust="hfq")` 用 pct_chg（小数口径）链式重建
    后复权价格，消除除权除息造成的价格断层（避免误触发 MA/突破类信号）。
  - B4 标注：回测结果 config 携带 adjust/scope_notes。

说明：本系统回测固定采用"当前在上市股票 + 近一年"口径，不涉及退市股，故不含
      as-of-date 股票池过滤逻辑。
"""
import pandas as pd
import pytest

from app.core.config import settings
from app.strategy_system import data_adapter
from app.strategy_system.backtest import _load_panel, _scope_tags

pytestmark = [pytest.mark.regression, pytest.mark.unit]


# ---------------------------------------------------------------
# 假 MongoDB 集合（仅支持本测试用到的 find 查询子集）
# ---------------------------------------------------------------
class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def _match(self, doc, query) -> bool:
        for key, cond in query.items():
            if key == "$or":
                if not any(self._match(doc, sub) for sub in cond):
                    return False
                continue
            val = doc.get(key)
            if isinstance(cond, dict):
                for op, ref in cond.items():
                    if op == "$in" and val not in ref or op == "$gte" and not (val is not None and val >= ref) or op == "$lte" and not (val is not None and val <= ref):
                        return False
            elif val != cond:
                return False
        return True

    def find(self, query, projection=None):
        out = []
        for doc in self._docs:
            if self._match(doc, query):
                if projection:
                    out.append({k: v for k, v in doc.items()
                                if k in projection or k == "_id"})
                else:
                    out.append(doc)
        return _FakeCursor(out)


class _FakeDb:
    def __init__(self, **collections):
        for name, docs in collections.items():
            setattr(self, name, _FakeCollection(docs))

    def __getitem__(self, name):
        return getattr(self, name)


def _quote_doc(symbol, date, close, pct_chg, source="tushare", open_=None):
    return {
        "code": symbol, "symbol": symbol, "trade_date": date,
        "open": open_ if open_ is not None else close,
        "high": close * 1.02, "low": close * 0.98, "close": close,
        "volume": 1000, "amount": 10000, "pct_chg": pct_chg,
        "period": "daily", "data_source": source,
    }


# ---------------------------------------------------------------
# B3：hfq 复权链重建
# ---------------------------------------------------------------
def test_hfq_chain_rebuild():
    """hfq_close 应等于 raw_close × cumprod(1+pct_chg)，首行锚定 raw close，
    scale 应用到 OHLC，volume/amount 保持原值。"""
    docs = [
        _quote_doc("000001", "2026-01-05", 10.0, None),      # 首行 pct_chg 缺失
        _quote_doc("000001", "2026-01-06", 11.0, 10.0),      # +10%
        _quote_doc("000001", "2026-01-07", 9.9, -10.0),      # -10%
    ]
    db = _FakeDb(stock_daily_quotes=docs)
    df = data_adapter.load_daily_panel(
        db, ["000001"], "2026-01-05", "2026-01-07", adjust="hfq"
    ).sort_values("date").reset_index(drop=True)

    assert len(df) == 3
    # 首行锚定 raw close
    assert df.loc[0, "close"] == pytest.approx(10.0, rel=1e-6)
    # 01-06: 10 * (1+0.10) = 11.0
    assert df.loc[1, "close"] == pytest.approx(11.0, rel=1e-4)
    # 01-07: 11 * (1-0.10) = 9.9
    assert df.loc[2, "close"] == pytest.approx(9.9, rel=1e-4)
    # scale 应用到 open/high/low：01-06 的 open 应为 11.0 * (11.0/11.0) = 11.0
    assert df.loc[1, "open"] == pytest.approx(11.0, rel=1e-4)
    # volume/amount 保持原值
    assert df.loc[1, "volume"] == 1000
    assert df.loc[1, "amount"] == 10000


def test_hfq_missing_pct_chg_flat():
    """中间 pct_chg 缺失（停牌）按当日零涨跌处理（回退 raw），后续链仍连续。"""
    docs = [
        _quote_doc("000001", "2026-01-05", 10.0, None),
        _quote_doc("000001", "2026-01-06", 12.0, 20.0),   # +20% → 12.0
        _quote_doc("000001", "2026-01-07", 12.0, None),   # 停牌，pct_chg 缺失
        _quote_doc("000001", "2026-01-08", 13.2, 10.0),   # +10% → 13.2
    ]
    db = _FakeDb(stock_daily_quotes=docs)
    df = data_adapter.load_daily_panel(
        db, ["000001"], "2026-01-05", "2026-01-08", adjust="hfq"
    ).sort_values("date").reset_index(drop=True)

    assert df.loc[0, "close"] == pytest.approx(10.0, rel=1e-6)
    assert df.loc[1, "close"] == pytest.approx(12.0, rel=1e-4)
    # 停牌日：hfq 价保持 12.0（零涨跌）
    assert df.loc[2, "close"] == pytest.approx(12.0, rel=1e-4)
    assert df.loc[3, "close"] == pytest.approx(13.2, rel=1e-4)


def test_hfq_mixed_source_fallback_none():
    """同一 symbol 出现多个数据源（pct_chg 口径可能不一致）→ 整只回退不复权。"""
    docs = [
        _quote_doc("000001", "2026-01-05", 10.0, None, source="tushare"),
        _quote_doc("000001", "2026-01-06", 11.0, 10.0, source="akshare"),
    ]
    db = _FakeDb(stock_daily_quotes=docs)
    notes: list[str] = []
    df = data_adapter.load_daily_panel(
        db, ["000001"], "2026-01-05", "2026-01-06", adjust="hfq", notes=notes
    ).sort_values("date").reset_index(drop=True)

    # 回退不复权：close 保持 raw
    assert df.loc[1, "close"] == pytest.approx(11.0, rel=1e-6)
    assert notes
    assert any("混源" in n for n in notes)


def test_adjust_none_keeps_raw():
    """adjust="none"（默认）不改变价格。"""
    docs = [
        _quote_doc("000001", "2026-01-05", 10.0, None),
        _quote_doc("000001", "2026-01-06", 11.0, 10.0),
    ]
    db = _FakeDb(stock_daily_quotes=docs)
    df = data_adapter.load_daily_panel(db, ["000001"], "2026-01-05", "2026-01-06")
    assert df.loc[1, "close"] == pytest.approx(11.0, rel=1e-6)


# ---------------------------------------------------------------
# B4：口径标注
# ---------------------------------------------------------------
def test_scope_tags_default_and_attrs():
    """无 attrs 的 panel 返回保守默认；带 bt_scope attrs 时原样返回 adjust/notes。"""
    assert _scope_tags(pd.DataFrame()) == {"adjust": "none", "notes": []}
    panel = pd.DataFrame()
    panel.attrs["bt_scope"] = {"adjust": "hfq", "notes": ["x"]}
    assert _scope_tags(panel)["adjust"] == "hfq"
    assert _scope_tags(panel)["notes"] == ["x"]


def test_load_panel_scope_adjust_hfq(monkeypatch):
    """_load_panel 默认启用 hfq，并把 adjust 写入 panel.attrs['bt_scope']。"""
    monkeypatch.setattr(settings, "BACKTEST_ADJUST", "hfq")

    quotes = [
        _quote_doc("000001", "2026-01-05", 10.0, None),
        _quote_doc("000001", "2026-01-06", 11.0, 10.0),
    ]
    db = _FakeDb(stock_daily_quotes=quotes)

    config = {
        "start": "2026-01-05", "end": "2026-01-06",
        "symbols": ["000001"],
    }
    panel = _load_panel(db, config, enrich_fundamentals=False, keep_columns=set())

    assert not panel.empty
    # hfq 链生效：01-06 close = 10 * 1.10 = 11.0
    row = panel[(panel["symbol"] == "000001") & (panel["date"] == "2026-01-06")]
    assert len(row) == 1
    assert float(row["close"].iloc[0]) == pytest.approx(11.0, rel=1e-4)

    scope = panel.attrs["bt_scope"]
    assert scope["adjust"] == "hfq"
    # 单源、无混源/退市过滤时 notes 为空属正常
    assert isinstance(scope["notes"], list)