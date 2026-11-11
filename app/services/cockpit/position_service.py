"""纪律持仓服务（交易驾驶舱 · 区块 05）

手动标记买入的持仓，离场判定统一交给 exit_rule_engine.evaluate_unified_exit
（与模拟交易持仓追踪同一份口径）：
- 假突破：现价跌回触发价 98% 以下 → 离场
- 止损：触及交易计划止损价；无计划价时用成本 -8% → 离场
- 跌破 MA5：盘中预警，收盘确认 → 离场（移动止盈线）
- 止盈：浮盈 +15% 卖一半；价格回到 MA20 附近 → 均线止盈
- 时间止损：持仓超 30 天无进展 → 提示释放资金
- 三买三卖卖点 S1/S2/S3/SafetyNet/TrailingStop 直接消费
T+1 约束：买入当日所有离场信号降级为预警标注（当日无法卖出）。
"""

import logging
from datetime import datetime, timezone

from bson import ObjectId

from app.core.collections import Collections
from app.services.retail.exit_rule_engine import (
    UNIFIED_EXIT_PARAMS,
    PositionExitContext,
    evaluate_unified_exit,
)
from app.utils.timezone import now_tz
from app.utils.trading_time import is_trading_day

logger = logging.getLogger(__name__)

# 兼容旧引用：驾驶舱离场参数统一取自 UNIFIED_EXIT_PARAMS
COCKPIT_EXIT_PARAMS = {
    "stop_loss_pct": UNIFIED_EXIT_PARAMS["stop_loss_pct"],
    "ma_period": UNIFIED_EXIT_PARAMS["ma_period"],
    "false_breakout_buffer": UNIFIED_EXIT_PARAMS["false_breakout_buffer"],
    "max_hold_days": UNIFIED_EXIT_PARAMS["max_hold_days"],
}


def _holding_days(buy_date: str, today: str) -> int:
    try:
        d0 = datetime.strptime(buy_date, "%Y-%m-%d")
        d1 = datetime.strptime(today, "%Y-%m-%d")
        return max((d1 - d0).days, 0)
    except (ValueError, TypeError):
        return 0


def evaluate_exit(
    pos: dict,
    current_price: float | None,
    ma5: float | None,
    trade_date: str,
    is_intraday: bool,
    ma20: float | None = None,
    signal: dict | None = None,
) -> dict:
    """离场纪律判定（薄封装，统一走 evaluate_unified_exit）。

    返回 {"state": normal|warn|exit, "reasons": [...], ...}，字段保持历史契约。
    """
    decision = evaluate_unified_exit(
        PositionExitContext(
            symbol=str(pos.get("code") or ""),
            buy_price=float(pos.get("buy_price") or 0),
            current_price=current_price,
            buy_date=pos.get("buy_date"),
            trade_date=trade_date,
            trigger_price=pos.get("trigger_price"),
            stop_loss_price=pos.get("stop_loss_price"),
            take_profit_price=pos.get("take_profit_price"),
            ma5=ma5,
            ma20=ma20,
            is_intraday=is_intraday,
            signal=signal,
        )
    )
    return {
        "state": decision.state,
        "reasons": [r["text"] for r in decision.reasons],
        "pnl_pct": round(decision.current_pnl_pct, 4) if current_price else None,
        "holding_days": decision.holding_days,
        "t1_locked": decision.t1_locked,
        "stop_loss_line": decision.stop_loss_line,
        "trailing_line": decision.trailing_line,
    }


async def create_position(db, user_id: str, code: str, buy_price: float, buy_date: str | None = None) -> dict:
    """标记买入：从观察池文档富集触发价/行业/名称。"""
    if not buy_price or buy_price <= 0:
        raise ValueError("买入价必须为正数")
    trade_date = buy_date or now_tz().strftime("%Y-%m-%d")

    pool_doc = await db[Collections.cockpit_watch_pool].find_one({"code": code})
    now_utc = now_tz().astimezone(timezone.utc)
    doc = {
        "user_id": str(user_id),
        "code": code,
        "name": (pool_doc or {}).get("name", ""),
        "industry": (pool_doc or {}).get("industry", ""),
        "buy_price": float(buy_price),
        "buy_date": trade_date,
        "trigger_price": (pool_doc or {}).get("trigger_price"),
        "stop_loss_price": (pool_doc or {}).get("b1_stop_loss_price"),
        "range_low": (pool_doc or {}).get("range_low"),
        "status": "open",
        "sell_price": None,
        "sell_date": None,
        "close_reason": None,
        "created_at": now_utc,
        "updated_at": now_utc,
    }
    res = await db[Collections.cockpit_positions].insert_one(doc)
    doc["id"] = str(res.inserted_id)
    doc.pop("_id", None)
    return doc


