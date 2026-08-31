"""当日交易计划（P2）单元测试。

对应设计文档《第六章·交易工具与日常流程》§4 缺口2：
  - 计划方向/状态常量
  - 价格触达判断：买入=回落至触发价以下；卖出=涨至触发价以上
"""

from __future__ import annotations

from app.services import plan_service as ps


class TestConstants:
    def test_directions(self):
        assert ps.DIRECTION_BUY == "buy"
        assert ps.DIRECTION_SELL == "sell"

    def test_status_labels(self):
        assert ps._STATUS_LABELS["pending"] == "待执行"
        assert ps._STATUS_LABELS["executed"] == "已执行"
        assert ps._STATUS_LABELS["cancelled"] == "已取消"


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
