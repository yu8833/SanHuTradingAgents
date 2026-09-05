"""改造三消费端单测：结构化双写字段的提取与优先读取。

覆盖：
- portfolio_manager._flatten_decision_fields：从结构化对象落盘归一字段
- accuracy_guardian._structured_max_position：从 risk_control_object 读仓位上限
- memory.store_decision：rating 直传优先、缺省回退文本解析

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/decisions/test_structured_consumers.py
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

from tradingagents.agents.guardians.accuracy_guardian import AccuracyGuardian
from tradingagents.agents.managers.portfolio_manager import _flatten_decision_fields
from tradingagents.agents.utils.memory import TradingMemoryLog


def _rating(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


# ---------------------------------------------------------------------------
# _flatten_decision_fields
# ---------------------------------------------------------------------------


def test_flatten_extracts_rating_confidence_and_positions():
    risk_obj = SimpleNamespace(max_position_size=5.0, recommended_position_size=3.0)
    final_obj = SimpleNamespace(
        rating=_rating("Buy"), conviction_score=80,
    )
    out = _flatten_decision_fields(risk_obj, final_obj)
    assert out["final_rating"] == "买入"
    assert out["final_confidence"] == 0.8
    assert out["max_position_size"] == 5.0
    assert out["recommended_position_size"] == 3.0


def test_flatten_handles_none_objects():
    assert _flatten_decision_fields(None, None) == {}


def test_flatten_bad_conviction_skipped():
    final_obj = SimpleNamespace(rating=_rating("Sell"), conviction_score="oops")
    out = _flatten_decision_fields(None, final_obj)
    assert out["final_rating"] == "卖出"
    assert "final_confidence" not in out


# ---------------------------------------------------------------------------
# AccuracyGuardian._structured_max_position
# ---------------------------------------------------------------------------


def test_structured_max_position_reads_object():
    guardian = AccuracyGuardian()
    state = {"risk_control_object": {"max_position_size": 6.5}}
    assert guardian._structured_max_position(state) == 6.5


def test_structured_max_position_falls_back_when_missing():
    guardian = AccuracyGuardian()
    assert guardian._structured_max_position({}) is None
    assert guardian._structured_max_position({"risk_control_object": None}) is None
    assert guardian._structured_max_position({"risk_control_object": {"max_position_size": "bad"}}) is None


# ---------------------------------------------------------------------------
# TradingMemoryLog.store_decision rating 直传
# ---------------------------------------------------------------------------


def test_store_decision_uses_passed_rating(tmp_path):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "log.md")})
    log.store_decision("600000.SH", "2024-01-02", "# 最终交易决策\n**Rating**: Buy", rating="买入")
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "[2024-01-02 | 600000.SH | 买入 | pending]" in text


def test_store_decision_falls_back_to_text_rating(tmp_path):
    log = TradingMemoryLog({"memory_log_path": str(tmp_path / "log.md")})
    log.store_decision("600000.SH", "2024-01-02", "# 最终交易决策\n**Rating**: Sell", rating=None)
    text = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert "[2024-01-02 | 600000.SH | Sell | pending]" in text