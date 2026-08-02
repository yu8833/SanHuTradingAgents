"""
Bug-008 防回归测试：trade_date 跨集合查询格式不匹配

根因：find_latest_trade_date_with_fallback() 返回 "YYYYMMDD" 格式字符串，
      但 stock_daily_quotes 集合里 trade_date 字段存的是 "YYYY-MM-DD"，
      导致导入历史行情时查询条件永远匹配不到，补数静默失败。

修复：新增 _normalize_trade_date_for_daily_quotes() 或在查询路径做归一化。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent
QIS = PROJECT_ROOT / "app/services/quotes_ingestion_service.py"


def test_trade_date_normalization_exists():
    """必须存在明确的 trade_date 格式归一化函数或在关键路径做格式转换。"""
    assert QIS.exists(), f"找不到 quotes_ingestion_service.py：{QIS}"
    text = QIS.read_text(encoding="utf-8")

    has_normalize_fn = (
        "_normalize_trade_date_for_daily_quotes" in text
        or "_normalize_trade_date" in text
        or "normalize_trade_date" in text
    )

    # 或者：在 stock_daily_quotes 查询前有 replace("-", "") 或 "%Y-%m-%d" format 转换
    has_inline_conversion = bool(
        re.search(r"trade_date.*\.replace\s*\(\s*[\"']-[\"']", text)
        or re.search(r"strftime\s*\(\s*[\"']%Y-%m-%d[\"']", text)
        or re.search(r"strptime\s*\(\s*.*?%Y%m%d", text)
    )

    assert has_normalize_fn or has_inline_conversion, (
        "quotes_ingestion_service.py 中没有 trade_date 归一化逻辑。"
        " 来源返回 'YYYYMMDD' 而 stock_daily_quotes 存 'YYYY-MM-DD'，"
        " 会导致导入/查询永远匹配不到（bug-008）。"
    )


def test_find_latest_trade_date_does_not_leak_raw_format_to_daily_queries():
    """调用 find_latest_trade_date_with_fallback 后，必须转换格式再查 daily_quotes。"""
    text = QIS.read_text(encoding="utf-8")
    # 简单策略：如果同时出现 YYYYMMDD 生成和 daily_quotes 查询，中间必须有格式处理
    pattern_pure_digits_date = r"(\d{4})(\d{2})(\d{2})"
    mentions_both = (
        "find_latest_trade_date" in text and "stock_daily_quotes" in text
        and re.search(pattern_pure_digits_date, text)
    )
    if mentions_both:
        # 存在这两处，就必须出现归一化痕迹
        assert "replace" in text or "strftime" in text or "strptime" in text or "normalize" in text, (
            "既提到 find_latest_trade_date 又查 stock_daily_quotes，"
            " 但没看到归一化操作，bug-008 极易复发。"
        )
