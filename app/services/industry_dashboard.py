"""行业板块看板数据层 —— 行业多周期资金流 + 行业 AI 分析。

数据源：同花顺 stock_fund_flow_industry（即时 + 3/5/10/20 日排行），与
「大盘热力图·行业板块全景」共用 market 级缓存，不重复抓取、不估算。
- get_industry_period_flows()：多周期资金流（金额单位元），供前端「行业资金·多周期」卡
- analyze_industry(name)：单行业 AI 分析（LLM 优先，规则兜底），
  输入即时数据 + 多周期数据，输出与个股趋势同构的操作结论。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import vibe_astock as astock
from app.services.cache_layer import cached
from app.services.market_overview import _fund_amount, _parse_pct_str, get_overview
from app.services.stock_quadrant_analysis import (
    _AI_RETRY_TAIL,
    _llm_cfg,
    _llm_chat,
    _normalize_llm_result,
    _score_to_action,
)

logger = logging.getLogger("webapi")

BEIJING = timezone(timedelta(hours=8))

# 多周期档 symbol 映射（同花顺 stock_fund_flow_industry）
PERIOD_SYMBOLS = {"3": "3日排行", "5": "5日排行", "10": "10日排行", "20": "20日排行"}
PERIOD_LABELS = {"3": "3日", "5": "5日", "10": "10日", "20": "20日"}


def _num(v) -> int:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def _r(v, n: int = 2) -> float | None:
    try:
        return round(float(v), n)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 1) 行业多周期资金流（3/5/10/20 日）
# ---------------------------------------------------------------------------
def _build_period_flows() -> dict[str, list[dict]]:
    """拉取 3/5/10/20 日排行（各档独立抓取约 0.8s）。金额归一为「元」。单档失败跳过。"""
    periods: dict[str, list[dict]] = {}
    for key, symbol in PERIOD_SYMBOLS.items():
        try:
            f = astock._akshare().stock_fund_flow_industry(symbol=symbol)
            if f is None or getattr(f, "empty", True):
                continue
            # 阶段涨跌幅为「X.XX%」字符串 → 数值；金额列归一为「元」
            if "阶段涨跌幅" in f.columns:
                f["阶段涨跌幅"] = f["阶段涨跌幅"].map(_parse_pct_str)
            for col in ("净额", "流入资金", "流出资金"):
                if col in f.columns:
                    f[col] = f[col].map(_fund_amount)
            rows = []
            for _, row in f.iterrows():
                rows.append({
                    "name": str(row["行业"]),
                    "pct": round(float(_parse_pct_str(row.get("阶段涨跌幅", 0)) or 0), 2),
                    "net": round(float(row.get("净额", 0) or 0), 2),
                    "inflow": round(float(row.get("流入资金", 0) or 0), 2),
                    "outflow": round(float(row.get("流出资金", 0) or 0), 2),
                    "firms": _num(row.get("公司家数")),
                })
            rows.sort(key=lambda x: x["net"], reverse=True)
            if rows:
                periods[key] = rows
        except Exception as e:
            logger.warning(f"行业资金流多周期档[{symbol}]失败: {type(e).__name__}: {str(e)[:120]}")
    return periods


async def get_industry_period_flows() -> dict:
    """行业多周期资金流（3/5/10/20 日）。Redis market 级缓存，金额单位「元」。"""
    def build():
        return {
            "as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M"),
            "periods": _build_period_flows(),
        }
    return await cached(
        "vibe:industry_period_flows", build, category="market",
        valid=lambda v: bool((v.get("periods") or {}).get("5")),
    )


# ---------------------------------------------------------------------------
# 2) 行业规则引擎（兜底 + LLM 参考信号）
# ---------------------------------------------------------------------------
def _net_ratio(net: float, inflow: float, outflow: float) -> float | None:
    """主力净额占比（净额 / 流入+流出绝对值，%）。"""
    denom = abs(inflow) + abs(outflow)
    return (net / denom * 100) if denom > 0 else None


def _industry_rule_conclusion(name: str, today: dict, period_pts: dict[str, dict | None]) -> dict:
    """行业规则结论（供兜底 + 作为 LLM 参考）。评分 -100~100，六档 action。"""
    pct = _r(today.get("pct"))
    net = _r(today.get("net"))
    inflow = _r(today.get("inflow"))
    outflow = _r(today.get("outflow"))
    lead_pct = _r(today.get("lead_pct"))

    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    # 1) 今日涨跌幅分档
    if pct is not None:
        if pct >= 9.5:
            score += 25
            reasons.append(f"今日强势上涨 {pct}%")
        elif pct >= 5:
            score += 18
            reasons.append(f"今日上涨 {pct}%，动能较强")
        elif pct >= 2:
            score += 12
            reasons.append(f"今日上涨 {pct}%")
        elif pct >= 0:
            score += 6
        elif pct >= -2:
            score -= 5
        elif pct >= -5:
            score -= 12
            risks.append(f"今日下跌 {pct}%，警惕走弱")
        elif pct >= -9.5:
            score -= 18
            risks.append(f"今日大跌 {pct}%，短期承压")
        else:
            score -= 25
            risks.append(f"今日重挫 {pct}%")

    # 2) 主力净占比分档
    ratio = _net_ratio(net or 0.0, inflow or 0.0, outflow or 0.0)
    if ratio is not None:
        if ratio >= 15:
            score += 20
            reasons.append(f"主力净流入占比 {ratio:.0f}%，资金主动性强")
        elif ratio >= 8:
            score += 14
            reasons.append(f"主力净流入占比 {ratio:.0f}%")
        elif ratio >= 3:
            score += 8
        elif ratio >= 0:
            score += 3
        elif ratio >= -3:
            score -= 3
        elif ratio >= -8:
            score -= 8
            risks.append(f"主力净流出占比 {ratio:.0f}%")
        else:
            score -= 14
            risks.append(f"主力净流出占比 {ratio:.0f}%，资金承压")

    # 3) 领涨股涨幅
    if lead_pct is not None:
        if lead_pct >= 9.5:
            score += 8
            reasons.append(f"领涨股涨停 {lead_pct}%，板块人气强")
        elif lead_pct >= 3:
            score += 5
            reasons.append(f"领涨股上涨 {lead_pct}%")
        elif lead_pct >= 0:
            score += 2
        elif lead_pct >= -3:
            score -= 3
        else:
            score -= 8
            risks.append(f"领涨股下跌 {lead_pct}%，龙头转弱")

    # 4) 多周期净额符号一致性
    nets = [_r((p or {}).get("net")) for p in period_pts.values()]
    signs = [1 if (n or 0) > 0 else -1 if (n or 0) < 0 else 0 for n in nets if n is not None]
    if len(signs) >= 3:
        if all(s > 0 for s in signs):
            score += 8
            reasons.append("3/5/10/20 日资金净流入一致，中期做多信号")
        elif all(s < 0 for s in signs):
            score -= 8
            risks.append("3/5/10/20 日资金净流出一致，中期承压")
        elif sum(s > 0 for s in signs) > sum(s < 0 for s in signs):
            score += 3
            reasons.append("多周期资金净流入居多")
        else:
            score -= 3
            risks.append("多周期资金净流出居多")

    # 5) 多周期涨跌动量（10/20 日阶段涨跌幅同向取其一）
    for p in (_r((period_pts.get("10") or {}).get("pct")), _r((period_pts.get("20") or {}).get("pct"))):
        if p is None:
            continue
        if p >= 5:
            score += 3
            reasons.append(f"中期累计上涨 {p}%，趋势向上")
            break
        if p <= -5:
            score -= 3
            risks.append(f"中期累计下跌 {p}%，趋势向下")
            break

    score = max(-100, min(100, score))
    action, action_label = _score_to_action(score)

    # 一句话结论
    net_yi = (net or 0.0) / 1e8
    parts = [f"{name}行业"]
    if pct is not None:
        parts.append(f"今日 {pct}%")
    parts.append(("主力净流入" if net_yi >= 0 else "主力净流出") + f" {abs(net_yi):.2f} 亿")
    if signs:
        pos, neg = sum(1 for s in signs if s > 0), sum(1 for s in signs if s < 0)
        parts.append("多周期资金" + ("流入为主" if pos >= neg else "流出为主"))
    parts.append(f"综合评分 {score} 分")
    parts.append(f"操作建议：{action_label}")
    summary = "，".join(parts) + "。"

    if not reasons:
        reasons.append("今日数据信号平淡，方向待观察")
    return {
        "action": action, "action_label": action_label, "score": score,
        "reasons": reasons[:6], "risks": risks[:5], "summary": summary,
    }


# ---------------------------------------------------------------------------
# 3) 行业 AI 分析（LLM 优先，规则兜底）
# ---------------------------------------------------------------------------
_INDUSTRY_SYSTEM_PROMPT = (
    "你是一名资深 A 股行业策略分析师，精通行业轮动、资金流、技术面与景气度分析。\n"
    "我会给你一个行业在「大盘看板」中的数据：今日行情（涨跌幅/主力资金/领涨股/行业指数）"
    "与多周期资金流（3/5/10/20 日），请基于这些数据给出该行业当前的操作结论。\n"
    "只输出一个 JSON 对象，不要输出任何解释文字、不要使用 markdown 代码块：\n"
    '{"action":"strong_buy|buy|hold|wait|reduce|avoid","action_label":"积极买入|逢低关注|持有观察|观望等待|减仓防范|回避为主",'
    '"score":<必填，-100~100 的整数，越高越积极>,"summary":"1-2 句话的操作结论",'
    '"reasons":["判断要点 2-4 条，每条一句话，必须基于给定数据"],"risks":["风险提示 0-3 条"]}\n'
    "action 六档含义：strong_buy=积极关注（资金+动量+人气共振）；buy=逢低关注（有逻辑但需等买点）；"
    "hold=持有观察（趋势未破）；wait=观望等待（方向不明）；reduce=减仓防范（资金流出/趋势走弱）；"
    "avoid=回避为主（破位/资金持续流出）。\n"
    "数据可能缺失：缺失时依据已有信息判断并在结论中体现，不要臆造数据。篇幅：全文 300 字以内。"
)


def _build_industry_ai_prompt(name: str, today: dict, period_pts: dict[str, dict | None], rule: dict) -> str:
    """"组装行业 AI 分析的用户文本（今日即时 + 多周期）。"""
    net_yi = (today.get("net") or 0) / 1e8
    inflow_yi = (today.get("inflow") or 0) / 1e8
    outflow_yi = (today.get("outflow") or 0) / 1e8
    pct_s = _r(today.get("pct"))
    lines = [
        f"【行业】{name}",
        f"【今日行情】涨跌幅: {pct_s if pct_s is not None else '—'}%"
        f"；主力净流入: {net_yi:.2f} 亿（流入 {inflow_yi:.2f} 亿 / 流出 {outflow_yi:.2f} 亿）",
        f"【领涨股】{(today.get('lead') or '—')}，涨跌幅 {_r(today.get('lead_pct'))}%，现价 {_r(today.get('lead_price'))} 元",
        f"【行业指数】{_r(today.get('index'))}",
        "【多周期资金流与累计涨跌】",
    ]
    for k in ("3", "5", "10", "20"):
        p = period_pts.get(k)
        if not p:
            lines.append(f"  {k}日: 数据缺失")
            continue
        pct_k = _r(p.get("pct"))
        net_k = (_r(p.get("net")) or 0) / 1e8
        lines.append(f"  {k}日: 累计涨跌 {pct_k if pct_k is not None else '—'}%，净额 {net_k:.2f} 亿")
    lines.append(f"【规则引擎参考】基于上述数据的规则评分 {rule['score']} 分，方向：{rule['action_label']}（仅供模型参考，请独立判断）")
    lines.append("请基于上述行业数据，给出该行业当前的操作结论 JSON。")
    return "\n".join(lines)


