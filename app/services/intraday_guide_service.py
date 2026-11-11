"""盘中买卖实时指导 + 盘前卖出观测（卖出侧缺口补齐）。

用户诉求两条主线：
  A. 盘前能预测「哪些股票需要卖」→ 今日卖出观测（持仓逐只评估：止损/止盈 + 三买三卖卖点）
     —— 经 plan_generation_service 并入当日计划结果 sell_candidates，由流水线审计展示。
  B. 盘中能指导「已买入的股票是否要卖、什么时候卖」→ 持仓卖出建议（信号 + 实时价 + 止损止盈）
     与「没买入的股票什么时候适合买」→ 当日计划/候选买入触达指导（实时价偏离触发价）。

设计要点：
- 卖出信号评估（S1/S2/S3/SafetyNet/TrailingStop）复用三买三卖 check_single_stock，
  进程内按「代码+日期」缓存（TTL 5 分钟），盘中重复轮询/刷新不重复重算；
- 止损/止盈触发用实时行情价格判定（比信号晚一拍更直接）；
- 全程容错：任何单一数据源失败只降级该行，不阻断整体返回。
"""
from __future__ import annotations

import logging
import threading
import time

from app.core.database import get_mongo_db
from app.services.retail.exit_rule_engine import PositionExitContext, evaluate_unified_exit
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

# 卖出方向信号（与 monitor_service 同口径）
_SELL_SIGNAL_TYPES = {"S1", "S2", "S3", "SafetyNet", "TrailingStop"}
# 同时多信号命中时的优先级（高 → 低）
_SELL_PRIORITY = {"S3": 5, "SafetyNet": 4, "S2": 3, "S1": 2, "TrailingStop": 1}
# 卖出观测/指导的上限（防止持仓过多时拖慢接口）
_SELL_LIMIT = 20
# 卖出信号评估缓存：5 分钟（盘中起算，跑错/失败下次重试）
_EVAL_CACHE_TTL = 300
_eval_cache: dict[str, tuple[float, dict | None]] = {}
_eval_lock = threading.Lock()


async def _eval_sell_signal(code: str) -> dict | None:
    """对单只股票做三买三卖卖点评估，返回最高优先级 S 系信号（已合并实时快照）。

    失败/无信号返回 None（不缓存失败标记以外的中间态）；结果按「代码+日期」缓存。
    """
    raw = str(code).strip()
    # A股 6 位、港股 5 位：统一 zfill(6) 会把 00700 变成 000700（另一只股票）
    code = (raw.zfill(6) if len(raw) >= 6 else raw.zfill(5)) if raw.isdigit() else raw
    if not code:
        return None
    today = now_tz().strftime("%Y-%m-%d")
    key = f"{code}:{today}"
    with _eval_lock:
        hit = _eval_cache.get(key)
        if hit and time.monotonic() - hit[0] < _EVAL_CACHE_TTL:
            return hit[1]
    result: dict | None = None
    try:
        from app.services.three_buys_three_sells_service import get_three_buys_three_sells_service
        svc = get_three_buys_three_sells_service()
        r = await svc.check_single_stock(code)
        if r and r.get("success"):
            # 无论是否命中卖点都返回结构（close 供止损/止盈判定）；
            # 无 S 系信号时 signal_type=None，由调用方按「持有」处理。
            result = {
                "code": code,
                "name": r.get("name") or code,
                "close": r.get("close"),
                "pct_chg": r.get("pct_chg"),
                "ma5": r.get("ma5"),
                "ma20": r.get("ma20"),
                "signal_type": None,
                "signal_label": "",
                "sell_pct": 0.0,
                "trigger_price": None,
                "reasons": [],
                "checked_at": now_tz().strftime("%Y-%m-%d %H:%M:%S"),
            }
            sells = [s for s in (r.get("signals") or []) if s.get("type") in _SELL_SIGNAL_TYPES]
            if sells:
                sells.sort(key=lambda s: _SELL_PRIORITY.get(s.get("type"), 0), reverse=True)
                top = sells[0]
                result.update({
                    "signal_type": top.get("type"),
                    "signal_label": top.get("type_label") or top.get("type"),
                    "sell_pct": float(top.get("sell_pct") or 0),
                    "trigger_price": top.get("trigger_price"),
                    "reasons": top.get("reasons") or [],
                })
    except Exception as e:
        logger.warning(f"卖出信号评估失败 {code}: {e}")
    with _eval_lock:
        _eval_cache[key] = (time.monotonic(), result)
    return result


