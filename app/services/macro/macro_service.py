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
import math
from datetime import datetime, timezone
from typing import Any

from app.services.cache_layer import cached, clear_cache
from app.services.macro.financial_calendar import get_financial_calendar
from app.services.macro.macro_scorer import score_macro
from app.services.macro.news_classifier import get_macro_news

logger = logging.getLogger(__name__)

# 快照集合名（与 design doc §5.5 一致）
SNAPSHOT_COLLECTION = "macro_daily_snapshots"

# 当日方向"低置信度"门槛（百分比）：低于它 → 基调定为"中性(观望)"，不强断言多空
CONFIDENCE_THRESHOLD = 30
_STRONG = {"偏多": "偏多", "偏空": "偏空", "多": "偏多", "空": "偏空"}

# --- 宏观快照"缺失时后台自动补生成"的防并发单飞机制 ---
# 冷启动/非交易日恢复后，快照可能缺失。作战室打开时不再空态等用户点「立即生成」，
# 而是 GET 缺失时自动在后台起一次补生成（当日仅一次），前端展示"自动生成中…"并轻轮询取回。
import asyncio

_snapshot_gen_lock = asyncio.Lock()
# 记录"当日是否已触发过后台补生成"，跨请求避免重复启动（进程内即可，重启即复位为重新允许）
_snapshot_auto_attempted: set[str] = set()

# --- 快照构建各数据步的硬时限（秒）：弱网下任何一步都不无限等待 ---
# 外围指数 / 日历 / 快讯 / 大盘宽度 并行收集，各自带硬上限；超时的步降级为空值，
# 其余步不受影响、已取到数据不丢弃。score_macro 对空输入安全（出「数据不足」），
# 空数据快照照常落库 ⇒ 宏观快照必然在有限时间内生成，前端不再长时「未就绪」。
SNAPSHOT_FETCH_TIMEOUTS = {
    "indices": 20,   # 外围指数全量（并行拉取）
    "breadth": 10,   # 大盘宽度
    "calendar": 15,  # 财经日历（缓存 1 天，通常秒回）
    "news": 60,      # 分级快讯（108 RSS / 多源合并，最慢步）
}
SNAPSHOT_LLM_TIMEOUT = 30  # LLM 解读（日历逐条 + 盘前解读）单次硬上限


async def _bounded_fetch(coro, name: str, timeout: float, default):
    """包硬超时运行单个数据收集步；超时/异常一律降级为 default，绝不把耗时外抛。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"宏观数据步[{name}]超时（>{timeout:.0f}s），降级处理")
        return default
    except Exception as e:
        logger.warning(f"宏观数据步[{name}]失败，降级处理: {e}")
        return default


async def _ensure_snapshot_auto_generated() -> bool:
    """快照缺失时后台自动补生成（幂等：当日仅触发一次，并发只进一个）。

    Returns:
        True 表示本次已捕获并启动（或复用进行中的）后台生成；False 表示无需/不可
        （非交易日、已有快照、已在生成、或前序已触发过）。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        from app.utils.trading_time import is_trading_day
        if not is_trading_day(datetime.now()):
            return False
    except Exception:
        pass  # 交易日判断失败不阻塞，仍尝试生成（快照缺失本身就是要补的）

    # 快照已存在 → 无需补生成
    try:
        if await get_macro_snapshot(today) is not None:
            return False
    except Exception:
        pass

    async with _snapshot_gen_lock:
        if today in _snapshot_auto_attempted:
            return False
        _snapshot_auto_attempted.add(today)
        # 二次确认（锁内）：可能生成刚完成
        try:
            if await get_macro_snapshot(today) is not None:
                return False
        except Exception:
            pass
        logger.info("🌅 宏观快照缺失，自动在后台补生成（当日首次）…")
        asyncio.create_task(_auto_generate_safely())
        return True