async def analyze_industry(name: str) -> dict[str, Any]:
    """对单个行业给出操作结论（LLM 优先，规则兜底）。

    取数全部走缓存（get_overview + get_industry_period_flows），不重复抓取；
    名称按同花顺行业名精确匹配。
    """
    name = str(name or "").strip()
    ov = await get_overview()
    sector_map = {str(s.get("name") or "").strip(): s for s in (ov.get("sectors") or [])}
    today = sector_map.get(name)
    if today is None:
        return {"found": False, "name": name, "message": f"未找到行业「{name}」"}

    flows = await get_industry_period_flows()
    period_pts = {
        k: {str(r.get("name") or "").strip(): r for r in rows}.get(name)
        for k, rows in (flows.get("periods") or {}).items()
    }

    # 规则引擎先行（供兜底 + 作为 LLM 的参考信号）
    rule = _industry_rule_conclusion(name, today, period_pts)

    # LLM 优先：失败/未配置 → 规则兜底
    engine = "rule"
    pick = {k: rule[k] for k in ("action", "action_label", "score", "reasons", "risks", "summary")}
    cfg = _llm_cfg()
    if cfg:
        for attempt in (1, 2):
            try:
                user_p = _build_industry_ai_prompt(name, today, period_pts, rule)
                if attempt == 2:
                    user_p += _AI_RETRY_TAIL
                res = await asyncio.to_thread(_llm_chat, cfg, _INDUSTRY_SYSTEM_PROMPT, user_p)
                pick = _normalize_llm_result(res, rule)
                engine = "llm"
                break
            except Exception as e:
                logger.warning(f"行业AI分析 LLM 第 {attempt}/2 次失败（降级规则）: {type(e).__name__}: {str(e)[:120]}")

    return {
        "found": True,
        "name": name,
        "as_of": ov.get("updated", ""),
        "engine": engine,
        "action": pick["action"], "action_label": pick["action_label"],
        "score": pick["score"],
        "reasons": pick["reasons"], "risks": pick["risks"], "summary": pick["summary"],
        "data": {
            "today": {
                "pct": _r(today.get("pct")),
                "net_yi": _r((today.get("net") or 0) / 1e8, 3),
                "inflow_yi": _r((today.get("inflow") or 0) / 1e8, 3),
                "outflow_yi": _r((today.get("outflow") or 0) / 1e8, 3),
                "index": _r(today.get("index")),
                "lead": today.get("lead") or "",
                "lead_pct": _r(today.get("lead_pct")),
                "lead_price": _r(today.get("lead_price")),
            },
            "period_flows": {
                k: {
                    "pct": _r((p or {}).get("pct")),
                    "net_yi": _r(((p or {}).get("net") or 0) / 1e8, 3),
                }
                for k, p in period_pts.items()
            },
        },
    }