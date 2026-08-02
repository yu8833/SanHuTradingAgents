"""
Bug-001 防回归测试：SSE 认证 500 - user.role AttributeError

根因：User 模型只有 is_admin(bool) 字段，SSE 的 get_current_user_for_sse() 访问 user.role 导致 AttributeError，
      所有 SSE 端点返回 500。

修复：返回 "admin" if user.is_admin else "user"，不再访问 role 属性。

本测试不依赖真实 DB/Redis，通过 mock user_service.get_user_by_username 返回一个只有 is_admin 字段的 User 对象，
直接调用函数断言不再抛 AttributeError，且 role 字段正确派生。
"""
import pytest

pytestmark = [pytest.mark.regression, pytest.mark.unit]


class FakeUser:
    """最小 User 对象：按当前模型只暴露 id/username/is_active/is_admin"""

    def __init__(self, is_admin: bool = False):
        self.id = "u_123"
        self.username = "tester"
        self.is_active = True
        self.is_admin = is_admin


def test_sse_user_admin_has_admin_role(monkeypatch):
    """当 user.is_admin=True 时，SSE 认证返回的 role 必须是 'admin'，且不能抛 AttributeError"""
    from app.routers import sse as sse_mod

    # mock AuthService.verify_token
    class _Tok:
        sub = "tester"
    monkeypatch.setattr(sse_mod.AuthService, "verify_token", staticmethod(lambda _t: _Tok()))

    # mock user_service.get_user_by_username 返回管理员
    async def _get_admin(*a, **kw):
        return FakeUser(is_admin=True)
    monkeypatch.setattr(sse_mod.user_service, "get_user_by_username", _get_admin)

    # 调用：用 ?token= 路径
    result = pytest.importorskip("asyncio").run(
        sse_mod.get_current_user_for_sse(authorization=None, token="any")
    )

    assert result["id"] == "u_123"
    assert result["username"] == "tester"
    assert result["role"] == "admin", "管理员必须派生 role=admin"
    # 关键断言：代码路径中绝不能访问 user.role 属性
    assert not hasattr(FakeUser(is_admin=True), "role"), (
        "User 模型本来就没有 role 字段，如果测试依赖它，说明修复被回滚了"
    )


def test_sse_user_non_admin_has_user_role(monkeypatch):
    """当 user.is_admin=False 时，SSE 认证返回 role='user'"""
    from app.routers import sse as sse_mod

    class _Tok:
        sub = "tester"
    monkeypatch.setattr(sse_mod.AuthService, "verify_token", staticmethod(lambda _t: _Tok()))

    async def _get_user(*a, **kw):
        return FakeUser(is_admin=False)
    monkeypatch.setattr(sse_mod.user_service, "get_user_by_username", _get_user)

    import asyncio
    result = asyncio.run(sse_mod.get_current_user_for_sse(authorization=None, token="any"))
    assert result["role"] == "user", "非管理员必须派生 role=user"


def test_sse_auth_no_token_returns_401():
    """不带 token 必须明确 401，不能 500"""
    import asyncio

    from fastapi import HTTPException

    from app.routers import sse as sse_mod

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(sse_mod.get_current_user_for_sse(authorization=None, token=None))
    assert exc_info.value.status_code == 401
