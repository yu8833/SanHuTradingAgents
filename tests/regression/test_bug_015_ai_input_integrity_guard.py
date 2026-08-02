"""
防回归测试：bug-015 AI 输入层数据校验拦截

根因：
    route_to_vendor 返回数据前无任何校验：
    - 日线数据可能过期（缓存未更新），AI 基于旧数据分析
    - 无数据哨兵未识别，AI 对着空结果推理
    - 异常值（PE=9999）未拦截，AI 基于脏数据得出结论
    仅回测层有数据契约，AI 输入层是空白。

修复：
    新增 tradingagents/dataflows/integrity_guard.py
    - L1 时效性：日线过期 → 触发即时补数 → 补数失败抛 DataStaleError 阻断
    - L2 完整性：无数据哨兵 → 标记 MISSING
    - L3 异常值：PE/PB 等超范围 → 标记 ABNORMAL
    route_to_vendor 返回前调用 check_integrity

测试要点：
    - 无数据哨兵识别 + MISSING 标记
    - 日线过期 + 补数失败 → DataStaleError 阻断
    - 日线过期 + 补数成功 → 返回新数据
    - 日线不过期 → 原样返回
    - fundamentals 异常值标记
    - route_to_vendor 已接入 guard
    - DataStaleError 不被 fallback 捕获
"""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ========================================================================
# Axiom 1：无数据哨兵识别 + MISSING 标记
# ========================================================================

@pytest.mark.regression
def test_bug_015_empty_result_marked_missing():
    """无数据哨兵应被识别并附加 MISSING 标记"""
    from tradingagents.dataflows.integrity_guard import check_integrity

    empty_results = [
        "No data found for A-stock '600379' between 2026-01-01 and 2026-07-29",
        "（无数据）",
        "Tushare 数据不可用: 600379",
        "No fundamentals data found for A-stock '600379'",
        "",
    ]
    for result in empty_results:
        checked = check_integrity(result, "get_stock_data", ("600379",))
        assert "数据缺失" in checked or "⚠️" in checked, f"无数据结果应附加缺失标记: {result!r}"


@pytest.mark.regression
def test_bug_015_normal_data_no_marker():
    """正常数据不应附加任何质量标记"""
    from tradingagents.dataflows.integrity_guard import check_integrity

    # 模拟正常的 fundamentals 返回（非 get_stock_data，不会做过期检查）
    normal = "=== 公司基本信息\nPE (TTM): 23.5\nPB: 3.2\n"
    checked = check_integrity(normal, "get_fundamentals", ("600379",))
    # 正常值不应有异常标记
    assert "数据异常值" not in checked, "正常 fundamentals 数据不应有异常标记"


# ========================================================================
# Axiom 2：日线过期 + 补数失败 → DataStaleError 阻断
# ========================================================================

@pytest.mark.regression
def test_bug_015_stale_daily_blocks_on_remediation_failure():
    """日线过期且补数失败应抛 DataStaleError"""
    from tradingagents.dataflows.integrity_guard import (
        check_integrity,
        DataStaleError,
    )

    # 模拟过期的日线数据（末行日期很旧）
    stale_data = (
        "# Stock data for 600379 (A-stock) from 2026-06-01 to 2026-07-29\n"
        "# Total records: 2\n"
        "# Data source: tushare\n"
        "# Data retrieved on: 2026-07-29 15:30:00\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2026-06-02,10.0,10.5,9.8,10.2,1000000\n"
        "2026-06-03,10.2,10.8,10.1,10.6,1200000\n"
    )

    # mock 补数失败
    with patch("tradingagents.dataflows.integrity_guard._trigger_remediation", return_value=False):
        # mock calc_stale_days 返回过期
        with patch("tradingagents.dataflows.integrity_guard._calc_stale_days_safe", return_value=5):
            with pytest.raises(DataStaleError) as exc_info:
                check_integrity(stale_data, "get_stock_data", ("600379", "2026-06-01", "2026-07-29"))

            assert "600379" in str(exc_info.value)
            assert "5" in str(exc_info.value) or "过期" in str(exc_info.value)


# ========================================================================
# Axiom 3：日线过期 + 补数成功 → 返回新数据
# ========================================================================

@pytest.mark.regression
def test_bug_015_stale_daily_remediated_returns_new_data():
    """日线过期但补数成功应返回新数据"""
    from tradingagents.dataflows.integrity_guard import check_integrity

    stale_data = (
        "# Stock data for 600379 (A-stock) from 2026-06-01 to 2026-07-29\n"
        "# Total records: 1\n"
        "# Data source: tushare\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2026-06-02,10.0,10.5,9.8,10.2,1000000\n"
    )
    fresh_data = (
        "# Stock data for 600379 (A-stock) from 2026-06-01 to 2026-07-29\n"
        "# Total records: 1\n"
        "# Data source: akshare\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2026-07-29,11.0,11.5,10.8,11.2,1500000\n"
    )

    # mock 补数成功
    with patch("tradingagents.dataflows.integrity_guard._trigger_remediation", return_value=True):
        # mock 重新获取数据返回新数据
        with patch("tradingagents.dataflows.interface._get_vendor_method") as mock_get:
            mock_func = MagicMock(return_value=fresh_data)
            mock_get.return_value = mock_func
            # mock 新数据不过期
            with patch("tradingagents.dataflows.integrity_guard._calc_stale_days_safe", side_effect=[5, 0]):
                result = check_integrity(stale_data, "get_stock_data", ("600379", "2026-06-01", "2026-07-29"))
                assert "2026-07-29" in result, "应返回补数后的新数据"


