"""simple_analysis_service 中文评级提取单测（防股票代码被误当评级）。

背景：free-text 决策标题形如 `# 最终交易决策：600519`，旧正则会把股票代码
当成评级（action 曾被解析成 "6005"）。本测试固化修复行为。

运行：pytest -o addopts="" -m "not integration" tests/unit/services/test_cn_rating_extract.py
"""

from __future__ import annotations

from app.services.simple_analysis_service import _extract_cn_rating, _normalize_cn_rating


def test_normalize_rating():
    assert _normalize_cn_rating("强烈买入") == "买入"
    assert _normalize_cn_rating("做多") == "买入"
    assert _normalize_cn_rating("增持") == "增持"
    assert _normalize_cn_rating("观望") == "持有"
    assert _normalize_cn_rating("强烈卖出") == "卖出"
    assert _normalize_cn_rating("6005") == ""  # 股票代码绝不是评级


def test_extract_from_bold_label_inline():
    # **评级：持有**（冒号在星号内）——旧正则曾在此漏匹配
    text = "## 最终交易决策：600519\n\n**评级：持有**\n正文……"
    assert _extract_cn_rating(text) == "持有"


def test_extract_from_bold_label_outside():
    # **投资评级：卖出** / **评级**：买入
    assert _extract_cn_rating("**投资评级：卖出**") == "卖出"
    assert _extract_cn_rating("**评级**：买入") == "买入"


def test_extract_from_decision_title_with_rating_word():
    assert _extract_cn_rating("交易方向：增持") == "增持"
    assert _extract_cn_rating("## 最终交易决策：买入") == "买入"


def test_extract_ignores_stock_code_in_title():
    # 标题仅含股票代码（无评级词）→ 不应误抓为评级
    assert _extract_cn_rating("# 最终交易决策：600519\n\n正文无评级") == ""


def test_extract_empty_input():
    assert _extract_cn_rating("") == ""