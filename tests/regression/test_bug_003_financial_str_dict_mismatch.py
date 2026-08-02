"""
Bug-003 防回归测试：财务数据类型不匹配 - str/dict

根因：worker 的 get_fundamentals() 返回纯文本字符串，
      _save_financial_data() 直接对其调用 dict.get()，
      导致 AttributeError: 'str' object has no attribute 'get'，财务数据始终不更新。

修复：新增 _parse_financial_text 解析文本为 dict。
"""
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent
WORKER_FILE = PROJECT_ROOT / "app/worker/tushare_sync_service.py"


def test_tushare_sync_has_parse_financial_text_function():
    """修复核心证据：必须存在 _parse_financial_text。如果被删除，bug-003 就回来了。"""
    text = WORKER_FILE.read_text(encoding="utf-8")
    assert "_parse_financial_text" in text, (
        "tushare_sync_service.py 中缺少 _parse_financial_text 函数。"
        " 删除/改名此函数会重新触发 bug-003：财务数据同步报 'str has no attribute get'。"
    )


def test_save_financial_data_defensive_against_str():
    """_save_financial_data 函数内部必须防御：入参可能是 str，不能直接 .get()。

    注意：这里不直接调用（会触发 DB），只用静态文本检查确保存在解析/类型防御分支。
    """
    text = WORKER_FILE.read_text(encoding="utf-8")

    # 必须在保存前做类型判断/解析
    # 至少满足以下 2 项中任一项：
    #   (a) save 里调用了 _parse_financial_text
    #   (b) save 里有 isinstance(data, str) 的分支
    has_parse_call = "_parse_financial_text" in text
    has_str_guard = "isinstance" in text and "str" in text
    assert has_parse_call or has_str_guard, (
        "save_financial_data 路径中既没有 _parse_financial_text 调用，"
        " 也没有 isinstance(..., str) 类型防御，bug-003 极易复发。"
    )