async def list_positions(db, user_id: str, include_closed: bool = False) -> dict:
    """持仓列表 + 现价富集 + 实时离场判定。"""
    from app.services.quotes_service import get_quotes_service

    query: dict = {"user_id": str(user_id)}
    if not include_closed:
        query["status"] = "open"
    items = await db[Collections.cockpit_positions].find(query).sort("created_at", -1).to_list(200)

    now = now_tz()
    trade_date = now.strftime("%Y-%m-%d")
    is_intraday = False
    if is_trading_day(now.strftime("%Y%m%d")):
        minutes = now.hour * 60 + now.minute
        is_intraday = (9 * 60 + 25) <= minutes <= (15 * 60 + 5)

    codes = [p["code"] for p in items]
    quotes: dict = {}
    pool_map: dict = {}
    if codes:
        try:
            quotes = await get_quotes_service().get_quotes(codes)
        except Exception as exc:
            logger.warning(f"持仓现价富集失败: {exc}")
        pool_docs = await db[Collections.cockpit_watch_pool].find(
            {"code": {"$in": codes}}, {"code": 1, "ma5": 1, "ma20": 1, "trigger_price": 1}
        ).to_list(None)
        pool_map = {d["code"]: d for d in pool_docs}

    out = []
    for pos in items:
        code = pos["code"]
        current = (quotes.get(code) or {}).get("close") if pos.get("status") == "open" else pos.get("sell_price")
        ma5 = (pool_map.get(code) or {}).get("ma5")
        ma20 = (pool_map.get(code) or {}).get("ma20")
        if pos.get("status") == "open":
            eval_result = evaluate_exit(pos, current, ma5, trade_date, is_intraday, ma20=ma20)
            # 合并盘中扫描落库的统一离场结论（含 S1/S2/S3 卖点，当日有效）
            if pos.get("exit_trade_date") == trade_date and pos.get("exit_state") in ("exit", "warn"):
                persisted = list(pos.get("exit_reasons") or [])
                live = eval_result["reasons"]
                if pos["exit_state"] == "exit" and eval_result["state"] != "exit":
                    eval_result["state"] = "exit"
                elif pos["exit_state"] == "warn" and eval_result["state"] == "normal":
                    eval_result["state"] = "warn"
                eval_result["reasons"] = persisted + [r for r in live if r not in persisted]
        else:
            eval_result = {"state": "closed", "reasons": [], "pnl_pct": None, "holding_days": _holding_days(pos.get("buy_date", ""), pos.get("sell_date") or trade_date), "t1_locked": False, "stop_loss_line": None, "trailing_line": None}
            if pos.get("sell_price") and pos.get("buy_price"):
                eval_result["pnl_pct"] = round(pos["sell_price"] / pos["buy_price"] - 1, 4)
        out.append(
            {
                "id": str(pos["_id"]),
                "code": code,
                "name": pos.get("name", ""),
                "industry": pos.get("industry", ""),
                "buy_price": pos.get("buy_price"),
                "buy_date": pos.get("buy_date"),
                "sell_price": pos.get("sell_price"),
                "sell_date": pos.get("sell_date"),
                "status": pos.get("status"),
                "current_price": current,
                **eval_result,
            }
        )

    # 触发离场的持仓置顶（重要性分级）
    order = {"exit": 0, "warn": 1, "normal": 2, "closed": 3}
    out.sort(key=lambda x: (order.get(x["state"], 9), -(x["pnl_pct"] or 0)))
    return {"items": out, "evaluated_at": now.replace(microsecond=0).isoformat(), "trade_date": trade_date, "is_intraday": is_intraday}


async def close_position(db, user_id: str, position_id: str, sell_price: float, sell_date: str | None = None) -> bool:
    """卖出/了结：归档持仓。"""
    if not sell_price or sell_price <= 0:
        raise ValueError("卖出价必须为正数")
    try:
        oid = ObjectId(position_id)
    except Exception:
        return False
    res = await db[Collections.cockpit_positions].update_one(
        {"_id": oid, "user_id": str(user_id), "status": "open"},
        {
            "$set": {
                "status": "closed",
                "sell_price": float(sell_price),
                "sell_date": sell_date or now_tz().strftime("%Y-%m-%d"),
                "updated_at": now_tz().astimezone(timezone.utc),
            }
        },
    )
    return res.modified_count > 0
