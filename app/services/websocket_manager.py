"""
WebSocket 连接管理器 - 使用 Redis PubSub 支持多 Worker
替代原有的纯内存管理器，解决 uvicorn --workers >1 时的连接共享问题
"""

import asyncio
import json
import logging
from typing import Dict, Set, Any
from fastapi import WebSocket

from app.core.database import get_redis_client

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 连接管理器 - 支持多进程部署"""
    
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.active_task_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._pubsub_task = None
        self._pubsub_listening = False
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """建立用户通知 WebSocket 连接"""
        await websocket.accept()
        
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
        
        total_connections = sum(len(conns) for conns in self.active_connections.values())
        logger.info(f"🔌 WS连接建立: user={user_id}, 用户连接数={len(self.active_connections[user_id])}, 总连接数={total_connections}")
        
        await self._ensure_pubsub_listening()
    
    async def connect_task(self, websocket: WebSocket, task_id: str, user_id: str):
        """建立任务进度 WebSocket 连接"""
        await websocket.accept()
        
        async with self._lock:
            if task_id not in self.active_task_connections:
                self.active_task_connections[task_id] = set()
            self.active_task_connections[task_id].add(websocket)
        
        logger.info(f"🔌 WS任务连接建立: task={task_id}, user={user_id}")
    
    async def disconnect(self, websocket: WebSocket, user_id: str):
        """断开用户通知 WebSocket 连接"""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        
        total_connections = sum(len(conns) for conns in self.active_connections.values())
        logger.info(f"🔌 WS连接断开: user={user_id}, 总连接数={total_connections}")
    
    async def disconnect_task(self, websocket: WebSocket, task_id: str):
        """断开任务进度 WebSocket 连接"""
        async with self._lock:
            if task_id in self.active_task_connections:
                self.active_task_connections[task_id].discard(websocket)
                if not self.active_task_connections[task_id]:
                    del self.active_task_connections[task_id]
        
        logger.info(f"🔌 WS任务连接断开: task={task_id}")
    
    async def send_personal_message(self, user_id: str, message: Dict[str, Any]):
        """发送消息给指定用户的所有连接"""
        await self._publish_to_redis(f"notifications:{user_id}", message)
        
        async with self._lock:
            if user_id not in self.active_connections:
                return
            connections = list(self.active_connections[user_id])
        
        message_json = json.dumps(message, ensure_ascii=False)
        dead_connections = []
        
        for connection in connections:
            try:
                await connection.send_text(message_json)
                logger.debug(f"📤 WS发送消息: user={user_id}")
            except Exception as e:
                logger.warning(f"⚠️ WS发送失败: {e}")
                dead_connections.append(connection)
        
        if dead_connections:
            async with self._lock:
                if user_id in self.active_connections:
                    for conn in dead_connections:
                        self.active_connections[user_id].discard(conn)
                    if not self.active_connections[user_id]:
                        del self.active_connections[user_id]
    
    async def send_task_progress(self, task_id: str, user_id: str, message: Dict[str, Any]):
        """发送任务进度给指定任务的所有连接"""
        await self._publish_to_redis(f"task_progress:{task_id}", message)
        
        async with self._lock:
            if task_id not in self.active_task_connections:
                return
            connections = list(self.active_task_connections[task_id])
        
        message_json = json.dumps(message, ensure_ascii=False)
        dead_connections = []
        
        for connection in connections:
            try:
                await connection.send_text(message_json)
                logger.debug(f"📤 WS发送任务进度: task={task_id}")
            except Exception as e:
                logger.warning(f"⚠️ WS发送任务进度失败: {e}")
                dead_connections.append(connection)
        
        if dead_connections:
            async with self._lock:
                if task_id in self.active_task_connections:
                    for conn in dead_connections:
                        self.active_task_connections[task_id].discard(conn)
                    if not self.active_task_connections[task_id]:
                        del self.active_task_connections[task_id]
    
    async def broadcast(self, message: Dict[str, Any]):
        """广播消息给所有连接"""
        await self._publish_to_redis("notifications:broadcast", message)
        
        async with self._lock:
            all_connections = []
            for connections in self.active_connections.values():
                all_connections.extend(connections)
        
        message_json = json.dumps(message, ensure_ascii=False)
        
        for connection in all_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"⚠️ WS广播失败: {e}")
    
    async def _publish_to_redis(self, channel: str, message: Dict[str, Any]):
        """发布消息到 Redis PubSub 频道"""
        try:
            r = get_redis_client()
            await r.publish(channel, json.dumps(message, ensure_ascii=False))
            logger.debug(f"📤 Redis发布: channel={channel}")
        except Exception as e:
            logger.warning(f"⚠️ Redis发布失败: {e}")
    
    async def _ensure_pubsub_listening(self):
        """确保 Redis PubSub 监听器正在运行"""
        if self._pubsub_listening:
            return
        
        self._pubsub_listening = True
        self._pubsub_task = asyncio.create_task(self._pubsub_listener())
    
    async def _pubsub_listener(self):
        """Redis PubSub 监听器 - 接收其他 worker 发送的消息"""
        while self._pubsub_listening:
            try:
                r = get_redis_client()
                pubsub = r.pubsub()
                await pubsub.subscribe("notifications:*", "task_progress:*")
                
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        channel = message["channel"]
                        data = json.loads(message["data"])
                        
                        if channel.startswith("notifications:"):
                            user_id = channel.replace("notifications:", "")
                            if user_id != "broadcast" and user_id in self.active_connections:
                                message_json = json.dumps(data, ensure_ascii=False)
                                connections = list(self.active_connections[user_id])
                                for conn in connections:
                                    try:
                                        await conn.send_text(message_json)
                                    except Exception as e:
                                        logger.warning(f"⚠️ WS转发消息失败: {e}")
                        
                        elif channel.startswith("task_progress:"):
                            task_id = channel.replace("task_progress:", "")
                            if task_id in self.active_task_connections:
                                message_json = json.dumps(data, ensure_ascii=False)
                                connections = list(self.active_task_connections[task_id])
                                for conn in connections:
                                    try:
                                        await conn.send_text(message_json)
                                    except Exception as e:
                                        logger.warning(f"⚠️ WS转发任务进度失败: {e}")
            
            except Exception as e:
                logger.error(f"❌ Redis PubSub 监听失败: {e}")
                await asyncio.sleep(5)
    
    async def get_stats(self) -> dict:
        """获取连接统计"""
        async with self._lock:
            return {
                "total_users": len(self.active_connections),
                "total_connections": sum(len(conns) for conns in self.active_connections.values()),
                "total_task_connections": sum(len(conns) for conns in self.active_task_connections.values()),
                "users": {user_id: len(conns) for user_id, conns in self.active_connections.items()}
            }


_websocket_manager = None


def get_websocket_manager() -> WebSocketManager:
    """获取 WebSocket 管理器实例"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager