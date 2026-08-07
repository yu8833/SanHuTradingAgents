"""回测任务管理器 — 内存级异步任务注册表。

将长时回测（策略/因子/参数优化/步进优化）改造为异步任务：
- 提交端立即返回 task_id，不阻塞 HTTP 请求。
- 后台线程执行计算，运行结果写入任务对象，与 HTTP 请求生命周期解耦，
  即使前端切换页面/刷新/断开连接，任务仍会继续并在完成后保留结果。
- 前端按 task_id 轮询状态/进度/结果。
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Callable, Optional


class BacktestTask:
    """单个回测任务的状态与结果。"""

    __slots__ = (
        "task_id", "kind", "status", "progress", "message",
        "started_at", "updated_at", "result", "error",
    )

    def __init__(self, task_id: str, kind: str) -> None:
        self.task_id = task_id
        self.kind = kind
        self.status = "running"
        self.progress = 0.0
        self.message = "任务已创建，等待执行…"
        now = time.time()
        self.started_at = now
        self.updated_at = now
        self.result: Optional[dict] = None
        self.error: Optional[str] = None


class TaskManager:
    """线程安全的任务注册表（内存级，单进程内有效）。"""

    def __init__(self, ttl_seconds: int = 24 * 3600) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, BacktestTask] = {}
        self._ttl = ttl_seconds

    def create(self, kind: str) -> BacktestTask:
        with self._lock:
            self._gc()
            task = BacktestTask(uuid.uuid4().hex[:12], kind)
            self._tasks[task.task_id] = task
            return task

    def get(self, task_id: str) -> Optional[BacktestTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, *, progress: Optional[float] = None,
               message: Optional[str] = None, status: Optional[str] = None,
               result: Optional[dict] = None, error: Optional[str] = None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if progress is not None:
                task.progress = float(progress)
            if message is not None:
                task.message = message
            if status is not None:
                task.status = status
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            task.updated_at = time.time()

    def _gc(self) -> None:
        now = time.time()
        expired = [tid for tid, t in self._tasks.items() if now - t.updated_at > self._ttl]
        for tid in expired:
            del self._tasks[tid]


# 全局单例
task_manager = TaskManager()


def make_progress_cb(task_id: str) -> Callable[[float, str], None]:
    """返回一个把进度/消息写入 task_manager 的回调，供回测函数调用。"""

    def _cb(progress: float, message: str) -> None:
        task_manager.update(
            task_id,
            progress=min(1.0, max(0.0, float(progress))),
            message=message,
        )

    return _cb