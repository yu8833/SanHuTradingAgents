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

# ETF 主题行业 → 本地行业（stock_basic_info.industry，190 细类）映射，用于行业 ΔG 景气聚合
# 与个股筛选的成分股定位。未覆盖的 ETF 行业不做 ΔG 融合（sector_dg=None）。
ETF_TO_LOCAL_INDUSTRIES = {
    "通信": ["通信设备", "电信运营", "电信、广播电视和卫星传输服务"],
    "军工": ["船舶", "航空", "铁路、船舶、航空航天和其他运输设备制造业"],
    "有色金属": ["有色金属冶炼和压延加工业", "有色金属矿采选业", "铜", "铝", "铅锌", "黄金", "小金属"],
    "煤炭": ["煤炭开采", "煤炭开采和洗选业", "焦炭加工"],
    "机械": ["通用设备制造业", "专用设备制造业", "工程机械", "机床制造", "机械基件", "轻工机械", "化工机械", "纺织机械", "农用机械"],
    "化工": ["化学原料和化学制品制造业", "化学纤维制造业", "化工原料", "日用化工", "农药化肥", "染料涂料", "橡胶"],
    "银行": ["银行"],
    "电子": ["元器件", "IT设备", "计算机、通信和其他电子设备制造业", "电器仪表"],
    "钢铁": ["普钢", "特种钢", "钢加工", "黑色金属冶炼和压延加工业", "黑色金属矿采选业"],
    "交通运输": ["铁路", "公路", "机场", "港口", "空运", "水运", "航空运输业", "道路运输业", "铁路运输业", "水上运输业"],
    "环保": ["环境保护", "生态保护和环境治理业", "废弃资源综合利用业", "水务"],
    "汽车": ["汽车制造业", "汽车整车", "汽车服务", "汽车配件", "摩托车"],
    "房地产": ["全国地产", "区域地产", "房地产业", "房产服务", "园区开发"],
    "新能源": ["新型电力", "水力发电", "电气设备"],
    "人工智能": ["软件和信息技术服务业", "互联网", "互联网和相关服务"],
    "传媒": ["影视音像", "出版业", "新闻和出版业", "广告包装", "广播、电视、电影和录音制作业", "互联网"],
    "农业": ["农业", "种植业", "畜牧业", "渔业", "农、林、牧、渔专业及辅助性活动", "饲料"],
    "消费": ["食品", "白酒", "啤酒", "软饮料", "乳制品", "百货", "超市连锁", "家用电器", "家居用品", "纺织", "服饰"],
    "计算机": ["软件和信息技术服务业", "软件服务", "互联网", "互联网和相关服务", "计算机、通信和其他电子设备制造业"],
    "电力": ["电力、热力生产和供应业", "火力发电", "水力发电", "新型电力", "供气供热"],
    "半导体": ["半导体"],
    "证券": ["证券", "资本市场服务", "多元金融", "其他金融业"],
    "医药": ["医药制造业", "医药商业", "中成药", "生物制药", "化学制药", "医疗保健", "卫生"],
}


def local_industries_for(etf: str) -> list[str]:
    """返回 ETF 主题行业对应的本地行业细类列表（未覆盖返回空列表）。"""
    return ETF_TO_LOCAL_INDUSTRIES.get(etf or "", [])


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


def _aggregate_sector_dg(dgs: list[dict]) -> dict | None:
    """把多个本地细类的行业 ΔG 按成分股数加权聚合成一个行业级景气（ETF 行业用）。"""
    valid = [d for d in dgs if d and d.get("data_count")]
    if not valid:
        return None

    member_count = sum(int(d.get("member_count") or 0) for d in valid)
    data_count = sum(int(d.get("data_count") or 0) for d in valid)

    # 平均 G / 平均 ΔG（按 data_count 加权）
    wsum = data_count
    avg_g = None
    avg_dg = None
    if wsum:
        g_vals = [(float(d.get("avg_g")), int(d.get("data_count") or 0))
                  for d in valid if d.get("avg_g") is not None]
        dg_vals = [(float(d.get("avg_dg")), int(d.get("data_count") or 0))
                   for d in valid if d.get("avg_dg") is not None]
        if g_vals:
            avg_g = round(sum(v * w for v, w in g_vals) / sum(w for _, w in g_vals), 2)
        if dg_vals:
            avg_dg = round(sum(v * w for v, w in dg_vals) / sum(w for _, w in dg_vals), 2)

    # 四象限分布聚合 + 主导象限（平局按 双击>反转>见顶>双杀）
    dist: dict[str, int] = {}
    for d in valid:
        for q, c in (d.get("distribution") or {}).items():
            dist[q] = dist.get(q, 0) + int(c or 0)
    dominant = "unknown"
    for q in ["double_click", "reversal", "peaking", "double_kill"]:
        if dist.get(q, 0) > 0:
            dominant = q
            break
    labels = {}
    try:
        from app.services.dg_prosperity_service import QUADRANT_LABELS
        labels = QUADRANT_LABELS
    except Exception:
        labels = {}
    quadrant_label = labels.get(dominant, "数据不足")

    report_period = ""
    for d in valid:
        if d.get("report_period"):
            report_period = max(report_period, str(d["report_period"]))

    return {
        "industry": dgs[0].get("industry", ""),
        "quadrant": dominant,
        "quadrant_label": quadrant_label,
        "quadrant_color": "info",
        "avg_g": avg_g,
        "avg_dg": avg_dg,
        "member_count": member_count,
        "data_count": data_count,
        "distribution": dist,
        "report_period": report_period,
        "available": True,
    }


