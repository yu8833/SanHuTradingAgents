"""
Bug-020 防回归测试：回测估值数据应为每日历史而非最新快照广播

根因：`_enrich_panel_fundamentals` 此前用 `screener._load_fundamentals` 的每股最新快照
      （pe_ttm/pb/total_mv）按 symbol 广播到所有日期行，导致依赖估值条件的策略
      （如"低估值高股息龙头"）在整个回测区间每天都用同一估值判断，估值变化无法
      触发卖出——表现为三只股票从头持有到尾、买在起点卖在终点。

修复：估值/市值优先从 stock_daily_basic 按 (symbol, date) 对齐并前向填充，
      无每日数据时回退快照广播。行业仍来自快照（静态字段）。

本测试验证：
1. 存在每日估值数据时，pe_ttm/pb/total_mv 随日期变化（而非快照广播）；
2. 缺失每日数据时，回退到最新快照广播（保持历史行为）。
"""
import pandas as pd
import pytest

from app.strategy_system.backtest import _enrich_panel_fundamentals, _entry_exit_mask

pytestmark = [pytest.mark.regression, pytest.mark.unit]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    """微型假 MongoDB 集合，仅支持本测试用到的 find 查询子集。"""

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
                    if op == "$in" and val not in ref:
                        return False
                    elif op == "$gte" and not (val is not None and val >= ref):
                        return False
                    elif op == "$lte" and not (val is not None and val <= ref):
                        return False
            elif val != cond:
                return False
        return True

    def find(self, query, projection=None):
        out = []
        for doc in self._docs:
            if self._match(doc, query):
                if projection:
                    keep = {k: v for k, v in doc.items()
                            if k in projection or k == "_id"}
                    out.append(keep)
                else:
                    out.append(doc)
        return _FakeCursor(out)


class _FakeDb:
    def __init__(self, basic, daily, dividend):
        self.stock_basic_info = _FakeCollection(basic)
        self.stock_daily_basic = _FakeCollection(daily)
        self.stock_dividend = _FakeCollection(dividend)

    def __getitem__(self, name):
        return getattr(self, name)


def _build_panel(dates):
    rows = []
    for i, d in enumerate(dates):
        rows.append({
            "symbol": "000001", "date": d,
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0 + i,
            "volume": 1000, "amount": 10000, "pct_chg": 0.0,
        })
    return pd.DataFrame(rows)


def _basic_doc():
    return {
        "_id": 0, "code": "000001", "symbol": "000001",
        "industry": "银行", "pe_ttm": 20.0, "pb": 3.0, "total_mv": 100.0,
    }


def test_daily_valuation_override_snapshot():
    """存在每日估值时，pe_ttm/pb/total_mv 应随日期变化，而非快照广播。"""
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    daily = [
        {"code": "000001", "symbol": "000001", "trade_date": "2026-01-05",
         "pe_ttm": 10.0, "pb": 1.0, "total_mv": 50.0},
        {"code": "000001", "symbol": "000001", "trade_date": "2026-01-06",
         "pe_ttm": 12.0, "pb": 1.5, "total_mv": 60.0},
        {"code": "000001", "symbol": "000001", "trade_date": "2026-01-07",
         "pe_ttm": 18.0, "pb": 2.5, "total_mv": 70.0},
    ]
    db = _FakeDb([_basic_doc()], daily, [])
    panel = _build_panel(dates)
    out = _enrich_panel_fundamentals(db, panel)
    out = out.sort_values("date").reset_index(drop=True)

    # 每日估值生效：pe_ttm 应为 [10,12,18]，而非快照广播的 20
    assert out["pe_ttm"].tolist() == [10.0, 12.0, 18.0], \
        f"每日估值未生效（bug-020 复发）：pe_ttm={out['pe_ttm'].tolist()}"
    assert out["pb"].tolist() == [1.0, 1.5, 2.5], \
        f"每日 PB 未生效：pb={out['pb'].tolist()}"
    assert out["total_mv"].tolist() == [50.0, 60.0, 70.0], \
        f"每日市值未生效：total_mv={out['total_mv'].tolist()}"

    # 行业仍来自快照（静态）
    assert out["industry"].tolist() == ["银行"] * 3


def test_fallback_to_snapshot_when_no_daily_data():
    """无每日估值数据时，应回退到最新快照广播（保持历史行为）。"""
    dates = ["2026-01-05", "2026-01-06"]
    db = _FakeDb([_basic_doc()], [], [])  # stock_daily_basic 为空
    panel = _build_panel(dates)
    out = _enrich_panel_fundamentals(db, panel)
    out = out.sort_values("date").reset_index(drop=True)

    assert out["pe_ttm"].tolist() == [20.0, 20.0], \
        f"应为快照广播，实际 pe_ttm={out['pe_ttm'].tolist()}"
    assert out["pb"].tolist() == [3.0, 3.0]
    assert out["total_mv"].tolist() == [100.0, 100.0]
    assert out["industry"].tolist() == ["银行"] * 2


