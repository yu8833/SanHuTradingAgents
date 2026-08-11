"""
研究笔记服务
存储用户的研究记录、笔记等数据到MongoDB
"""

import logging
from datetime import datetime
from typing import Any

from bson import ObjectId

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)

MAX_NOTES_PER_USER = 100


class ResearchNotesService:
    """研究笔记服务类"""

    def __init__(self):
        self.db = None

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _format_note(self, note: dict[str, Any]) -> dict[str, Any]:
        note_id = note.get("_id")
        if isinstance(note_id, ObjectId):
            note_id = str(note_id)

        created_at = note.get("created_at")
        if isinstance(created_at, datetime):
            created_at = created_at.isoformat()

        updated_at = note.get("updated_at")
        if isinstance(updated_at, datetime):
            updated_at = updated_at.isoformat()

        return {
            "id": note_id,
            "kind": note.get("kind", ""),
            "title": note.get("title", ""),
            "content": note.get("content", ""),
            "ts": note.get("ts", 0),
            "created_at": created_at,
            "updated_at": updated_at,
            # 交易复盘关联字段（可选）
            "related_code": note.get("related_code"),
            "related_strategy": note.get("related_strategy"),
            "related_trade_id": note.get("related_trade_id"),
        }

    async def get_user_notes(self, user_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        """获取用户的研究笔记列表"""
        db = await self._get_db()

        query: dict[str, Any] = {"user_id": user_id}
        if kind:
            query["kind"] = kind

        cursor = db.research_notes.find(query).sort("created_at", -1).limit(MAX_NOTES_PER_USER)
        notes = await cursor.to_list(length=None)

        return [self._format_note(note) for note in notes]

    async def add_note(
        self,
        user_id: str,
        kind: str,
        title: str,
        content: str,
        related_code: str | None = None,
        related_strategy: str | None = None,
        related_trade_id: str | None = None,
    ) -> dict[str, Any] | None:
        """添加研究笔记"""
        try:
            db = await self._get_db()

            now = datetime.now()
            note = {
                "user_id": user_id,
                "kind": kind,
                "title": title,
                "content": content,
                "ts": int(now.timestamp() * 1000),
                "created_at": now,
                "updated_at": now,
            }
            # 交易复盘关联字段（可选）
            if related_code:
                note["related_code"] = related_code
            if related_strategy:
                note["related_strategy"] = related_strategy
            if related_trade_id:
                note["related_trade_id"] = related_trade_id

            result = await db.research_notes.insert_one(note)
            note["_id"] = result.inserted_id

            # 限制每个用户的笔记数量
            count = await db.research_notes.count_documents({"user_id": user_id})
            if count > MAX_NOTES_PER_USER:
                # 删除最旧的笔记
                oldest = await db.research_notes.find(
                    {"user_id": user_id}
                ).sort("created_at", 1).limit(count - MAX_NOTES_PER_USER).to_list(length=None)
                if oldest:
                    ids_to_delete = [n["_id"] for n in oldest]
                    await db.research_notes.delete_many({"_id": {"$in": ids_to_delete}})

            return self._format_note(note)
        except Exception as e:
            logger.error(f"添加研究笔记失败: {e}")
            return None

    async def delete_note(self, user_id: str, note_id: str) -> bool:
        """删除研究笔记"""
        try:
            db = await self._get_db()

            # 尝试用ObjectId查询
            try:
                oid = ObjectId(note_id)
                result = await db.research_notes.delete_one({
                    "_id": oid,
                    "user_id": user_id
                })
            except Exception:
                # 失败则用字符串ID查询
                result = await db.research_notes.delete_one({
                    "_id": note_id,
                    "user_id": user_id
                })

            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"删除研究笔记失败: {e}")
            return False

    async def clear_notes(self, user_id: str) -> bool:
        """清空用户所有研究笔记"""
        try:
            db = await self._get_db()
            await db.research_notes.delete_many({"user_id": user_id})
            return True
        except Exception as e:
            logger.error(f"清空研究笔记失败: {e}")
            return False


research_notes_service = ResearchNotesService()
