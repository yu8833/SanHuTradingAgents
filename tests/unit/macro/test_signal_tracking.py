"""信号跟踪 + 有效性回填（P1）单元测试。

对应设计文档《第六章·交易工具与日常流程》§4 缺口1：
  - 扫描结果 → signal_tracking 记录构造（字段/去重/信号价）
  - 交易日递推：触发日之后第 n 个交易日
  - 只跟踪买点信号（B1/B2/B3/B2G），卖出信号（S 系）不纳入正向收益跟踪
"""

from __future__ import annotations

from datetime import date

from app.services import signal_tracking_service as sts


def _item(**kw) -> dict:
    base = {
        "code": "002997",
        "name": "瑞鹄模具",
        "industry": "汽车零部件",
        "close": 20.0,
        "pct_chg": 1.5,
        "bias60": -22.0,
        "ma60": 22.0,
        "ma60_direction": "走平",
        "stop_price": 20.9,
        "score": 80,
        "market_trend": "up",
        "trigger_date": "2026-08-25",
        "signals": [],
    }
    base.update(kw)
    return base


def _sig(**kw) -> dict:
    base = {
        "type": "B1",
        "type_label": "左侧买点",
        "trigger_price": 20.0,
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 记录构造
# ---------------------------------------------------------------------------
class TestBuildRecord:
    def test_basic_fields(self):
        rec = sts._build_record(_item(), _sig())
        assert rec["signal_type"] == "B1"
        assert rec["signal_label"] == "左侧买点"
        assert rec["code"] == "002997"
        assert rec["trigger_date"] == "2026-08-25"
        assert rec["signal_price"] == 20.0
        assert rec["status"] == "pending"
        assert rec["snapshot"]["bias60"] == -22.0
        assert rec["snapshot"]["ma60_direction"] == "走平"
        assert rec["snapshot"]["stop_price"] == 20.9

    def test_signal_price_fallback_to_close(self):
        """trigger_price 缺失时回退当日收盘价。"""
        rec = sts._build_record(_item(), _sig(trigger_price=None))
        assert rec["signal_price"] == 20.0

    def test_signal_price_invalid_fallback(self):
        """trigger_price 非法时回退当日收盘价。"""
        rec = sts._build_record(_item(), _sig(trigger_price="abc"))
        assert rec["signal_price"] == 20.0

    def test_label_from_map(self):
        assert sts._build_record(_item(), _sig(type="B2G"))["signal_label"] == "GMMA加仓"


# ---------------------------------------------------------------------------
# 交易日递推
# ---------------------------------------------------------------------------
class TestNthTradingDay:
    def test_five_trading_days(self):
        """2026-08-25(周二) 之后第 5 个交易日 = 2026-09-01(周二)。"""
        d = sts._nth_trading_day_after(date(2026, 8, 25), 5)
        assert d == date(2026, 9, 1), d

    def test_zero_returns_same_day(self):
        d = sts._nth_trading_day_after(date(2026, 8, 25), 0)
        assert d == date(2026, 8, 25)


# ---------------------------------------------------------------------------
# 信号类型筛选
# ---------------------------------------------------------------------------
class TestTrackedTypes:
    def test_buy_types_tracked(self):
        assert {"B1", "B2", "B3", "B2G"} == sts._TRACKED_TYPES

    def test_sell_types_not_tracked(self):
        for t in ("S1", "S2", "S3"):
            assert t not in sts._TRACKED_TYPES
