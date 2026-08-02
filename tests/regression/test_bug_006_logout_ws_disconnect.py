"""
Bug-006 防回归测试：登出后 notifications WebSocket 未断开（前端）

根因：stores/notifications.ts 中 watch auth token 的逻辑只在 token 变为非空时 connect，
      当 token 变空（登出）时没有主动 close WebSocket，WS 因鉴权失效触发自动重连，
      进入空转重连循环，刷错误日志、耗 CPU/网络。

修复：watch 分支中 token 为空时 disconnectWebSocket()。
"""
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]

PROJECT_ROOT = Path(__file__).parent.parent.parent


def test_notifications_watch_disconnects_on_empty_token():
    """notifications store 中必须有 watch token，且 token 为空时断开 WS。"""
    fpath = PROJECT_ROOT / "frontend/src/stores/notifications.ts"
    assert fpath.exists(), "notifications store 不存在或路径变更"
    text = fpath.read_text(encoding="utf-8")

    # 1. 必须有 watch token 的逻辑
    # 匹配多种写法：watch(() => xxx.token, ...) 或 watch(token_ref, ...)
    has_watch = bool(re.search(r"watch\s*\(", text)) and "token" in text.lower()
    assert has_watch, (
        "notifications store 中没有 watch token 的逻辑，"
        "登出时不会主动断开 WebSocket（bug-006）"
    )

    # 2. 必须有 disconnect/close 函数
    has_disconnect = (
        "disconnectWebSocket" in text
        or "ws.value.close" in text
        or ".close(" in text
    )
    assert has_disconnect, (
        "notifications store 中没有 WebSocket close/disconnect 逻辑（bug-006）"
    )

    # 3. 关键：watch 回调中，token 为空时必须调用 disconnect/close
    # 找到 watch 块，检查内部是否有 !newToken/!token/else + disconnect/close
    watch_match = re.search(r"watch\s*\([^)]*token[^)]*,\s*\([^)]*\)\s*=>\s*\{", text)
    if not watch_match:
        # 也可能是 watch(() => store.token, (new, old) => { ... })
        watch_match = re.search(r"watch\s*\(\s*\(\)\s*=>\s*[^,]*token", text)

    assert watch_match, (
        "未找到 watch token 的回调函数，登出时无法触发断开逻辑（bug-006）"
    )

    # 从 watch 开始位置往后找 800 字符，检查是否有 disconnect/close 在 !token 分支
    start = watch_match.start()
    snippet = text[start:start + 800]

    has_empty_token_disconnect = bool(
        re.search(r"(!newToken|!token|===?\s*null|===?\s*['\"]['\"])", snippet)
    )
    has_disconnect_call = (
        "disconnectWebSocket" in snippet
        or "disconnect()" in snippet
        or ".close(" in snippet
    )

    assert has_empty_token_disconnect, (
        "watch token 回调中，没有 !newToken/!token 分支，"
        "登出时不会触发断开 WebSocket（bug-006）。"
    )
    assert has_disconnect_call, (
        "watch token 回调中，token 为空（登出）时没有调用 disconnect/close。"
        f" 检查片段: ...{snippet[max(0,snippet.find('disconnect')-50):snippet.find('disconnect')+100] if 'disconnect' in snippet else 'NO DISCONNECT FOUND'}..."
        " 这会导致 WS 因鉴权失效疯狂重连（bug-006）。"
    )
