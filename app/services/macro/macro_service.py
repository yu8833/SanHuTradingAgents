"""宏观快扫（盘前）编排层 —— 聚合数据层 + 规则引擎 + LLM 解读 + 落库。

设计文档《第六章·交易工具与日常流程》§5.4 / §5.5：
- 数据层：A 外围指数（扩展）/ B 财经日历 / C 分级快讯 / D 大盘状态 —— 聚合为同一份快照；
- 规则引擎 macro_scorer：硬锚点，定方向 + 置信度 + 依据明细；
- LLM 解读：软解读（快速模型 1 次调用），输出固定结构（今日关键词/事件影响/风格倾向/风险提示），
  只做环境解读、不做个股推荐；LLM 不可用时降级为仅规则结果并标注"解读不可用"；
- 落库：`macro_daily_snapshots`（date 唯一），供 API / 前端盘前 tab / 周度复盘回溯。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.services.cache_layer import cached
from app.services.macro.financial_calendar import get_financial_calendar
from app.services.macro.macro_scorer import score_macro
from app.services.macro.news_classifier import get_macro_news

logger = logging.getLogger(__name__)

# 快照集合名（与 design doc §5.5 一致）
SNAPSHOT_COLLECTION = "macro_daily_snapshots"

# 当日方向"低置信度"门槛（百分比）：低于它 → 基调定为"中性(观望)"，不强断言多空
CONFIDENCE_THRESHOLD = 30
_STRONG = {"偏多": "偏多", "偏空": "偏空", "多": "偏多", "空": "偏空"}


def _direction_status(direction: str | None, confidence: int, threshold: int = CONFIDENCE_THRESHOLD) -> str:
    """当日方向四态：偏多 / 偏空 / 中性(观望) / 数据不足。

    低置信度(<threshold)或中性方向一律归为「观望」，明确不做多空强断言；
    无方向数据归为「数据不足」。实现对文档 5.2「状态四态」的权威口径。
    """
    if not direction:
        return "数据不足"
    base = _STRONG.get(direction) or "中性"
    if base == "中性" or confidence < threshold:
        return "中性(观望)"
    return base


def _build_basis(rule: dict, created_at) -> dict:
    """构建当日方向基准（5.2）：状态四态 + 低置信度标记 + 锁定时间戳。"""
    direction = rule.get("direction")
    confidence = int(rule.get("confidence") or 0)
    return {
        "status": _direction_status(direction, confidence),
        "direction": direction,
        "confidence": confidence,
        "low_confidence": bool(direction) and confidence < CONFIDENCE_THRESHOLD,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "locked_at": created_at,
        "score": rule.get("score", 0),
    }


# ---------------------------------------------------------------------------
# 数据聚合（数据层 A-D）
# ---------------------------------------------------------------------------
async def _collect_indices() -> list[dict]:
    """外围指数全集：7 指数 + VIX + 美股期货 + 富时A50期货（各档失败仅跳过）。"""
    try:
        from app.services import vibe_gstock as gstock
        return gstock.macro_indices()
    except Exception as e:
        logger.warning(f"外围指数获取失败: {e}")
        return []


async def _collect_breadth() -> dict | None:
    """昨日大盘情绪（涨跌家数），供规则引擎最后一项。失败返回 None。"""
    try:
        from app.services.market_dashboard import get_dashboard
        dash = await get_dashboard()
        b = dash.get("breadth") or {}
        if b.get("up") is None or b.get("down") is None:
            return None
        return {"up": b["up"], "down": b["down"]}
    except Exception as e:
        logger.warning(f"大盘宽度获取失败: {e}")
        return None


# ---------------------------------------------------------------------------
# LLM 解读（§5.4-B，带降级）
# ---------------------------------------------------------------------------
_LLM_SYSTEM_PROMPT = (
    "你是一个专业的A股宏观环境解读助理。基于用户提供的客观数据（外围指数、财经日历、"
    "分级快讯、规则引擎评分结果），输出今日盘前宏观环境解读。\n"
    "硬性规则：\n"
    "- 只做环境解读，绝不推荐任何具体个股、不预测涨跌与价位、不给买卖时机\n"
    "- 必须严格输出 JSON，不要输出任何其他文字\n"
    "- 数字必须来自用户提供的数据，不要编造\n"
    "- 使用中文，简洁专业\n"
    "JSON 结构（固定字段，不得缺失）：\n"
    '{"keywords": ["今日关键词1", "..."],\n'
    ' "event_impact": "今天要盯什么：按重要性列出事件及其潜在影响（1-3句）",\n'
    ' "style_tendency": "风格倾向：大小盘/成长价值/题材（1-2句）",\n'
    ' "risk_tips": "风险提示：1-3条"}'
)


def _get_llm_cfg() -> dict | None:
    """获取快速分析模型的 {model, api_base, api_key, temperature, max_tokens}；无则 None。"""
    try:
        from app.services.simple_analysis_service import get_provider_and_url_by_model_sync
        from app.core.unified_config import unified_config

        model = unified_config.get_quick_analysis_model()
        if not model:
            return None
        info = get_provider_and_url_by_model_sync(model)
        api_key = (info.get("api_key") or "").strip()
        backend_url = (info.get("backend_url") or "").strip()
        if not api_key or not backend_url:
            return None
        return {
            "model": model,
            "api_base": backend_url,
            "api_key": api_key,
            "temperature": 0.3,
            "max_tokens": 800,
        }
    except Exception as e:
        logger.warning(f"获取 LLM 配置失败（解读将降级）: {e}")
        return None


def _call_llm_interpretation(cfg: dict, prompt: str) -> dict:
    """非流式调用 chat/completions，返回结构化解读；任何失败抛异常（由调用方降级）。"""
    import requests

    api_base = cfg["api_base"].rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base += "/chat/completions"
    resp = requests.post(
        api_base,
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": cfg.get("max_tokens", 800),
            "stream": False,
        },
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_llm_json(content)


def _parse_llm_json(content: str) -> dict:
    """容错解析 LLM JSON 输出（去 ```json 包裹，必要时截取首个 { } 段）。"""
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError("LLM 输出不是合法 JSON")


def _build_llm_prompt(indices: list[dict], calendar: list[dict],
                      news: list[dict], rule: dict) -> str:
    """构造 LLM 输入：外围表 + 日历 + 分级快讯 + 规则评分结果。"""
    lines: list[str] = []

    lines.append("【外围指数】")
    if indices:
        for i in indices:
            chg = i.get("change_pct")
            chg_s = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else "n/a"
            lines.append(f"- {i.get('name')}（{i.get('region')}）: 点位 {i.get('price')}, 涨跌 {chg_s}")
    else:
        lines.append("- （无数据）")

    lines.append("\n【未来7日财经日历】")
    if calendar:
        for e in calendar:
            lines.append(f"- {e.get('date')} {e.get('region')} {e.get('event')} "
                         f"(重要性:{e.get('importance')} 发布:{e.get('release_time')})")
    else:
        lines.append("- （无数据）")

    lines.append("\n【近24小时重要快讯】")
    if news:
        for n in news[:15]:
            lines.append(f"- [{n.get('importance')}] {n.get('title')}")
    else:
        lines.append("- （无数据）")

    lines.append("\n【规则引擎评分】")
    lines.append(f"- 方向: {rule.get('direction')}, 总分: {rule.get('score')}, "
                 f"置信度: {rule.get('confidence')}%")
    for s in rule.get("signals", [])[:20]:
        lines.append(f"- {s.get('name')}: {s.get('detail')} → {s.get('score'):+d}")

    return "\n".join(lines)


async def _llm_interpretation(indices: list[dict], calendar: list[dict],
                              news: list[dict], rule: dict) -> dict:
    """LLM 解读（带降级）。返回 {available, interpretation}；不可用返回 available=False。"""
    cfg = _get_llm_cfg()
    if not cfg:
        return {"available": False, "interpretation": None}
    try:
        import asyncio
        prompt = _build_llm_prompt(indices, calendar, news, rule)
        result = await asyncio.to_thread(_call_llm_interpretation, cfg, prompt)
        # 结构规整：只保留设计文档要求的四段，缺字段补空
        return {
            "available": True,
            "interpretation": {
                "keywords": result.get("keywords") or [],
                "event_impact": result.get("event_impact") or "",
                "style_tendency": result.get("style_tendency") or "",
                "risk_tips": result.get("risk_tips") or "",
            },
        }
    except Exception as e:
        logger.warning(f"LLM 宏观解读失败（降级为仅规则结果）: {e}")
        return {"available": False, "interpretation": None}


# ---------------------------------------------------------------------------
# 快照构建 / 读取 / 刷新
# ---------------------------------------------------------------------------
async def build_macro_snapshot(days: int = 7) -> dict:
    """构建当日宏观快照：聚合数据 → 规则引擎 → LLM 解读。"""
    indices = await _collect_indices()
    calendar = await get_financial_calendar(days)
    news = await get_macro_news(hours_back=24, top_n=40)
    breadth = await _collect_breadth()

    rule = score_macro(indices, calendar, news, breadth)
    created_at = datetime.now(timezone.utc)

    # 5.1：为每条信号补充"判定"（利多/利空/中性），便于面板逐条复核
    for sig in rule.get("signals", []):
        sig["judge"] = "利多" if sig.get("score", 0) > 0 else ("利空" if sig.get("score", 0) < 0 else "中性")

    llm = await _llm_interpretation(indices, calendar, news, rule)

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "indices": indices,
        "calendar": calendar,
        "news_top": news[:20],
        "breadth": breadth,
        "rule": rule,
        "basis": _build_basis(rule, created_at),  # 5.2 当日方向基准
        "llm_interpretation": llm["interpretation"],
        "llm_available": llm["available"],
        "created_at": created_at,
    }


async def _persist_snapshot(snapshot: dict) -> bool:
    """写入 macro_daily_snapshots（date 唯一，upsert）。"""
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        await db[SNAPSHOT_COLLECTION].update_one(
            {"date": snapshot["date"]},
            {"$set": snapshot},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.error(f"宏观快照落库失败: {e}", exc_info=True)
        return False


async def get_macro_snapshot(date_str: str | None = None) -> dict | None:
    """读取指定日期（默认今日）快照；Redis 短缓存。"""
    from app.core.database import get_mongo_db

    # None（未指定日期）解析为今日，保证查询的是有效日期而非 {"date": None}
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    async def _load():
        db = get_mongo_db()
        doc = await db[SNAPSHOT_COLLECTION].find_one({"date": date_str})
        if not doc:
            return None
        doc.pop("_id", None)
        # 兼容旧快照：若缺少 basis（当日方向基准，5.2），按 rule 实时补齐，
        # 保证已落库的存量快照也能提供"状态四态 + 置信 + 锁定"基准。
        if not doc.get("basis") and doc.get("rule"):
            doc["basis"] = _build_basis(doc["rule"], doc.get("created_at") or datetime.now(timezone.utc))
        return doc

    key = f"macro:snapshot:{date_str}"
    return await cached(key, _load, category="market", valid=lambda v: v is not None)


async def refresh_macro_snapshot() -> dict:
    """生成今日快照并落库（手动刷新 / 8:15 调度共用）。返回快照。

    5.2 盘前锁定：当日方向基准一旦锁定（存在 locked_at），盘中刷新只更新
    事实数据（指数/日历/快讯/信号值），沿用盘前基准，避免方向盘中横跳
    （对应文档 §3.2"盘中不重算标签，只展示基准"、§5.2 指针仅在盘前定位一次）。
    """
    snap = await build_macro_snapshot()
    # 今日是否已存在锁定基准 → 若已锁定则保留原基准
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        existing = await db[SNAPSHOT_COLLECTION].find_one({"date": snap["date"]})
        old_basis = (existing or {}).get("basis") or {}
        if old_basis.get("locked_at"):
            snap["basis"] = old_basis
    except Exception as e:
        logger.warning(f"盘前基准锁定判断跳过: {e}")
    await _persist_snapshot(snap)
    # 清今日快照缓存，下次读取即时生效
    from app.services.cache_layer import clear_cache
    await clear_cache(f"macro:snapshot:{snap['date']}")
    return snap