async def _auto_generate_safely() -> None:
    """后台安全补生成：任何异常都不外抛，仅记录日志。"""
    try:
        await refresh_macro_snapshot()
    except Exception as e:
        logger.error(f"❌ 宏观快照后台自动补生成失败: {e}", exc_info=True)


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
    """外围指数全集：7 指数 + VIX + 美股期货 + 富时A50期货（各档失败仅跳过）。

    整体硬超时 30s：弱网/东财主机不可达时（串行重试 3 主机 × 7 指数理论最坏
    可达数分钟）降级为空，绝不让参考 Tab / 快照被指数步长时间拖住。
    """
    try:
        from app.services import vibe_gstock as gstock
        return await asyncio.wait_for(asyncio.to_thread(gstock.macro_indices), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("外围指数收集超时（>30s），降级为空")
        return []
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


# A股技术面信号：上证指数日线由 AKShare 实时拉取（stock_daily_quotes 未同步指数数据）。
_A_SHARE_DAYS = 70   # 取 70 个交易日，容 60 日均线


async def _collect_a_share_signals() -> dict | None:
    """上证指数近 70 交易日（AKShare 实时）→ close/ma20/ma60 + 当日/近5日量能。失败返回 None。

    数据源：ak.stock_zh_index_daily(sh000001)（免费、秒级；stock_daily_quotes 未同步指数日线）。
    量能：上证指数成交量（手）当日 vs 近 5 日均量，判断放量/缩量。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol="sh000001")
        if df is None or df.empty:
            return None
        # 取最近 _A_SHARE_DAYS 个交易日；列名 date/open/high/low/close/volume
        tail = df.tail(_A_SHARE_DAYS)
        closes = []
        for v in tail["close"]:
            f = float(v)
            if f == f:            # 过滤 NaN
                closes.append(f)
        if len(closes) < 21:
            return None
        ma20 = sum(closes[-20:]) / 20
        ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
        latest = closes[-1]

        volumes = []
        for v in tail["volume"]:
            f = float(v)
            if f == f:
                volumes.append(f)
        amount = volumes[-1] if volumes else None
        amount_avg5 = (sum(volumes[-5:]) / 5) if len(volumes) >= 5 else None
        return {
            "close": round(latest, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2) if ma60 else None,
            "amount": amount,
            "amount_avg5": amount_avg5,
        }
    except Exception as e:
        logger.warning(f"A股技术面信号获取失败: {e}")
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
        from app.core.unified_config import unified_config
        from app.services.simple_analysis_service import get_provider_and_url_by_model_sync

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
            # 模型带隐式推理（如 deepseek-v4-flash 有 reasoning_tokens，实测一次思考约 250-300 token），
            # 800 会被推理占满导致 content 截断为空 → 提高到 2048，给「推理 + 四段 JSON」留足空间
            "max_tokens": 2048,
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


def _re_clean_trailing_comma(s: str) -> str:
    """剔除 JSON 对象/数组尾部多余逗号（常见 LLM 输出瑕疵）。"""
    import re as _re
    return _re.sub(r",\s*([}\]])", r"\1", s)


def _extract_balanced_json(text: str) -> str | None:
    """从含前/后散文的文本中，按括号配平截取首个完整 JSON 子串。"""
    import re as _re
    cleaned = _re.sub(r",\s*([}\]])", r"\1", text)  # 容忍对象尾部多余逗号
    for start_c, end_c in (("{", "}"), ("[", "]")):
        start = cleaned.find(start_c)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == start_c:
                depth += 1
            elif ch == end_c:
                depth -= 1
                if depth == 0:
                    return cleaned[start:i + 1]
    return None


def _parse_llm_json(content: str) -> dict:
    """容错解析 LLM JSON 输出（多数供应商会把 JSON 包在 markdown 围栏/引号/散文里）。

    逐级兜底：
    1) 直接 json.loads（先剥 BOM / 空白 / ```json 围栏）；
    2) 包裹成 JSON 字符串（'"{...}"'）时解一层引号；
    3) 括号配平截取首个完整 JSON（容忍前后散文）；
    4) 剔除对象尾部多余逗号后重试。
    全部失败抛 ValueError（由调用方降级/重试）。
    """
    text = (content or "").strip().lstrip("\ufeff")
    candidates: list[str] = [text]
    if text.startswith("```"):
        cleaned = text.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        candidates.append(cleaned.strip())
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        try:
            candidates.append(json.loads(text))
        except (json.JSONDecodeError, TypeError):
            pass
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            pass
    sub = _extract_balanced_json(text)
    if sub is not None:
        for cand in (sub, _re_clean_trailing_comma(sub)):
            try:
                return json.loads(cand)
            except (json.JSONDecodeError, TypeError):
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
    """LLM 解读（带降级 + 失败重试）。返回 {available, interpretation}；不可用返回 available=False。

    保障解读可用：单次失败先重试一次（追加「只输出 JSON」的强约束），
    两次仍失败才降级为「仅规则结果」。JSON 解析已做多层容错（见 _parse_llm_json）。
    """
    cfg = _get_llm_cfg()
    if not cfg:
        return {"available": False, "interpretation": None}
    retry_tail = (
        "\n\n【重要】直接输出符合上述 JSON 结构的原始 JSON："
        "不要输出任何解释文字，不要使用 markdown 代码块（不要以 ``` 开头），结尾不要追加说明。"
    )
    for attempt in (1, 2):
        try:
            prompt = _build_llm_prompt(indices, calendar, news, rule)
            if attempt == 2:
                prompt += retry_tail
            import asyncio
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
            logger.warning(f"LLM 宏观解读第 {attempt}/2 次失败（降级为仅规则结果）: {e}")
    return {"available": False, "interpretation": None}


