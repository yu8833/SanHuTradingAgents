"""
Bug-007 防回归测试：vibe.ts chatStream localStorage token key 错误

根因：chatStream 里写死 localStorage.getItem('token')，而全站统一使用 'auth-token'，
      导致 AI 对话接口拿不到 token，持续 401。

修复：优先从 auth store 取 token，fallback 到 localStorage.getItem('auth-token')。
"""
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent
VIBE_TS = PROJECT_ROOT / "frontend/src/api/vibe.ts"


def test_vibe_chatstream_does_not_use_wrong_key():
    """vibe.ts 中 chatStream 函数不能再出现 localStorage.getItem('token')。

    任何对 key='token' 的 getItem 都是可疑的，全站标准 key 是 'auth-token'。
    """
    text = VIBE_TS.read_text(encoding="utf-8")
    # 允许出现在注释里，代码里的字面量必须禁止
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith(("//", "/*", "*")):
            continue
        if "getItem('token')" in line or 'getItem("token")' in line:
            pytest.fail(
                f"vibe.ts:{i} 仍使用 localStorage.getItem('token') 获取 token，"
                " 全站 key 是 'auth-token'（bug-007 会复发）。 行内容: " + stripped
            )


def test_vibe_chatstream_prefer_store_or_auth_token_key():
    """vibe.ts 中 chatStream 应读取 'auth-token' 或直接从 auth store 拿 token。"""
    text = VIBE_TS.read_text(encoding="utf-8")
    use_store = "useAuthStore" in text or "authStore" in text or "auth store" in text.lower()
    use_correct_key = "auth-token" in text
    assert use_store or use_correct_key, (
        "vibe.ts 既没有从 auth store 取 token，也没有读 'auth-token'，"
        " AI 对话可能无法鉴权。"
    )
