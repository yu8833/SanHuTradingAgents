"""公式化硬打分单测：公式分计算 / 报告评分解析 / 偏差标注 / 质量门控降级。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/analysts/test_hard_score.py
"""

from __future__ import annotations

import sys
from unittest import mock

from tradingagents.agents.utils.hard_score import (
    _FUNDAMENTALS,
    _MARKET,
    compute_analyst_formula_scores,
    extract_report_score,
    formula_score_baseline_text,
    score_deviation_tag,
)
from tradingagents.agents.quality_gate import _hard_check_report

# 避免 tests/unit/tradingagents 目录缺失导致收集失败
sys.path.insert(0, "tests/unit")


# ---------------------------------------------------------------------------
# compute_analyst_formula_scores
# ---------------------------------------------------------------------------


def test_market_formula_score_from_signal_score():
    state = {"quick_analysis_result": {"signal_score": 78}}
    scores = compute_analyst_formula_scores(state, {})
    fs = scores[_MARKET]
    assert fs.available
    assert fs.score == 78
    assert fs.source == "quick_scan_signal_score"


def test_market_formula_unavailable_when_no_signal_score():
    scores = compute_analyst_formula_scores({}, {})
    fs = scores[_MARKET]
    assert not fs.available


def test_fundamentals_formula_score_from_tool_text():
    tool_data = {
        _FUNDAMENTALS: {
            "get_fundamentals": [
                "Name: XXX\nPE (TTM): 22.5\nPB: 3.2\nROE (%): 18.4\nNet Profit: 125000000.0"
            ]
        }
    }
    scores = compute_analyst_formula_scores({}, tool_data)
    fs = scores[_FUNDAMENTALS]
    assert fs.available
    assert fs.source == "fundamentals_static"
    # 基准 50 + ROE>=15(15) + 净利正(10) + PE 0-30(10) + PB 0-5(5) = 90
    assert fs.score == 90


def test_fundamentals_unavailable_without_parsable_data():
    tool_data = {_FUNDAMENTALS: {"get_fundamentals": ["无数据可用"]}}
    scores = compute_analyst_formula_scores({}, tool_data)
    fs = scores[_FUNDAMENTALS]
    assert not fs.available


def test_non_target_analysts_stay_llm_only():
    state = {"quick_analysis_result": {"signal_score": 60}}
    scores = compute_analyst_formula_scores(state, {})
    # 仅 market/fundamentals 有公式分条目；其余分析师不进入 dict
    assert set(scores.keys()) == {_MARKET, _FUNDAMENTALS}


# ---------------------------------------------------------------------------
# extract_report_score
# ---------------------------------------------------------------------------


def test_extract_report_score_market():
    report = "## 📊 技术面评分：82/100\n\n技术分析正文……"
    assert extract_report_score(report, _MARKET) == 82


def test_extract_report_score_fundamentals():
    report = "## 📈 基本面评分：55/100\n\n基本面正文……"
    assert extract_report_score(report, _FUNDAMENTALS) == 55


def test_extract_report_score_missing():
    assert extract_report_score("没有评分标题的报告", _MARKET) is None
    assert extract_report_score("", _MARKET) is None


# ---------------------------------------------------------------------------
# score_deviation_tag
# ---------------------------------------------------------------------------


def test_no_tag_when_within_threshold():
    assert score_deviation_tag(60, 65) == ""
    assert score_deviation_tag(60, 60) == ""


def test_tag_when_deviation_exceeds_threshold():
    tag = score_deviation_tag(60, 90)
    assert tag and "60" in tag and "90" in tag


def test_no_tag_when_unavailable_or_unparsed():
    assert score_deviation_tag(None, 90) == ""
    assert score_deviation_tag(60, None) == ""


def test_no_tag_when_report_justifies_deviation():
    report = "第一行评分：85/100（偏离公式分基线，因 MACD 金叉强势加速，详见下方分析）"
    assert score_deviation_tag(60, 85, report) == ""


# ---------------------------------------------------------------------------
# formula_score_baseline_text
# ---------------------------------------------------------------------------


def test_baseline_text_market_contains_number():
    text = formula_score_baseline_text(_MARKET, 75)
    assert "公式分基线" in text and "75" in text


def test_baseline_text_fundamentals_is_constraint():
    text = formula_score_baseline_text(_FUNDAMENTALS, None)
    assert "量化口径约束" in text


def test_baseline_text_other_empty():
    assert formula_score_baseline_text("news", None) == ""


# ---------------------------------------------------------------------------
# quality gate 降级
# ---------------------------------------------------------------------------


def test_quality_gate_downgrades_on_formula_deviation():
    formula_entry = {"available": True, "score": 60, "source": "quick_scan_signal_score"}
    report = (
        "## 📊 技术面评分：95/100\n\n"
        "充足正文" + "。" * 300 + "\n\n| 指标 | 值 |\n|---|---|\n| 收盘 | 10 |"
    )
    grade, detail = _hard_check_report(_MARKET, report, formula_entry)
    assert grade in ("B", "C")  # 有偏差时不应为 A
    assert "公式分偏差" in detail


def test_quality_gate_pass_without_formula_deviation():
    formula_entry = {"available": True, "score": 60, "source": "quick_scan_signal_score"}
    report = (
        "## 📊 技术面评分：65/100\n\n"
        "充足正文" + "。" * 300 + "\n\n| 指标 | 值 |\n|---|---|\n| 收盘 | 10 |"
    )
    grade, detail = _hard_check_report(_MARKET, report, formula_entry)
    assert grade == "A"
    assert "公式分偏差" not in detail


def test_quality_gate_no_suppression_when_justified():
    formula_entry = {"available": True, "score": 60, "source": "quick_scan_signal_score"}
    report = (
        "## 📊 技术面评分：95/100（偏离公式分基线，因放量突破）\n\n"
        "充足正文" + "。" * 300 + "\n\n| 指标 | 值 |\n|---|---|\n| 收盘 | 10 |"
    )
    grade, detail = _hard_check_report(_MARKET, report, formula_entry)
    assert "公式分偏差" not in detail