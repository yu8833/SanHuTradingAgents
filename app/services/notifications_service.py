"""
通知服务：持久化 + 列表 + 已读 + SSE 发布
"""
import contextlib
import logging
from datetime import timedelta
from typing import Any

from bson import ObjectId

from app.core.database import get_mongo_db
from app.models.notification import NotificationCreate, NotificationList, NotificationOut
from app.utils.timezone import now_tz, to_config_tz

logger = logging.getLogger("webapi.notifications")


class NotificationsService:
    def __init__(self):
        self.collection = "notifications"
        self.channel_prefix = "notifications:"
        self.retain_days = 90
        self.max_per_user = 1000

    async def _ensure_indexes(self):
        try:
            db = get_mongo_db()
            await db[self.collection].create_index([("user_id", 1), ("created_at", -1)])
            await db[self.collection].create_index([("user_id", 1), ("status", 1)])
        except Exception as e:
            logger.warning(f"创建索引失败(忽略): {e}")

    async def create_and_publish(self, payload: NotificationCreate) -> str:
        await self._ensure_indexes()
        db = get_mongo_db()
        doc = {
            "user_id": payload.user_id,
            "type": payload.type,
            "title": payload.title,
            "content": payload.content,
            "link": payload.link,
            "source": payload.source,
            "severity": payload.severity or "info",
            "status": "unread",
            "created_at": now_tz(),
            "metadata": payload.metadata or {},
        }
        res = await db[self.collection].insert_one(doc)
        doc_id = str(res.inserted_id)

        payload_to_publish = {
            "id": doc_id,
            "type": doc["type"],
            "title": doc["title"],
            "content": doc.get("content"),
            "link": doc.get("link"),
            "source": doc.get("source"),
            "status": doc.get("status", "unread"),
            "created_at": doc["created_at"].isoformat(),
        }

        # 🔥 使用 WebSocket 发送通知
        try:
            from app.routers.websocket_notifications import send_notification_via_websocket
            await send_notification_via_websocket(payload.user_id, payload_to_publish)
            logger.debug(f"✅ [WS] 通知已通过 WebSocket 发送: user={payload.user_id}")
        except Exception as e:
            logger.warning(f"⚠️ [WS] WebSocket 发送失败: {e}")

        # 清理策略：保留最近N天/最多M条
        try:
            await db[self.collection].delete_many({
                "user_id": payload.user_id,
                "created_at": {"$lt": now_tz() - timedelta(days=self.retain_days)}
            })
            # 超过配额按时间删旧
            count = await db[self.collection].count_documents({"user_id": payload.user_id})
            if count > self.max_per_user:
                skip = count - self.max_per_user
                ids = []
                async for d in db[self.collection].find({"user_id": payload.user_id}, {"_id": 1}).sort("created_at", 1).limit(skip):
                    ids.append(d["_id"])
                if ids:
                    await db[self.collection].delete_many({"_id": {"$in": ids}})
        except Exception as e:
            logger.warning(f"通知清理失败(忽略): {e}")

        return doc_id

    async def unread_count(self, user_id: str, ntype: str | None = None) -> int:
        db = get_mongo_db()
        # user_id 兼容查询：支持字符串和 ObjectId，支持 admin 特殊处理
        uid_candidates = self._build_uid_candidates(user_id)
        or_conditions = [
            {"user_id": {"$in": uid_candidates}},
            {"user": {"$in": uid_candidates}}
        ]
        conditions = [{"$or": or_conditions}, {"status": "unread"}]
        if ntype in ("analysis", "alert", "system"):
            conditions.append({"type": ntype})
        query = {"$and": conditions}
        return await db[self.collection].count_documents(query)

    def _build_uid_candidates(self, user_id: str) -> list:
        """构建 user_id 候选列表，支持字符串和 ObjectId 兼容"""
        uid_candidates = [user_id]
        # 特殊处理 admin 用户
        if str(user_id) == 'admin':
            try:
                admin_oid_str = '507f1f77bcf86cd799439011'
                uid_candidates.append(ObjectId(admin_oid_str))
                uid_candidates.append(admin_oid_str)
            except Exception:
                pass
        else:
            # 普通用户：尝试转换为 ObjectId
            with contextlib.suppress(Exception):
                uid_candidates.append(ObjectId(user_id))
        return uid_candidates

    async def list(self, user_id: str, *, status: str | None = None, ntype: str | None = None, page: int = 1, page_size: int = 20) -> NotificationList:
        db = get_mongo_db()
        # user_id 兼容查询：支持字符串和 ObjectId，支持 admin 特殊处理
        uid_candidates = self._build_uid_candidates(user_id)
        or_conditions = [
            {"user_id": {"$in": uid_candidates}},
            {"user": {"$in": uid_candidates}}
        ]
        q: dict[str, Any] = {"$or": or_conditions}
        if status in ("read", "unread"):
            q["status"] = status
        if ntype in ("analysis", "alert", "system"):
            q["type"] = ntype
        total = await db[self.collection].count_documents(q)
        cursor = db[self.collection].find(q).sort("created_at", -1).skip((page-1)*page_size).limit(page_size)
        items: list[NotificationOut] = []
        async for d in cursor:
            raw_dt = d.get("created_at")
            # MongoDB 存储 datetime 时会剥离 tzinfo，UTC 时间存储
            # 读取后需要用 to_config_tz 转为配置时区
            created_at = to_config_tz(raw_dt) if raw_dt else now_tz()
            items.append(NotificationOut(
                id=str(d.get("_id")),
                type=d.get("type"),
                title=d.get("title"),
                content=d.get("content"),
                link=d.get("link"),
                source=d.get("source"),
                status=d.get("status", "unread"),
                created_at=created_at,
            ))
        return NotificationList(items=items, total=total, page=page, page_size=page_size)

    async def mark_read(self, user_id: str, notif_id: str) -> bool:
        db = get_mongo_db()
        try:
            oid = ObjectId(notif_id)
        except Exception:
            return False
        # user_id 兼容查询
        uid_candidates = self._build_uid_candidates(user_id)
        or_conditions = [
            {"user_id": {"$in": uid_candidates}},
            {"user": {"$in": uid_candidates}}
        ]
        query = {"$and": [{"_id": oid}, {"$or": or_conditions}]}
        res = await db[self.collection].update_one(query, {"$set": {"status": "read"}})
        return res.modified_count > 0

    async def mark_all_read(self, user_id: str) -> int:
        db = get_mongo_db()
        # user_id 兼容查询
        uid_candidates = self._build_uid_candidates(user_id)
        or_conditions = [
            {"user_id": {"$in": uid_candidates}},
            {"user": {"$in": uid_candidates}}
        ]
        query = {"$and": [{"$or": or_conditions}, {"status": "unread"}]}
        res = await db[self.collection].update_many(query, {"$set": {"status": "read"}})
        return res.modified_count


_notifications_service: NotificationsService | None = None


def get_notifications_service() -> NotificationsService:
    global _notifications_service
    if _notifications_service is None:
        _notifications_service = NotificationsService()
    return _notifications_service

