"""
缓存 TTL 节假日感知 防回归测试。

统一后 cache_layer/sync_cache_layer 的 _is_trading_hours 走 trading_time.is_trading_day
（权威日历,节假日感知）:法定节假日落在工作日时 TTL 用 non_trading 长档;
交易日盘中(9:30-11:30 / 13:00-15:00)用 trading 短档;周末为非交易档。
"""
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = [pytest.mark.unit]

BEIJING = timezone(timedelta(hours=8))


class _FakeDT(datetime):
    """固定四川北京时间时钟,注入到 cache_layer/sync_cache_layer。"""

    @classmethod
    def now(cls, tz=None):
        return cls._fixed


def _patch_clock(monkeypatch, iso_local: str) -> _FakeDT:
    _FakeDT._fixed = datetime.fromisoformat(iso_local).replace(tzinfo=BEIJING)
    return _FakeDT


def test_ttl_holiday_uses_non_trading(monkeypatch):
    """法定节假日(工作日)盘中 → non_trading 长 TTL。"""
    import app.services.cache_layer as cl
    import app.utils.trading_time as tt

    _patch_clock(monkeypatch, "2026-10-01T10:30:00")   # 国庆节 10:30
    monkeypatch.setattr(cl, "datetime", _FakeDT)
    monkeypatch.setattr(tt, "is_trading_day", lambda now: False)  # 节假日判定

    assert cl.get_ttl("realtime") == 300                 # non_trading
    assert cl.get_ttl("market") == 1800
    assert cl._is_trading_hours() is False


def test_ttl_trading_day_session_uses_trading(monkeypatch):
    """交易日盘中 9:30-11:30 与 13:00-15:00 → trading 短 TTL。"""
    import app.services.cache_layer as cl
    import app.utils.trading_time as tt

    monkeypatch.setattr(tt, "is_trading_day", lambda now: True)

    for _t, d in [("2026-10-09T09:30:00", "2026-10-09T11:30:00"),
                  ("2026-10-09T13:00:00", "2026-10-09T15:00:00")]:
        _patch_clock(monkeypatch, _t)
        monkeypatch.setattr(cl, "datetime", _FakeDT)
        assert cl.get_ttl("realtime") == 30              # trading
    # 午休/盘前/盘后仍为 non_trading
    for _t in ("2026-10-09T09:00:00", "2026-10-09T12:00:00", "2026-10-09T15:30:00"):
        _patch_clock(monkeypatch, _t)
        monkeypatch.setattr(cl, "datetime", _FakeDT)
        assert cl.get_ttl("realtime") == 300


def test_ttl_weekend_uses_non_trading(monkeypatch):
    """周末(非交易日) → non_trading。"""
    import app.services.cache_layer as cl
    import app.utils.trading_time as tt

    _patch_clock(monkeypatch, "2026-09-26T10:30:00")     # 周六
    monkeypatch.setattr(cl, "datetime", _FakeDT)
    monkeypatch.setattr(tt, "is_trading_day", lambda now: False)

    assert cl.get_ttl("realtime") == 300
    assert cl._is_trading_hours() is False


def test_sync_cache_ttl_holiday(monkeypatch):
    """sync_cache_layer 同款节假日感知。"""
    import app.services.sync_cache_layer as scl
    import app.utils.trading_time as tt

    _patch_clock(monkeypatch, "2026-10-01T10:30:00")
    monkeypatch.setattr(scl, "datetime", _FakeDT)
    monkeypatch.setattr(tt, "is_trading_day", lambda now: False)
    assert scl.get_ttl("realtime") == 300

    _patch_clock(monkeypatch, "2026-10-09T10:30:00")
    monkeypatch.setattr(scl, "datetime", _FakeDT)
    monkeypatch.setattr(tt, "is_trading_day", lambda now: True)
    assert scl.get_ttl("realtime") == 30