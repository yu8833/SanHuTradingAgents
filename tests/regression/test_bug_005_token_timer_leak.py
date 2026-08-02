"""
Bug-005 防回归测试：token 刷新定时器泄漏（前端）

根因：utils/auth.ts setupTokenRefreshTimer() 内部调用 setInterval 但不返回/保存 timerId，
      auth store 在 clearAuthInfo 里无法清除旧定时器，每登录一次就多一个永久存活的 setInterval。

修复：setupTokenRefreshTimer 返回 timerId，store 新增 _tokenRefreshTimerId 管理生命周期，
      clearAuthInfo 时清除，新增 ensureTokenRefreshTimer 确保唯一。

本测试：静态 TS 代码扫描，确保定时器生命周期被正确管理。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_auth_util_returns_timer_id():
    """utils/auth.ts 中 setupTokenRefreshTimer 必须返回 timer id。"""
    fpath = PROJECT_ROOT / "frontend/src/utils/auth.ts"
    assert fpath.exists(), "auth.ts 不存在或路径变更"
    text = fpath.read_text(encoding="utf-8")

    # 找到 setupTokenRefreshTimer 定义位置，检查其后 1500 字符内有 setInterval + return
    idx = text.find("setupTokenRefreshTimer")
    assert idx >= 0, "未找到 setupTokenRefreshTimer 函数"

    snippet = text[idx:idx + 1500]
    assert "setInterval" in snippet, (
        "setupTokenRefreshTimer 函数中没有 setInterval，无法创建定时器"
    )
    assert "return" in snippet, (
        "setupTokenRefreshTimer 没有 return 语句，调用方无法拿到 timer id 清理（bug-005）"
    )


def test_auth_store_clears_timer_on_logout():
    """stores/auth.ts 中 clearAuthInfo 必须包含 clearInterval 清理逻辑。"""
    fpath = PROJECT_ROOT / "frontend/src/stores/auth.ts"
    assert fpath.exists(), "auth store 不存在或路径变更"
    text = fpath.read_text(encoding="utf-8")

    # 简化策略：整个文件中必须有 clearInterval 和 _tokenRefreshTimerId
    assert "clearInterval" in text, (
        "auth store 中没有 clearInterval，定时器无法被清理（bug-005）"
    )
    assert "_tokenRefreshTimerId" in text, (
        "auth store 中缺少 _tokenRefreshTimerId 字段，无法管理定时器生命周期"
    )

    # 检查 clearAuthInfo 函数附近有 clearInterval
    clear_match = re.search(r"clearAuthInfo[^{]*\{", text)
    if clear_match:
        start = clear_match.end()
        # 往后找 500 字符内的 clearInterval
        snippet = text[start:start + 500]
        assert "clearInterval" in snippet, (
            "clearAuthInfo 函数附近没有 clearInterval，登出时定时器不会被清理（bug-005）"
        )


def test_auth_store_has_ensure_timer_unique():
    """最佳实践：存在 ensureTokenRefreshTimer 或等价唯一性保护。"""
    fpath = PROJECT_ROOT / "frontend/src/stores/auth.ts"
    text = fpath.read_text(encoding="utf-8")
    has_timer_id_field = "_tokenRefreshTimerId" in text
    assert has_timer_id_field, (
        "auth store 中缺少 _tokenRefreshTimerId 等定时器状态字段，"
        "无法保证全局只创建一个 refresh 定时器。"
    )
