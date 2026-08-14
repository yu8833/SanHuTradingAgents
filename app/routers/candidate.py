"""候选池路由：行业 → 个股 → 择时 三层流水线的对外接口。

接口：
  GET  /api/candidate/industries         强势行业列表（Tab1）
  GET  /api/candidate/members?industry=  某行业成分股（Tab1 → 预览）
  GET  /api/candidate/stocks?industry=   某行业候选个股（top30，ΔG过滤+择时预览）
  POST /api/candidate/favorites/batch    批量加入自选
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.candidate_pool import candidate_pool_service
from app.services.candidate_pool.candidate_pool_service import (
    local_industries_for, _aggregate_sector_dg,
)

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
    """第2层+第3层：某行业候选个股（top30，ΔG 过滤 + 择时预览，仅保留三买三卖信号）。"""
    try:
        data = await candidate_pool_service.get_candidate_stocks(
            industry=industry, limit=limit, as_of=as_of, with_timing=with_timing)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/stocks] 失败: {e}")
        return ok({"as_of": as_of or "", "industry": industry, "items": [], "total": 0})


@router.get("/stocks-overview")
async def candidate_stocks_overview(top_n: int = 10, as_of: str | None = None,
                                    industries: str | None = None,
                                    _: dict = Depends(get_current_user)):
    """个股筛选默认视图（未选行业）：前 top_n 个行业，每行业 top 3 只三买三卖信号个股，共约 30 只。

    industries 为逗号分隔的行业名列表（默认取行业资金流排名的前 top_n 个）。
    """
    ind_names = [s.strip() for s in (industries or "").split(",") if s.strip()] or None
    try:
        data = await candidate_pool_service.get_candidate_stocks_overview(
            top_n=top_n, as_of=as_of, industries=ind_names)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/stocks-overview] 失败: {e}")
        return ok({"as_of": as_of or "", "industry": "", "items": [], "total": 0})


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


# 象限展示优先级（平局时）
_DG_PRIORITY = ["双击", "反转", "见顶", "双杀"]


@router.get("/industry-screening")
async def candidate_industry_screening(top_n: int = 10, refresh: bool = False,
                                       _: dict = Depends(get_current_user)):
    """行业筛选：行业 ETF 主力净流入资金流排名（资金为王，动量/量能仅展示不参与排序）。

    对每个行业 best-effort 融合行业 ΔG 景气（ETF 主题 → 本地细类映射聚合，未覆盖则 sector_dg 为空）。
    refresh=1 时强制实时采集（约20s），否则读快照秒回。
    """
    try:
        from app.services.etf_radar import get_etf_radar_service
        data = await get_etf_radar_service().get_summary(top_n=top_n, refresh=refresh)
        rankings = data.get("rankings", []) or []
        if rankings:
            await _attach_sector_dg(rankings)
        return ok(data)
    except Exception as e:
        logger.exception(f"[candidate/industry-screening] 失败: {e}")
        return ok({"success": False, "message": "行业筛选加载失败",
                   "as_of": "", "updated_at": "", "top": [], "rankings": [],
                   "industry_count": 0, "industry_flows": []})


async def _attach_sector_dg(items: list[dict]) -> None:
    """为行业资金流排名融合行业 ΔG 景气（ETF 主题 → 本地细类映射聚合，失败静默置空）。

    对每个 ETF 行业，并行取其所映射本地细类的 get_sector_dg，再按成分股数加权聚合
    出行业级景气（主导象限 / 平均 G / 平均 ΔG / 数据覆盖）。
    """
    try:
        from app.services.dg_prosperity_service import get_dg_prosperity_service
    except Exception as e:
        logger.warning(f"行业筛选 ΔG 融合失败（导入失败）: {e}")
        for it in items:
            it["sector_dg"] = None
        return

    try:
        dg_svc = get_dg_prosperity_service()

        # 收集所有需要查询的本地细类（去重）
        local_names: dict[str, list[str]] = {}   # local -> [etf industries]
        for it in items:
            etf = it.get("industry", "")
            for local in local_industries_for(etf):
                local_names.setdefault(local, []).append(etf)

        # 并行查询所有本地细类的行业 ΔG
        results = await asyncio.gather(
            *[dg_svc.get_sector_dg(n) for n in local_names],
            return_exceptions=True,
        )
        local_dg: dict[str, dict] = {}
        for n, res in zip(local_names, results):
            if isinstance(res, dict) and res.get("member_count"):
                local_dg[n] = res

        for it in items:
            etf = it.get("industry", "")
            locals_of_etf = local_industries_for(etf)
            agg = _aggregate_sector_dg([local_dg[n] for n in locals_of_etf if n in local_dg])
            it["sector_dg"] = agg
    except Exception as e:
        logger.warning(f"行业筛选 ΔG 融合失败（跳过）: {e}")
        for it in items:
            it["sector_dg"] = None