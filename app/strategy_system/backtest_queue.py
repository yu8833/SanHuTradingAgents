"""回测任务队列 — 基于 Redis List 的简单生产者/消费者队列。

回测任务由后端 web 进程投递到 Redis 队列，由独立的回测 Worker 进程消费执行，
从而与后端进程生命周期解耦：后端重启/升级/崩溃不会杀掉正在运行的回测任务。

任务状态通过 TaskManager（Redis 持久化）跨进程共享，前端可正常轮询进度/结果。
"""
import json
import logging

import redis

QUEUE_KEY = "backtest:queue"
# 在途任务标记：Worker 取出任务后立即写入，处理完成后再清除。
# 用于 Worker 异常重启（信号/PID 被杀/崩溃）时恢复被中断的任务，避免任务永久丢失。
INFLIGHT_KEY = "backtest:inflight"
# 在途标记 TTL：远大于最坏回测时长，防止陈旧标记长期占用
_INFLIGHT_TTL = 24 * 3600

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


def mark_inflight(task_id: str, payload: dict) -> None:
    """记录当前正在执行的在途任务。

    Worker 用 BLPOP 取出任务后队列即移除该条目，若 Worker 中途被重启，
    任务会永久丢失。因此在取出任务后立即把完整 payload 写入在途标记，
    处理完成后再清除；Worker 启动时若发现残留标记，则据此把任务重新入队。
    """
    r = _r()
    if r is None:
        return
    try:
        r.setex(
            INFLIGHT_KEY, _INFLIGHT_TTL,
            json.dumps({"kind": payload["kind"], "task_id": task_id,
                        "request": payload.get("request")}, ensure_ascii=False),
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"写入在途任务标记失败: {e}")


def clear_inflight() -> None:
    """清除在途任务标记（任务成功或失败后调用）。"""
    r = _r()
    if r is None:
        return
    try:
        r.delete(INFLIGHT_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"清除在途任务标记失败: {e}")


def drain_inflight() -> dict | None:
    """读取并清除在途任务标记，返回被中断任务的 payload。

    Worker 启动时调用：若存在残留标记，说明上次进程在任务执行中被重启，
    返回该任务 payload 以便重新入队恢复执行。
    """
    r = _r()
    if r is None:
        return None
    try:
        raw = r.get(INFLIGHT_KEY)
        if not raw:
            return None
        cleared = r.delete(INFLIGHT_KEY)
        if cleared:
            return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"读取在途任务标记失败: {e}")
    return None