async def get_candidate_stocks(industry: str, limit: int = 30, as_of=None,
                               with_timing: bool = True) -> dict:
    """第2层 + 第3层：对某行业成分股多因子打分 → ΔG 过滤 → 择时预览。

    编排顺序：打分截断 top(limit*2) → ΔG 过滤 → 择时预览 → 按 quality_score 排序。
    industry 可能是 ETF 主题行业名（来自行业筛选），也可能是本地细类行业名：
      - ETF 主题行业 → 映射到多个本地细类分别打分后合并。
      - 本地细类行业 → 直接打分。
    同时返回行业级 ΔG 景气（宏观层面判断）。
    """
    dg_svc = None
    local_inds = local_industries_for(industry)

    if local_inds:
        # ETF 主题行业：对每个本地细类打分后合并
        scored_list = []
        for ind in local_inds:
            scored = stock_score_layer.score_stocks(industry=ind, as_of=as_of,
                                                    limit=limit * 2)
            scored_list.append(scored)
        items = []
        for scored in scored_list:
            items.extend(scored.get("items", []))
        as_of_date = next((s.get("as_of") for s in scored_list if s.get("as_of")), None)
        # 去重（部分本地细类可能重叠，如「银行」仅一个，但同一股票不应重复）
        seen = set()
        uniq = []
        for it in items:
            c = it.get("code")
            if c in seen:
                continue
            seen.add(c)
            uniq.append(it)
        items = uniq
        # 行业级 ΔG：聚合全部映射本地细类的景气
        try:
            from app.services.dg_prosperity_service import get_dg_prosperity_service
            dg_svc = get_dg_prosperity_service()
            results = await asyncio.gather(
                *[dg_svc.get_sector_dg(ind) for ind in local_inds],
                return_exceptions=True,
            )
            valid_dg = [r for r in results if isinstance(r, dict)]
            sector_dg = _aggregate_sector_dg(valid_dg) or {}
        except Exception as e:
            logger.warning(f"候选池 ETF 行业级 ΔG 聚合失败（跳过）: {e}")
            sector_dg = {}
    else:
        # 本地细类行业：直接打分
        scored = stock_score_layer.score_stocks(industry=industry, as_of=as_of,
                                                limit=limit * 2)
        items = scored.get("items", [])
        as_of_date = scored.get("as_of")
        sector_dg = {}
        try:
            from app.services.dg_prosperity_service import get_dg_prosperity_service
            dg_svc = get_dg_prosperity_service()
            sector_dg = await dg_svc.get_sector_dg(industry)
        except Exception as e:
            logger.warning(f"候选池行业级 ΔG 获取失败（跳过）: {e}")

    # 先按质量分排序，避免 ΔG 过滤后顺序错乱
    items.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    if with_timing:
        items = await _apply_dg_filter(items)
        items = await _attach_timing_preview(items)
        # 个股筛选展示三买三卖信号（B1/B2/B3 买入 + S1/S2/S3 卖出），其余剔除
        items = [it for it in items if it.get("signal_type") in ("B1", "B2", "B3", "S1", "S2", "S3")]

    # 此时已全部为三买三卖信号，按质量分排序
    items.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    items = items[:limit]

    return {
        "as_of": as_of_date,
        "industry": industry,
        "sector_dg": sector_dg,
        "items": items,
        "total": len(items),
    }


async def get_candidate_stocks_overview(top_n: int = 10, per_industry: int = 3,
                                        limit: int = 30, as_of=None,
                                        industries: list[str] | None = None) -> dict:
    """个股筛选默认视图（未选择行业）：前 top_n 个行业，每行业取 per_industry 只 B 信号个股。

    复用 get_candidate_stocks（已只保留 B1/B2/B3 信号），按行业资金流排名顺序聚合，
    去重后共约 limit 只，供前端默认展示。

    industries 可显式传入（默认取行业资金流排名的前 top_n 个行业名），否则回退到强势行业列表。
    """
    if industries:
        ind_names = [n for n in (industries or []) if n][:top_n]
    else:
        inds = await get_candidate_industries(top_n=top_n, as_of=as_of)
        ind_names = [ind.get("industry", "") for ind in (inds.get("industries", []) or [])
                     if ind.get("industry")]
    if not ind_names:
        return {"as_of": as_of or "", "industry": "", "items": [], "total": 0}

    results = await asyncio.gather(
        *[get_candidate_stocks(ind, limit=per_industry, as_of=as_of)
          for ind in ind_names],
        return_exceptions=True,
    )
    items = []
    for res in results:
        if isinstance(res, dict):
            items.extend(res.get("items", []))
    # 去重（同一股票可能出现在多个 ETF→细类的映射里）
    seen = set()
    uniq = []
    for it in items:
        c = it.get("code")
        if c in seen:
            continue
        seen.add(c)
        uniq.append(it)
        if len(uniq) >= limit:
            break
    return {"as_of": as_of or "", "industry": "",
            "items": uniq, "total": len(uniq)}


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