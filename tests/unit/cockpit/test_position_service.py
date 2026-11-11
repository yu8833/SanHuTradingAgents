"""纪律持仓（position_service.evaluate_exit 纯函数）单元测试。

覆盖：假突破缓冲、-8% 止损边界、MA5 盘中预警/收盘离场、时间止损、T+1 降级。
"""
from app.services.cockpit.position_service import COCKPIT_EXIT_PARAMS, evaluate_exit

P = COCKPIT_EXIT_PARAMS
TRADE_DATE = "2026-11-10"


def _pos(**kw):
    base = {"buy_price": 10.0, "buy_date": "2026-11-01", "trigger_price": 10.5}
    base.update(kw)
    return base


class TestBasics:
    def test_no_price_returns_normal(self):
        r = evaluate_exit(_pos(), None, 10.0, TRADE_DATE, False)
        assert r["state"] == "normal"
        assert r["pnl_pct"] is None
        assert r["reasons"] == []

    def test_normal_hold(self):
        r = evaluate_exit(_pos(), 11.0, 10.8, TRADE_DATE, False)
        assert r["state"] == "normal"
        assert r["pnl_pct"] == 0.1
        assert r["holding_days"] == 9
        assert r["t1_locked"] is False
        assert r["stop_loss_line"] == round(10.0 * (1 - P["stop_loss_pct"]), 3)
        assert r["trailing_line"] == 10.8


class TestFalseBreakout:
    def test_exit_below_buffer(self):
        r = evaluate_exit(_pos(trigger_price=10.5), 10.2, None, TRADE_DATE, False)
        assert r["state"] == "exit"
        assert any("假突破" in x for x in r["reasons"])

    def test_boundary_exact_not_exit(self):
        """恰好等于触发价 98% 不触发（严格小于）。"""
        price = 10.0 * (1 - P["false_breakout_buffer"])
        r = evaluate_exit(_pos(trigger_price=10.0), price, None, TRADE_DATE, False)
        assert all("假突破" not in x for x in r["reasons"])

    def test_no_trigger_price_skips_check(self):
        r = evaluate_exit(_pos(trigger_price=None), 9.9, None, TRADE_DATE, False)
        assert all("假突破" not in x for x in r["reasons"])


class TestStopLoss:
    def test_exit_at_boundary(self):
        """浮盈恰达 -8% 触发止损（≤）。"""
        r = evaluate_exit(_pos(buy_price=100.0, trigger_price=None), 92.0, None, TRADE_DATE, False)
        assert r["state"] == "exit"
        assert any("止损" in x for x in r["reasons"])

    def test_no_exit_above_boundary(self):
        r = evaluate_exit(_pos(buy_price=100.0, trigger_price=None), 92.01, None, TRADE_DATE, False)
        assert r["state"] == "normal"


class TestMa5:
    def test_intraday_warn_only(self):
        """盘中跌破 MA5 → 预警（不被日内洗盘洗出）。"""
        r = evaluate_exit(_pos(trigger_price=None), 9.5, 9.6, TRADE_DATE, True)
        assert r["state"] == "warn"
        assert any("盘中预警" in x for x in r["reasons"])

    def test_close_confirm_exit(self):
        """非盘中（收盘确认）跌破 MA5 → 离场。"""
        r = evaluate_exit(_pos(trigger_price=None), 9.5, 9.6, TRADE_DATE, False)
        assert r["state"] == "exit"
        assert any("收盘跌破 MA5" in x for x in r["reasons"])


class TestTimeStop:
    def test_over_30_days_warns(self):
        r = evaluate_exit(_pos(buy_date="2026-09-30", trigger_price=None), 11.0, None, TRADE_DATE, False)
        assert r["holding_days"] == 41
        assert r["state"] == "warn"
        assert any("30" in x for x in r["reasons"])

    def test_exactly_30_days_quiet(self):
        r = evaluate_exit(_pos(buy_date="2026-10-11", trigger_price=None), 11.0, None, TRADE_DATE, False)
        assert r["holding_days"] == 30
        assert r["state"] == "normal"

    def test_bad_buy_date_defaults_zero(self):
        r = evaluate_exit(_pos(buy_date="", trigger_price=None), 11.0, None, TRADE_DATE, False)
        assert r["holding_days"] == 0
        assert r["t1_locked"] is False


class TestT1Demotion:
    def test_buy_day_exits_demoted_to_warn(self):
        """T+1：买入当日离场信号降级为预警，并标注次一交易日执行。"""
        r = evaluate_exit(_pos(buy_date=TRADE_DATE, trigger_price=10.5), 10.2, None, TRADE_DATE, False)
        assert r["t1_locked"] is True
        assert r["state"] == "warn"
        assert any("T+1" in x for x in r["reasons"])
        assert all("假突破" not in x or "T+1" in x for x in r["reasons"])

    def test_next_day_exits_restore(self):
        r = evaluate_exit(_pos(buy_date="2026-11-09", trigger_price=10.5), 10.2, None, TRADE_DATE, False)
        assert r["t1_locked"] is False
        assert r["state"] == "exit"
