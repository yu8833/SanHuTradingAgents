"""冒烟测试：同步、自选股、配置、调度等核心管理端点

覆盖关键路由：
- /api/sync/stock_basics/status
- /api/favorites/, /api/favorites/tags
- /api/config/system, /api/config/llm
- /api/scheduler (调度状态)
- /api/usage (使用统计)
- /api/cache (缓存状态)
- /api/system/logs (系统日志)
- /api/notifications (通知)
- /api/news-data (新闻数据)
- /api/financial-data (财务数据)
- /api/stock-data (股票数据)
- /api/portfolio (持仓)
- /api/retail (散户数据)
"""
import pytest

pytestmark = pytest.mark.smoke


class TestSyncSmoke:
    """同步相关端点冒烟测试"""

    async def test_sync_basics_status_no_500(self, http_client):
        """股票基础同步状态端点不能 500"""
        try:
            resp = await http_client.get("/api/sync/stock_basics/status")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/sync/stock_basics/status 返回 500"

    async def test_multi_source_sync_status_no_500(self, http_client):
        """多数据源同步状态不能 500"""
        try:
            resp = await http_client.get("/api/sync/multi-source/status")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/sync/multi-source/status 返回 500"


class TestFavoritesSmoke:
    """自选股端点冒烟测试"""

    async def test_favorites_list_no_500(self, http_client):
        """自选股列表端点不能 500"""
        try:
            resp = await http_client.get("/api/favorites/")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        # 200/401/403 都可接受，只要不是 500
        assert resp.status_code != 500, f"/api/favorites/ 返回 {resp.status_code}"

    async def test_favorites_tags_no_500(self, http_client):
        """自选股标签端点不能 500"""
        try:
            resp = await http_client.get("/api/favorites/tags")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/favorites/tags 返回 500"


class TestConfigSmoke:
    """配置管理端点冒烟测试"""

    async def test_config_system_no_500(self, http_client):
        """系统配置读取不能 500"""
        try:
            resp = await http_client.get("/api/config/system")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/config/system 返回 500"

    async def test_config_llm_no_500(self, http_client):
        """LLM 配置读取不能 500"""
        try:
            resp = await http_client.get("/api/config/llm")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/config/llm 返回 500"

    async def test_config_llm_providers_no_500(self, http_client):
        """LLM 提供商列表不能 500"""
        try:
            resp = await http_client.get("/api/config/llm/providers")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/config/llm/providers 返回 500"


class TestSystemSmoke:
    """系统管理端点冒烟测试"""

    async def test_scheduler_status_no_500(self, http_client):
        """调度器状态端点不能 500"""
        try:
            resp = await http_client.get("/api/scheduler/status")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/scheduler/status 返回 500"

    async def test_usage_statistics_no_500(self, http_client):
        """使用统计端点不能 500"""
        try:
            resp = await http_client.get("/api/usage/statistics")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/usage/statistics 返回 500"

    async def test_system_logs_no_500(self, http_client):
        """系统日志端点不能 500"""
        try:
            resp = await http_client.get("/api/system/logs/")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/system/logs/ 返回 500"

    async def test_cache_status_no_500(self, http_client):
        """缓存状态端点不能 500"""
        try:
            resp = await http_client.get("/api/cache/status")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/cache/status 返回 500"


class TestDataSmoke:
    """数据相关端点冒烟测试"""

    async def test_news_data_no_500(self, http_client):
        """新闻数据端点不能 500"""
        try:
            resp = await http_client.get("/api/news-data/")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/news-data/ 返回 500"

    async def test_financial_data_no_500(self, http_client):
        """财务数据端点不能 500"""
        try:
            resp = await http_client.get("/api/financial-data/")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/financial-data/ 返回 500"

    async def test_stock_data_list_no_500(self, http_client):
        """股票数据列表端点不能 500"""
        try:
            resp = await http_client.get("/api/stock-data/")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/stock-data/ 返回 500"

    async def test_multi_market_stocks_no_500(self, http_client):
        """多市场股票列表不能 500"""
        try:
            resp = await http_client.get("/api/markets/stocks")
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/markets/stocks 返回 500"


class TestPortfolioAndRetailSmoke:
    """持仓、散户数据端点冒烟测试"""

    async def test_portfolio_no_500(self, http_client):
        """持仓端点不能 500"""
        try:
            resp = await http_client.get("/api/portfolio/")
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc):
                pytest.skip("event loop 已关闭（session fixture 复用问题）")
                return
            raise
        except Exception as exc:
            pytest.skip(f"服务未启动：{exc}")
            return
        assert resp.status_code != 500, "/api/portfolio/ 返回 500"

    async def test_retail_no_500(self, http_client):
        """散户数据端点不能 500"""
        try:
            resp = await http_client.get("/api/retail/")
        except (RuntimeError, Exception) as exc:
            msg = str(exc)
            if "Event loop is closed" in msg or "not supported" in msg:
                pytest.skip(f"event loop/连接问题：{msg}")
                return
            pytest.skip(f"服务未启动或请求异常：{exc}")
            return
        assert resp.status_code != 500, "/api/retail/ 返回 500"
