"""
回退/最近交易日收敛 防回归测试。

覆盖:
1. tushare_sync._latest_settled_trade_day:交易日 18:30 前回退上一交易日(统一 prev_trading_day),18:30 后不回退;
2. pipeline_backtest._prev_day:自然日-1 升级为交易日语义(周一的前一日=上周五,非周日);
3. basics_sync.utils.find_latest_trade_date:日期生成走 date_utils(YYYYMMDD),探测语义不变。
"""
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = [pytest.mark.unit]

BEIJING = timezone(timedelta(hours=8))


class _Clock:
    """受控"当前时间"。"""

    fixed = None

    @classmethod
    def set(cls, iso):
        cls.fixed = datetime.fromisoformat(iso).replace(tzinfo=BEIJING)

    def __call__(self):
        return self.fixed


def _patch_trading_time(monkeypatch, *, latest: date, previous: date):
    """打桩 trading_time 三个函数,让被测逻辑调用它。"""
    import app.utils.trading_time as tt

    monkeypatch.setattr(tt, "get_latest_trade_day", lambda now: latest)
    monkeypatch.setattr(tt, "is_trading_day", lambda d: True)
    monkeypatch.setattr(tt, "prev_trading_day", lambda ref: previous)


def test_latest_settled_rolls_back_before_1830(monkeypatch):
    """交易日 10:00(18:30 前) → 回退上一交易日《多为》 prev_trading_day 结果。"""
    import app.worker.tushare_sync_service as ts

    clock = _Clock()
    clock.set("2026-10-09T10:00:00")
    monkeypatch.setattr(ts, "now_tz", clock)
    _patch_trading_time(monkeypatch, latest=date(2026, 10, 9), previous=date(2026, 10, 8))

    svc = ts.TushareSyncService.__new__(ts.TushareSyncService)  # 绕过 __init__ 避免触 DB
    assert svc._latest_settled_trade_day() == "2026-10-08"


def test_latest_settled_no_rollback_after_1830(monkeypatch):
    """交易日 19:00(18:30 后) → 不回退,保持最新交易日。"""
    import app.worker.tushare_sync_service as ts

    clock = _Clock()
    clock.set("2026-10-09T19:00:00")
    monkeypatch.setattr(ts, "now_tz", clock)
    _patch_trading_time(monkeypatch, latest=date(2026, 10, 9), previous=date(2026, 10, 8))

    svc = ts.TushareSyncService.__new__(ts.TushareSyncService)  # 绕过 __init__ 避免触 DB
    assert svc._latest_settled_trade_day() == "2026-10-09"


def test_pipeline_prev_day_trade_semantics(monkeypatch):
    """周一的前一日应为上周五(交易日),而非周日;周五前日为周四。"""
    import app.services.pipeline_backtest_service as pb
    import app.utils.trading_time as tt

    monkeypatch.setattr(tt, "is_trading_day", lambda d: d.weekday() < 5)  # 简化:仅排周末
    assert pb._prev_day("2026-10-12") == "2026-10-09"   # 周一 → 上周五
    assert pb._prev_day("2026-10-09") == "2026-10-08"   # 周五 → 周四


def test_find_latest_trade_date_uses_compact(monkeypatch):
    """basics_sync 探测日期为 YYYYMMDD(compact)且探测语义不变。"""
    import app.services.basics_sync.utils as bsu
    from app.utils.date_utils import compact_date

    today = bsu.now_tz().date()

    class _HitToday:
        def daily_basic(self, trade_date="", fields=""):
            if trade_date == compact_date(today):
                class _Df:
                    empty = False
                return _Df()
            raise RuntimeError("未开盘")

    monkeypatch.setattr(bsu, "get_pro", lambda: _HitToday())
    assert bsu.find_latest_trade_date() == compact_date(today)

    class _AllFail:
        def daily_basic(self, trade_date="", fields=""):
            raise RuntimeError("全部失败")

    monkeypatch.setattr(bsu, "get_pro", lambda: _AllFail())
    # 全部探测失败 → 回退昨天(YYYYMMDD),语义保持
    assert bsu.find_latest_trade_date() == compact_date(today - timedelta(days=1))