# ---------------------------------------------------------------------------
# 日历事件增强：已公布事件 → 快讯流提取实际值 + LLM 逐条解读（AI 分析）
# ---------------------------------------------------------------------------
def _calendar_news_keyword(event: str) -> str | None:
    """从事件名映射快讯检索关键词（用于在公开快讯流中提取实际值）。"""
    for key in ("初请", "非农", "失业", "CPI", "PPI", "PMI", "ISM", "LPR", "MLF", "社融"):
        if key in event:
            return key
    return None


def _extract_news_value(ev: dict, news: list[dict]) -> float | None:
    """从公开快讯流（近 24h）提取已公布事件的实际值。

    典型快讯如「美国上周初请失业金人数 24.3 万人」；AKShare/东财宏观序列常缺失或陈旧，
    快讯流即"公开可查"的数据来源。提取失败返回 None（交给 LLM 定性）。
    """
    kw = _calendar_news_keyword(str(ev.get("event") or ""))
    if not kw:
        return None
    for n in news or []:
        blob = f"{n.get('title') or ''} {n.get('content') or ''}"
        if kw not in blob:
            continue
        # 单位覆盖 万/亿/%/千/K 及无空格变体（如 "23.4万"、"初请 23.1K"）
        for unit in ("万人", "万", "千人", "K", "k", "%", "个百分点"):
            m = __import__("re").search(rf"([0-9]+(?:\.[0-9]+)?)\s*{unit}", blob)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    continue
    return None


def _call_llm_calendar(cfg: dict, prompt: str) -> str:
    """同步调用 chat/completions，返回日历事件逐条解读文本。"""
    import requests
    api_base = cfg["api_base"].rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base += "/chat/completions"
    resp = requests.post(
        api_base,
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system",
                 "content": "你是宏观数据解读助手。针对列表中的已公布财经事件，逐条输出一行解读，"
                            "格式严格为「事件名：解读（1-2 句）」。只做定性分析（对 A 股情绪/风格/"
                            "货币政策的含义），可引用快讯；不得编造任何具体数值；数据缺失项明确写"
                            "『实际值未获取』并提示该数据公开可查（如金十数据/英为财情）。每条一行，不要输出其它内容。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 800,
            "stream": False,
        },
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _calendar_fallback_analysis(ev: dict) -> str:
    """LLM 不可用时保留的可读兜底解读（透明说明数据获取链路，避免"查不到"误解）。"""
    actual = ev.get("actual")
    if actual is not None:
        return f"已公布 · 实际 {actual}（公开快讯流提取）；对市场的解读请结合下方宏观方向判断与快讯"
    return ("已公布。系统采用的结构化财经接口当前未取到该数值：AKShare 初请序列数据陈旧"
            "（上游停在旧日期）、东财/金十等接口不可用；该数据为公开信息，可通过搜索引擎/"
            "金十数据/英为财情等渠道查看，快讯流如出现带数值条目将自动回填。")


