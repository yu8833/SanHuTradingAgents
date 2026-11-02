"""市场温度分位：盘中交易进度折算的单元测试。"""

from datetime import datetime

from app.services.market_metrics import _session_progress, _temperature


def _dt(h: int, m: int) -> datetime:
    return datetime(2026, 11, 2, h, m)


def test_progress_before_open():
    assert _session_progress(_dt(9, 0)) == 0.0


def test_progress_morning():
    # 10:30 已交易 60 分钟，占全天 240 分钟的 25%
    assert abs(_session_progress(_dt(10, 30)) - 60 / 240) < 1e-9


def test_progress_noon_break():
    assert _session_progress(_dt(12, 0)) == 0.5


def test_progress_afternoon():
    # 14:00 已交易 180 分钟
    assert abs(_session_progress(_dt(14, 0)) - 180 / 240) < 1e-9


def test_progress_after_close():
    assert _session_progress(_dt(15, 30)) == 1.0


def test_temperature_scales_cumulative_metrics_only():
    hist = [{"date": "2026-10-30", "amount": 20000, "avg_turnover": 3.0,
             "up_pct": 50, "zt": 50, "dt": 10}]
    live = {"date": "2026-11-02", "amount": 10000, "avg_turnover": 1.5,
            "up_pct": 50, "zt": 50, "dt": 10}
    temp = {t["key"]: t for t in _temperature(hist, live, 0.5)}
    # 成交额按进度折算回全天后续，恰好等于历史值 → 50% 分位
    assert temp["amount"]["rank"] == 50
    assert temp["amount"]["projected"] == 20000
    assert temp["avg_turnover"]["projected"] == 3.0
    # 瞬时指标（上涨率）不折算
    assert temp["up_pct"]["rank"] == 50
    assert "projected" not in temp["up_pct"]


def test_temperature_no_scaling_after_close():
    hist = [{"date": "2026-10-30", "amount": 20000, "avg_turnover": 3.0,
             "up_pct": 50, "zt": 50, "dt": 10}]
    live = {"date": "2026-11-02", "amount": 20000, "avg_turnover": 3.0,
            "up_pct": 50, "zt": 50, "dt": 10}
    temp = {t["key"]: t for t in _temperature(hist, live, 1.0)}
    assert "projected" not in temp["amount"]
    assert temp["amount"]["rank"] == 50
