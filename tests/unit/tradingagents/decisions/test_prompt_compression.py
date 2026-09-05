"""Prompt 输入压缩（compact_markdown）单测。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/decisions/test_prompt_compression.py
"""

from __future__ import annotations

from tradingagents.agents.utils.prompt_compression import compact_markdown

LONG = "\n".join([
    "## 📊 技术面评分：82/100",
    "**评分解读**：80-100分代表技术面强势",
    "正文第一段 " + "x" * 300,
    "**止损位**：-5%",
    "**建议仓位**：3%",
    "正文第二段 " + "y" * 300,
    "**风险提示**：放量下跌关注",
    "## 结论",
    "综合看多",
])


def test_short_text_unchanged():
    assert compact_markdown("短暂文本", keep=700) == "短暂文本"
    assert compact_markdown("", keep=700) == ""


def test_compressed_keeps_score_and_key_lines():
    out = compact_markdown(LONG, keep=300)
    assert "技术面评分：82" in out
    assert "止损位" in out and "建议仓位" in out
    assert "风险提示" in out
    assert "已压缩" in out
    assert len(out) < len(LONG)


def test_compressed_keeps_tail_conclusion():
    out = compact_markdown(LONG, keep=300)
    assert "综合看多" in out


def test_long_report_budget():
    # keep 极小也必须有截断标记，且不能无限膨胀
    out = compact_markdown(LONG, keep=60)
    assert "已压缩" in out
    assert len(out) < len(LONG) * 0.6