"""Agent 策略问股 —— 会话数据模型。

会话存储在 MongoDB `chat_sessions` 集合（集合名在 collections.py 登记），
预算计数（轮次/累计token/费用）随会话存储，用条件 $inc 原子更新防并发超卖。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """一轮对话消息（user / assistant / tool）。"""

    role: str                       # user / assistant / tool
    content: str
    tool_calls: list[dict] | None = None   # LLM 发起的工具调用（tool 角色时回填结果）
    tool_name: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tokens_in: int = 0
    tokens_out: int = 0


class ChatBudget(BaseModel):
    """会话级预算运行计数。"""

    rounds: int = 0
    total_tokens: int = 0
    total_input: int = 0
    total_output: int = 0
    total_cost: float = 0.0
    model_name: str = ""


class ChatSession(BaseModel):
    """一次问股会话。"""

    session_id: str = Field(...)
    user_id: str = Field(...)
    title: str = "新问股会话"
    messages: list[ChatTurn] = Field(default_factory=list)
    active_strategy: str | None = None
    status: str = "active"          # active / closed / budget_exceeded
    budget: ChatBudget = Field(default_factory=ChatBudget)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatTurnRequest(BaseModel):
    """发起一轮问股。"""

    session_id: str
    message: str


class ChatSessionCreateRequest(BaseModel):
    """新建会话。"""

    title: str = "新问股会话"
    strategy: str | None = None