async def evaluate_sell_signal(code: str) -> dict | None:
    """公开入口：三买三卖卖点评估（供驾驶舱 05 与持仓追踪共用同一份信号）。"""
    return await _eval_sell_signal(code)


async def _load_open_positions(user_id: str) -> list[dict]:
    """读取用户全部未平仓持仓（字段精简，供卖出评估使用）。"""
    try:
        db = get_mongo_db()
        docs = await db["paper_positions"].find(
            {"user_id": user_id, "quantity": {"$gt": 0}}
        ).to_list(None)
    except Exception as e:
        logger.warning(f"持仓读取失败（卖出评估降级为空）: {e}")
        return []
    out: list[dict] = []
    for d in docs:
        try:
            qty = int(d.get("quantity") or 0)
            cost = float(d.get("avg_cost") or 0)
        except (TypeError, ValueError):
            continue
        if qty <= 0 or cost <= 0:
            continue
        code = str(d.get("code") or "").strip()
        out.append({
            "code": (code.zfill(6) if len(code) >= 6 else code.zfill(5)) if code.isdigit() else code,
            "name": d.get("stock_name") or code,
            "quantity": qty,
            "avg_cost": round(cost, 3),
            "stop_loss_price": d.get("stop_loss_price"),
            "take_profit_price": d.get("take_profit_price"),
            "trigger_price": d.get("trigger_price"),
            "buy_date": d.get("buy_date"),
            "user_id": d.get("user_id"),
        })
    return out


def _is_intraday_now() -> bool:
    """当前是否处于连续竞价时段（用于 MA5 盘中预警 / 收盘确认区分）。"""
    now = now_tz()
    try:
        from app.utils.trading_time import is_trading_day

        if not is_trading_day(now.strftime("%Y%m%d")):
            return False
    except Exception:
        return False
    minutes = now.hour * 60 + now.minute
    return (9 * 60 + 30) <= minutes <= (15 * 60)


def _advice_for(position: dict, price: float | None, sig: dict | None) -> dict:
    """把 实时价 + 卖点信号 + 止损止盈 合成一条持仓卖出建议。

    判定统一走 exit_rule_engine.evaluate_unified_exit（与驾驶舱 05 同一口径）：
    兜底止损 8% > 假突破 > 三买三卖卖点（S3/SafetyNet/S2/S1/TrailingStop）
    > 跌破 MA5 > 止盈 15% > MA20 均线止盈 > 时间止损。
    """
    code = position["code"]
    name = position.get("name") or code
    cost = position.get("avg_cost")
    stop = position.get("stop_loss_price")
    take = position.get("take_profit_price")
    base = {
        "code": code,
        "name": name,
        "quantity": position.get("quantity", 0),
        "avg_cost": cost,
        "last_price": price,
        "profit_loss_rate": round((float(price) / float(cost) - 1) * 100, 2)
            if price and cost else None,
        "stop_loss_price": stop if stop else None,
        "take_profit_price": take if take else None,
        "reasons": [],  # 依据编号列表：每条 {kind, text}，前端按编号展开
    }
    if price is None:
        base["sells_cached"] = not bool(sig)  # 无实时价：信号态兜底
        base["reasons"] = [{"kind": "warn", "text": "实时价暂不可用，由信号快照兜底（可点「对照实时价评估」刷新）"}]
        return {**base, "advice": "持有", "advice_label": "等待实时价",
                "sell_pct": 0.0, "trigger_price": None,
                "reason": "实时价暂不可用，由信号快照兜底（可点「对照实时价评估」刷新）"}

    signal_type = (sig or {}).get("signal_type")
    decision = evaluate_unified_exit(
        PositionExitContext(
            symbol=code,
            buy_price=float(cost or 0),
            current_price=price,
            buy_date=position.get("buy_date"),
            trigger_price=position.get("trigger_price"),
            stop_loss_price=float(stop) if stop else None,
            take_profit_price=float(take) if take else None,
            ma5=(sig or {}).get("ma5"),
            ma20=(sig or {}).get("ma20"),
            is_intraday=_is_intraday_now(),
            signal=(
                {
                    "signal_type": signal_type,
                    "sell_pct": (sig or {}).get("sell_pct"),
                    "reasons": (sig or {}).get("reasons"),
                }
                if signal_type
                else None
            ),
        )
    )

    reason_items = [
        {"kind": "warn" if r.get("kind") == "exit" else r.get("kind", "flat"), "text": r.get("text", "")}
        for r in decision.reasons
    ]
    reason_text = "；".join(r["text"] for r in reason_items) or "继续持有观察"

    if not decision.should_exit:
        # 仅有预警（时间止损 / 盘中跌破 MA5）：保持「持有」，但把预警展示出来
        return {**base, "advice": "持有", "advice_label": "继续持有",
                "sell_pct": 0.0, "trigger_price": decision.trailing_line,
                "reasons": reason_items or [{"kind": "flat", "text": "未触发卖出信号，继续持有观察"}],
                "reason": reason_text}

    reason = decision.reason
    ratio = float(decision.suggested_sell_ratio or 0.0)
    if reason.value == "stop_loss":
        advice, label, trigger = "触发止损", "无条件离场", decision.stop_loss_line
    elif reason.value == "false_breakout":
        advice, label, trigger = "假突破离场", "离场", position.get("trigger_price")
    elif reason.value == "signal":
        st = decision.signal_type or signal_type
        advice = {
            "S3": "S3 清仓卖出",
            "SafetyNet": "SafetyNet 安全网",
            "S2": "S2 主减仓",
            "S1": "S1 减仓预警",
            "TrailingStop": "TrailingStop 移动止损",
        }.get(st, "触发卖出信号")
        label = {
            "S3": "清仓",
            "SafetyNet": "强制减至50%",
            "S2": "主减仓",
            "S1": "减仓1/3",
            "TrailingStop": "离场",
        }.get(st, "离场")
        trigger = (sig or {}).get("trigger_price") or price
    elif reason.value == "ma_break":
        advice, label, trigger = "跌破 MA5", "离场", decision.trailing_line
    elif reason.value == "take_profit":
        advice, label = "触及止盈", "分批止盈" if ratio < 1 else "止盈离场"
        trigger = take or decision.trailing_line or price
    else:
        advice, label, trigger = "触发卖出信号", "离场", price

    return {**base, "advice": advice, "advice_label": label,
            "sell_pct": ratio, "trigger_price": trigger,
            "reasons": reason_items, "reason": reason_text}


