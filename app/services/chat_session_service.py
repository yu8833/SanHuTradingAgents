"""Agent 策略问股 —— 会话持久化服务。

存储：MongoDB chat_sessions 集合（集合名登记在 app/core/collections.py）。
职责：会话 CRUD + 预算记账（条件 $inc 原子更新防并发超卖）。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from app.core.collections import Collections, col
from app.models.chat import ChatSession, ChatTurn

logger = logging.getLogger("webapi")

_COL = Collections.chat_sessions


def _now() -> datetime:
    return datetime.utcnow()


def _budget_limits() -> tuple[int, int, float]:
    """预算护栏上限（优先读配置，缺省：20 轮 / 8 万 tokens / ¥5）。"""
    try:
        from app.core.config import settings
        return (
            int(getattr(settings, "CHAT_BUDGET_MAX_ROUNDS", 20) or 20),
            int(getattr(settings, "CHAT_BUDGET_MAX_TOTAL_TOKENS", 80000) or 80000),
            float(getattr(settings, "CHAT_BUDGET_MAX_COST", 5.0) or 5.0),
        )
    except Exception:
        return 20, 80000, 5.0


async def create_session(user_id: str, title: str = "新问股会话",
                         strategy: str | None = None) -> ChatSession:
    """创建新会话。"""
    session = ChatSession(
        session_id=uuid.uuid4().hex,
        user_id=user_id,
        title=title or "新问股会话",
        active_strategy=strategy,
        created_at=_now(),
        updated_at=_now(),
    )
    doc = session.model_dump()
    doc["_id"] = session.session_id
    await col(_COL).insert_one(doc)
    return session


async def get_session(session_id: str) -> ChatSession | None:
    doc = await col(_COL).find_one({"session_id": session_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return ChatSession(**doc)


async def list_sessions(user_id: str, limit: int = 50) -> list[ChatSession]:
    cursor = col(_COL).find({"user_id": user_id}).sort("updated_at", -1).limit(limit)
    out = []
    async for doc in cursor:
        doc.pop("_id", None)
        out.append(ChatSession(**doc))
    return out


async def append_turn(session_id: str, turn: ChatTurn) -> None:
    """向会话追加一条消息（不改变预算计数）。"""
    await col(_COL).update_one(
        {"session_id": session_id},
        {"$push": {"messages": turn.model_dump()}, "$set": {"updated_at": _now()}},
    )


async def mark_budget_exceeded(session_id: str) -> None:
    await col(_COL).update_one(
        {"session_id": session_id}, {"$set": {"status": "budget_exceeded"}}
    )


async def charge_budget(session_id: str, tokens_in: int, tokens_out: int,
                        cost: float, model_name: str, count_round: bool = True) -> bool:
    """原子扣减会话预算：条件 $inc 保证不超卖 + 上限护栏。

    - count_round=True（入轮门禁）：rounds+1，同时校验 rounds/tokens/cost 均未触顶，
      任一项触顶则更新失败（matched=0）→ 返回 False，调用方据此中断（budget_exceeded）。
    - count_round=False（执行后记账）：仅追加 tokens/cost 与模型名，不再重复计轮次。
    """
    mr, mt, mc = _budget_limits()
    budget = {
        "total_tokens": tokens_in + tokens_out,
        "total_input": tokens_in,
        "total_output": tokens_out,
        "total_cost": cost,
    }
    if count_round:
        budget["rounds"] = 1
    inc = {f"budget.{k}": v for k, v in budget.items()}
    condition = {
        "session_id": session_id,
        "status": "active",
        "$and": [
            {"$or": [{"budget.rounds": {"$exists": False}}, {"budget.rounds": {"$lt": mr}}]},
            {"$or": [{"budget.total_tokens": {"$exists": False}}, {"budget.total_tokens": {"$lt": mt}}]},
            {"$or": [{"budget.total_cost": {"$exists": False}}, {"budget.total_cost": {"$lt": mc}}]},
        ],
    }
    result = await col(_COL).update_one(
        condition,
        {"$inc": inc,
         "$set": {"budget.model_name": model_name, "updated_at": _now()}},
    )
    return result.matched_count > 0


async def close_session(session_id: str) -> None:
    await col(_COL).update_one(
        {"session_id": session_id}, {"$set": {"status": "closed", "updated_at": _now()}}
    )


def public_view(session: ChatSession) -> dict:
    """会话对外序列化（不暴露内部字段）。"""
    return {
        "session_id": session.session_id,
        "title": session.title,
        "status": session.status,
        "active_strategy": session.active_strategy,
        "message_count": len(session.messages),
        "created_at": session.created_at.isoformat(),
        "updated_at": session.updated_at.isoformat(),
        "budget": {
            "rounds": session.budget.rounds,
            "total_tokens": session.budget.total_tokens,
            "total_cost": round(session.budget.total_cost, 4),
        },
    }


async def budget_view(session_id: str) -> dict | None:
    s = await get_session(session_id)
    if not s:
        return None
    b = s.budget
    return {
        "rounds_used": b.rounds,
        "tokens_used": b.total_tokens,
        "cost_used": round(b.total_cost, 4),
        "model_name": b.model_name,
    }