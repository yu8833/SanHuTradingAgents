"""回测任务管理器 — Redis 持久化 + 内存兜底的异步任务注册表。

将长时回测（策略/因子/参数优化/步进优化）改造为异步任务：
- 提交端立即返回 task_id，不阻塞 HTTP 请求。
- 后台线程执行计算，运行结果写入任务对象，与 HTTP 请求生命周期解耦，
  即使前端切换页面/刷新/断开连接，任务仍会继续并在完成后保留结果。
- 前端按 task_id 轮询状态/进度/结果。

与纯内存注册表的区别：
- 任务状态优先写入 Redis（key: backtest_task:{task_id}，TTL=24h），
  因此多 worker 进程之间、或进程崩溃后被自动拉起时，任务仍可被查询到，
  避免出现"任务不存在或已过期"。
- Redis 不可用时自动回退到进程内内存 dict，保证单机场景不失效。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Callable, Optional

# 任务在 Redis 中的前缀
_KEY_PREFIX = "backtest_task"


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

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BacktestTask":
        task = cls(data.get("task_id", ""), data.get("kind", ""))
        task.status = data.get("status", "running")
        task.progress = float(data.get("progress", 0.0))
        task.message = data.get("message", "")
        task.started_at = float(data.get("started_at", time.time()))
        task.updated_at = float(data.get("updated_at", task.started_at))
        task.result = data.get("result")
        task.error = data.get("error")
        return task


class TaskManager:
    """线程安全的任务注册表（Redis 持久化 + 内存兜底）。"""

    def __init__(self, ttl_seconds: int = 24 * 3600) -> None:
        self._lock = threading.RLock()
        # 进程内兜底存储：仅当 Redis 不可用时使用
        self._mem: dict[str, BacktestTask] = {}
        self._ttl = ttl_seconds

    # ── Redis 访问 ──────────────────────────────────────────────
    def _redis(self):
        """懒加载同步 Redis 客户端，不可用返回 None（不抛异常）。"""
        try:
            from app.core.sync_redis import get_sync_redis
            return get_sync_redis()
        except Exception:
            return None

    @staticmethod
    def _key(task_id: str) -> str:
        return f"{_KEY_PREFIX}:{task_id}"

    # ── 读写核心 ────────────────────────────────────────────────
    def _save(self, task: BacktestTask) -> None:
        """优先写 Redis，失败则写内存兜底。"""
        r = self._redis()
        if r is not None:
            try:
                r.setex(self._key(task.task_id), self._ttl,
                        json.dumps(task.to_dict(), ensure_ascii=False))
                return
            except Exception:
                pass
        with self._lock:
            self._mem[task.task_id] = task

    def _load(self, task_id: str) -> Optional[BacktestTask]:
        """优先读 Redis，miss 时读内存兜底。"""
        r = self._redis()
        if r is not None:
            try:
                raw = r.get(self._key(task_id))
                if raw:
                    return BacktestTask.from_dict(json.loads(raw))
            except Exception:
                pass
        with self._lock:
            return self._mem.get(task_id)

    # ── 对外接口（与原有内存版签名保持一致） ─────────────────────
    def create(self, kind: str) -> BacktestTask:
        task = BacktestTask(uuid.uuid4().hex[:12], kind)
        self._save(task)
        return task

    def get(self, task_id: str) -> Optional[BacktestTask]:
        return self._load(task_id)

    def update(self, task_id: str, *, progress: Optional[float] = None,
               message: Optional[str] = None, status: Optional[str] = None,
               result: Optional[dict] = None, error: Optional[str] = None) -> None:
        task = self._load(task_id)
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
        self._save(task)


# 全局单例
task_manager = TaskManager()

# 僵尸任务判定阈值：正常全市场回测最长约几分钟，
# 超过该时长仍无进度更新（progress 卡在早期阶段）即视为被中断的僵尸任务
STALE_RUNNING_THRESHOLD_SECONDS = 10 * 60


def cleanup_stale_tasks(stale_after_seconds: float = STALE_RUNNING_THRESHOLD_SECONDS) -> int:
    """清理僵尸回测任务：把 Redis 中"长时间无更新"的 running 任务标记为失败。

    回测任务在 web 进程的守护线程中执行，若后端进程被重启/崩溃，线程被杀，
    任务会永远停留在 running 状态（progress 卡在早期值），前端据此外推出离谱的 ETA。
    该方法在应用启动时调用，让这类任务尽快收敛为 failure，避免误导用户。
    """
    r = task_manager._redis()
    if r is None:
        return 0
    now = time.time()
    cleaned = 0
    try:
        keys = list(r.scan_iter(f"{_KEY_PREFIX}:*"))
    except Exception:
        return 0
    for k in keys:
        try:
            raw = r.get(k)
            if not raw:
                continue
            task = BacktestTask.from_dict(json.loads(raw))
            if task.status != "running":
                continue
            if now - task.updated_at < stale_after_seconds:
                continue
            task.status = "failure"
            task.error = (
                f"检测到僵尸任务：超过 {int(stale_after_seconds / 60)} 分钟无进度更新，"
                "可能因后端进程重启被中断"
            )
            task.message = "任务已中断（后端重启导致线程被杀）"
            task.updated_at = now
            task_manager._save(task)
            cleaned += 1
        except Exception:
            continue
    return cleaned


def make_progress_cb(task_id: str) -> Callable[[float, str], None]:
    """返回一个把进度/消息写入 task_manager 的回调，供回测函数调用。"""

    def _cb(progress: float, message: str) -> None:
        task_manager.update(
            task_id,
            progress=min(1.0, max(0.0, float(progress))),
            message=message,
        )

    return _cb