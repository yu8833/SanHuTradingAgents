"""Agent 策略问股 —— 对话执行服务。

设计（务实版，避免 bind_tools 的 schema 依赖风险）：
- 每轮先注入「策略模板 + 环境画像 + 可用工具说明」，由 LLM 判断需要哪些数据。
- 一次「预取工具数据」阶段：按用户消息关键词命中相关工具（get_stock_data /
  get_risk_scan / get_fund_flow / get_profit_forecast / get_hot_stocks 等），
  ainvoke 真实执行，结果拼进 system 上下文。
- 再走一次 LLM 生成最终回答（流式 NDJSON）。
- 预算护栏：入轮前条件 $inc（rounds/tokens/cost），触顶中断并标记 budget_exceeded。
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

from app.models.chat import ChatTurn
from app.services.chat_session_service import (
    append_turn,
    budget_view,
    charge_budget,
    get_session,
    mark_budget_exceeded,
)

logger = logging.getLogger("webapi")

# ── 工具注册表：名字 → 可 ainvoke 的工具函数（延迟 import） ──
_TOOLS = {}


def _load_tools() -> dict:
    global _TOOLS
    if _TOOLS:
        return _TOOLS
    from tradingagents.agents.utils.core_stock_tools import get_stock_data
    from tradingagents.agents.utils.signal_data_tools import (
        get_dragon_tiger_board,
        get_fund_flow,
        get_hot_stocks,
        get_industry_comparison,
        get_lockup_expiry,
        get_margin_trading,
        get_northbound_flow,
        get_profit_forecast,
        get_risk_scan,
        get_shareholder_concentration,
    )
    _TOOLS = {
        "get_stock_data": get_stock_data,
        "get_hot_stocks": get_hot_stocks,
        "get_northbound_flow": get_northbound_flow,
        "get_fund_flow": get_fund_flow,
        "get_dragon_tiger_board": get_dragon_tiger_board,
        "get_lockup_expiry": get_lockup_expiry,
        "get_industry_comparison": get_industry_comparison,
        "get_margin_trading": get_margin_trading,
        "get_shareholder_concentration": get_shareholder_concentration,
        "get_risk_scan": get_risk_scan,
        "get_profit_forecast": get_profit_forecast,
    }
    return _TOOLS


def _ticker_from_msg(msg: str) -> str | None:
    """从用户消息提取 6 位 A 股代码。"""
    m = re.search(r"\b(\d{6})\b", msg or "")
    return m.group(1) if m else None


_TOOL_KEYWORDS = [
    ("get_hot_stocks", ("热点", "热门", "强势股")),
    ("get_northbound_flow", ("北向", "外资")),
    ("get_fund_flow", ("主力", "资金流", "净流入", "净流出")),
    ("get_dragon_tiger_board", ("龙虎榜", "游资")),
    ("get_lockup_expiry", ("解禁", "减持")),
    ("get_industry_comparison", ("板块", "行业", "对比")),
    ("get_margin_trading", ("两融", "融资", "杠杆")),
    ("get_shareholder_concentration", ("股东户数", "筹码")),
    ("get_risk_scan", ("风险", "雷", "违约", "退市")),
    ("get_profit_forecast", ("业绩", "预测", "盈利", "EPS")),
]


def _select_tools(msg: str, ticker: str | None) -> list[str]:
    """按关键词选择要预取的工具名称。"""
    out: list[str] = []
    if ticker:
        out.append("get_stock_data")
    for name, kws in _TOOL_KEYWORDS:
        if any(k in msg for k in kws) and name not in out:
            out.append(name)
    # 预算保护：单轮最多取 4 个工具
    return out[:4]


def _tool_args(name: str, msg: str, ticker: str | None) -> dict:
    """按工具构造调用参数（尽量从消息提码/日期）。"""
    cur = ""
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", msg or "")
    if m:
        cur = m.group(1)
    if name == "get_stock_data" and ticker:
        return {"symbol": ticker, "start_date": cur or "2026-01-01", "end_date": cur or "2026-12-31"}
    if name == "get_hot_stocks":
        return {"curr_date": cur}
    if name == "get_northbound_flow":
        return {"curr_date": cur or "2026-09-04", "include_history": False}
    if ticker:
        return {"ticker": ticker, "curr_date": cur or "2026-09-04"}
    return {}


async def _prefetch_tools(msg: str, ticker: str | None) -> list[dict]:
    """执行工具预取，返回 [{name, ok, text}]。失败不中断。"""
    _load_tools()
    results = []
    for name in _select_tools(msg, ticker):
        fn = _TOOLS.get(name)
        if fn is None:
            continue
        try:
            args = _tool_args(name, msg, ticker)
            text = str(await fn.ainvoke(args))
            results.append({"name": name, "ok": True, "text": text[:1500]})
        except Exception as e:
            logger.warning("问股工具 %s 调用失败: %s", name, e)
            results.append({"name": name, "ok": False, "text": f"调用失败: {e}"})
    return results


_SYSTEM = (
    "你是 SANHU 系统的资深 A 股策略分析师。用中文回答，结论必须落到可执行操作。\n"
    "纪律：给出方向、入场位、止损位、仓位；必须列失效条件；不确定时明确说不确定。\n"
    "评分：正向信号 +8~+15，负向 -10~-20，不确定维持中性并降低置信度。\n"
)

# ── 策略路由（管道C）：7 个新增策略 → 各自 LLM 模板；其余走量化 filter 工具 ──
_STRATEGY_KEYWORDS = {
    "chan_theory": ("缠论", "中枢", "背驰", "分型", "笔段"),
    "wave_theory": ("波浪", "浪型", "艾略特", "五浪", "推动浪", "调整浪"),
    "event_driven": ("事件驱动", "事件", "催化"),
    "expectation_repricing": ("预期重估", "预期差", "预期修复", "重估", "利好不涨"),
    "emotion_cycle": ("情绪周期", "情绪", "换手率", "过热", "退潮"),
    "one_yang_three_yin": ("一阳夹三阴", "阳夹阴", "多方蓄势"),
    "bottom_volume": ("底部放量", "放量", "缩量后", "反转底部"),
}


def _route_strategy(msg: str) -> str | None:
    """按关键词路由到策略模板；顺序：7 新增策略 → 存量策略（registry 元数据）。

    存量量化策略未命中模板时，由 _build_strategy_prompt 回退到 registry 元数据
    （description + 买卖规则 + 参数）注入，LLM 依据已预取的行情数据执行判断。
    """
    for sid, kws in _STRATEGY_KEYWORDS.items():
        if any(k in msg for k in kws):
            return sid
    try:
        import app.strategy_system.strategies  # noqa: F401 确保存量策略已注册进 registry
        from app.strategy_system.registry import registry
        all_strats = registry.all()
        for s in all_strats:                      # 优先策略名精确包含
            if s.name and s.name in msg:
                return s.id
        for s in all_strats:                      # 其次 tags 命中
            if any(t in msg for t in s.tags):
                return s.id
    except Exception:
        pass
    return None


def _regime_profile() -> str:
    """注入当日大盘画像（复用 market_dashboard 实时检测结果；无则默认中性环境）。"""
    try:
        from app.services.market_dashboard import _market_regime
        r = _market_regime() or {}
        trend = r.get("trend_label") or "中性"
        vol = r.get("volatility_label") or "波动待研判"
        advice = r.get("advice") or ""
        as_of = r.get("as_of") or ""
        hint = f"当前市场环境：{trend}＋{vol}"
        if advice:
            hint += f"（建议：{advice}）"
        if as_of:
            hint += f"（检测时间：{as_of}）"
        return hint
    except Exception:
        return "（未获取到当日大盘画像，回答时默认中性环境）"


def _build_strategy_prompt(strategy_id: str) -> str:
    """策略提示词：优先 7 新增策略模板；存量量化策略回退 registry 元数据。"""
    try:
        from app.strategy_system.strategy_templates import build_strategy_prompt
        t = build_strategy_prompt(strategy_id)
        if t:
            return t
    except Exception:
        pass
    try:
        import app.strategy_system.strategies  # noqa: F401 确保存量策略已注册进 registry
        from app.strategy_system.registry import registry
        s = registry.get(strategy_id)
        if s:
            parts = [f"【{s.name}·策略说明】{s.description}"]
            if s.buy_desc:
                parts.append("【买入规则】" + "；".join(s.buy_desc))
            if s.sell_desc:
                parts.append("【卖出规则】" + "；".join(s.sell_desc))
            if s.params:
                defaults = "; ".join(
                    f"{p.get('label', p.get('id'))}={p.get('default')}" for p in s.params
                )
                parts.append(f"【关键参数】{defaults}")
            parts.append("【结论约束】给出方向、入场位、止损位、仓位，并输出失效条件。")
            return "\n".join(parts)
    except Exception:
        pass
    return ""


async def _run_llm_stream(messages: list[dict], cfg: dict) -> AsyncIterator[dict]:
    """调用 LLM 流式生成；yield {type: delta|error|done, text?, message?}。"""
    import requests

    api_base = str(cfg["api_base"]).rstrip("/")
    if not api_base.endswith("/chat/completions"):
        api_base += "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": float(cfg.get("temperature", 0.7)),
        "max_tokens": int(cfg.get("max_tokens", 4000)),
        "stream": True,
    }
    try:
        resp = requests.post(
            api_base, json=payload, stream=True, timeout=120,
            headers={"Authorization": f"Bearer {cfg['api_key']}",
                     "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            yield {"type": "error", "message": f"AI 服务返回错误({resp.status_code}): {resp.text[:300]}"}
            return
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            chunk = line[6:]
            if chunk.strip() == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
                delta = obj.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content", "")
                if text:
                    yield {"type": "delta", "text": text}
            except (json.JSONDecodeError, IndexError, KeyError):
                continue
        yield {"type": "done"}
    except requests.exceptions.Timeout:
        yield {"type": "error", "message": "AI 响应超时，请稍后重试。"}
    except Exception as e:
        yield {"type": "error", "message": f"对话失败：{e}"}


async def run_turn(session_id: str, user_msg: str, llm_cfg: dict | None) -> AsyncIterator[dict]:
    """执行一轮对话，产出 NDJSON 事件流。"""
    session = await get_session(session_id)
    if not session:
        yield {"type": "error", "message": "会话不存在"}
        return
    if session.status != "active":
        yield {"type": "error", "message": "会话已关闭或预算超限"}
        return

    # 预算门禁：占位 1 轮（失败表示触顶）
    if not await charge_budget(session_id, 0, 0, 0.0, ""):
        await mark_budget_exceeded(session_id)
        yield {"type": "error", "code": "budget_exceeded",
               "message": "会话预算已达上限（轮次）。请新建会话。"}
        return

    if not llm_cfg or not llm_cfg.get("api_key"):
        yield {"type": "error", "message": "系统尚未配置 AI 模型或 API Key，请先在设置中配置。"}
        return

    ticker = _ticker_from_msg(user_msg)
    strategy = _route_strategy(user_msg)

    # 1) 工具预取
    yield {"type": "info", "text": "正在获取行情数据…" if ticker else "正在分析…"}
    tool_results = await _prefetch_tools(user_msg, ticker)

    # 2) 组装 system 上下文
    tool_blob = ""
    for r in tool_results:
        mark = "✅" if r["ok"] else "⚠️"
        tool_blob += f"\n[{mark} {r['name']}]\n{r['text'][:1000]}\n"
    hint = _build_strategy_prompt(strategy) if strategy else ""
    sys_msg = _SYSTEM
    if strategy:
        sys_msg += f"\n用户要求用该策略分析：\n{hint}"
    if tool_blob:
        sys_msg += f"\n【已获取的实时数据】\n{tool_blob}"
    if ticker:
        sys_msg += f"\n【标的】{ticker}"
    sys_msg += f"\n【当日大盘画像】{_regime_profile()}"

    history = []
    for turn in session.messages[-6:]:  # 保留最近 6 轮
        history.append({"role": turn.role, "content": turn.content})

    messages = [{"role": "system", "content": sys_msg}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_msg})

    # 3) LLM 流式回答
    full_answer = ""
    async for evt in _run_llm_stream(messages, llm_cfg):
        if evt.get("type") == "delta":
            full_answer += evt.get("text", "")
        yield evt
        if evt.get("type") in ("error", "done"):
            break

    # 4) 记账 + 落消息（仅成功/部分成功时；error 不追加）
    if full_answer.strip():
        # 消耗估算：按字符粗略估计 token（输入=上下文长度，输出=回答长度）
        est_in = sum(len(m.get("content", "")) for m in messages) // 2
        est_out = len(full_answer) // 2
        # count_round=False：轮次已在入轮门禁记账，这里只补 tokens/cost
        await charge_budget(session_id, est_in, est_out, 0.0, llm_cfg.get("model", ""), count_round=False)
        await append_turn(session_id, ChatTurn(role="user", content=user_msg))
        await append_turn(session_id, ChatTurn(role="assistant", content=full_answer))


def session_budget_view(session_id: str):
    return budget_view(session_id)