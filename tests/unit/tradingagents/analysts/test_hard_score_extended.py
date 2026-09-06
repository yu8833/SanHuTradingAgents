"""公式化硬打分扩展单测：news / hot_money / social / lockup 四位分析师的确定性公式分。

运行：pytest -o addopts="" -m "not integration" tests/unit/tradingagents/analysts/test_hard_score_extended.py
"""

from __future__ import annotations

import sys

from tradingagents.agents.utils.hard_score import (
    _HOT_MONEY,
    _LOCKUP,
    _NEWS,
    _POLICY,
    _SOCIAL,
    compute_analyst_formula_scores,
    extract_report_score,
    formula_score_baseline_text,
)

# 避免 tests/unit/tradingagents 目录缺失导致收集失败
sys.path.insert(0, "tests/unit")


# ---------------------------------------------------------------------------
# news（消息面：get_risk_scan 风险安全分）
# ---------------------------------------------------------------------------


def test_news_formula_from_risk_scan_safety():
    tool_data = {
        _NEWS: {
            "get_risk_scan": [
                "# 通达信风险扫描 | 000001 | 2026-09-06\n"
                "## 风险概览\n"
                "- **风险项数**: 🔴 2\n"
                "- **风险安全分**: 90/100（分数越高越安全）"
            ]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_NEWS]
    assert fs.available
    assert fs.source == "risk_scan_safety"
    # 50 + (90-50)*0.8 = 82
    assert fs.score == 82


def test_news_formula_low_safety_scores_low():
    tool_data = {
        _NEWS: {
            "get_risk_scan": ["- **风险安全分**: 20/100"]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_NEWS]
    assert fs.available
    # 50 + (20-50)*0.8 = 26
    assert fs.score == 26


def test_news_formula_unavailable_without_safety():
    tool_data = {_NEWS: {"get_risk_scan": ["暂无风险数据"]}}
    fs = compute_analyst_formula_scores({}, tool_data)[_NEWS]
    assert not fs.available


# ---------------------------------------------------------------------------
# hot_money（资金面：主力净流入 + 北向 + 龙虎榜）
# ---------------------------------------------------------------------------


def test_hot_money_formula_positive_flows():
    tool_data = {
        _HOT_MONEY: {
            "get_fund_flow": [
                "# 资金流向\nClose: 主力净流入=8500万元\nSignal: Net main force INFLOW (bullish)"
            ],
            "get_northbound_flow": [
                "Close: HGT(沪股通)=12.30亿 SGT(深股通)=5.60亿 Total=17.90亿\n"
                "Signal: Net northbound INFLOW (bullish)"
            ],
            "get_dragon_tiger_board": [
                "# 龙虎榜数据\n## 上榜记录 (3 次)\n  2026-09-04 | 日涨幅偏离值达7% | 1234 | 8.20%"
            ],
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_HOT_MONEY]
    assert fs.available
    # 50 + 15（主力流入）+ 10（北向流入）+ 5（龙虎榜）= 80
    assert fs.score == 80


def test_hot_money_formula_negative_flows():
    tool_data = {
        _HOT_MONEY: {
            "get_fund_flow": ["Close: 主力净流入=-3200万元"],
            "get_northbound_flow": ["Signal: Net northbound OUTFLOW (bearish)"],
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_HOT_MONEY]
    assert fs.available
    # 50 - 15 - 10 = 25
    assert fs.score == 25


def test_hot_money_formula_unavailable_without_flow_data():
    tool_data = {_HOT_MONEY: {"get_stock_data": ["# K线数据"]}}
    fs = compute_analyst_formula_scores({}, tool_data)[_HOT_MONEY]
    assert not fs.available


# ---------------------------------------------------------------------------
# social（情绪面：主力方向 + 股东户数变化）
# ---------------------------------------------------------------------------


def test_social_formula_positive_sentiment():
    tool_data = {
        _SOCIAL: {
            "get_fund_flow": ["Close: 主力净流入=6000万元"],
            "get_shareholder_concentration": [
                "## 筹码集中度分析\n📈 信号: 股东户数显著下降 → 筹码正在集中，可能有主力/机构在吸筹（看多信号）"
            ],
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_SOCIAL]
    assert fs.available
    # 50 + 12 + 8 = 70
    assert fs.score == 70


def test_social_formula_negative_sentiment():
    tool_data = {
        _SOCIAL: {
            "get_fund_flow": ["Close: 主力净流入=-2000万元"],
            "get_shareholder_concentration": [
                "📉 信号: 股东户数显著增加 → 筹码正在分散，可能主力在派发给散户（看空信号）"
            ],
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_SOCIAL]
    assert fs.available
    # 50 - 12 - 8 = 30
    assert fs.score == 30


def test_social_formula_neutral_holder_change():
    tool_data = {
        _SOCIAL: {
            "get_shareholder_concentration": ["📊 信号: 股东户数变化不大 → 筹码集中度稳定"]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_SOCIAL]
    assert fs.available
    # 无主力数据但股东户数信号命中：50 + 0 = 50
    assert fs.score == 50


def test_social_formula_unavailable_without_signals():
    tool_data = {_SOCIAL: {"get_news": ["# 新闻"]}}
    fs = compute_analyst_formula_scores({}, tool_data)[_SOCIAL]
    assert not fs.available


# ---------------------------------------------------------------------------
# lockup（解禁面：待解禁日历）
# ---------------------------------------------------------------------------


def _lockup_tool_output(trade_date: str, future_rows: list[str] | None) -> str:
    lines = [f"# 限售解禁日历 | 000001 | {trade_date}", "", "## 个股解禁记录 (共 2 批)"]
    lines.append("  2020-01-10 | 首发原股东限售 | 数量 1000 | 占比 5.0%")
    if future_rows is None:
        lines.append("")
        lines.append("## 未来 90 天待解禁")
        lines.append("  2026-10-01 | 首发原股东限售 | 数量 5000 | 占比 15.0%")
    else:
        lines.append("")
        if not future_rows:
            lines.append("未来 90 天无待解禁。")
        else:
            lines.append("## 未来 90 天待解禁")
            lines.extend(f"  {r}" for r in future_rows)
    return "\n".join(lines)


def test_lockup_formula_unlock_within_30_days():
    tool_data = {
        _LOCKUP: {
            "get_lockup_expiry": [_lockup_tool_output("2026-09-06", ["2026-09-20 | 定增限售 | 数量 3000 | 占比 8.0%"])]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_LOCKUP]
    assert fs.available
    # 14 天内解禁：50 - 25 = 25
    assert fs.score == 25


def test_lockup_formula_unlock_within_90_days():
    tool_data = {
        _LOCKUP: {
            "get_lockup_expiry": [_lockup_tool_output("2026-09-06", ["2026-11-01 | 股权激励限售 | 数量 1000 | 占比 2.0%"])]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_LOCKUP]
    assert fs.available
    # 56 天后解禁：50 - 10 = 40
    assert fs.score == 40


def test_lockup_formula_no_upcoming_unlock():
    tool_data = {
        _LOCKUP: {
            "get_lockup_expiry": [_lockup_tool_output("2026-09-06", [])]
        }
    }
    fs = compute_analyst_formula_scores({}, tool_data)[_LOCKUP]
    assert fs.available
    # 无待解禁：50 + 10 = 60
    assert fs.score == 60


def test_lockup_formula_unavailable_without_data():
    tool_data = {_LOCKUP: {"get_lockup_expiry": ["解禁日历查询失败: timeout"]}}
    fs = compute_analyst_formula_scores({}, tool_data)[_LOCKUP]
    assert not fs.available


# ---------------------------------------------------------------------------
# extract_report_score：新分析师报告标题解析
# ---------------------------------------------------------------------------


def test_extract_report_score_new_analysts():
    assert extract_report_score("## 📰 消息面评分：70/100\n正文", _NEWS) == 70
    assert extract_report_score("## 💰 资金面评分：45/100\n正文", _HOT_MONEY) == 45
    assert extract_report_score("## 💭 情绪面评分：55/100\n正文", _SOCIAL) == 55
    assert extract_report_score("## 🔓 解禁面评分：35/100\n正文", _LOCKUP) == 35


# ---------------------------------------------------------------------------
# formula_score_baseline_text
# ---------------------------------------------------------------------------


def test_baseline_text_new_analysts_numeric_when_formula_available():
    for analyst_type in (_NEWS, _HOT_MONEY, _SOCIAL, _LOCKUP):
        text = formula_score_baseline_text(analyst_type, 65)
        assert "公式分基线" in text and "65" in text


def test_baseline_text_new_analysts_constraint_when_prompt_phase():
    for analyst_type in (_NEWS, _HOT_MONEY, _SOCIAL, _LOCKUP):
        text = formula_score_baseline_text(analyst_type, None)
        assert "量化口径约束" in text


def test_baseline_text_policy_empty():
    assert formula_score_baseline_text(_POLICY, None) == ""
