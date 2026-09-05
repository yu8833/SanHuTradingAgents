"""Extract the 5-tier portfolio rating from the Portfolio Manager's decision.

The Portfolio Manager produces a typed ``PortfolioDecision`` via structured
output and renders it to markdown that always carries a ``**Rating**: X``
header (see :func:`tradingagents.agents.schemas.render_pm_decision`).  The
deterministic heuristic in :mod:`tradingagents.agents.utils.rating` is more
than sufficient to extract that rating; no extra LLM call is needed.

This module exists for backwards compatibility with callers that expect a
``SignalProcessor.process_signal(text)`` interface.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.utils.rating import parse_rating

# 结构化归一中文评级 → 标准 5-tier 英文（SignalProcessor 输出口径保持英文）。
_CN_TO_EN = {
    "买入": "Buy",
    "增持": "Overweight",
    "持有": "Hold",
    "减持": "Underweight",
    "卖出": "Sell",
}


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        # The LLM argument is accepted for backwards compatibility but no
        # longer used: the PM's structured output guarantees the rating is
        # parseable from the rendered markdown without a second LLM call.
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str, rating: Any = None) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell.

        rating: 结构化归一中文评级（来自 final_rating，如「买入」）优先直通；
            非中文评级/股票代码等任意其他值均回退对 full_signal 文本的解析，
            且与旧签名 process_signal(text, stock_symbol) 兼容。
        """
        if isinstance(rating, str):
            norm = _CN_TO_EN.get(rating.strip())
            if norm:
                return norm
        return parse_rating(full_signal)