def _sell_condition_text(advice: dict) -> str:
    """把一条卖出建议转成当日计划 sell_condition 文本。"""
    label = advice.get("advice")
    tp = advice.get("trigger_price")
    pct = advice.get("sell_pct")
    parts = [f"{label}{(' · 触发价 ' + str(tp)) if tp is not None else ''}"]
    if pct:
        ratio = int(round(float(pct) * 100))
        parts.append(f"建议卖出持仓 {ratio}%")
    reason = (advice.get("reason") or "").strip()
    if reason:
        parts.append(reason)
    return "；".join(parts)[:200]


async def build_premarket_sell_candidates(user_id: str) -> list[dict]:
    """盘前卖出观测：持仓逐只评估（止损/止盈 + 三买三卖卖点）→ 需卖/需减仓清单。

    仅返回有明确卖出动作（清仓/减仓/止损/止盈）的持仓；
    「继续持有」的持仓不列入候选（减少噪声，避免人工误操作）。

    参考价口径：优先取行情服务最新价（盘前多为最近收盘/昨收），失败回退三买三卖
    日K 快照收盘价，避免盘前把 T-1 收盘价当作"现价"误导用户。
    """
    positions = await _load_open_positions(user_id)
    scope = positions[: _SELL_LIMIT]
    # 一次取齐参考价（失败降级，不影响整体）
    quotes: dict[str, dict] = {}
    codes = [p["code"] for p in scope if p.get("code")]
    if codes:
        try:
            from app.services.quotes_service import get_quotes_service
            quotes = await get_quotes_service().get_quotes(codes)
        except Exception as e:
            logger.warning(f"盘前卖出观测参考价获取失败（回退信号快照价）: {e}")
    items: list[dict] = []
    for pos in scope:
        sig = await _eval_sell_signal(pos["code"])
        # 名称兜底：持仓未存 stock_name 时用信号评估返回的名称
        if not pos.get("name") or pos.get("name") == pos["code"]:
            pos = {**pos, "name": (sig or {}).get("name") or pos["name"]}
        ref_price = ((quotes.get(pos["code"]) or {}).get("close")
                     or (sig.get("close") if sig else None))
        advice = _advice_for(pos, ref_price, sig)
        if advice.get("advice") == "持有":
            continue
        if advice.get("advice_label") == "等待实时价":
            continue  # 盘前无信号快照也无实时价 → 无法给出卖出结论，跳过
        items.append({
            "code": advice["code"],
            "name": advice["name"],
            "direction": "sell",
            "trigger_price": advice.get("trigger_price"),
            "last_price": advice.get("last_price"),
            "profit_loss_rate": advice.get("profit_loss_rate"),
            "stop_loss_price": advice.get("stop_loss_price"),
            "take_profit_price": advice.get("take_profit_price"),
            "sell_pct": advice.get("sell_pct"),
            "sell_condition": _sell_condition_text(advice),
            "signal_label": f"{advice.get('advice_label')} · {advice.get('advice')}",
            "reason": advice.get("reason"),
            "holding": True,
            "source": {"type": "position_eval", "ref": advice["code"], "label": "持仓卖出评估"},
        })
    return items


