"""回归测试：cockpit 路由的缓存包装必须传协程函数。

背景：cache_layer.cached 依 asyncio.iscoroutinefunction 判定构建函数类型；
曾用 `lambda: build_gate(db)`（同步函数返回协程），被当同步函数丢线程池，
返回未 await 的协程对象，最终在响应序列化时崩溃
（TypeError: 'coroutine' object is not iterable）。
"""
import asyncio

from app.routers import cockpit as cockpit_router


async def test_gate_cached_passes_coroutine_function(monkeypatch):
    captured = {}

    async def fake_cached(key, build_fn, **_kw):
        captured["fn"] = build_fn
        return await build_fn()

    async def fake_build(_db):
        return {"gate": "green", "label": "可进攻"}

    monkeypatch.setattr(cockpit_router, "cached", fake_cached)
    monkeypatch.setattr(cockpit_router.gate_service, "build_gate", fake_build)

    result = await cockpit_router._gate_cached(object())

    assert result == {"gate": "green", "label": "可进攻"}
    assert not asyncio.iscoroutine(result)
    # 钉住回归：传入 cached 的必须是协程函数，不能是返回协程的同步 lambda
    assert asyncio.iscoroutinefunction(captured["fn"])
