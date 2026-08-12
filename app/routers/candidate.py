"""候选池路由：行业 → 个股 → 择时 三层流水线的对外接口。

接口：
  GET  /api/candidate/industries         强势行业列表（Tab1）
  GET  /api/candidate/members?industry=  某行业成分股（Tab1 → 预览）
  GET  /api/candidate/stocks?industry=   某行业候选个股（top30，ΔG过滤+择时预览）
  POST /api/candidate/favorites/batch    批量加入自选
"""

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.candidate_pool import candidate_pool_service

router = APIRouter(prefix="/candidate", tags=["candidate"])
logger = logging.getLogger("webapi")


class BatchFavoriteIn(BaseModel):
    """批量加入自选入参。"""
    items: list[dict] = Field(default_factory=list)


@router.get("/industries")
async def candidate_industries(top_n: int = 20, as_of: str | None = None,
                               _: dict = Depends(get_current_user)):
    """第1层：强势行业列表。"""
    try:
        data = await candidate_pool_service.get_candidate_industries(top_n=top_n, as_of=as_of)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/industries] 失败: {e}")
        return ok({"as_of": as_of or "", "industries": []})


@router.get("/members")
async def candidate_members(industry: str, as_of: str | None = None,
                            _: dict = Depends(get_current_user)):
    """某行业成分股清单（Tab1 预览用）。"""
    if not industry:
        return ok({"as_of": as_of or "", "industry": "", "items": [], "member_count": 0})
    try:
        data = candidate_pool_service.get_candidate_industry_members(industry, as_of=as_of)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/members] 失败: {e}")
        return ok({"as_of": as_of or "", "industry": industry, "items": [], "member_count": 0})


@router.get("/stocks")
async def candidate_stocks(industry: str, limit: int = 30, as_of: str | None = None,
                           with_timing: bool = True,
                           _: dict = Depends(get_current_user)):
    """第2层+第3层：某行业候选个股（top30，ΔG 过滤 + 择时预览）。"""
    try:
        data = await candidate_pool_service.get_candidate_stocks(
            industry=industry, limit=limit, as_of=as_of, with_timing=with_timing)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/stocks] 失败: {e}")
        return ok({"as_of": as_of or "", "industry": industry, "items": [], "total": 0})


@router.post("/favorites/batch")
async def candidate_batch_favorites(payload: BatchFavoriteIn,
                                    current_user: dict = Depends(get_current_user)):
    """批量加入自选。"""
    try:
        res = await candidate_pool_service.batch_add_favorites(
            user_id=current_user["id"], items=payload.items)
        return ok(res)
    except Exception as e:
        logger.exception(f"[candidate/favorites/batch] 失败: {e}")
        return ok({"added": 0, "failed": len(payload.items), "total": len(payload.items)})