def test_daily_valuation_does_not_break_without_daily_column():
    """面板无估值列时，注入后应仍具备 pe_ttm/pb/total_mv/industry 列。"""
    dates = ["2026-01-05"]
    daily = [
        {"code": "000001", "symbol": "000001", "trade_date": "2026-01-05",
         "pe_ttm": 8.0, "pb": 0.9, "total_mv": 40.0},
    ]
    db = _FakeDb([_basic_doc()], daily, [])
    panel = _build_panel(dates)
    out = _enrich_panel_fundamentals(db, panel)
    for col in ("pe_ttm", "pb", "total_mv", "industry", "div_yield"):
        assert col in out.columns, f"缺少列 {col}"
    assert out["pe_ttm"].iloc[0] == 8.0


def test_exit_mask_when_valuation_exceeds_threshold():
    """估值突破阈值时应产生卖出信号（bug-020 第3步：估值变化驱动卖出）。"""
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    daily = [
        {"code": "000001", "symbol": "000001", "trade_date": d,
         "pe_ttm": pe, "pb": pb, "total_mv": 50.0}
        for d, pe, pb in [
            ("2026-01-05", 10.0, 1.0),  # 满足 max_pe=15 / max_pb=3
            ("2026-01-06", 16.0, 1.2),  # PE 突破 15
            ("2026-01-07", 12.0, 3.5),  # PB 突破 3
        ]
    ]
    db = _FakeDb([_basic_doc()], daily, [])
    panel = _enrich_panel_fundamentals(db, _build_panel(dates))
    panel = panel.sort_values("date").reset_index(drop=True)
    # 面板需含 symbol/date 列作为 _entry_exit_mask 的索引来源
    _, exit_mask = _entry_exit_mask(
        panel, "low_pe_high_div_leader",
        {"max_pe": 15, "max_pb": 3.0, "min_div_yield": 0.03,
         "min_div_years": 4, "top_n": 3},
    )
    by_date = exit_mask.groupby(panel["date"]).first()
    # 估值未突破的最后一天也应为 False（仅突破当日为 True）
    assert bool(by_date.get("2026-01-05", False)) is False, \
        "估值未突破即不应卖出"
    assert bool(by_date.get("2026-01-06", False)) is True, \
        "PE 突破 15 应触发卖出（bug-020 复发）"
    assert bool(by_date.get("2026-01-07", False)) is True, \
        "PB 突破 3 应触发卖出"


def test_exit_mask_fires_with_empty_params_using_defaults():
    """前端传空 params 时，估值退出仍应生效（用策略默认阈值，不静默跳过）。

    根因：调用方（前端）只传 `params={}`，此前 `_entry_exit_mask` 仅在
    `params` 明确含 max_pe/max_pb 键时才生成估值退出掩码，导致依赖估值条件的
    策略从不触发卖出（买入起点→卖出终点，全部持仓持有到期末）。修复后应合并
    策略声明默认值（max_pe=15, max_pb=3.0）再判断退出。
    """
    dates = ["2026-01-05", "2026-01-06", "2026-01-07"]
    # 第2日 PE=16 突破默认 max_pe=15，应触发卖出
    daily = [
        {"code": "000001", "symbol": "000001", "trade_date": d,
         "pe_ttm": pe, "pb": pb, "total_mv": 50.0}
        for d, pe, pb in [
            ("2026-01-05", 10.0, 1.0),
            ("2026-01-06", 16.0, 1.2),
            ("2026-01-07", 10.0, 1.0),
        ]
    ]
    db = _FakeDb([_basic_doc()], daily, [])
    panel = _enrich_panel_fundamentals(db, _build_panel(dates))
    panel = panel.sort_values("date").reset_index(drop=True)
    _, exit_mask = _entry_exit_mask(panel, "low_pe_high_div_leader", {})
    by_date = exit_mask.groupby(panel["date"]).first()
    assert bool(by_date.get("2026-01-05", False)) is False, \
        "估值未突破即不应卖出"
    assert bool(by_date.get("2026-01-06", False)) is True, \
        "空 params 下 PE 突破默认 15 仍应触发卖出（本次修复）"
    assert bool(by_date.get("2026-01-07", False)) is False, \
        "估值回落回阈值内不应持续卖出"