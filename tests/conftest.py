"""
TradingAgents-CN 测试共享 fixtures

提供：
- project_root / base_url：路径与基准 URL
- auth_token：登录态
- http_client：已带 token 的异步 HTTP 客户端
- mock_redis / mock_mongo：单元测试用的轻量 fake
- fastapi_testclient：基于 TestClient 的 ASGI 同步客户端
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from collections.abc import AsyncGenerator, Generator
from typing import TYPE_CHECKING

import pytest

# 类型引用，避免循环导入 + 让 ruff 识别 F821 错误
if TYPE_CHECKING:
    import httpx
    from fastapi.testclient import TestClient

# 将项目根目录加入 sys.path，确保 app 包可导入
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ==========================================================
# 基础路径 / 环境
# ==========================================================
@pytest.fixture(scope="session")
def project_root() -> str:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def base_url() -> str:
    """测试目标地址；CI/本地用默认 8001，远端可通过 TEST_BASE_URL 覆盖。"""
    return os.environ.get("TEST_BASE_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def admin_username() -> str:
    return os.environ.get("TEST_ADMIN_USER", "admin")


@pytest.fixture(scope="session")
def admin_password() -> str:
    return os.environ.get("TEST_ADMIN_PASS", "admin123")


# ==========================================================
# 登录 token（session 级缓存）
# ==========================================================
@pytest.fixture(scope="session")
async def auth_token(base_url: str, admin_username: str, admin_password: str) -> str | None:
    """
    尝试登录获取 access_token；失败返回 None（测试应自行判断是否跳过。
    单元测试/契约测试不依赖真实 token。"""
    try:
        import httpx
    except ImportError:
        return None
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=15.0, verify=False) as c:
            resp = await c.post(
                "/api/auth/login",
                json={"username": admin_username, "password": admin_password},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("access_token")
    except Exception:
        return None
    return None


# ==========================================================
# 异步 HTTP 客户端（带 token）
# ==========================================================
@pytest.fixture(scope="session")
async def http_client(
    base_url: str, auth_token: str | None
) -> AsyncGenerator[httpx.AsyncClient, None]:
    import httpx

    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    client = httpx.AsyncClient(
        base_url=base_url,
        timeout=30.0,
        verify=False,
        headers=headers,
    )
    try:
        yield client
    finally:
        # 容忍 event loop 已关闭的情况（session 级 fixture teardown 时常见）
        with contextlib.suppress(RuntimeError):
            await client.aclose()


# ==========================================================
# FastAPI TestClient（本地 ASGI，不需要启服务，适合冒烟快速路径）
# ==========================================================
@pytest.fixture(scope="module")
def fastapi_app():
    """懒加载 FastAPI app，失败则跳过该 module。"""
    try:
        from app.main import app
        return app
    except Exception as exc:
        pytest.skip(f"无法加载 FastAPI app: {exc}")


@pytest.fixture(scope="module")
def fastapi_testclient(fastapi_app) -> Generator[TestClient, None, None]:
    from fastapi.testclient import TestClient
    with TestClient(fastapi_app) as client:
        yield client


# ==========================================================
# Mock helpers（简单版 Redis / Mongo 用于单元测试
# ==========================================================
class FakeRedis:
    """最小内存版 Redis（只实现最常用的 set/get/exists/delete，用于 mock"""

    def __init__(self):
        self._d = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self._d:
            return False
        self._d[key] = value
        return True

    async def aget(self, key):
        return self._d.get(key)

    get = aget

    def exists(self, *keys):
        return sum(1 for k in keys if k in self._d)

    def delete(self, *keys):
        n = 0
        for k in keys:
            if k in self._d:
                del self._d[k]
                n += 1
        return n

    def close(self):
        pass

    def pubsub(self):
        return FakePubSub()


class FakePubSub:
    async def subscribe(self, *channels):
        return None

    async def get_message(self, ignore_subscribe_messages=True):
        await asyncio.sleep(0)
        return None

    async def unsubscribe(self, *channels):
        return None

    async def close(self):
        return None


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