async def build_intraday_guide(user_id: str) -> dict:
    """盘中买卖实时指导：
      buys:  当日 pending 买入计划 + 当日未确认的买入候选（实时价 → 触发/偏离/建议）
      sells: 持仓逐只评估（卖点信号 + 止损止盈 + 实时价 → 持有/减仓/清仓/止损/止盈）
    """
    from app.services import plan_service
    from app.services.plan_generation_service import load_daily_plan_snapshot, _today_planned_codes
    from app.services.quotes_service import get_quotes_service

    today = now_tz().strftime("%Y-%m-%d")

    # ── 数据源：买入（计划 + 候选，按 code 去重，计划优先） ──
    buys_src: dict[str, dict] = {}
    try:
        plans = await plan_service.list_plans(user_id, plan_date=today, status="pending")
        for p in plans:
            if p.get("direction") == "buy" and p.get("code"):
                # 已确认计划不再出现在「今日买入」清单（与「决定卖出」对称：入计划即从清单消失，
                # 触发盯盘由今日计划管理区承担）；未确认计划保留（仍需人工到今日计划确认）。
                if p.get("confirmed"):
                    continue
                buys_src[p["code"]] = {"type": "plan", "plan_id": p.get("id"), "item": p}
        # 今日已写入当日计划的代码（无论状态：待确认/已确认/已执行）：
        # 已在计划中覆盖的标的不再从快照候选重复加入，避免「已执行」的股票仍在盘中显示可执行。
        # 同样跳过用户在盘前页「否」掉的候选（plan_overrides 持久化否决）。
        planned_today = await _today_planned_codes(user_id)
        try:
            from app.services.plan_generation_service import load_plan_overrides
            _ovr = await load_plan_overrides(user_id)
            _dismissed = _ovr.get("dismissed") or {}
        except Exception:
            _dismissed = {}
        snap = await load_daily_plan_snapshot(today)
        for c in (snap or {}).get("candidates") or []:
            if c.get("direction") != "buy" or not c.get("code"):
                continue
            code = str(c["code"]).strip()
            if code in planned_today:
                continue
            if _dismissed.get(code) == "candidate":
                continue  # 盘前已否决：盘中不再提醒
            buys_src.setdefault(code, {"type": "candidate", "plan_id": None, "item": c})
    except Exception as e:
        logger.warning(f"盘中买入数据源读取失败（降级）: {e}")

    # ── 数据源：卖出（当前持仓；当日已有卖出计划的持仓不再重复建议） ──
    positions = await _load_open_positions(user_id)
    sell_planned: set[str] = set()
    try:
        _sp = await plan_service.list_plans(user_id, plan_date=today, status="pending")
        sell_planned = {str(p.get("code")) for p in _sp if p.get("direction") == "sell" and p.get("code")}
    except Exception as e:
        logger.warning(f"当日卖出计划读取失败（卖出建议不过滤）: {e}")
    sell_src = {pos["code"]: pos for pos in positions if str(pos["code"]) not in sell_planned}

    # ── 实时行情（买入 code ∪ 持仓 code 一次取齐） ──
    all_codes = list(dict.fromkeys([*buys_src.keys(), *sell_src.keys()]))
    quotes: dict[str, dict] = {}
    if all_codes:
        try:
            quotes = await get_quotes_service().get_quotes(all_codes)
        except Exception as e:
            logger.warning(f"盘中指导实时行情获取失败（走信号快照价）: {e}")

    # ── 买入理由 · 宏观新闻环境（新闻打分：利好/利空方向 + 最强影响度） ──
    # 一次性取宏观快讯打分聚合，避免逐卡重复调用（get_macro_news 有 5min/1h 缓存）
    news_env: dict = {"bull": 0, "bear": 0}
    try:
        from app.services.macro.news_classifier import get_macro_news
        for _n in await get_macro_news(hours_back=24, top_n=40):
            sc = float(_n.get("impact_score") or 0)
            if sc > 0:
                news_env["bull"] = max(news_env["bull"], abs(sc))
            elif sc < 0:
                news_env["bear"] = max(news_env["bear"], abs(sc))
    except Exception as e:
        logger.warning(f"买入理由·新闻环境获取失败（跳过）: {e}")

    buys: list[dict] = []
    for code, src in buys_src.items():
        item = src.get("item") or {}
        tp = item.get("trigger_price")
        try:
            tp_f = float(tp) if tp else None
        except (TypeError, ValueError):
            tp_f = None
        price = (quotes.get(code) or {}).get("close")
        dist = round((float(price) / tp_f - 1) * 100, 2) if price is not None and tp_f else None
        # 三态确认闸门：仅 confirmed=True（已确认）的计划进入"可执行/触达"判定；
        # 候选（无 plan_id）默认可按已确认处理（用户在候选卡已人工拍板）。
        confirmed = bool(item.get("confirmed", True)) if src.get("type") == "plan" else True
        triggered = bool(confirmed and tp_f is not None and price is not None and float(price) <= tp_f)
        if not confirmed:
            advice = "待确认：请先在当日计划中确认该计划，确认后进入盘中提醒"
        elif triggered:
            advice = f"已回落至 {tp_f} 下方，时间点成立，可执行买入"
        elif dist is not None and dist <= 2:
            advice = f"接近触发价（距触发价 {dist}%），可提前挂单等待成交"
        elif dist is not None:
            advice = f"等待回落至 {tp_f}（当前价 {price} 偏离 {dist}%）"
        else:
            advice = "等待实时价确认触发"
        # 买入理由 = 信号依据（signal_label + 信效/样本）+ 宏观新闻环境打分
        reason_parts: list[str] = []
        buy_reasons: list[dict] = []  # 依据编号列表：每条 {kind, text}
        if item.get("signal_label"):
            reason_parts.append(f"信号 {item['signal_label']}")
            buy_reasons.append({"kind": "good", "text": f"信号 {item['signal_label']}"})
        if item.get("hit_rate") is not None:
            reason_parts.append(f"信效 {item['hit_rate']}%（样本 {item.get('signal_count') or '—'}）")
            buy_reasons.append({"kind": "good",
                                "text": f"历史信效 {item['hit_rate']}%（样本 {item.get('signal_count') or '—'}）"})
        if news_env["bull"] or news_env["bear"]:
            if news_env["bull"] >= news_env["bear"]:
                reason_parts.append(f"新闻环境偏利好（最强 +{news_env['bull']}）")
                buy_reasons.append({"kind": "good",
                                    "text": f"宏观新闻环境偏利好（最强影响 +{news_env['bull']}）"})
            else:
                reason_parts.append(f"新闻环境偏利空（最强 -{news_env['bear']}）")
                buy_reasons.append({"kind": "warn",
                                    "text": f"宏观新闻环境偏利空（最强影响 -{news_env['bear']}），买入需谨慎"})
        buy_reasons.append({"kind": "flat", "text": advice})
        buy_reason = "；".join(reason_parts) or f"{item.get('name') or code} 触发买入信号"
        buys.append({
            "code": code,
            "name": item.get("name") or code,
            "direction": "buy",
            "trigger_price": tp_f,
            "last_price": price,
            "distance_pct": dist,
            "triggered": triggered,
            "confirmed": confirmed,
            "signal_label": item.get("signal_label"),
            "source": item.get("source"),
            "plan_id": src.get("plan_id"),
            "advice": advice,
            "buy_reason": buy_reason,
            "reasons": buy_reasons,
        })

    sells: list[dict] = []
    for pos in sell_src.values():
        code = pos["code"]
        sig = await _eval_sell_signal(code)
        price = (quotes.get(code) or {}).get("close")  # 实时价优先
        # 名称兜底：持仓未存 stock_name（如 null）时，用信号评估/实时行情返回的名称补全
        if not pos.get("name") or pos.get("name") == code:
            pos = {**pos, "name": (sig or {}).get("name")
                   or (quotes.get(code) or {}).get("name") or pos["name"]}
        advice = _advice_for(pos, price, sig)
        sells.append({
            **advice,
            "advice_text": _sell_condition_text(advice),
            "holding": True,
        })

    return {
        "as_of": now_tz().strftime("%Y-%m-%d %H:%M:%S"),
        "buys": buys,
        "sells": sells[: _SELL_LIMIT],
        "buy_count": len(buys),
        "sell_count": len(sells),
    }