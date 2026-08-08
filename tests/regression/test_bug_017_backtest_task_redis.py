"""
Bug-017 防回归测试：回测任务丢失，提示"任务不存在或已过期"

根因：异步回测任务注册表（app/strategy_system/task_manager.py）是纯进程内存 dict，
      任务状态不落任何持久化存储。当后端为多 worker 进程、或进程崩溃后被自动拉起
      （restart: unless-stopped）时，提交 /backtest/start 与轮询 /task/{id} 落在不同
      进程，或进程重启清空了内存，导致 get(task_id) 返回 None，前端弹出
      "任务不存在或已过期"。

修复：任务状态优先写入 Redis（key: backtest_task:{task_id}，TTL=24h），
      多进程/重启后仍可查询；Redis 不可用时回退到进程内内存兜底。

本测试：用两个全新的 TaskManager 实例模拟"不同进程/重启"，验证经 Redis 写入的任务
        能被另一个实例读到（旧的纯内存实现第二个实例必然读不到）。
"""
import pytest

from app.strategy_system.task_manager import TaskManager

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _redis_available() -> bool:
    """判断当前环境是否连得上真实 Redis；连不上则该持久化用例跳过。"""
    try:
        from app.core.sync_redis import get_sync_redis
        return get_sync_redis() is not None
    except Exception:
        return False


def test_basic_create_update_get():
    """基础流程：create 后能 get，update 的进度/状态能被读到。"""
    tm = TaskManager()
    task = tm.create("strategy")
    assert task.task_id
    assert task.status == "running"

    tm.update(task.task_id, progress=0.5, message="正在计算…")
    got = tm.get(task.task_id)
    assert got is not None
    assert got.progress == pytest.approx(0.5)
    assert got.message == "正在计算…"
    assert got.status == "running"

    tm.update(task.task_id, status="success", progress=1.0, result={"x": 1})
    done = tm.get(task.task_id)
    assert done is not None
    assert done.status == "success"
    assert done.result == {"x": 1}


@pytest.mark.skipif(
    not _redis_available(), reason="真实 Redis 不可用，跳过跨实例持久化断言"
)
def test_task_persists_across_instances_via_redis():
    """
    核心防御：模拟"提交进程"与"查询进程"不同（或进程重启）。

    用两个独立的 TaskManager 做写/读，二者唯一的共享媒介是 Redis。
    若实现是纯内存，第二个实例必然取不到任务 → 本测试失败，即 bug 复发。
    """
    writer = TaskManager()
    task = writer.create("strategy")
    writer.update(task.task_id, progress=0.3, message="计算中…")

    # 全新实例：内存为空，只有 Redis 能读到
    reader = TaskManager()
    got = reader.get(task.task_id)
    assert got is not None, "任务未持久化到 Redis，跨进程/重启后查询不到（bug-017 复发）"
    assert got.progress == pytest.approx(0.3)
    assert got.message == "计算中…"

    # 更新同样要能跨实例可见
    reader.update(task.task_id, status="success", progress=1.0, result={"ok": True})
    reread = TaskManager().get(task.task_id)
    assert reread is not None
    assert reread.status == "success"
    assert reread.result == {"ok": True}