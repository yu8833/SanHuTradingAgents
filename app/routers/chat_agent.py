"""Agent 策略问股 API 路由。

- POST    /api/chat-agent/sessions            新建会话 {title?, strategy?}
- GET     /api/chat-agent/sessions            本人会话列表
- GET     /api/chat-agent/sessions/{sid}       会话详情（历史消息）
- DELETE  /api/chat-agent/sessions/{sid}       关闭会话
- POST    /api/chat-agent/turns                核心：{session_id,message} → NDJSON 流式
- GET     /api/chat-agent/budget/{sid}         剩余额度
- GET     /api/chat-agent/strategies           转发策略列表（含适配画像）
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.core.response import ok
from app.models.chat import ChatSessionCreateRequest, ChatTurnRequest
from app.routers.auth_db import get_current_user
from app.services import chat_agent_service
from app.services import chat_session_service as ssvc

router = APIRouter(prefix="/api/chat-agent", tags=["chat-agent"])
logger = logging.getLogger("webapi")


async def _get_optional_user(authorization: str | None = Header(default=None)) -> dict:
    """可选鉴权：无 token 视为 guest（用 ip/空 id 隔离）。"""
    if not authorization:
        return {"id": "guest", "username": "guest", "is_guest": True}
    try:
        user = await get_current_user(authorization)
        user["is_guest"] = False
        return user
    except Exception:
        return {"id": "guest", "username": "guest", "is_guest": True}


def _uid(user: dict) -> str:
    return str(user.get("id") or user.get("user_id") or "guest")


@router.post("/sessions")
async def create_session(req: ChatSessionCreateRequest,
                         user: dict = Depends(_get_optional_user)):
    try:
        s = await ssvc.create_session(_uid(user), title=req.title, strategy=req.strategy)
        return ok(ssvc.public_view(s))
    except Exception as e:
        logger.error(f"创建问股会话失败: {e}")
        raise HTTPException(500, f"创建会话失败: {e}") from e


@router.get("/sessions")
async def list_sessions(user: dict = Depends(_get_optional_user)):
    try:
        sessions = await ssvc.list_sessions(_uid(user))
        return ok([ssvc.public_view(s) for s in sessions])
    except Exception as e:
        logger.error(f"列出问股会话失败: {e}")
        return ok([], message="获取失败")


@router.get("/sessions/{sid}")
async def get_session(sid: str, user: dict = Depends(_get_optional_user)):
    s = await ssvc.get_session(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    if s.user_id != _uid(user):
        raise HTTPException(403, "无权访问该会话")
    base = ssvc.public_view(s)
    base["messages"] = [
        {"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in s.messages
    ]
    return ok(base)


@router.delete("/sessions/{sid}")
async def close_session(sid: str, user: dict = Depends(_get_optional_user)):
    s = await ssvc.get_session(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    if s.user_id != _uid(user):
        raise HTTPException(403, "无权访问该会话")
    await ssvc.close_session(sid)
    return ok({"session_id": sid, "status": "closed"})


@router.post("/turns")
async def run_turn(req: ChatTurnRequest, user: dict = Depends(_get_optional_user)):
    s = await ssvc.get_session(req.session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    if s.user_id != _uid(user):
        raise HTTPException(403, "无权访问该会话")

    # LLM 配置复用 vibe_research._get_llm_config（有 key 的首个模型）
    llm_cfg = _get_llm_config_shared()

    async def gen():
        async for evt in chat_agent_service.run_turn(req.session_id, req.message, llm_cfg):
            yield json.dumps(evt, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("/budget/{sid}")
async def budget(sid: str, user: dict = Depends(_get_optional_user)):
    s = await ssvc.get_session(sid)
    if not s:
        raise HTTPException(404, "会话不存在")
    if s.user_id != _uid(user):
        raise HTTPException(403, "无权访问该会话")
    b = await ssvc.budget_view(sid)
    return ok(b)


@router.get("/strategies")
async def strategies(user: dict = Depends(_get_optional_user)):
    """策略列表（含适配画像），供对话策略下拉。"""
    try:
        from app.strategy_system.registry import registry
        items = [s.to_dict() for s in registry.all()]
        return ok(items)
    except Exception as e:
        logger.error(f"获取策略列表失败: {e}")
        return ok([], message="获取失败")


def _get_llm_config_shared():
    """从系统配置取第一个可用的 LLM 配置（与 vibe chat 一致）。"""
    try:
        from app.routers.vibe_research import _get_llm_config
        return _get_llm_config()
    except Exception as e:
        logger.error(f"获取 LLM 配置失败: {e}")
        return None