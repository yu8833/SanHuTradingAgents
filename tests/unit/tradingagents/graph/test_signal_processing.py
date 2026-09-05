"""SignalProcessor 结构化评级直通与旧签名兼容性单测。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/graph/test_signal_processing.py
"""

from __future__ import annotations

from tradingagents.graph.signal_processing import SignalProcessor


def _signal(text: str) -> str:
    return f"# 最终交易决策\n\n**Rating**: {text}\n\n正文……"


def test_structured_cn_rating_passthrough():
    processor = SignalProcessor()
    assert processor.process_signal("任何文本", "买入") == "Buy"
    assert processor.process_signal("任何文本", "卖出") == "Sell"
    assert processor.process_signal("任何文本", "持有") == "Hold"


def test_non_rating_arg_falls_back_to_text():
    processor = SignalProcessor()
    # 旧签名 process_signal(text, stock_symbol)：第二参数是股票代码，必须回退文本解析
    assert processor.process_signal(_signal("Sell"), "600000") == "Sell"
    assert processor.process_signal(_signal("Overweight")) == "Overweight"
    assert processor.process_signal("无评级文本", None) == "Hold"  # 默认值


def test_unknown_cn_value_falls_back():
    processor = SignalProcessor()
    # 中文但不在 5 档映射里的值（如字段漂移）→ 回退文本解析
    assert processor.process_signal(_signal("Buy"), "不清楚的评级") == "Buy"