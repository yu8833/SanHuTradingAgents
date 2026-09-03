"""当日计划编排层 —— 环境 → 行业 → 个股 → 计划（5.3/5.4）。

把宏观方向基准与候选池打通：
- 读取今日宏观快照（direction/basis），作为"环境"约束；
- 取候选池强势行业 + B 信号个股（已 TTL 缓存，秒回），作为"行业/个股"来源；
- 按方向执行过滤（偏空→剔除 B1 追涨），产出"计划"候选 + 全程审计痕迹（5.3）；
- 每个候选带来源标签(5.4)，但不自动落库——由前端人工确认/改价/删除后才写 daily_plans。

保持"自动生成 ≠ 自动下单"，所有候选均可否。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Awaitable

from app.services.macro import macro_service
from app.services import plan_service

logger = logging.getLogger(__name__)

# 供应链 Redis 进度事件 JSON 序列化兜底（写进度含 datetime 字段）
def _json_default(obj: Any) -> Any:
    from datetime import datetime, date
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

# 四段流水线进度映射（统一整数刻度，仅前进不回退）；「卖出」为卖出观测附加段，与「计划」同终态
STAGE_PROGRESS = {"环境": 25, "行业": 50, "个股": 75, "计划": 100, "卖出": 100}
_JOB_RESULT_TTL = 3600  # 后台任务结果在 Redis 保留 1h，供前端 done 后取回

# 买入计划默认止损距离（相对触发价）：
#  偏多=7%；偏空/观望=10%（更宽，给足波动空间，同时配合低置信度减仓）
STOP_PCT_BULL = 0.07
STOP_PCT_CONSERVATIVE = 0.10
# 每只候选买入统一卖出条件模板
SELL_CONDITION_TMPL = "跌破MA60 或 盈利{target}% 分批止盈，触及止损无条件离场"

# 候选阈值：行业数 / 每行业个股数 / 候选上限
DEFAULT_TOP_N = 10
DEFAULT_PER_INDUSTRY = 3
DEFAULT_LIMIT = 20


def _audit(step: str, scanned: int, rule: str, kept: int, dropped: int, reasons: list[str]) -> dict:
    return {
        "step": step,
        "scanned": scanned,
        "rule": rule,
        "kept": kept,
        "dropped": dropped,
        "reasons": reasons,
    }


def _direction_tag(direction: str | None, basis: dict | None) -> str:
    # 以宏观基准四态为准（低置信度视为观望）
    if basis and basis.get("status"):
        return basis["status"]
    return direction or "中性"


async def _build_environment_step() -> dict:
    """环境段：读取今日宏观快照，得到方向基准 + 触发信号。

    宏观快照应由盘前 8:15 定时任务（或用户手动「刷新宏观快照」）预先生成。
    这里只做**纯读取**，缺失时快速返回「未就绪」降级 step，绝不隐式触发
    refresh_macro_snapshot() —— 其现场拉取外围指数/LLM 解读实测可达 100-200s，
    会把「当日计划生成」这个本应秒回的后台任务拖到超时，前端表现为按钮无限转圈。
    """
    snap = await macro_service.get_macro_snapshot()
    if snap is None:
        step = _audit(
            "环境", scanned=0,
            rule="宏观快照未就绪（等待盘前 8:15 自动生成，或手动刷新宏观快照）",
            kept=0, dropped=0,
            reasons=[
                "今日宏观快照尚未生成",
                "请先在「宏观方向」卡片点击刷新，或等待盘前定时任务",
            ],
        )
        step["meta"] = {"direction": None, "basis": None, "ready": False}
        return step
    rule = snap.get("rule") or {}
    basis = snap.get("basis") or {}
    signals = rule.get("signals") or []
    strong = [s for s in signals if s.get("score", 0) > 0]
    weak = [s for s in signals if s.get("score", 0) < 0]
    total = len(strong) + len(weak)
    step = _audit(
        "环境", scanned=total,
        rule=f"方向 {basis.get('status') or rule.get('direction')} · 置信 {basis.get('confidence', 0)}%",
        kept=total, dropped=0,
        reasons=[
            f"触发 {total} 条信号",
            f"利多 {len(strong)} / 利空 {len(weak)}",
            "低置信度 → 观望并减半仓位" if basis.get("low_confidence") else "置信度达标，可作为方向约束",
        ],
    )
    return {**step, "meta": {"direction": rule.get("direction"), "basis": basis, "ready": True}}


# ══════════════════════════════════════════════════════════════
# ── Stage2 行业方向预测：把「环境」与「行业」接通 ──
# 多因子评分（全部读库/快照，绝不现场拉网络）：
#   1) 动量：候选池强势行业 sector_score（industry_layer 结果级缓存）
#   2) 资金流：ETF 雷达 composite_score（etf_radar_snapshot 快照，纯读）
#   3) 资讯热度：宏观快照 news_top 标题 vs 行业关键词命中数
#   4) 方向×β：偏空压制高β行业、保住防御；偏多反之；低置信观望压缩行业区分度
# 输出「当日行业池」[{industry, forecast_score, confidence, factors}]，
# Stage3 个股段按该池**硬绑定**，实现「预测哪些行业会涨 → 只在该行业内挑股」。
# ══════════════════════════════════════════════════════════════
_HIGH_BETA_INDUSTRIES = {
    "军工", "有色金属", "半导体", "计算机", "传媒", "人工智能", "证券",
    "新能源", "汽车", "电子", "通信", "房地产",
}
_LOW_BETA_INDUSTRIES = {
    "银行", "保险", "食品", "白酒", "乳制品", "电力", "公共交通",
    "公用事业", "农业", "石油", "煤炭",
}
# 行业→资讯关键词（弱信号：标题命中即加权；与 ETF 主题名自动并集）
_EXTRA_NEWS_KEYWORDS = {
    "半导体": ("芯片", "晶圆", "集成电路", "存储"),
    "人工智能": ("AI", "大模型", "算力", "机器人"),
    "新能源": ("光伏", "风电", "锂电", "充电桩", "储能"),
    "医药": ("创新药", "医保", "药品"),
    "白酒": ("酿酒", "酒企", "白酒"),
    "汽车": ("新能源车", "整车", "车企"),
    "通信": ("5G", "光模块", "6G"),
    "有色金属": ("铜", "铝", "稀土", "黄金"),
    "煤炭": ("煤价", "煤炭"),
}
# 因子权重（0-100 分制，相对 50 基准加权偏离）
_W_MOM = 0.35
_W_FUND = 0.30
_W_NEWS = 0.15


def _industry_news_hits(news_list: list[dict], industry: str) -> int:
    """资讯标题命中次数：行业名 + 关联 ETF 主题名 + 别名关键词。"""
    from app.services.candidate_pool.candidate_pool_service import ETF_TO_LOCAL_INDUSTRIES
    kws = {industry}
    for theme, locals_ in ETF_TO_LOCAL_INDUSTRIES.items():
        if industry in locals_:
            kws.add(theme)
    kws.update(_EXTRA_NEWS_KEYWORDS.get(industry, ()))
    hits = 0
    for n in news_list or []:
        title = str(n.get("title") or "")
        if title and any(k in title for k in kws):
            hits += 1
    return hits


def _industry_fund_score(industry: str, radar_by_theme: dict[str, float]) -> float | None:
    """该细类行业关联 ETF 主题的资金流分均值；无映射返回 None（数据缺失）。"""
    from app.services.candidate_pool.candidate_pool_service import ETF_TO_LOCAL_INDUSTRIES
    scores = []
    for theme, locals_ in ETF_TO_LOCAL_INDUSTRIES.items():
        if industry in locals_ and theme in radar_by_theme:
            scores.append(radar_by_theme[theme])
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _beta_adjust(direction: str | None, industry: str) -> float:
    d = str(direction or "")
    if "空" in d:
        return -12.0 if industry in _HIGH_BETA_INDUSTRIES else (6.0 if industry in _LOW_BETA_INDUSTRIES else 0.0)
    if "多" in d:
        return 8.0 if industry in _HIGH_BETA_INDUSTRIES else (-4.0 if industry in _LOW_BETA_INDUSTRIES else 0.0)
    return 0.0


def _industry_confidence(basis: dict, mom: float | None, fund: float | None, news: float | None) -> float:
    """行业置信度：因子一致度 + 数据覆盖 + 方向置信；低置信观望时整体压低。"""
    m_ok = mom is not None
    f_ok = fund is not None
    n_ok = news is not None
    data_cover = (m_ok + f_ok + n_ok) / 3
    agree = 0
    if m_ok and mom >= 55:
        agree += 1
    if f_ok and fund >= 55:
        agree += 1
    if n_ok and news >= 60:
        agree += 1
    conv = 0.5 if (basis or {}).get("low_confidence") else ((basis or {}).get("confidence") or 50) / 100
    c = 0.35 * data_cover + 0.40 * (agree / 3) + 0.25 * conv
    return round(min(max(c * 100, 10), 95))


async def _build_industry_step(direction: str | None, basis: dict | None) -> dict:
    """行业段：盘前行业方向预测 → 当日行业池（供 Stage3 个股段硬绑定）。"""
    from app.services.candidate_pool import candidate_pool_service
    from app.services.candidate_pool.candidate_pool_service import ETF_TO_LOCAL_INDUSTRIES
    from app.services.macro import macro_service

    # ① 行业动量：候选池强势行业（含 sector_score；结果级缓存，热路径秒回）
    mom_map: dict[str, float] = {}
    try:
        inds = await candidate_pool_service.get_candidate_industries(top_n=DEFAULT_TOP_N * 2)
        for i in (inds.get("industries") or []):
            nm = (i.get("industry") or "").strip()
            if nm:
                mom_map[nm] = float(i.get("sector_score") or 50.0)
    except Exception as e:
        logger.warning(f"行业预测-动量读取失败: {e}")

    # ② 资金流：ETF 雷达快照（纯读 MongoDB，无网络副作用）
    radar_by_theme: dict[str, float] = {}
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        doc = await db["etf_radar_snapshot"].find_one(sort=[("as_of", -1), ("updated_at", -1)])
        for it in ((doc or {}).get("items") or []):
            if it.get("industry") and it.get("composite_score") is not None:
                radar_by_theme[it["industry"]] = float(it["composite_score"])
    except Exception as e:
        logger.warning(f"行业预测-资金流读取失败: {e}")

    # ③ 资讯：宏观快照 news_top（已落库，非网络）
    news_list: list[dict] = []
    try:
        snap = await macro_service.get_macro_snapshot()
        news_list = (snap or {}).get("news_top") or []
    except Exception as e:
        logger.warning(f"行业预测-资讯读取失败: {e}")

    # 候选行业 = 强势行业（细类）∪ 资金流领跑 ETF 主题映射的细类（补资金强但动量未上榜的行业）
    candidates: dict[str, dict] = {nm: {"momentum_score": mom_map[nm]} for nm in mom_map}
    for theme in sorted(radar_by_theme, key=radar_by_theme.get, reverse=True)[:5]:
        for local in ETF_TO_LOCAL_INDUSTRIES.get(theme, []):
            if local not in candidates:
                candidates[local] = {"momentum_score": None}

    if not candidates:
        step = _audit("行业", scanned=0, rule="行业预测数据不可用", kept=0, dropped=0,
                      reasons=["行业动量/资金流均缺失"])
        return {**step, "meta": {"industries": []}}

    # 逐行业计算预测分（0-100）与置信度
    max_hits = max((cand.get("news_hits") or 0) for cand in candidates.values())
    pool: list[dict] = []
    for ind, c in candidates.items():
        mom = c.get("momentum_score")
        fund = _industry_fund_score(ind, radar_by_theme)
        hits = _industry_news_hits(news_list, ind)
        news = round(100 * hits / max_hits, 2) if max_hits and hits else None
        beta = _beta_adjust(direction, ind)
        raw = 50.0 + ((mom - 50) if mom is not None else 0) * _W_MOM \
                  + ((fund - 50) if fund is not None else 0) * _W_FUND \
                  + ((news - 50) if news is not None else 0) * _W_NEWS + beta
        if (basis or {}).get("low_confidence"):
            raw = 50 + (raw - 50) * 0.6  # 观望：压缩行业区分度，不给强偏好
        raw = min(max(raw, 5.0), 98.0)
        conf = _industry_confidence(basis, mom, fund, news)
        c.update({"news_hits": hits, "forecast_score": raw, "confidence": conf})
        pool.append({
            "industry": ind,
            "forecast_score": round(raw, 1),
            "confidence": conf,
            "factors": {
                "momentum_score": mom,
                "fund_score": fund,
                "news_score": news,
                "news_hits": hits,
                "beta_adjust": beta,
            },
        })

    pool.sort(key=lambda x: x["forecast_score"], reverse=True)
    scanned = len(candidates)
    # 偏空 → 收缩行业池（只保留高置信 top8）；其余剔除低置信弱行业
    min_conf = 45 if "空" in str(direction) else 30
    kept = [x for x in pool if x["confidence"] >= min_conf]
    dropped = scanned - len(kept)
    keep_n = 8 if "空" in str(direction) else DEFAULT_TOP_N
    kept = kept[:keep_n]

    top_desc = "、".join(f"{x['industry']}({x['confidence']}%)" for x in kept[:8])
    reasons = ["评分因子: 资金流30% + 动量35% + 资讯热度15% + 方向β调整"]
    if "空" in str(direction):
        reasons.append("偏空 → 压制高β行业并收缩行业池，仅保留高置信行业")
    elif (basis or {}).get("low_confidence"):
        reasons.append("低置信观望 → 压缩行业区分度，默认减半仓位")
    if dropped:
        reasons.append(f"剔除 {dropped} 个低置信/弱因子行业")
    if kept:
        reasons.append(f"行业池: {top_desc}")

    step = _audit(
        "行业", scanned=scanned,
        rule=f"盘前行业方向预测 · 方向={(basis or {}).get('status') or direction or '中性'}",
        kept=len(kept), dropped=dropped, reasons=reasons,
    )
    return {**step, "meta": {"industries": kept}}


# 散户策略族中文名（用于 5.4 “策略族”来源标签）
_STRATEGY_ZH = {
    "extreme_reversal": "极端反转",
    "turnaround": "困境反转",
    "small_cap_value": "小盘价值",
    "convertible_arbitrage": "转债博弈",
    "default": "默认",
}
# 策略族“精选”质量门槛：候选池评分达到该值才归因到激活策略族来源
_STRATEGY_FAMILY_QUALITY_THRESHOLD = 80


async def _collect_pool_items() -> list[dict]:
    """数据源①：候选池 B 信号个股。

    优先读「当日候选快照」（持久化，纯读秒回）；无快照时回退现场计算并缓存。
    """
    from app.services.candidate_pool import candidate_pool_service
    items: list[dict] = []
    try:
        snap = await candidate_pool_service.load_daily_candidate_snapshot()
        if snap:
            items = (snap.get("overview") or {}).get("items") or []
    except Exception as e:
        logger.warning(f"候选快照个股读取失败（生成计划回退现场计算）: {e}")
    if not items:
        view = await candidate_pool_service.get_candidate_stocks_overview(
            top_n=DEFAULT_TOP_N, per_industry=DEFAULT_PER_INDUSTRY, limit=DEFAULT_LIMIT,
        )
        items = view.get("items") or []
    for it in items:
        it.setdefault("_src", "candidate_pool")
    return items


async def _collect_verified_items() -> list[dict]:
    """数据源②：已验证信号 —— 当日待成交的 B 买入信号（signal_tracking）。

    与候选池互补（按 code 去重），命中则 plan 来源标记为 signal_verified。
    """
    from app.services import signal_tracking_service
    try:
        docs = await signal_tracking_service.list_signals(status="pending", limit=60)
    except Exception as e:
        logger.warning(f"已验证信号读取失败（生成计划降级）: {e}")
        return []
    items = []
    for d in docs:
        sig = d.get("signal_type") or ""
        if not sig.startswith("B"):
            continue  # 仅纳入买入信号
        close = d.get("close") or (d.get("snapshot") or {}).get("close")
        items.append({
            "code": d.get("code"),
            "name": d.get("name") or d.get("code"),
            "industry": d.get("industry") or "",
            "signal_type": sig,
            "signal_label": d.get("signal_label") or sig,
            "close": close,
            "trigger_price": d.get("signal_price") or close,
            "quality_score": d.get("quality_score"),
            "trigger_date": d.get("trigger_date"),
            "_src": "signal_verified",
        })
    return items


async def _active_strategy(direction: str | None) -> str | None:
    """数据源③：策略族 —— 市场环境检测激活的偏多策略（仅非偏空时启用）。"""
    if "空" in str(direction):
        return None
    try:
        from app.services.retail.retail_strategy_service import get_retail_strategy_service
        regime, _ = await get_retail_strategy_service().detect_regime_auto()
        active = regime.active_strategies or []
    except Exception:
        return None
    return active[0].value if active else None


def _source_for(it: dict, strategy: str | None) -> dict:
    """5.4 来源标签：signal_verified / strategy / candidate_pool 三态（每只一个主来源）。"""
    code = it.get("code")
    industry = it.get("industry") or ""
    sig_type = it.get("signal_type") or ""
    if it.get("_src") == "signal_verified":
        label = f"已验证信号 {sig_type}（{it.get('trigger_date') or '当日'}）"
        return {"type": "signal_verified", "ref": code, "label": label}
    # 激活策略族对高质候选池个股“精选”归因（低于阈值的仍归候选池）
    if strategy and (it.get("quality_score") or 0) >= _STRATEGY_FAMILY_QUALITY_THRESHOLD:
        zh = _STRATEGY_ZH.get(strategy, strategy)
        return {"type": "strategy", "ref": code, "label": f"策略族《{zh}》精选，主题命中 {industry or '—'}"}
    return {"type": "candidate_pool", "ref": code, "label": f"候选池 {sig_type}，主题命中 {industry or '—'}"}


# 三买三卖信号体系：B1/B2/B3 = 三买，S1/S2/S3 = 三卖（含安全网/移动止损）
# 已触发卖出预警区的个股不宜作为「当日买入候选」
_SELL_SIGNAL_TYPES = {"S1", "S2", "S3", "SafetyNet", "TrailingStop"}


async def _today_planned_codes(user_id: str) -> set[str]:
    """查询用户当日已写入 daily_plans 的代码集合（buy+sell）。

    用于候选去重：已确认/已手动添加的计划不再重复出现在「待确认计划候选」/「卖出观测」。
    user_id 为空（盘前定时任务无用户上下文）返回空集，保持共享快照原样。
    """
    if not user_id:
        return set()
    try:
        from app.core.database import get_mongo_db
        from app.utils.timezone import now_tz
        db = get_mongo_db()
        today = now_tz().strftime("%Y-%m-%d")
        docs = await db["daily_plans"].find(
            {"user_id": user_id, "date": today},
            {"_id": 0, "code": 1},
        ).to_list(None)
        return {str(d.get("code") or "").strip() for d in docs if d.get("code")}
    except Exception as e:
        logger.warning(f"当日已计划代码读取失败（跳过去重）: {e}")
        return set()


async def _build_stock_step(user_id: str, direction: str | None, basis: dict | None,
                            industry_pool: list[dict]) -> tuple[dict, list[dict]]:
    """个股段：候选池+已验证信号 **硬绑定** 当日预测行业池（Stage3）。

    行业池由 Stage2 行业方向预测产出（含行业置信度）；本段只保留
    industry ∈ 行业池 的个股，并按行业限流（每行业上限默认3只）+ 方向过滤，
    且剔除「当日计划中已存在」的代码（避免已确认/已添加的标的重复出现在候选）。
    """
    allowed = {x.get("industry") for x in (industry_pool or []) if x.get("industry")}
    planned_codes = await _today_planned_codes(user_id)
    try:
        pool_items = await _collect_pool_items()
    except Exception as e:
        logger.warning(f"候选池个股读取失败（生成计划降级）: {e}")
        pool_items = []
    verified_items = await _collect_verified_items()
    strategy = await _active_strategy(direction)

    # code → 本地细类行业 映射（补全无 industry 字段的已验证信号；纯读 stock_basic_info）
    code_industry: dict[str, str] = {}
    try:
        from app.core.database import get_mongo_db_sync
        codes = {str(it.get("code")) for it in pool_items if it.get("code")}
        cursor = get_mongo_db_sync()["stock_basic_info"].find(
            {"code": {"$in": [c for c in codes if c]}}, {"_id": 0, "code": 1, "industry": 1})
        code_industry = {str(d.get("code")): str(d.get("industry") or "") for d in cursor}
    except Exception as e:
        logger.warning(f"个股行业映射读取失败（跳过）: {e}")

    # 按 code 合并，多来源去重（signal_verified 优先，避免同股重复候选）
    merged: dict[str, dict] = {}
    for it in pool_items:
        merged[it.get("code")] = it
    for it in verified_items:
        merged.setdefault(it.get("code"), it)

    scanned = len(merged)
    kept_items: list[dict] = []
    dropped_reasons: list[str] = []
    per_ind: dict[str, int] = {}
    for it in merged.values():
        code = it.get("code")
        sig_type = it.get("signal_type") or it.get("primary_signal_type") or ""
        industry = str(it.get("industry") or "").strip()
        if not industry and code:
            industry = code_industry.get(str(code), "")
        it["industry"] = industry
        # 去重：已在当日计划中的标的（人工确认/手动添加）不再重复推荐
        if code and str(code).strip() in planned_codes:
            dropped_reasons.append(f"{code} 已在当日计划中，跳过重复候选")
            continue
        # 风控：已触发卖出预警（S1/S2/S3 等）的个股不纳入买入候选
        if sig_type in _SELL_SIGNAL_TYPES:
            dropped_reasons.append(f"{code} 处于 {sig_type} 卖出预警区，不宜买入")
            continue
        # 偏空口径：剔除追涨信号 B1，保留低吸 B2/B3
        if "空" in str(direction) and sig_type == "B1":
            dropped_reasons.append(f"{code} B1 追涨 · 偏空剔除")
            continue
        # 行业硬绑定：不在当日预测行业池的个股一律不入选
        if not industry or industry not in allowed:
            dropped_reasons.append(f"{code} 行业『{industry or '未知'}』不在当日预测行业池")
            continue
        # 行业内限流：保证行业分散（每行业最多 N 只）
        cap = per_ind.get(industry, 0)
        if cap >= DEFAULT_PER_INDUSTRY:
            dropped_reasons.append(f"{code} 行业『{industry}』已达 {DEFAULT_PER_INDUSTRY} 只上限")
            continue
        per_ind[industry] = cap + 1
        it["source"] = _source_for(it, strategy)
        kept_items.append(it)

    kept = len(kept_items)
    rule_desc = f"行业硬绑定当日预测行业池({len(allowed)}个) + 剔除卖出预警区个股"
    if planned_codes:
        rule_desc += f"；剔除当日已计划 {len(planned_codes)} 只"
    if "空" in str(direction):
        rule_desc += "；偏空 → 剔除 B1 追涨"
    if strategy:
        rule_desc += f"；策略族《{_STRATEGY_ZH.get(strategy, strategy)}》精选高质个股"
    reasons = [f"扫描 {scanned} 只（候选池 {len(pool_items)} + 已验证信号 {len(verified_items)}）"]
    if allowed:
        reasons.append(f"仅在预测行业池内选股: {'、'.join(list(allowed)[:8])}")
    if dropped_reasons:
        reasons.extend(dropped_reasons[:5])
    if not dropped_reasons and kept:
        reasons.append("全部通过行业绑定与方向过滤")
    step = _audit("个股", scanned=scanned, rule=rule_desc, kept=kept,
                  dropped=scanned - kept, reasons=reasons)
    return step, kept_items


async def _build_plan_step(user_id: str, items: list[dict], direction: str | None,
                           basis: dict | None) -> tuple[dict, list[dict]]:
    """计划段：把候选个股装配成计划（来源 + 触发价/止损 + 仓位反算）。"""
    stop_pct = STOP_PCT_CONSERVATIVE if ("空" in str(direction) or basis.get("low_confidence")) else STOP_PCT_BULL
    target_pct = 8 if stop_pct == STOP_PCT_BULL else 5
    candidates: list[dict] = []
    skipped = 0
    for it in items[:DEFAULT_LIMIT]:
        code = it.get("code")
        if not code:
            continue
        sig_type = it.get("signal_type") or ""
        close = it.get("close") or it.get("price")
        if close is None:
            skipped += 1
            continue
        trigger_price = it.get("trigger_price") or close
        try:
            tp = round(float(trigger_price), 2)
            sl = round(tp * (1 - stop_pct), 2)
        except (TypeError, ValueError):
            skipped += 1
            continue
        industry = it.get("industry") or ""
        # 5.4 来源标签：沿用个股段已判定的三态来源（signal_verified/strategy/candidate_pool）
        source = it.get("source") or {
            "type": "candidate_pool",
            "ref": code,
            "label": f"候选池 {sig_type}，主题命中 {industry or '—'}",
        }
        # 仓位反算（buy）：失败不阻塞
        position = await plan_service._position_sizing(
            user_id, code, tp, "default"
        )
        candidates.append({
            "code": code,
            "name": it.get("name") or code,
            "direction": "buy",
            "trigger_price": tp,
            "stop_loss": sl,
            "sell_condition": SELL_CONDITION_TMPL.format(target=target_pct),
            "position": position,
            "quality_score": it.get("quality_score"),
            "signal_label": it.get("signal_label") or sig_type,
            "source": source,
            "industry": industry,
        })
        if len(candidates) >= DEFAULT_LIMIT:
            break

    step = _audit(
        "计划", scanned=len(items),
        rule=f"触发价=候选近价，止损 = 触发价×{int((1 - stop_pct) * 100)}%，仓位按 paper 账户反算",
        kept=len(candidates), dropped=skipped,
        reasons=[f"装配 {len(candidates)} 条候选计划",
                 "人工确认后备选写库，自动生成≠自动下单"],
    )
    return step, candidates


async def _build_sell_step(user_id: str, basis: dict | None) -> tuple[dict, list[dict]]:
    """卖出观测段（附加段）：回答盘前「哪些股票需要卖」。

    复用 intraday_guide_service 的持仓卖出评估（止损/止盈 + 三买三卖卖点），
    只列出有明确卖出动作的持仓（清仓/减仓/止损/止盈），「继续持有」不进入候选。
    """
    from app.services.intraday_guide_service import build_premarket_sell_candidates
    try:
        items = await build_premarket_sell_candidates(user_id)
    except Exception as e:
        logger.warning(f"卖出观测生成失败（降级为空）: {e}")
        items = []
    # 去重：已写入当日计划的持仓（人工确认卖出/手动添加）不再重复出现在卖出观测
    planned_codes = await _today_planned_codes(user_id)
    if planned_codes:
        items = [it for it in items if (it.get("code") or "").strip() not in planned_codes]
    rule_desc = "持仓卖出评估：止损/止盈触发 + 三买三卖卖点（S1减仓/S2主减/S3清仓/安全网/移动止损）"
    if "空" in str((basis or {}).get("status") or ""):
        rule_desc += "；偏空 → 卖出观测从严，减仓优先"
    step = _audit(
        "卖出", scanned=len(items), rule=rule_desc,
        kept=len(items), dropped=0,
        reasons=[
            f"卖出观测 {len(items)} 条" if items else "暂无需要卖出的持仓，全部继续持有",
            "未触发卖出信号、未触及止损/止盈的持仓不列出，避免噪声",
            "人工确认后写入当日计划（direction=sell），自动生成≠自动下单",
        ],
    )
    return step, items


async def generate_daily_plan(user_id: str,
                              on_stage: Callable[[dict], Awaitable[None]] | None = None) -> dict:
    """生成当日计划候选 + 四段审计痕迹。不落库，交由前端人工确认。

    on_stage: 可选进度回调，每完成一段即以当前累积审计调用一次
    {step, progress, steps}，供后台任务发布 SSE 进度。
    """
    steps: list[dict] = []          # 5.3 流水线审计痕迹
    candidates: list[dict] = []     # 5.4 计划候选（带 source）

    async def run_step(name: str, fn: Any) -> Any:
        t0 = time.monotonic()
        try:
            return await fn()
        finally:
            logger.info(f"计划生成 · {name}段 耗时 {time.monotonic() - t0:.2f}s")

    async def emit(stage: str) -> None:
        if on_stage:
            try:
                await on_stage({
                    "status": "running",
                    "stage": stage,
                    "progress": STAGE_PROGRESS.get(stage, 0),
                    "steps": list(steps),
                })
            except Exception as e:
                logger.warning(f"计划进度回调失败（忽略）: {e}")

    env_step = await run_step("环境", _build_environment_step)
    steps.append(env_step)
    env_meta = env_step.get("meta") or {}
    direction = env_meta.get("direction")
    basis = env_meta.get("basis")
    await emit("环境")

    # 宏观快照未就绪 → 快速降级返回（不现场重算，绝不拖入 100-200s 的现场刷新）
    if env_meta.get("ready") is False:
        return {
            "direction": None,
            "basis": None,
            "candidates": [],
            "candidates_count": 0,
            "sell_candidates": [],
            "sell_count": 0,
            "audit": {"steps": steps, "total": len(steps)},
            "pending_reason": "宏观快照未就绪，请先刷新宏观快照后再生成当日计划",
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        }

    ind_step = await run_step("行业", lambda: _build_industry_step(direction, basis))
    steps.append(ind_step)
    await emit("行业")
    # 行业方向预测 → 当日行业池（供 Stage3 个股段硬绑定）
    industry_pool = (ind_step.get("meta") or {}).get("industries") or []

    stock_step, kept_items = await run_step(
        "个股", lambda: _build_stock_step(user_id, direction, basis, industry_pool)
    )
    steps.append(stock_step)
    await emit("个股")

    plan_step, candidates = await run_step(
        "计划", lambda: _build_plan_step(user_id, kept_items, direction, basis)
    )
    steps.append(plan_step)
    await emit("计划")

    sell_step, sell_candidates = await run_step(
        "卖出", lambda: _build_sell_step(user_id, basis)
    )
    steps.append(sell_step)
    await emit("卖出")

    return {
        "direction": direction,
        "basis": basis,
        "industries": industry_pool,   # 当日预测行业池（5.3 行业段产物，前端可展示）
        "candidates": candidates,
        "candidates_count": len(candidates),
        "sell_candidates": sell_candidates,   # 当日卖出观测（持仓卖出评估，人工确认写库）
        "sell_count": len(sell_candidates),
        "audit": {"steps": steps, "total": len(steps)},
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    }


# ══════════════════════════════════════════════════════════════
# 今日计划快照：盘前 8:15 预生成落库（date 唯一），前端「打开即读」退化为纯读取，
# 彻底消除"点击生成 → 异步任务 → SSE/轮询完成"链路（也是按钮卡死 bug 的根）。
# ══════════════════════════════════════════════════════════════
_DAILY_PLAN_COLLECTION = "daily_plan_snapshots"


async def persist_daily_plan_snapshot(result: dict) -> dict:
    """把当日计划结果按「今日日期」落库（upsert，跨天自动重建）。"""
    from datetime import datetime, timezone as dt_timezone
    from app.core.database import get_mongo_db
    from app.utils.timezone import now_tz
    date = now_tz().strftime("%Y-%m-%d")
    doc = {"date": date, "result": result, "generated_at": datetime.now(dt_timezone.utc)}
    try:
        db = get_mongo_db()
        await db[_DAILY_PLAN_COLLECTION].update_one(
            {"date": date}, {"$set": doc}, upsert=True)
        logger.info(
            f"✅ 当日计划快照已落库: date={date}, "
            f"行业{len(result.get('industries') or [])}个, 候选{result.get('candidates_count', 0)}条"
        )
    except Exception as e:
        logger.warning(f"当日计划快照落库失败: {e}")
    return doc


async def load_daily_plan_snapshot(date: str | None = None) -> dict | None:
    """纯读取今日计划快照（不触发任何重算）。无快照返回 None。"""
    from app.core.database import get_mongo_db
    from app.utils.timezone import now_tz
    date = date or now_tz().strftime("%Y-%m-%d")
    try:
        db = get_mongo_db()
        doc = await db[_DAILY_PLAN_COLLECTION].find_one({"date": date}, {"_id": 0, "result": 1})
        return (doc or {}).get("result")
    except Exception as e:
        logger.warning(f"当日计划快照读取失败: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 异步任务编排：POST 秒回 job_id，后台跑四段流水线，
# 进度经 Redis pubsub `task_progress:{job_id}` 推给前端 SSE，结果落 Redis。
# ══════════════════════════════════════════════════════════════
_plan_jobs: dict[str, dict] = {}


def _rkey(job_id: str, kind: str) -> str:
    return f"dailyplan:{kind}:{job_id}"


def start_plan_job(user_id: str) -> dict:
    """启动当日计划后台任务，立即返回 job 元信息（不在请求内等待计算）。"""
    job_id = uuid.uuid4().hex
    _plan_jobs[job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "running",
        "progress": 0,
        "stage": "环境",
    }
    try:
        asyncio.create_task(_run_plan_job(job_id, user_id))
    except Exception as e:
        logger.error(f"当日计划后台任务创建失败: {e}", exc_info=True)
        _plan_jobs[job_id].update({"status": "error", "error": str(e)})
    return _job_view(job_id)


def _job_view(job_id: str) -> dict | None:
    j = _plan_jobs.get(job_id)
    if j is None:
        return None
    # 含 user_id：status / stream 端点用它做所有权校验（此前遗漏导致恒判"任务不存在"，SSE 一直 404）
    return {k: j.get(k) for k in ("job_id", "status", "progress", "stage", "error", "user_id")}


async def get_plan_result(job_id: str) -> dict | None:
    """取回已完成任务的结果：优先内存，其次 Redis（供跨进程/重启后取回）。"""
    j = _plan_jobs.get(job_id)
    if j and j.get("status") == "done" and j.get("result") is not None:
        return j["result"]
    try:
        from app.core.database import get_redis_client
        raw = await get_redis_client().get(_rkey(job_id, "result"))
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"计划结果 Redis 读取失败: {e}")
    return None


async def _run_plan_job(job_id: str, user_id: str) -> None:
    try:
        from app.core.database import get_redis_client
    except Exception:
        get_redis_client = None

    async def emit(evt: dict) -> None:
        evt = {**evt, "job_id": job_id}
        _plan_jobs.get(job_id, {}).update(
            {k: evt.get(k) for k in ("status", "progress", "stage") if k in evt}
        )
        if get_redis_client is None:
            return
        try:
            await get_redis_client().publish(
                f"task_progress:{job_id}",
                json.dumps(evt, ensure_ascii=False, default=_json_default),
            )
        except Exception as e:
            logger.warning(f"计划进度 publish 失败（跳过）: {e}")

    try:
        await emit({"status": "running", "stage": "环境", "progress": 0, "steps": []})
        result = await generate_daily_plan(user_id, on_stage=emit)
        # 落内存 + Redis，供 status/result 端点在 done 后取回
        j = _plan_jobs.get(job_id)
        if j is not None:
            j.update({"status": "done", "progress": 100, "stage": "计划", "result": result})
        await emit({"status": "done", "stage": "计划", "progress": 100, "result": result})
        # 落库为「今日计划快照」，前端 GET /daily-plan/today 打开即读（不依赖本 job 会话）
        try:
            await persist_daily_plan_snapshot(result)
        except Exception as e:
            logger.warning(f"计划快照持久化失败（跳过）: {e}")
        if get_redis_client is not None:
            try:
                await get_redis_client().setex(
                    _rkey(job_id, "result"), _JOB_RESULT_TTL,
                    json.dumps(result, ensure_ascii=False, default=_json_default),
                )
            except Exception as e:
                logger.warning(f"计划结果存 Redis 失败（仅内存）: {e}")
    except Exception as e:
        logger.error(f"当日计划后台任务失败: {e}", exc_info=True)
        j = _plan_jobs.get(job_id)
        if j is not None:
            j.update({"status": "error", "error": str(e)})
        await emit({"status": "error", "stage": j.get("stage") if j else "环境",
                    "message": str(e)})