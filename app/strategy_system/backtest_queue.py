"""回测任务队列 — 基于 Redis List 的简单生产者/消费者队列。

回测任务由后端 web 进程投递到 Redis 队列，由独立的回测 Worker 进程消费执行，
从而与后端进程生命周期解耦：后端重启/升级/崩溃不会杀掉正在运行的回测任务。

任务状态通过 TaskManager（Redis 持久化）跨进程共享，前端可正常轮询进度/结果。
"""
import json
import logging

import redis

QUEUE_KEY = "backtest:queue"

logger = logging.getLogger(__name__)


def _r():
    from app.core.sync_redis import get_sync_redis
    return get_sync_redis()


def enqueue(kind: str, task_id: str, request: dict) -> bool:
    """把回测任务投递到队列。request 为已 JSON 序列化的请求字典。

    Returns:
        True 表示入队成功；False 表示 Redis 不可用（入队失败）。
    """
    r = _r()
    if r is None:
        return False
    try:
        payload = json.dumps(
            {"kind": kind, "task_id": task_id, "request": request}, ensure_ascii=False
        )
        r.rpush(QUEUE_KEY, payload)
        return True
    except Exception as e:
        logger.warning(f"回测任务入队失败: {e}")
        return False


def dequeue(timeout: float = 5.0) -> dict | None:
    """阻塞地从队列取出一个回测任务。超时返回 None。"""
    r = _r()
    if r is None:
        return None
    try:
        item = r.blpop(QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        return json.loads(item[1])
    except redis.exceptions.TimeoutError:
        # 队列为空时的正常阻塞超时，不视为错误
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"回测任务出队失败: {e}")
        return None