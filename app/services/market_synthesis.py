"""市场综合研判 —— 聚合「市场」菜单四页面（大盘看板/短线情绪/概念分析/资讯）+ 市场环境 + 现有买卖信号，
调用快速分析模型产出综合研判结论，并附带个股买卖清单，指导用户买卖操作。

判定方式（纯 LLM）：
- 把四页关键数据 + 市场环境 + 现有买卖信号打包成 prompt 喂给 LLM，输出结构化 verdict。
- LLM 不可用或两次失败 → 降级为基于市场环境的规则结论（llm_available=False），页面不空白、不报错。

买卖清单（确定性）：
- 复用 intraday_guide_service.build_intraday_guide：buys=建议买入触达，sells=持仓卖出建议。

复用项：
- LLM 配置与容错解析：macro_service._get_llm_cfg / _parse_llm_json（稳定且已被宏观解读使用）。
- 数据源：market_dashboard.get_dashboard / market_overview.get_short_term_emotion /
  concept_analysis.get_concept_analysis /
  newsradar.get_radar_cached / retail.retail_strategy_service（市场环境）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.services.macro.macro_service import _get_llm_cfg, _parse_llm_json

logger = logging.getLogger(__name__)

BEIJING = timezone(timedelta(hours=8))

# ── 综合研判 LLM 系统提示：只输出固定 JSON 结构 ──
_SYSTEM_PROMPT = (
    "你是一名资深 A 股交易员与机构策略师。基于给定的市场数据，输出一份当日市场综合研判。\n"
    "只输出一个 JSON 对象，不要输出任何解释文字、不要使用 markdown 代码块：\n"
    '{"direction":"偏多|偏空|中性","confidence":<0-100整数>,"conclusion":"2-3句话总研判",'
    '"strategy":"一句话操作策略，含仓位建议、主攻风格与攻防侧重",'
    '"points":["2-4条具体操作要点：基于数据指出该重仓/该回避的方向，明确买点立场（如：沿5日线低吸科技主线；回避高位连板股）"],'
    '"watch":["1-3条今日需盯的观察信号，如指数关键点位、量能变化、板块轮动确认信号"]，'
    '"risk_tips":["1-3条风险提示"]}\n'
    "数据可能有缺失：缺失时依据已有信息判断并在结论里点明不确定性，不要臆造数据。"
)

_RETRY_TAIL = (
    "\n\n【重要】直接输出符合上述 JSON 结构的原始 JSON："
    "不要输出任何解释文字，不要使用 markdown 代码块（不要以 ``` 开头），结尾不要追加说明。"
)


def _call_llm(cfg: dict, prompt: str) -> dict:
    """非流式调用 chat/completions，返回结构化 verdict；失败抛异常由调用方降级。"""
    import requests

    api_base = cfg["api_base"].rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base += "/chat/completions"
    resp = requests.post(
        api_base,
        json={
            "model": cfg["model"],
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": cfg.get("temperature", 0.3),
            "max_tokens": cfg.get("max_tokens", 1200),
            "stream": False,
        },
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _parse_llm_json(content)


# ── prompt 构建：把四页数据做成精简、分节、可解释的文本 ──

def _fmt_pct(v):
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "n/a"


def _prompt_dashboard(d: dict) -> str:
    if not d:
        return "- （无数据）"
    lines: list[str] = []
    idx = d.get("indices") or []
    if idx:
        lines.append("- 指数: " + " ".join(
            f"{i.get('name')}{_fmt_pct(i.get('change_pct'))}" for i in idx[:6]))
    b = d.get("breadth") or {}
    if b:
        lines.append(f"- 广度: 涨 {b.get('up')} / 跌 {b.get('down')}，"
                     f"平均 {b.get('avg_pct')}%")
    emo = d.get("emotion") or {}
    if emo:
        lines.append(f"- 情绪: {emo.get('label')}（评分 {emo.get('score')}）")
    lim = d.get("limit") or {}
    if lim.get("limit_up") is not None:
        lines.append(f"- 涨跌停: 涨停 {lim.get('limit_up')} / 跌停 {lim.get('limit_down')}，"
                     f"最高连板 {lim.get('max_boards')} 板")
    reg = d.get("regime")
    if reg and reg.get("trend_label"):
        lines.append(f"- 环境: {reg.get('trend_label')} · {reg.get('volatility_label')}"
                     f"{('；' + str(reg.get('advice')) + '') if reg.get('advice') else ''}")
    gain = d.get("top_gainers") or []
    if gain:
        lines.append("- 领涨: " + "、".join(f"{x.get('name')}+{x.get('pct_chg')}%" for x in gain[:5]))
    lose = d.get("top_losers") or []
    if lose:
        lines.append("- 领跌: " + "、".join(f"{x.get('name')}{x.get('pct_chg')}%" for x in lose[:5]))
    return "\n".join(lines) or "- （无数据）"


def _prompt_emotion(e: dict) -> str:
    if not e:
        return "- （无数据）"
    ladder = e.get("ladder") or []
    ladder_s = "；".join(f"{t.get('boards')}板×{t.get('count')}家" for t in ladder) or "无连板梯队"
    return (
        f"- 涨停 {e.get('zt_count')} / 跌停 {e.get('dt_count')} / 炸板 {e.get('zb_count')}\n"
        f"- 连板 {e.get('lianban_count')} 家，最高 {e.get('max_boards')} 板；梯队: {ladder_s}\n"
        f"- 封板率 {e.get('seal_rate')} / 炸板率 {e.get('break_rate')} / 晋级率 {e.get('promotion_rate')}"
    )


def _prompt_concept(c: dict) -> str:
    if not c:
        return "- （无数据）"
    b = c.get("breadth") or {}
    lines = [f"- 概念 {c.get('total')} 个: 涨 {b.get('up')} / 跌 {b.get('down')}，"
             f"平均 {b.get('avg_pct')}%"]
    g = c.get("gainers") or []
    if g:
        lines.append("- 领涨概念: " + "、".join(
            f"{x.get('name')}{_fmt_pct(x.get('pct_chg'))}" for x in g[:5]))
    losers = c.get("losers") or []
    if losers:
        lines.append("- 领跌概念: " + "、".join(
            f"{x.get('name')}{_fmt_pct(x.get('pct_chg'))}" for x in losers[:5]))
    m = c.get("money_leaders") or []
    if m:
        lines.append("- 资金流入: " + "、".join(
            f"{x.get('name')}({x.get('money_flow')}亿)" for x in m[:5]))
    return "\n".join(lines)


def _prompt_radar(rd: dict, limit: int = 12) -> str:
    """资讯：扁平化为最近若干条标题（带来源），控制 prompt 长度。"""
    items: list[dict] = []
    for ind in rd.get("industries") or []:
        for it in ind.get("items") or []:
            items.append({"source": ind.get("name"), "title": it.get("title"), "ts": it.get("ts") or 0})
    if not items:
        return "- （无数据）"
    items.sort(key=lambda x: x["ts"], reverse=True)
    return "\n".join(f"- [{x['source']}] {x['title']}" for x in items[:limit])


_TREND_ZH = {"bull": "偏多/牛市", "range": "震荡", "bear": "偏空/熊市", "sideways": "震荡"}
_VOL_ZH = {"high": "高波动", "normal": "正常", "low": "低波动"}
_BREADTH_ZH = {"broad": "普涨", "neutral": "中性", "narrow": "分化"}
_SENTIMENT_ZH = {"euphoric": "狂热", "neutral": "中性", "panic": "恐慌"}


def _regime_text(reg: dict) -> tuple[str, str]:
    """把 regime 基础值转成 {中文环境描述, 一句话建议}。"""
    trend = (reg or {}).get("trend")
    vol = (reg or {}).get("volatility")
    strategies = (reg or {}).get("active_strategies") or []
    t = _TREND_ZH.get(str(trend), "中性")
    v = _VOL_ZH.get(str(vol), "")
    b = _BREADTH_ZH.get(str((reg or {}).get("breadth")), "")
    s = _SENTIMENT_ZH.get(str((reg or {}).get("sentiment")), "")
    dims = " · ".join(x for x in (v, b, s) if x)
    env = f"{t}{('，' + dims) if dims else ''}"
    advice = f"建议激活策略：{'、'.join(strategies)}" if strategies else "顺势控制仓位，等待偏好方向。"
    return env, advice


def _prompt_regime(reg: dict) -> str:
    if not reg:
        return "- （无数据）"
    env, advice = _regime_text(reg)
    strategies = reg.get("active_strategies") or []
    return (f"- 环境: {env}\n"
            f"- {advice}\n"
            f"- 建议激活策略: {'、'.join(strategies) if strategies else '无'}")


def _prompt_guide(guide: dict) -> str:
    buys = guide.get("buys") or []
    sells = guide.get("sells") or []
    lines: list[str] = []
    if buys:
        lines.append("- 建议买入候选:")
        for b in buys[:10]:
            tp = b.get("trigger_price")
            lines.append(f"  • {b.get('name')}: 触发价 {tp}，"
                         f"现价 {b.get('last_price')}，{b.get('advice') or ''}")
    if sells:
        lines.append("- 持仓卖出建议:")
        for s in sells[:15]:
            lines.append(f"  • {s.get('name')}: {s.get('advice')}，"
                         f"盈亏 {s.get('profit_loss_rate')}%，卖比 {s.get('sell_pct')}")
    if not lines:
        lines.append("- 暂无明确买卖清单")
    return "\n".join(lines)


def _build_prompt(dashboard, emotion, concept, radar, regime, guide) -> str:
    return (
        "【大盘看板】\n" + _prompt_dashboard(dashboard)
        + "\n\n【短线情绪】\n" + _prompt_emotion(emotion)
        + "\n\n【概念分析】\n" + _prompt_concept(concept)
        + "\n\n【资讯要闻】\n" + _prompt_radar(radar)
        + "\n\n【市场环境】\n" + _prompt_regime(regime)
        + "\n\n【现有买卖信号】\n" + _prompt_guide(guide)
        + "\n\n请综合以上信息，输出当日市场综合研判 JSON。"
    )


def _fallback_verdict(regime: dict) -> dict:
    """LLM 不可用/失败时的规则兜底结论（基于市场环境）。"""
    trend = (regime or {}).get("trend")
    env, advice = _regime_text(regime)
    if trend == "bull":
        direction = "偏多"
    elif trend == "bear":
        direction = "偏空"
    else:
        direction = "中性"
    return {
        "direction": direction,
        "confidence": 50,
        "conclusion": f"市场环境为{env}；依据环境规则给出方向（未启用 LLM 深度研判）。",
        "strategy": advice,
        "points": ["规则兜底：按当前市场环境匹配的攻防方向执行，控制仓位等待信号确认"],
        "watch": ["市场环境趋势是否延续（关注后续成交量与宽度变化）"],
        "risk_tips": ["本结论为规则兜底（AI 研判暂不可用）", "数据来自公开市场级信息，仅供参考，不构成投资建议"],
    }


def _slim_sources(dashboard, emotion, concept, radar, regime) -> dict:
    """只回传前端证据展示所需的精简字段（避免把完整大对象透传）。"""
    d = dashboard or {}
    e = emotion or {}
    c = concept or {}
    return {
        "dashboard": {
            "indices": d.get("indices"),
            "breadth": d.get("breadth"),
            "emotion": d.get("emotion"),
            "limit": d.get("limit"),
            "top_gainers": (d.get("top_gainers") or [])[:5],
            "top_losers": (d.get("top_losers") or [])[:5],
            "updated": d.get("updated"),
        },
        "emotion": {
            "date": e.get("date"),
            "zt_count": e.get("zt_count"), "dt_count": e.get("dt_count"),
            "max_boards": e.get("max_boards"), "lianban_count": e.get("lianban_count"),
            "zb_count": e.get("zb_count"),
            "seal_rate": e.get("seal_rate"), "break_rate": e.get("break_rate"),
            "promotion_rate": e.get("promotion_rate"), "ladder": e.get("ladder"),
        },
        "concept": {
            "total": c.get("total"), "breadth": c.get("breadth"),
            "gainers": (c.get("gainers") or [])[:5],
            "losers": (c.get("losers") or [])[:5],
            "money_leaders": (c.get("money_leaders") or [])[:5],
            "as_of": c.get("as_of"),
        },
        "regime": regime or {},
        "radar": _slim_radar(radar or {}),
    }


def _slim_radar(rd: dict) -> dict:
    out = {
        "generated_at": rd.get("generated_at"),
        "stats": rd.get("stats"),
    }
    inds = []
    for ind in (rd.get("industries") or []):
        inds.append({
            "name": ind.get("name"),
            "total": ind.get("total"),
            "items": [{"title": x.get("title"), "url": x.get("url") or "",
                      "time": x.get("time"), "source": x.get("source")}
                      for x in (ind.get("items") or [])[:3]],
        })
    out["industries"] = inds
    return out


async def build_market_synthesis(user_id: str) -> dict:
    """聚合四页数据 + 市场环境 + 买卖信号 → 纯 LLM 综合研判 + 买卖清单。"""
    # ── 并行采集（每项独立降级，绝不外抛） ──
    async def _guard(coro, default):
        try:
            return await coro
        except Exception as e:
            logger.warning(f"综合研判数据源失败（降级）: {e}")
            return default

    from app.services.market_dashboard import get_dashboard
    from app.services.market_overview import get_short_term_emotion
    from app.services.concept_analysis import get_concept_analysis
    from app.services.newsradar import get_radar_cached
    from app.services.intraday_guide_service import build_intraday_guide

    dashboard, emotion, concept, radar, regime_res, guide = await asyncio.gather(
        _guard(get_dashboard(), {}),
        _guard(get_short_term_emotion(), {}),
        _guard(get_concept_analysis(), {}),
        _guard(get_radar_cached(), {}),
        _guard(_detect_regime(), {}),
        _guard(build_intraday_guide(user_id), {"buys": [], "sells": []}),
    )
    regime = regime_res if isinstance(regime_res, dict) else {}
    buys = guide.get("buys") or []
    sells = guide.get("sells") or []

    # ── 纯 LLM 研判（失败重试一次；仍失败用规则兜底） ──
    verdict: dict | None = None
    llm_available = False
    cfg = _get_llm_cfg()
    if cfg:
        for attempt in (1, 2):
            try:
                prompt = _build_prompt(dashboard, emotion, concept, radar, regime, guide)
                if attempt == 2:
                    prompt += "\n\n" + _RETRY_TAIL
                res = await asyncio.to_thread(_call_llm, cfg, prompt)
                verdict = {
                    "direction": res.get("direction") or "中性",
                    "confidence": int(res.get("confidence") or 0),
                    "conclusion": res.get("conclusion") or "",
                    "strategy": res.get("strategy") or "",
                    "points": res.get("points") or [],
                    "watch": res.get("watch") or [],
                    "risk_tips": res.get("risk_tips") or [],
                }
                llm_available = True
                break
            except Exception as e:
                logger.warning(f"综合研判 LLM 第 {attempt}/2 次失败（降级）: {e}")
    if not llm_available:
        verdict = _fallback_verdict(regime)

    return {
        "verdict": verdict,
        "buys": buys,
        "sells": sells,
        "llm_available": llm_available,
        "as_of": datetime.now(BEIJING).strftime("%Y-%m-%d %H:%M:%S"),
        "sources": _slim_sources(dashboard, emotion, concept, radar, regime),
    }


async def _detect_regime() -> dict:
    """获取市场环境四维检测（retail regime），失败返回空 dict。"""
    from app.services.retail.retail_strategy_service import get_retail_strategy_service
    regime, _ = await get_retail_strategy_service().detect_regime_auto()
    return regime.to_dict()