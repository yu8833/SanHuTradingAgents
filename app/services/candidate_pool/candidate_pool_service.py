"""候选池编排服务：0→1→2→3 层流水线，对外输出候选池。

编排：
  第0层 大盘开关（可复用 market_regime，本期先不阻塞，仅返回 trend 供前端提示）
  第1层 industry_layer.get_industries  → 强势行业
  第2层 stock_score_layer.score_stocks → 该行业成分股多因子打分 top30
  第3层 ΔG 硬过滤 + 三买三卖择时预览（复用 three_buys_three_sells_service）

对外接口（供 router 调用）：
  - get_candidate_industries(top_n)
  - get_candidate_industry_members(industry)
  - get_candidate_stocks(industry, limit)
  - batch_add_favorites(user_id, items)
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import get_mongo_db_sync
from app.services.candidate_pool import industry_layer, stock_score_layer
from app.services.favorites_service import favorites_service

logger = logging.getLogger(__name__)


async def get_candidate_industries(top_n: int = 20, as_of=None) -> dict:
    """第1层：强势行业列表，并叠加行业级 ΔG 景气（宏观层面判断）。

    对 top_n 个强势行业逐个聚合其成分股 ΔG，输出主导象限/平均 G/分布，供前端展示。
    """
    data = industry_layer.get_industries(top_n=top_n, as_of=as_of)
    industries = data.get("industries", [])
    if not industries:
        return data

    try:
        from app.services.dg_prosperity_service import get_dg_prosperity_service
        dg_svc = get_dg_prosperity_service()
        # 并行聚合各行业成分股 ΔG，避免逐行业串行 DB 查询拖慢候选池加载
        ind_names = [ind.get("industry", "") for ind in industries]
        results = await asyncio.gather(
            *[dg_svc.get_sector_dg(n) for n in ind_names],
            return_exceptions=True,
        )
        for ind, res in zip(industries, results):
            if isinstance(res, dict):
                ind["sector_dg"] = res
            else:
                ind["sector_dg"] = {}
                logger.warning(f"行业 {ind.get('industry')} ΔG 获取失败（跳过）: {res}")
    except Exception as e:
        logger.warning(f"候选池行业级 ΔG 批量获取失败（跳过）: {e}")

    return data


def get_candidate_industry_members(industry: str, as_of=None) -> dict:
    """某行业成分股清单（供 Tab2 数据源）。"""
    return industry_layer.get_industry_members(industry, as_of=as_of)


async def _apply_dg_filter(items: list[dict]) -> list[dict]:
    """ΔG 硬过滤：戴维斯双杀（double_kill）直接剔除，unknown 降权不剔除。"""
    if not items:
        return items
    codes = [it["code"] for it in items]
    dg_map = {}
    try:
        from app.services.dg_prosperity_service import get_dg_prosperity_service
        dg_svc = get_dg_prosperity_service()
        dg_map = await dg_svc.get_quadrant_batch(codes)
    except Exception as e:
        logger.warning(f"候选池 ΔG 过滤失败（跳过）: {e}")
    out = []
    for it in items:
        d = dg_map.get(str(it["code"]), {})
        q = d.get("quadrant", "unknown")
        it["dg_quadrant"] = d.get("quadrant_label", "数据不足")
        it["dg_available"] = bool(d.get("available"))
        it["dg_g"] = d.get("g")
        it["dg_dg"] = d.get("dg")
        if q == "double_kill":
            continue
        out.append(it)
    return out


async def _attach_timing_preview(items: list[dict]) -> list[dict]:
    """第3层：对候选池内每只票做三买三卖择时预览（复用扫描逻辑，限制在候选池内）。"""
    if not items:
        return items
    try:
        from app.services.three_buys_three_sells_service import (
            get_three_buys_three_sells_service,
        )
        svc = get_three_buys_three_sells_service()
        codes = [it["code"] for it in items]
        # 复用三买三卖扫描，但传入 pool 限制代码集（避免全市场 5000 只）
        # include_signaless: 候选池保留全部候选股，供辅助信号/base 信息展示（不改变全局扫描语义）
        params = {"limit": len(codes), "pool": codes, "enable_dg_filter": False,
                  "include_signaless": True}
        result = await svc.scan_three_buys_three_sells(params)
        sig_map = {it["code"]: it for it in result.get("items", [])}
        for it in items:
            sig = sig_map.get(it["code"])
            if sig:
                it["signal_type"] = sig.get("primary_signal_type", "")
                it["signal_label"] = sig.get("primary_signal_label", "")
                it["signal_score"] = sig.get("score", 0)
                it["market_trend"] = sig.get("market_trend", "")
                # 辅助信号（教材第三章）：aux_score + 明细 + 预警
                it["aux_score"] = sig.get("aux_score", 50.0)
                it["auxiliary"] = sig.get("auxiliary", {})
                it["aux_warnings"] = sig.get("aux_warnings", [])
            else:
                it["signal_type"] = ""
                it["signal_label"] = "无信号"
                it["signal_score"] = 0
                it["aux_score"] = 50.0
                it["auxiliary"] = {}
                it["aux_warnings"] = []
    except Exception as e:
        logger.warning(f"候选池择时预览失败（跳过）: {e}")
        for it in items:
            it.setdefault("signal_type", "")
            it.setdefault("signal_label", "--")
            it.setdefault("signal_score", 0)
    return items


async def get_candidate_stocks(industry: str, limit: int = 30, as_of=None,
                               with_timing: bool = True) -> dict:
    """第2层 + 第3层：对某行业成分股多因子打分 → ΔG 过滤 → 择时预览。

    编排顺序：打分截断 top(limit*2) → ΔG 过滤 → 择时预览 → 按 quality_score 排序。
    同时返回行业级 ΔG 景气（get_sector_dg，宏观层面判断）。
    """
    scored = stock_score_layer.score_stocks(industry=industry, as_of=as_of,
                                            limit=limit * 2)
    items = scored.get("items", [])
    # 先按质量分排序，避免 ΔG 过滤后顺序错乱（score_stocks 已按分排序）
    if with_timing:
        items = await _apply_dg_filter(items)
        items = await _attach_timing_preview(items)

    # 排序：有买入信号优先，其次质量分高
    def _key(it):
        has_sig = it.get("signal_type", "").startswith("B")
        return (1 if has_sig else 0, it.get("quality_score", 0))

    items.sort(key=_key, reverse=True)
    items = items[:limit]

    # 行业级 ΔG 景气（宏观层面，独立于个股过滤）
    sector_dg = {}
    try:
        from app.services.dg_prosperity_service import get_dg_prosperity_service
        dg_svc = get_dg_prosperity_service()
        sector_dg = await dg_svc.get_sector_dg(industry)
    except Exception as e:
        logger.warning(f"候选池行业级 ΔG 获取失败（跳过）: {e}")

    return {
        "as_of": scored.get("as_of"),
        "industry": industry,
        "sector_dg": sector_dg,
        "items": items,
        "total": len(items),
    }


async def batch_add_favorites(user_id: str, items: list[dict]) -> dict:
    """批量加入自选池。items: [{code, name}]。"""
    added = 0
    failed = 0
    for it in items:
        code = str(it.get("code") or "").strip()
        name = str(it.get("name") or "").strip()
        if not code:
            failed += 1
            continue
        try:
            ok = await favorites_service.add_favorite(
                user_id=user_id,
                stock_code=code,
                stock_name=name or code,
                market="A股",
            )
            if ok:
                added += 1
            else:
                failed += 1
        except Exception as e:
            logger.warning(f"加入自选失败 {code}: {e}")
            failed += 1
    return {"added": added, "failed": failed, "total": len(items)}