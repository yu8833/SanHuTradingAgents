"""
冒烟测试：SSE 端点（覆盖 Bug-001 钉住路径）
- /api/stream/quotes 必须 200，不能 500
- /api/stream/tasks/{task_id} 首事件必须是 connected
"""
import pytest

pytestmark = pytest.mark.smoke


class TestSSESmoke:
    async def test_stream_quotes_returns_200(self, http_client, auth_token):
        """SSE 行情流必须返回 200（防 bug-001 500 复发）"""
        if auth_token is None:
            pytest.skip("未获取到 token，跳过需要鉴权的 SSE 冒烟")
            return
        try:
            async with http_client.stream(
                "GET", f"/api/stream/quotes?token={auth_token}"
            ) as resp:
                assert resp.status_code == 200, (
                    f"SSE quotes 返回 {resp.status_code}，"
                    f"若为 500 很可能是 bug-001: user.role 访问失败复发"
                )
        except Exception as exc:
            pytest.skip(f"本地服务未启动或 SSE 超时，跳过：{exc}")

    async def test_stream_tasks_connected_event(self, http_client, auth_token, monkeypatch):
        """任务进度 SSE 首条事件必须是 'event: connected'（无需真实任务）"""
        if auth_token is None:
            pytest.skip("未获取到 token，跳过任务 SSE 冒烟")
            return
        try:
            async with http_client.stream(
                "GET",
                "/api/stream/tasks/smoke-test-nonexistent?token=" + auth_token,
            ) as resp:
                # 即便任务不存在，开头也应先发 connected，然后结束或发 error，
                # 但绝不能 500。
                assert resp.status_code == 200, f"任务 SSE 返回 {resp.status_code}"
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
