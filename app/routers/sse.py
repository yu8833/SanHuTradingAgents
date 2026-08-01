from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
import asyncio
import json
import logging
import time
from typing import Optional

from app.routers.auth_db import get_current_user
from app.core.database import get_redis_client
from app.core.config import settings
from app.services.auth_service import AuthService
from app.services.user_service import user_service

from app.services.queue_service import get_queue_service, QueueService

router = APIRouter()
logger = logging.getLogger("webapi.sse")


async def get_current_user_for_sse(
    authorization: Optional[str] = None,
    token: Optional[str] = None
) -> dict:
    """
    SSE 专用认证：支持 Authorization header 或 ?token= query 参数。

    EventSource 原生不支持自定义 header，因此 SSE 端点需要支持 query token。
    优先使用 header，其次 query 参数。
    """
    raw_token = None
    if authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1]
    elif token:
        raw_token = token

    if not raw_token:
        raise HTTPException(status_code=401, detail="No token provided")

    token_data = AuthService.verify_token(raw_token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = await user_service.get_user_by_username(token_data.sub)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    return {"id": str(user.id), "username": user.username, "role": "admin" if user.is_admin else "user"}


async def task_progress_generator(task_id: str, user_id: str):
    """Generate SSE events for task progress updates"""
    r = get_redis_client()
    pubsub = None
    channel = f"task_progress:{task_id}"

    try:
        # Load dynamic SSE settings
        try:
            from app.services.config_provider import provider as config_provider
            eff = await config_provider.get_effective_system_settings()
            poll_timeout = float(eff.get("sse_poll_timeout_seconds", 1.0))
            heartbeat_every = int(eff.get("sse_heartbeat_interval_seconds", 10))
            max_idle_seconds = int(eff.get("sse_task_max_idle_seconds", 300))
        except Exception:
            poll_timeout = float(getattr(settings, "SSE_POLL_TIMEOUT_SECONDS", 1.0))
            heartbeat_every = int(getattr(settings, "SSE_HEARTBEAT_INTERVAL_SECONDS", 10))
            max_idle_seconds = int(getattr(settings, "SSE_TASK_MAX_IDLE_SECONDS", 300))

        # 🔥 修复：创建 PubSub 连接
        pubsub = r.pubsub()
        logger.info(f"📡 [SSE-Task] 创建 PubSub 连接: task={task_id}, user={user_id}")

        # 🔥 修复：订阅频道（可能失败，需要确保 pubsub 被清理）
        try:
            await pubsub.subscribe(channel)
            logger.info(f"✅ [SSE-Task] 订阅频道成功: {channel}")
            # Send initial connection confirmation
            yield f"event: connected\ndata: {{\"task_id\": \"{task_id}\", \"message\": \"已连接进度流\"}}\n\n"
        except Exception as subscribe_error:
            # 🔥 订阅失败时立即清理 pubsub 连接
            logger.error(f"❌ [SSE-Task] 订阅频道失败: {subscribe_error}")
            try:
                await pubsub.close()
                logger.info(f"🧹 [SSE-Task] 订阅失败后已关闭 PubSub 连接")
            except Exception as close_error:
                logger.error(f"❌ [SSE-Task] 关闭 PubSub 连接失败: {close_error}")
            # 重新抛出异常，让外层 except 处理
            raise

        # Listen for progress updates
        idle_elapsed = 0.0
        last_hb = time.monotonic()

        while idle_elapsed < max_idle_seconds:
            try:
                message = await asyncio.wait_for(pubsub.get_message(ignore_subscribe_messages=True), timeout=poll_timeout)
                if message and message['type'] == 'message':
                    # Reset idle timer on valid message
                    idle_elapsed = 0.0
                    try:
                        progress_data = json.loads(message['data'])
                        yield f"event: progress\ndata: {json.dumps(progress_data, ensure_ascii=False)}\n\n"
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in progress message: {message['data']}")
                else:
                    # No update: accumulate idle time and send heartbeat if due
                    idle_elapsed += poll_timeout
                    now = time.monotonic()
                    if now - last_hb >= heartbeat_every:
                        yield f"event: heartbeat\ndata: {{\"timestamp\": \"{time.time()}\"}}\n\n"
                        last_hb = now

            except asyncio.TimeoutError:
                idle_elapsed += poll_timeout
                continue

    except Exception as e:
        logger.exception(f"SSE error for task {task_id}: {e}")
        yield f"event: error\ndata: {{\"error\": \"连接异常: {str(e)}\"}}\n\n"
    finally:
        # 🔥 修复：确保在所有情况下都释放连接
        if pubsub:
            logger.info(f"🧹 [SSE-Task] 清理 PubSub 连接: task={task_id}")

            # 分步骤关闭，确保即使 unsubscribe 失败也能关闭连接
            try:
                await pubsub.unsubscribe(channel)
                logger.debug(f"✅ [SSE-Task] 已取消订阅频道: {channel}")
            except Exception as e:
                logger.warning(f"⚠️ [SSE-Task] 取消订阅失败（将继续关闭连接）: {e}")

            try:
                await pubsub.close()
                logger.info(f"✅ [SSE-Task] PubSub 连接已关闭: task={task_id}")
            except Exception as e:
                logger.error(f"❌ [SSE-Task] 关闭 PubSub 连接失败: {e}", exc_info=True)
                # 即使关闭失败，也尝试重置连接
                try:
                    await pubsub.reset()
                    logger.info(f"🔄 [SSE-Task] PubSub 连接已重置: task={task_id}")
                except Exception as reset_error:
                    logger.error(f"❌ [SSE-Task] 重置 PubSub 连接也失败: {reset_error}")


async def batch_progress_generator(batch_id: str, user_id: str):
    """Generate SSE events for batch progress updates"""
    svc = get_queue_service()

    try:
        # Load dynamic SSE settings for batch stream
        try:
            from app.services.config_provider import provider as config_provider
            eff = await config_provider.get_effective_system_settings()
            batch_poll_interval = float(eff.get("sse_batch_poll_interval_seconds", 2))
            batch_max_idle_seconds = int(eff.get("sse_batch_max_idle_seconds", 600))
        except Exception:
            batch_poll_interval = float(getattr(settings, "SSE_BATCH_POLL_INTERVAL_SECONDS", 2.0))
            batch_max_idle_seconds = int(getattr(settings, "SSE_BATCH_MAX_IDLE_SECONDS", 600))

        # Send initial connection confirmation
        yield f"event: connected\ndata: {{\"batch_id\": \"{batch_id}\", \"message\": \"已连接批次进度流\"}}\n\n"

        idle_elapsed = 0.0

        while idle_elapsed < batch_max_idle_seconds:
            try:
                # Get current batch status
                batch_data = await svc.get_batch(batch_id)
                if not batch_data:
                    yield f"event: error\ndata: {{\"error\": \"批次不存在\"}}\n\n"
                    break

                # Check if batch belongs to user
                if batch_data.get("user") != user_id:
                    yield f"event: error\ndata: {{\"error\": \"无权限访问此批次\"}}\n\n"
                    break

                # Calculate batch progress based on task statuses
                task_ids = batch_data.get("tasks", [])
                if not task_ids:
                    yield f"event: progress\ndata: {{\"batch_id\": \"{batch_id}\", \"message\": \"批次无任务\", \"progress\": 0}}\n\n"
                    await asyncio.sleep(batch_poll_interval)
                    idle_elapsed += batch_poll_interval
                    continue

                completed_count = 0
                failed_count = 0
                processing_count = 0

                for task_id in task_ids:
                    task_data = await svc.get_task(task_id)
                    if task_data:
                        status = task_data.get("status", "queued")
                        if status == "completed":
                            completed_count += 1
                        elif status == "failed":
                            failed_count += 1
                        elif status == "processing":
                            processing_count += 1

                total_tasks = len(task_ids)
                finished_tasks = completed_count + failed_count
                progress = round((finished_tasks / total_tasks) * 100, 1) if total_tasks > 0 else 0

                # Determine batch status
                if finished_tasks == total_tasks:
                    if failed_count == 0:
                        batch_status = "completed"
                        message = f"批次完成: {completed_count}/{total_tasks} 成功"
                    elif completed_count == 0:
                        batch_status = "failed"
                        message = f"批次失败: {failed_count}/{total_tasks} 失败"
                    else:
                        batch_status = "partial"
                        message = f"批次部分成功: {completed_count} 成功, {failed_count} 失败"
                elif processing_count > 0 or finished_tasks < total_tasks:
                    batch_status = "processing"
                    message = f"批次处理中: {finished_tasks}/{total_tasks} 已完成, {processing_count} 处理中"
                else:
                    batch_status = "queued"
                    message = f"批次排队中: {total_tasks} 任务待处理"

                progress_data = {
                    "batch_id": batch_id,
                    "status": batch_status,
                    "message": message,
                    "progress": progress,
                    "total_tasks": total_tasks,
                    "completed": completed_count,
                    "failed": failed_count,
                    "processing": processing_count,
                    "timestamp": time.time()
                }

                yield f"event: progress\ndata: {json.dumps(progress_data, ensure_ascii=False)}\n\n"

                # Break if batch is finished
                if batch_status in ["completed", "failed", "partial"]:
                    yield f"event: finished\ndata: {{\"batch_id\": \"{batch_id}\", \"final_status\": \"{batch_status}\"}}\n\n"
                    break

                # Wait before next update
                await asyncio.sleep(batch_poll_interval)
                idle_elapsed += batch_poll_interval

            except Exception as e:
                logger.exception(f"Batch progress error: {e}")
                yield f"event: error\ndata: {{\"error\": \"获取批次状态失败: {str(e)}\"}}\n\n"
                break

    except Exception as e:
        logger.exception(f"SSE batch error for {batch_id}: {e}")
        yield f"event: error\ndata: {{\"error\": \"连接异常: {str(e)}\"}}\n\n"


@router.get("/tasks/{task_id}")
async def stream_task_progress(task_id: str, user: dict = Depends(get_current_user), svc: QueueService = Depends(get_queue_service)):
    """Stream real-time progress updates for a specific task"""
    # Verify task exists and belongs to user
    task_data = await svc.get_task(task_id)
    if not task_data or task_data.get("user") != user["id"]:
        raise HTTPException(status_code=404, detail="Task not found")

    return StreamingResponse(
        task_progress_generator(task_id, user["id"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


@router.get("/batches/{batch_id}")
async def stream_batch_progress(batch_id: str, user: dict = Depends(get_current_user), svc: QueueService = Depends(get_queue_service)):
    """Stream real-time progress updates for a batch"""
    # Verify batch exists and belongs to user
    batch_data = await svc.get_batch(batch_id)
    if not batch_data or batch_data.get("user") != user["id"]:
        raise HTTPException(status_code=404, detail="Batch not found")

    return StreamingResponse(
        batch_progress_generator(batch_id, user["id"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def quotes_update_generator(user_id: str):
    """
    生成实时行情更新信号 SSE 流。

    订阅 Redis 频道 `quotes_update`，当 quotes_ingestion_service 入库完成后会发布信号。
    前端收到信号后主动调用 /api/stocks/{code}/quote 拉取最新行情，
    避免 5000 只股票全量推送，实现"服务端 poke + 客户端 pull"。

    与前端 30 秒轮询互补：
    - SSE 信号到达后立即拉取（延迟约 0-2 秒）
    - 30 秒轮询作为兜底，防止 SSE 断连
    """
    r = get_redis_client()
    pubsub = None
    channel = "quotes_update"

    try:
        # 动态加载 SSE 设置
        try:
            from app.services.config_provider import provider as config_provider
            eff = await config_provider.get_effective_system_settings()
            poll_timeout = float(eff.get("sse_poll_timeout_seconds", 1.0))
            heartbeat_every = int(eff.get("sse_heartbeat_interval_seconds", 10))
            # 行情流允许更长的空闲时间（30分钟），避免盘中短暂无更新时断连
            max_idle_seconds = int(eff.get("sse_quotes_max_idle_seconds", 1800))
        except Exception:
            poll_timeout = float(getattr(settings, "SSE_POLL_TIMEOUT_SECONDS", 1.0))
            heartbeat_every = int(getattr(settings, "SSE_HEARTBEAT_INTERVAL_SECONDS", 10))
            max_idle_seconds = int(getattr(settings, "SSE_QUOTES_MAX_IDLE_SECONDS", 1800))

        pubsub = r.pubsub()
        try:
            await pubsub.subscribe(channel)
            yield f"event: connected\ndata: {{\"message\": \"已连接实时行情信号流\"}}\n\n"
        except Exception as subscribe_error:
            logger.error(f"❌ [SSE-Quotes] 订阅频道失败: {subscribe_error}")
            try:
                await pubsub.close()
            except Exception:
                pass
            raise

        idle_elapsed = 0.0
        last_hb = time.monotonic()

        while idle_elapsed < max_idle_seconds:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=poll_timeout
                )
                if message and message['type'] == 'message':
                    idle_elapsed = 0.0
                    try:
                        data = json.loads(message['data'])
                        yield f"event: quotes_update\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in quotes_update message: {message['data']}")
                else:
                    idle_elapsed += poll_timeout
                    now = time.monotonic()
                    if now - last_hb >= heartbeat_every:
                        # 用 time.time() 返回 Unix 时间戳，而非事件循环单调时间
                        yield f"event: heartbeat\ndata: {{\"timestamp\": {time.time()}}}\n\n"
                        last_hb = now
            except asyncio.TimeoutError:
                idle_elapsed += poll_timeout
                continue

    except Exception as e:
        logger.exception(f"SSE quotes error: {e}")
        yield f"event: error\ndata: {{\"error\": \"连接异常: {str(e)}\"}}\n\n"
    finally:
        if pubsub:
            logger.info(f"🧹 [SSE-Quotes] 清理 PubSub 连接")
            try:
                await pubsub.unsubscribe(channel)
            except Exception as e:
                logger.warning(f"⚠️ [SSE-Quotes] 取消订阅失败: {e}")
            try:
                await pubsub.close()
            except Exception as e:
                logger.error(f"❌ [SSE-Quotes] 关闭连接失败: {e}")


@router.get("/quotes")
async def stream_quotes_update(
    token: Optional[str] = Query(default=None, description="SSE 认证 token（EventSource 不支持自定义 header）"),
    authorization: Optional[str] = Header(default=None),
):
    """
    实时行情更新信号 SSE 端点。

    当后端 quotes_ingestion_service 完成行情入库后，会通过 Redis publish 通知。
    前端订阅本端点后，收到 `quotes_update` 事件即主动拉取最新行情。

    与前端 30 秒轮询互补，实现近实时（延迟约 0-2 秒）的行情刷新。

    认证方式：支持 `?token=xxx` query 参数（EventSource 兼容）或 Authorization header。
    """
    user = await get_current_user_for_sse(authorization=authorization, token=token)

    return StreamingResponse(
        quotes_update_generator(user["id"]),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )