"""
统一交易日历服务 单元测试。

覆盖:
1. 日期归一 `_norm`(date/datetime/YYYYMMDD/YYYY-MM-DD);
2. 内存视图 `is_open_day`(未装载→None,装载后 True/False);
3. 实收交叉校验 `effective_trade_days`(patch 聚合结果,兼容两种日期格式);
4. `trading_time.is_trading_day` 优先权威日历、未装载/异常降级规则;
5. `stock_quadrant_analysis._recent_dates` 优先日历+实收、失败回退 distinct。

统一 monkeypatch 数据库与外部接口,不触网、不落库。
"""
from datetime import date, datetime

import pytest

pytestmark = [pytest.mark.unit]


# ── _norm 格式归一 ──
def test_norm_formats():
    from app.services.trade_calendar_service import _norm

    assert _norm(date(2026, 9, 24)) == "2026-09-24"
    assert _norm(datetime(2026, 9, 24, 15, 30)) == "2026-09-24"
    assert _norm("20260924") == "2026-09-24"
    assert _norm("2026-09-24") == "2026-09-24"


# ── is_open_day 内存视图 ──
def test_is_open_day_未装载返回_none():
    import app.services.trade_calendar_service as tcs

    tcs._STATE["open"] = frozenset()
    assert tcs.is_open_day("2026-09-24") is None


def test_is_open_day_装载后判定():
    import app.services.trade_calendar_service as tcs

    tcs._STATE["open"] = frozenset({"2026-09-24", "2026-10-08"})
    assert tcs.is_open_day("2026-09-24") is True
    assert tcs.is_open_day("2026-10-08") is True
    assert tcs.is_open_day("2026-10-01") is False
    assert tcs.is_open_day(date(2026, 9, 24)) is True
    assert tcs.is_open_day("20260924") is True


class _Cursor:
    """可异步迭代的假游标。"""

    def __init__(self, docs):
        self._it = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


# ── effective_trade_days 实收交叉校验 ──
async def test_effective_trade_days(monkeypatch):
    import app.services.trade_calendar_service as tcs

    # 库内实际存在:2026-09-21(紧凑存储) / 2026-09-22(横线存储) / 09-24;09-23 缺失
    stored = [{"_id": "20260921"}, {"_id": "2026-09-22"}, {"_id": "2026-09-24"}]

    class _FakeCol:
        def aggregate(self, pipe):
            match_in = pipe[0]["$match"]["trade_date"]["$in"]
            # 断言查询兼容两种日期存储格式
            assert "2026-09-24" in match_in and "20260924" in match_in
            return _Cursor(stored)

    monkeypatch.setattr(tcs, "col", lambda name: _FakeCol())
    result = await tcs.effective_trade_days(
        ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"])
    assert result == ["2026-09-21", "2026-09-22", "2026-09-24"]


async def test_effective_trade_days_empty_ok():
    import app.services.trade_calendar_service as tcs

    assert await tcs.effective_trade_days([]) == []


# ── trading_time.is_trading_day 权威优先 + 降级 ──
def test_trading_day_优先权威日历(monkeypatch):
    import app.utils.trading_time as tt

    monkeypatch.setattr(
        "app.services.trade_calendar_service._STATE",
        {"open": frozenset({"2026-09-24"}), "loaded_date": "2026-09-27"},
    )
    # 权威视图判定:国庆休市 10-01 应为 False(即便 chinese_calendar 语义正常也一致)
    assert tt.is_trading_day("2026-10-01") is False
    assert tt.is_trading_day("2026-09-24") is True


def test_trading_day_视图未装载降级规则(monkeypatch):
    import app.utils.trading_time as tt

    monkeypatch.setattr(
        "app.services.trade_calendar_service._STATE",
        {"open": frozenset(), "loaded_date": None},
    )
    try:
        import chinese_calendar  # noqa: F401
        # 未装载 → 规则兜底:2026-10-01 为法定节假日 → False
        assert tt.is_trading_day("2026-10-01") is False
    except ImportError:
        # 未安装 chinese_calendar 时退化为仅排周末:2026-10-01 周四 → True
        assert tt.is_trading_day("2026-10-01") is True
    # 周末在任何路径下均为非交易日
    assert tt.is_trading_day("2026-09-26") is False


# ── _recent_dates 日历+实收优先,失败回退 distinct ──
def _patch_recent_dates_env(monkeypatch, *, effective=None, distinct=None):
    import app.services.stock_quadrant_analysis as sq

    async def fake_fetch_effective():
        if effective is None:
            raise RuntimeError("calendar unavailable")
        return effective

    monkeypatch.setattr(sq, "_fetch_effective_dates", fake_fetch_effective)

    class _FakeCol:
        async def distinct(self, key, filter=None):
            assert key == "trade_date"
            return distinct or []

    monkeypatch.setattr(sq, "col", lambda name: _FakeCol())
    sq._TRADE_DATES_CACHE["dates"] = []
    sq._TRADE_DATES_CACHE["ts"] = 0.0
    return sq


async def test_recent_dates_优先日历实收(monkeypatch):
    sq = _patch_recent_dates_env(
        monkeypatch, effective=["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"])
    days = await sq._recent_dates(3)
    assert days == ["2026-09-22", "2026-09-23", "2026-09-24"]
    # 缓存生效:再次读取直接命中缓存
    assert await sq._recent_dates(2) == ["2026-09-23", "2026-09-24"]


async def test_recent_dates_失败回退distinct(monkeypatch):
    sq = _patch_recent_dates_env(
        monkeypatch,
        effective=None,
        distinct=["2026-09-24", "20260922", "2026-09-23", "2026-09-21"],
    )
    days = await sq._recent_dates(3)
    assert days == ["2026-09-22", "2026-09-23", "2026-09-24"]