async def _calendar_ai_analysis(calendar: list[dict], news: list[dict]) -> list[dict]:
    """对已公布事件做增强：①快讯流提取实际值 ②LLM 逐条解读（失败静默回退兜底文案）。

    数据 ≠ 编造：实际值只来自 AKShare/快讯流等公开来源；LLM 只做定性分析，
    prompt 明确禁止输出未提供的数值。
    """
    announced = [e for e in calendar if e.get("announced")]
    if not announced:
        return calendar
    # ① 快讯流提取已公布事件实际值（覆盖 AKShare 序列缺失/陈旧）
    for ev in announced:
        if ev.get("actual") is None:
            val = _extract_news_value(ev, news)
            if val is not None:
                ev["actual"] = val
    # ② LLM 逐条解读（核心分析能力；失败不影响快照构建）
    cfg = _get_llm_cfg()
    if cfg:
        try:
            import asyncio
            lines = ["【已公布财经事件】"]
            for e in announced:
                lines.append(f"- {e.get('date')} {e.get('event')}："
                             f"实际={e.get('actual') or '未获取'} 预期={e.get('forecast') or '未提供'} "
                             f"前值={e.get('previous') or '未提供'}")
            lines.append("\n【近24小时相关快讯】")
            for n in (news or [])[:15]:
                lines.append(f"- {n.get('title')}")
            text = await asyncio.to_thread(_call_llm_calendar, cfg, "\n".join(lines))
            mapping: dict[str, str] = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or ("：" not in line and ":" not in line):
                    continue
                sep = "：" if "：" in line else ":"
                key, val = line.split(sep, 1)
                mapping[key.strip()] = val.strip()
            for ev in announced:
                for key, val in mapping.items():
                    if key and (key in ev["event"] or ev["event"] in key):
                        ev["analysis"] = f"AI解读：{val}"
                        break
        except Exception as e:
            logger.warning(f"日历事件 LLM 解读失败（保留兜底文案）: {e}")
    # ③ 兜底文案（LLM 未覆盖项）
    for ev in announced:
        if not ev.get("analysis"):
            ev["analysis"] = _calendar_fallback_analysis(ev)
    return calendar


# ---------------------------------------------------------------------------
# 快照构建 / 读取 / 刷新
# ---------------------------------------------------------------------------
async def build_macro_snapshot(days: int = 7) -> dict:
    """构建当日宏观快照：聚合数据 → 规则引擎 → LLM 解读。

    有界化（防弱网下无限等待）：
    - 四路数据收集并行拉取，各自包硬超时（SNAPSHOT_FETCH_TIMEOUTS），
      超时/失败降级为该步空值，其余步不受影响、已取到数据不丢弃；
    - LLM 解读（日历逐条 + 盘前解读）各包 SNAPSHOT_LLM_TIMEOUT 硬超时，超时走既有降级。
    最坏情况整体约 2 分钟内返回完整结构快照（数据不足也算）⇒ 快照必然有界落库。
    """
    indices, calendar, news, breadth, a_share = await asyncio.gather(
        _bounded_fetch(_collect_indices(), "外围指数", SNAPSHOT_FETCH_TIMEOUTS["indices"], []),
        _bounded_fetch(get_financial_calendar(days), "财经日历", SNAPSHOT_FETCH_TIMEOUTS["calendar"], []),
        _bounded_fetch(get_macro_news(hours_back=24, top_n=40), "分级快讯", SNAPSHOT_FETCH_TIMEOUTS["news"], []),
        _bounded_fetch(_collect_breadth(), "大盘宽度", SNAPSHOT_FETCH_TIMEOUTS["breadth"], None),
        _bounded_fetch(_collect_a_share_signals(), "A股技术面", SNAPSHOT_FETCH_TIMEOUTS["indices"], None),
    )

    rule = score_macro(indices, calendar, news, breadth, a_share=a_share)
    created_at = datetime.now(timezone.utc)

    # 5.1：为每条信号补充"判定"（利多/利空/中性），便于面板逐条复核
    for sig in rule.get("signals", []):
        sig["judge"] = "利多" if sig.get("score", 0) > 0 else ("利空" if sig.get("score", 0) < 0 else "中性")

    # 已公布事件：快讯流提取实际值 + LLM 逐条解读（参考 Tab 直接呈现分析）
    calendar = await _bounded_fetch(
        _calendar_ai_analysis(calendar, news), "日历LLM解读", SNAPSHOT_LLM_TIMEOUT, calendar
    )

    llm = await _bounded_fetch(
        _llm_interpretation(indices, calendar, news, rule),
        "盘前LLM解读", SNAPSHOT_LLM_TIMEOUT,
        {"available": False, "interpretation": None},
    )

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


def _sanitize_snapshot(obj: Any) -> Any:
    """递归清洗快照中的非有限浮点（NaN/Infinity）为 None。

    数据源偶发 NaN（停牌/源异常）会直接导致 JSON 序列化 500；
    落库与读库都过一遍，保证任何路径产出的快照均可安全序列化。
    """
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_snapshot(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_snapshot(v) for v in obj]
    return obj


