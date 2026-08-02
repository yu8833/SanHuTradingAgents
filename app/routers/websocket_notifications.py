"""
WebSocket 通知系统
使用 Redis PubSub 支持多 Worker 部署
"""
import asyncio
import contextlib
import logging
from datetime import datetime

from fastapi import APIRouter, Query, WebSocket

from app.services.auth_service import AuthService
from app.services.user_service import user_service
from app.services.websocket_manager import get_websocket_manager

router = APIRouter()
logger = logging.getLogger("webapi.websocket")

manager = get_websocket_manager()


@router.websocket("/ws/notifications")
async def websocket_notifications_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    WebSocket 通知端点
    
    客户端连接: ws://localhost:8000/api/ws/notifications?token=<jwt_token>
    
    消息格式:
    {
        "type": "notification",
        "data": {
            "id": "...",
            "title": "...",
            "content": "...",
            "type": "analysis",
            "link": "/stocks/000001",
            "source": "analysis",
            "created_at": "2025-10-23T12:00:00",
            "status": "unread"
        }
    }
    """
    token_data = AuthService.verify_token(token)
    if not token_data:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    user = await user_service.get_user_by_username(token_data.sub)
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return
    
    user_id = str(user.id)
    
    await manager.connect(websocket, user_id)
    
    await websocket.send_json({
        "type": "connected",
        "data": {
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "WebSocket 连接成功"
        }
    })
    
    try:
        async def send_heartbeat():
            while True:
                try:
                    await asyncio.sleep(30)
                    await websocket.send_json({
                        "type": "heartbeat",
                        "data": {
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })
                except Exception as e:
                    logger.debug(f"💓 WS心跳失败: {e}")
                    break
        
        heartbeat_task = asyncio.create_task(send_heartbeat())
        
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(f"📥 WS收到消息: user={user_id}, data={data}")
            except Exception as e:
                logger.info(f"🔌 WS客户端断开: user={user_id}, reason={e}")
                break
    
    finally:
        if 'heartbeat_task' in locals():
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        
        await manager.disconnect(websocket, user_id)


@router.websocket("/ws/tasks/{task_id}")
async def websocket_task_progress_endpoint(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(...)
):
    """
    WebSocket 任务进度端点
    
    客户端连接: ws://localhost:8000/api/ws/tasks/<task_id>?token=<jwt_token>
    
    消息格式:
    {
        "type": "progress",
        "data": {
            "task_id": "...",
            "message": "正在分析...",
            "step": 1,
            "total_steps": 5,
            "progress": 20.0,
            "timestamp": "2025-10-23T12:00:00"
        }
    }
    """
    token_data = AuthService.verify_token(token)
    if not token_data:
        await websocket.close(code=1008, reason="Unauthorized")
        return
    
    user = await user_service.get_user_by_username(token_data.sub)
    if not user:
        await websocket.close(code=1008, reason="User not found")
        return
    
    user_id = str(user.id)
    
    await manager.connect_task(websocket, task_id, user_id)
    
    await websocket.send_json({
        "type": "connected",
        "data": {
            "task_id": task_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "message": "已连接任务进度流"
        }
    })
    
    try:
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug(f"📥 WS-Task收到消息: task={task_id}, data={data}")
            except Exception as e:
                logger.info(f"🔌 WS-Task客户端断开: task={task_id}, reason={e}")
                break
    
    finally:
        await manager.disconnect_task(websocket, task_id)


@router.get("/ws/stats")
async def get_websocket_stats():
    """获取 WebSocket 连接统计"""
    return await manager.get_stats()


async def send_notification_via_websocket(user_id: str, notification: dict):
    """通过 WebSocket 发送通知"""
    message = {
        "type": "notification",
        "data": notification
    }
    await manager.send_personal_message(user_id, message)


async def send_task_progress_via_websocket(task_id: str, user_id: str, progress_data: dict):
    """通过 WebSocket 发送任务进度"""
    message = {
        "type": "progress",
        "data": progress_data
    }
    await manager.send_task_progress(task_id, user_id, message)