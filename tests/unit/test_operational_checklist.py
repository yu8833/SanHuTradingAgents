"""操作检查清单解析加固的单元测试。

覆盖 build_operational_checklist 对 LLM 输出漂移的容错：
- 风险回报比乱码（"1不支持方向性加仓"）不再被当作有效值
- 点位缺失时价格类键拒绝非数值/超长说明文
- extracted 结构化字段兜底补全缺失点位
"""
from __future__ import annotations

from app.routers.reports import build_operational_checklist


def _call(reports: dict, extracted: dict | None = None):
    return build_operational_checklist(reports, extracted or {})


def test_risk_reward_mojibake_not_accepted():
    """风险回报比行若夹带说明文字（如"1不支持方向性加仓"），不应返回乱码。"""
    trader = (
        "# 交易员执行方案\n"
        "## 🎯 交易决策：持有\n"
        "**交易置信度**：55/100\n"
        "## 🎯 交易参数\n"
        "- **入场价**：28.4 元\n"
        "- **第一目标位**：29.3 元\n"
        "- **止损位**：26.10 元\n"
        "- **风险/回报比**：约1:1（当前中性持有，主要风险来自预期下修）\n"
        "- **建议仓位**：不超过2%\n"
        "- **预计持有周期**：1-3个月\n"
    )
    oc = _call({"trader_investment_plan": trader})
    rr = oc.get("风险回报比")
    assert rr is not None
    assert "不支持" not in rr
    assert "1:1" in rr


def test_price_field_rejects_long_sentence():
    """价格类字段(fork入价)若被抓到一整句说明文（含数字但超长），应判无效。"""
    trader = (
        "# 交易员执行方案\n"
        "## 🎯 交易参数\n"
        "- **入场价**：当前处于28.4元附近震荡，需等待放量突破后再考虑分批建仓，同时观察量能配合情况\n"
        "- **第一目标位**：29.3 元\n"
        "- **止损位**：26.10 元\n"
        "- **风险/回报比**：约1:2.0\n"
    )
    oc = _call({"trader_investment_plan": trader})
    entry = oc.get("入场")
    # 超长说明句应被拒绝；若 extracted 提供了理想买入则用其兜底，否则为 None（绝不返回长句）
    assert entry is None or len(str(entry)) <= 20


def test_extracted_fallback_fills_missing_entry():
    """入场缺失但 extracted 有支撑位时，用支撑位兜底。"""
    trader = (
        "# 交易员执行方案\n"
        "## 🎯 交易参数\n"
        "- **第一目标位**：29.3 元\n"
        "- **止损位**：26.10 元\n"
        "- **风险/回报比**：约1:2.0\n"
    )
    oc = _call(
        {"trader_investment_plan": trader},
        {"支撑位": "28.0 元", "止盈目标": "29.5 元", "止损价格": "26.1 元"},
    )
    assert oc.get("入场") == "28.0 元"


def test_negated_values_rejected():
    """明确否定的值（"不支持/不建议/观望"）不应作为有效点位。"""
    trader = (
        "# 交易员执行方案\n"
        "## 🎯 交易参数\n"
        "- **入场价**：不建议入场，观望\n"
        "- **第一目标位**：29.3 元\n"
        "- **止损位**：26.10 元\n"
        "- **风险/回报比**：约1:2.0\n"
    )
    oc = _call({"trader_investment_plan": trader})
    assert oc.get("入场") is None or "不" not in str(oc.get("入场"))


def test_clean_order_already_good_unchanged():
    """好报告（字段规范）的结果不应被加固逻辑破坏。"""
    trader = (
        "# 交易员执行方案\n"
        "## 🎯 交易参数\n"
        "- **入场价**：28.4 元\n"
        "- **第一目标位**：29.5 元\n"
        "- **第二目标位**：32.0 元\n"
        "- **止损位**：26.10 元\n"
        "- **风险/回报比**：约1:0.5\n"
        "- **建议仓位**：不超过5%\n"
        "- **预计持有周期**：1-3个月\n"
    )
    oc = _call({"trader_investment_plan": trader})
    assert oc.get("入场") == "28.4 元"
    assert oc.get("止损") == "26.10 元"
    assert oc.get("目标1") == "29.5 元"
    assert oc.get("目标2") == "32.0 元"
    assert "不支持" not in (oc.get("风险回报比") or "")