# ========================================================================
# Axiom 4：日线不过期 → 原样返回
# ========================================================================

@pytest.mark.regression
def test_bug_015_fresh_daily_passes_through():
    """日线数据不过期应原样返回（无标记）"""
    from tradingagents.dataflows.integrity_guard import check_integrity

    fresh_data = (
        "# Stock data for 600379 (A-stock) from 2026-06-01 to 2026-07-29\n"
        "# Total records: 1\n"
        "# Data source: tushare\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2026-07-29,10.0,10.5,9.8,10.2,1000000\n"
    )
    with patch("tradingagents.dataflows.integrity_guard._calc_stale_days_safe", return_value=0):
        result = check_integrity(fresh_data, "get_stock_data", ("600379",))
        assert result == fresh_data, "不过期的数据应原样返回"


# ========================================================================
# Axiom 5：fundamentals 异常值标记
# ========================================================================

@pytest.mark.regression
def test_bug_015_abnormal_fundamentals_marked():
    """fundamentals 异常值（PE=9999）应被标记"""
    from tradingagents.dataflows.integrity_guard import check_integrity

    # PE=9999 超出 data_validator 的 [-500, 1000] 范围
    abnormal_data = (
        "=== 公司基本面\n"
        "PE (TTM): 9999\n"
        "PB: 3.2\n"
        "ROE: 15.0\n"
    )
    result = check_integrity(abnormal_data, "get_fundamentals", ("600379",))
    assert "数据异常值" in result, "PE=9999 应被标记为异常"
    assert "9999" in result, "异常值应出现在标记中"


# ========================================================================
# Axiom 6：route_to_vendor 已接入 check_integrity
# ========================================================================

@pytest.mark.regression
def test_bug_015_route_to_vendor_calls_guard():
    """route_to_vendor 必须调用 check_integrity"""
    import inspect
    from tradingagents.dataflows import interface

    source = inspect.getsource(interface.route_to_vendor)
    assert "check_integrity" in source, "route_to_vendor 必须调用 check_integrity"
    assert "DataStaleError" in source, "route_to_vendor 必须处理 DataStaleError"


# ========================================================================
# Axiom 7：DataStaleError 不被 fallback 捕获
# ========================================================================

@pytest.mark.regression
def test_bug_015_data_stale_error_not_caught_by_fallback():
    """DataStaleError 应直接向上传播，不触发 fallback"""
    from tradingagents.dataflows.integrity_guard import DataStaleError

    # 验证 DataStaleError 是 Exception 子类
    assert issubclass(DataStaleError, Exception)

    # 验证 route_to_vendor 的 except 块会重新抛出 DataStaleError
    import inspect
    from tradingagents.dataflows import interface

    source = inspect.getsource(interface.route_to_vendor)
    # 确认有 isinstance(e, DataStaleError) 的 re-raise 逻辑
    assert "isinstance(e, DataStaleError)" in source, "route_to_vendor 必须对 DataStaleError 做 re-raise"


# ========================================================================
# Axiom 8：DataStaleError 消息包含可操作的提示
# ========================================================================

@pytest.mark.regression
def test_bug_015_error_message_actionable():
    """DataStaleError 消息应包含股票代码、过期天数和操作建议"""
    from tradingagents.dataflows.integrity_guard import DataStaleError

    err = DataStaleError("600379", 3, detail="测试")
    msg = str(err)
    assert "600379" in msg, "消息应包含股票代码"
    assert "3" in msg, "消息应包含过期天数"
    assert "补数" in msg or "同步" in msg, "消息应包含操作建议"
    assert "中止" in msg or "阻断" in msg, "消息应说明已中止分析"


# ========================================================================
# Axiom 9：CSV 末行日期提取正确
# ========================================================================

@pytest.mark.regression
def test_bug_015_extract_last_date_from_csv():
    """应正确从 CSV 末行提取日期"""
    from tradingagents.dataflows.integrity_guard import _extract_last_date_from_stock_data

    csv_data = (
        "# Stock data for 600379 (A-stock)\n"
        "# Total records: 3\n"
        "Date,Open,High,Low,Close,Volume\n"
        "2026-07-25,10.0,10.5,9.8,10.2,1000000\n"
        "2026-07-28,10.2,10.8,10.1,10.6,1200000\n"
        "2026-07-29,10.6,11.0,10.5,10.8,1100000\n"
    )
    date = _extract_last_date_from_stock_data(csv_data)
    assert date == "2026-07-29", f"应提取末行日期 2026-07-29, 实际: {date}"


@pytest.mark.regression
def test_bug_015_extract_date_empty_result():
    """空结果应返回 None"""
    from tradingagents.dataflows.integrity_guard import _extract_last_date_from_stock_data

    assert _extract_last_date_from_stock_data("") is None
    assert _extract_last_date_from_stock_data(None) is None
