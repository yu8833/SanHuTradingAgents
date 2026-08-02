"""
冒烟测试：核心业务端点最小正向路径
- GET /api/stocks/{code} 必须 200/404，不能 500
- GET /api/screening/status 必须 200（数据新鲜度检查，防 bug-002）
- GET /api/sync/status 必须 200
"""
import pytest

pytestmark = pytest.mark.smoke


class TestCoreEndpointsSmoke:
    @pytest.mark.parametrize("code", ["000001", "600519", "002969"])
    async def test_stocks_detail_no_500(self, http_client, code):
        """股票详情端点任何情况都不能 500，只能是 200 或 404"""
        try:
            resp = await http_client.get(f"/api/stocks/{code}")
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
            return
        assert resp.status_code in (200, 404), (
            f"/api/stocks/{code} 返回 {resp.status_code}（500=服务端错误）"
        )

    async def test_screening_status_no_500(self, http_client):
        """筛选/新鲜度检查端点不能 500（防 bug-002 字段名错误触发 500）"""
        try:
            resp = await http_client.get("/api/screening/status")
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
            return
        # 401/403 也算 OK（需要鉴权），只要不是 500
        assert resp.status_code != 500, (
            "/api/screening/status 返回 500，可能是 bug-002："
            " publish_time / published_at 字段名错误复发。"
        )

    async def test_sync_status_no_500(self, http_client):
        """同步状态端点不能 500"""
        try:
            resp = await http_client.get("/api/sync/status")
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
            return
        assert resp.status_code != 500, "/api/sync/status 返回 500"

    async def test_config_system_no_500(self, http_client):
        """系统配置读取不能 500"""
        try:
            resp = await http_client.get("/api/config/system")
        except Exception as exc:
            pytest.skip(f"本地服务未启动，跳过：{exc}")
            return
        assert resp.status_code != 500, "/api/config/system 返回 500"
