"""当日交易计划（P2）单元测试。

对应设计文档《第六章·交易工具与日常流程》§4 缺口2：
  - 计划方向/状态常量
  - 价格触达判断：买入=回落至触发价以下；卖出=涨至触发价以上
"""

from __future__ import annotations

import asyncio

from app.services import plan_service as ps


class TestConstants:
    def test_directions(self):
        assert ps.DIRECTION_BUY == "buy"
        assert ps.DIRECTION_SELL == "sell"

    def test_status_labels(self):
        assert ps._STATUS_LABELS["pending"] == "待执行"
        assert ps._STATUS_LABELS["executed"] == "已执行"
        assert ps._STATUS_LABELS["cancelled"] == "已取消"


class TestAutoExecuteStopLossDecisions:
    """止损自动执行（A）：触发判定 —— 纯决策分支，不触库。

    跌破止损位 → 自动卖出；但未破位 / 无有效价 / 无持仓 / 当日买入(T+1) 均不得卖出。
    """

    @staticmethod
    def _run(pos: dict, price: float) -> dict:
        return asyncio.run(ps.auto_execute_stop_loss("u1", pos, price))

    def test_invalid_position(self):
        assert self._run({"code": "", "quantity": 0, "stop_loss_price": 0}, 10.0)["reason"] == "invalid_position"
        assert self._run({"code": "600000", "quantity": 100, "stop_loss_price": 0}, 10.0)["reason"] == "invalid_position"
        assert self._run({"code": "600000", "quantity": 0, "stop_loss_price": 9.0}, 10.0)["reason"] == "invalid_position"

    def test_no_price_never_sells(self):
        pos = {"code": "600000", "quantity": 100, "stop_loss_price": 10.0, "buy_date": "2026-09-01"}
        assert self._run(pos, None)["reason"] == "no_price"
        assert self._run(pos, 0.0)["reason"] == "no_price"

    def test_not_breached_never_sells(self):
        pos = {"code": "600000", "quantity": 100, "stop_loss_price": 10.0, "buy_date": "2026-09-01"}
        assert self._run(pos, 10.5)["reason"] == "not_breached"
        assert self._run(pos, 100.0)["reason"] == "not_breached"

    def test_t_plus_1_never_sells(self):
        """当日买入（A股 T+1）即使跌破止损位也不得卖出。"""
        from app.utils.timezone import now_tz
        pos = {"code": "600000", "quantity": 100, "stop_loss_price": 10.0,
               "buy_date": now_tz().strftime("%Y-%m-%d")}
        assert self._run(pos, 9.5)["reason"] == "t_plus_1"


class TestCheckTriggered:
    def test_buy_below_trigger(self):
        """买入：现价 <= 触发价 → 可执行。"""
        assert ps._check_triggered("buy", 20.0, 19.5) is True
        assert ps._check_triggered("buy", 20.0, 20.0) is True

    def test_buy_above_trigger(self):
        assert ps._check_triggered("buy", 20.0, 20.5) is False

    def test_sell_above_trigger(self):
        """卖出：现价 >= 触发价 → 可执行。"""
        assert ps._check_triggered("sell", 22.0, 22.3) is True
        assert ps._check_triggered("sell", 22.0, 22.0) is True

    def test_sell_below_trigger(self):
        assert ps._check_triggered("sell", 22.0, 21.5) is False

    def test_missing_price(self):
        assert ps._check_triggered("buy", 20.0, None) is False
        assert ps._check_triggered("buy", None, 20.0) is False

    def test_invalid_price(self):
        assert ps._check_triggered("buy", "abc", 20.0) is False