async def _persist_snapshot(snapshot: dict) -> bool:
    """写入 macro_daily_snapshots（date 唯一，upsert）。"""
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        await db[SNAPSHOT_COLLECTION].update_one(
            {"date": snapshot["date"]},
            {"$set": _sanitize_snapshot(snapshot)},
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
        # 清洗存量 NaN/Infinity（历史脏数据 + 序列化 500 兜底）
        return _sanitize_snapshot(doc)

    key = f"macro:snapshot:{date_str}"
    return await cached(key, _load, category="market", valid=lambda v: v is not None)


def snapshot_needs_refresh(snap: dict | None) -> bool:
    """判断快照是否需要在盘中轻量重算一次方向（放弃盘前锁定后支撑"页面打开即当下"）。

    规则：交易时段内，且快照缺失或已过期（created_at 距今 > SNAPSHOT_INTRADAY_REFRESH_SECONDS）
    → 返回 True，前端据此主动调一次 /api/macro/refresh 重算当下方向。
    非交易时段 / 快照足够新鲜 → 不刷新。
    """
    try:
        from app.core.config import settings
        from app.utils.trading_time import is_trading_time
        s = settings.SNAPSHOT_INTRADAY_REFRESH_SECONDS
        if not is_trading_time() or not s:
            return False
        if not snap or not snap.get("created_at"):
            return True
        created = snap["created_at"]
        if isinstance(created, str):
            created = datetime.fromisoformat(
                created.replace("Z", "+00:00")
            )
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        return age > s
    except Exception:
        return False


async def get_macro_reference(refresh: bool = False) -> dict:
    """参考 Tab 独立实时数据：外围指数 / 财经日历 / 重要快讯。

    与宏观快照解耦：不落库、不跑 LLM 逐条解读、不依赖快照是否生成。
    三块数据各自复用已有短 TTL 缓存（指数 market 级+SWR、日历 1 天、快讯 5min/1h），
    并行收集：整体耗时 ≈ 最慢一块，而非三块之和；任一超时降级为空，不拖垮整体。
    """
    # ① 外围指数：market 级缓存（交易 3min / 非交易 30min）；refresh 先清缓存强制重建
    if refresh:
        await clear_cache("macro:ref:indices:v1")

    async def _indices():
        return await cached(
            "macro:ref:indices:v1",
            _collect_indices,
            category="market",
            valid=bool,
            swr=True,
        )

    async def _calendar():
        # 财经日历：1 天 TTL；规则化 analysis 秒回
        return await get_financial_calendar(8)

    async def _news():
        # 快讯：5min/1h 缓存命中秒回；冷重建 108 RSS 源可能 30-60s，
        # 硬超时 60s 降级为空（重建任务仍在后台单飞进行，下个窗口命中缓存）
        try:
            return await asyncio.wait_for(
                get_macro_news(hours_back=24, top_n=40), timeout=60
            )
        except asyncio.TimeoutError:
            logger.warning("参考快讯获取超时（>60s），降级为空")
            return []
        except Exception:
            return []

    indices, calendar, news = await asyncio.gather(_indices(), _calendar(), _news())
    return {
        "indices": indices,
        "calendar": calendar,
        "news_top": news,
        "generated_at": datetime.now(timezone.utc),
    }


async def refresh_macro_snapshot() -> dict:
    """生成今日快照并落库（手动刷新 / 8:15 调度共用）。返回快照。

    放弃盘前锁定：每次生成都用最新数据重算方向基准（basis）并覆盖当日快照，
    页面打开/刷新即可提取当下盘面判断方向。

    兜底：若本次拉取数据不齐全（外围指数缺失或置信度为 0，典型如数据源瞬时限频）、
    而库里已有更完整快照，则保留旧快照方向，避免把好数据退化成空数据。
    """
    snap = await build_macro_snapshot()
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        existing = await db[SNAPSHOT_COLLECTION].find_one({"date": snap["date"]})
        # 新快照数据是否齐全：外围指数到位且置信度 > 0。
        new_data_ok = bool((snap.get("indices") or [])) and float((snap.get("rule") or {}).get("confidence") or 0) > 0
        if not new_data_ok and existing and existing.get("basis"):
            # 数据源瞬时失败：保留旧快照，避免把完整基准覆盖成空数据
            snap["basis"] = dict(existing["basis"])
            snap["rule"] = existing.get("rule") or snap.get("rule")
    except Exception as e:
        logger.warning(f"快照数据齐全度兜底判断跳过: {e}")
    await _persist_snapshot(snap)
    # 清今日快照缓存，下次读取即时生效
    from app.services.cache_layer import clear_cache
    await clear_cache(f"macro:snapshot:{snap['date']}")
    return snap
