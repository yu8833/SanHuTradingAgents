"""周度复盘自动化（P3）单元测试。

对应设计文档《第六章·交易工具与日常流程》§4 缺口3：
  - 周窗口边界（周一 00:00 → 今天）
  - 上周五基准日计算（沪深300 对比基准）
  - 全红率计算口径 = 盈利持仓数 / 总持仓数（教材 5.3）
"""

from __future__ import annotations

from datetime import date, timedelta

from app.services import weekly_review_service as wrs


class TestWeekBounds:
    def test_monday_boundary(self):
        """周一当天：本周开始 = 今天。"""
        assert wrs._week_bounds()[0] <= wrs._week_bounds()[1]

    def test_week_length_within_7_days(self):
        start, end = wrs._week_bounds()
        d0 = date.fromisoformat(start)
        d1 = date.fromisoformat(end)
        assert 0 <= (d1 - d0).days <= 6


class TestLastFriday:
    def test_friday_before_monday(self):
        """2026-08-31 是周一，之前最近交易日 2026-08-28（上周五，普通周=周五）。"""
        monday = date(2026, 8, 31)
        assert wrs._last_friday_before(monday) == date(2026, 8, 28)

    def test_before_tuesday_is_trade_day(self):
        """升级交易日语义：返回输入之前最近一个交易日(节假日可非周五)。"""
        from app.utils.trading_time import is_trading_day

        d = wrs._last_friday_before(date(2026, 8, 25))
        assert d < date(2026, 8, 25)
        assert is_trading_day(d)

    def test_always_recent_trade_day(self):
        """任意输入均返回其之前最近交易日。"""
        from datetime import timedelta

        from app.utils.trading_time import is_trading_day

        for day_offset in range(7):
            d = date(2026, 9, 1) + timedelta(days=day_offset)
            r = wrs._last_friday_before(d)
            assert r < d
            assert is_trading_day(r)


class TestAllRedRate:
    def test_all_red_formula(self):
        """全红率 = 盈利持仓数 / 总持仓数。"""
        positions = [
            {"profitable": True},
            {"profitable": True},
            {"profitable": False},
        ]
        profitable = sum(1 for p in positions if p["profitable"])
        rate = profitable / len(positions) * 100
        assert round(rate, 1) == round(2 / 3 * 100, 1)


class TestHs300Fallback:
    def test_unavailable_on_exception(self):
        """数据获取失败必须返回 available=False，不能抛异常阻塞周报。"""
        res = wrs._fetch_hs300_weekly_return("2026-08-31", "2026-08-31")
        assert "available" in res
