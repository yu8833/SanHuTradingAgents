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
    code = str(code).strip().zfill(6) if str(code).strip().isdigit() else str(code).strip()
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
            "code": code.zfill(6) if code.isdigit() else code,
            "name": d.get("stock_name") or code,
            "quantity": qty,
            "avg_cost": round(cost, 3),
            "stop_loss_price": d.get("stop_loss_price"),
            "take_profit_price": d.get("take_profit_price"),
            "user_id": d.get("user_id"),
        })
    return out


def _advice_for(position: dict, price: float | None, sig: dict | None) -> dict:
    """把 实时价 + 卖点信号 + 止损止盈 合成一条持仓卖出建议。

    判定优先级：触发止损 > S3清仓 > 安全网 > S2主减仓 > 触及止盈 > S1减仓 > 持有。
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
    }
    if price is None:
        base["sells_cached"] = not bool(sig)  # 无实时价：信号态兜底
        return {**base, "advice": "持有", "advice_label": "等待实时价",
                "sell_pct": 0.0, "trigger_price": None,
                "reason": "实时价暂不可用，由信号快照兜底（可点「对照实时价评估」刷新）"}

    def _hit() -> dict:
        return {**base, "advice": "触发止损", "advice_label": "无条件离场",
                "sell_pct": 1.0, "trigger_price": float(stop),
                "reason": f"现价 {price} 已跌破止损位 {stop}，无条件止损离场"}

    if stop and float(stop) > 0 and price <= float(stop):
        return _hit()
    if sig:
        st = sig.get("signal_type")
        tp = sig.get("trigger_price") or price
        reasons = "；".join(sig.get("reasons") or []) or "触发卖出信号"
        if st == "S3":
            return {**base, "advice": "S3 清仓卖出", "advice_label": "清仓",
                    "sell_pct": float(sig.get("sell_pct") or 1.0), "trigger_price": tp,
                    "reason": reasons or "中期/大级别趋势破坏，无条件清仓"}
        if st == "SafetyNet":
            return {**base, "advice": "SafetyNet 安全网", "advice_label": "强制减至50%",
                    "sell_pct": float(sig.get("sell_pct") or 0.5), "trigger_price": tp,
                    "reason": reasons or "单日跌幅超 ATR×3，强制减仓一半"}
        if st == "S2":
            return {**base, "advice": "S2 主减仓", "advice_label": "主减仓",
                    "sell_pct": float(sig.get("sell_pct") or 0.67), "trigger_price": tp,
                    "reason": reasons or "连续跌破 MA5/MA8/MA13，主减仓（减至1/3）"}
        if st == "TrailingStop":
            return {**base, "advice": "TrailingStop 移动止损", "advice_label": "离场",
                    "sell_pct": float(sig.get("sell_pct") or 1.0), "trigger_price": tp,
                    "reason": reasons or "触发移动止损，保护利润离场"}
        if st == "S1":
            return {**base, "advice": "S1 减仓预警", "advice_label": "减仓1/3",
                    "sell_pct": float(sig.get("sell_pct") or 0.33), "trigger_price": tp,
                    "reason": reasons or "BIAS 超阈值或慢组压缩，减仓1/3锁盈"}
    if take and float(take) > 0 and price >= float(take):
        return {**base, "advice": "触及止盈", "advice_label": "分批止盈",
                "sell_pct": 0.5, "trigger_price": float(take),
                "reason": f"现价 {price} 已达止盈位 {take}，分批止盈一半"}
    return {**base, "advice": "持有", "advice_label": "继续持有",
            "sell_pct": 0.0, "trigger_price": None,
            "reason": "未触发卖出信号、未触及止损/止盈，继续持有观察"}


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

    # ── 数据源：卖出（当前持仓） ──
    positions = await _load_open_positions(user_id)
    sell_src = {pos["code"]: pos for pos in positions}

    # ── 实时行情（买入 code ∪ 持仓 code 一次取齐） ──
    all_codes = list(dict.fromkeys([*buys_src.keys(), *sell_src.keys()]))
    quotes: dict[str, dict] = {}
    if all_codes:
        try:
            quotes = await get_quotes_service().get_quotes(all_codes)
        except Exception as e:
            logger.warning(f"盘中指导实时行情获取失败（走信号快照价）: {e}")

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