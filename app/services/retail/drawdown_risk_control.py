"""
账户级回撤风险控制（教材第五章 5.2 账户级止损 + 5.3 维护持仓全红）

规则（教材 P13「账户级止损」）：
- 周回撤 > 3%        → 降低总仓位至 50%
- 月回撤 > 5%        → 降低总仓位至 30%
- 月回撤 > 8%        → 全部清仓，暂停交易 1 周
- 连续止损 3 次      → 暂停该标的交易，重新评估

实现：
- paper_equity_history : 每日账户净值快照（现金 + 持仓市值，按 user_id+date 去重）
- compute_drawdown      : 由近 7 天 / 近 30 天净值峰值计算周回撤 / 月回撤
- get_risk_control      : 由回撤水平确定风控等级与总仓位上限
- record_exit           : 卖出时记录盈亏，累计连续止损并暂停标的
- enforce_buy           : 买入时按风控上限约束股数、暂停时拒绝

接入点：paper_executor.execute_market_order（唯一成交入口），
买入前校验、卖出后记账，保证纸面交易与「三买三卖·监控中心」共用同一套风控。
"""

from __future__ import annotations
from app.utils.timezone import now_tz

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)

# ── 风控阈值（回撤百分比）──────────────────────────────
WEEKLY_DD_REDUCE_50 = 3.0
MONTHLY_DD_REDUCE_30 = 5.0
MONTHLY_DD_CLEAR_PAUSE = 8.0
CONSECUTIVE_STOP_LOSS_LIMIT = 3
PAUSE_DAYS_ON_ACCOUNT_CLEAR = 7
PAUSE_DAYS_ON_SYMBOL_LOSSES = 7

# 风控等级定义（等级越高，总仓位上限越低）
RISK_LEVELS: list[dict[str, Any]] = [
    {"level": 0, "max_position_pct": 1.0, "label": "正常", "action": "无限制"},
    {"level": 1, "max_position_pct": 0.50, "label": "周回撤>3%", "action": "降低总仓位至50%"},
    {"level": 2, "max_position_pct": 0.30, "label": "月回撤>5%", "action": "降低总仓位至30%"},
    {"level": 3, "max_position_pct": 0.0, "label": "月回撤>8%", "action": "全部清仓，暂停交易1周"},
]

# 集合同名
EQUITY_HISTORY_COLL = "paper_equity_history"
SYMBOL_RISK_COLL = "paper_symbol_risk"


def _today_str() -> str:
    return now_tz().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return now_tz().isoformat()


async def _compute_equity_cny(db, user_id: str) -> float:
    """计算账户当前净资产（现金 + 持仓市值，统一折算为 CNY 口径）。"""
    from app.services.paper_executor import get_last_price

    acc = await db["paper_accounts"].find_one({"user_id": user_id})
    cash = acc.get("cash", {}) if acc else {}
    if not isinstance(cash, dict):
        cash = {"CNY": float(cash or 0.0), "HKD": 0.0, "USD": 0.0}
    total_cash = float(cash.get("CNY", 0.0))

    positions = await db["paper_positions"].find({
        "user_id": user_id, "quantity": {"$gt": 0}
    }).to_list(None)

    market_value = 0.0
    for p in positions:
        code = p.get("code")
        market = p.get("market", "CN")
        qty = int(p.get("quantity", 0))
        last = await get_last_price(code, market)
        market_value += (last or 0.0) * qty

    return round(total_cash + market_value, 2)


async def snapshot_equity(user_id: str) -> float:
    """对账户做一次净值快照（按 user_id+date 去重，每日最多一条）。"""
    db = get_mongo_db()
    equity = await _compute_equity_cny(db, user_id)
    key = {"user_id": user_id, "date": _today_str()}
    existing = await db[EQUITY_HISTORY_COLL].find_one(key)
    if existing:
        await db[EQUITY_HISTORY_COLL].update_one(
            {"_id": existing["_id"]},
            {"$set": {"equity": equity, "updated_at": _now_iso()}},
        )
    else:
        await db[EQUITY_HISTORY_COLL].insert_one({
            **key, "equity": equity, "created_at": _now_iso(),
            "updated_at": _now_iso(),
        })
    return equity


async def compute_drawdown(user_id: str) -> dict[str, Any]:
    """计算当前账户周/月回撤（基于净值快照峰值）。

    Returns:
        {current_equity, weekly_peak, monthly_peak, weekly_dd_pct,
         monthly_dd_pct, level, max_position_pct, level_label, level_action}
    """
    db = get_mongo_db()
    now = now_tz()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    docs = await db[EQUITY_HISTORY_COLL].find(
        {"user_id": user_id, "date": {"$gte": month_start}}
    ).sort("date", 1).to_list(None)

    if not docs:
        # 无历史快照：以当前净值为基准，回撤为 0
        current = await snapshot_equity(user_id)
        return {
            "current_equity": current,
            "weekly_peak": current,
            "monthly_peak": current,
            "weekly_dd_pct": 0.0,
            "monthly_dd_pct": 0.0,
            "level": 0,
            "max_position_pct": 1.0,
            "level_label": RISK_LEVELS[0]["label"],
            "level_action": RISK_LEVELS[0]["action"],
        }

    current = float(docs[-1]["equity"])
    weekly_peak = max(float(d["equity"]) for d in docs if d["date"] >= week_start)
    monthly_peak = max(float(d["equity"]) for d in docs)

    def _dd(cur: float, peak: float) -> float:
        if peak <= 0:
            return 0.0
        return round((1 - cur / peak) * 100.0, 2)

    weekly_dd = _dd(current, weekly_peak)
    monthly_dd = _dd(current, monthly_peak)

    level = _risk_level(weekly_dd, monthly_dd)
    lv = RISK_LEVELS[level]
    return {
        "current_equity": current,
        "weekly_peak": weekly_peak,
        "monthly_peak": monthly_peak,
        "weekly_dd_pct": weekly_dd,
        "monthly_dd_pct": monthly_dd,
        "level": level,
        "max_position_pct": lv["max_position_pct"],
        "level_label": lv["label"],
        "level_action": lv["action"],
    }


def _risk_level(weekly_dd: float, monthly_dd: float) -> int:
    """由回撤确定风控等级（教材 P13 账户级止损）。"""
    if monthly_dd > MONTHLY_DD_CLEAR_PAUSE:
        return 3
    if monthly_dd > MONTHLY_DD_REDUCE_30:
        return 2
    if weekly_dd > WEEKLY_DD_REDUCE_50:
        return 1
    return 0


async def _is_account_paused(db, user_id: str) -> tuple[bool, str]:
    """账户级暂停（月回撤>8% 清仓暂停 1 周）。"""
    doc = await db[SYMBOL_RISK_COLL].find_one({
        "user_id": user_id, "scope": "account", "paused_until": {"$gt": _now_iso()},
    })
    if doc:
        return True, f"账户暂停交易至 {doc['paused_until']}（月回撤>8% 清仓暂停1周）"
    return False, ""


async def _is_symbol_paused(db, user_id: str, symbol: str) -> tuple[bool, str]:
    """标的级暂停（连续止损≥3 次）。"""
    doc = await db[SYMBOL_RISK_COLL].find_one({
        "user_id": user_id, "scope": "symbol", "symbol": symbol,
        "paused_until": {"$gt": _now_iso()},
    })
    if doc:
        return True, f"{symbol} 已暂停交易至 {doc['paused_until']}（连续止损≥{CONSECUTIVE_STOP_LOSS_LIMIT}次，重新评估）"
    return False, ""


async def compute_holding_health(user_id: str) -> dict[str, Any]:
    """持仓全红率与加减仓优先级（教材 5.3 维护持仓全红）。

    核心原则：
    - 大盘将上涨时：加仓优先选择已经盈利的标的（让赢家继续赢）
    - 大盘将下跌时：优先减仓已经亏损或微利的标的（先砍不赚钱的）

    返回：
        {total, red, green, all_red_rate, holdings: [{code, name, pnl, pnl_pct, status}]}
    """
    db = get_mongo_db()
    holdings_doc = await db["paper_positions"].find({
        "user_id": user_id, "quantity": {"$gt": 0}
    }).to_list(None)

    from app.services.paper_executor import get_last_price

    holdings: list[dict[str, Any]] = []
    red = 0
    for p in holdings_doc:
        code = p.get("code")
        market = p.get("market", "CN")
        qty = int(p.get("quantity", 0))
        avg_cost = float(p.get("avg_cost", 0.0))
        last = await get_last_price(code, market)
        pnl = round((last - avg_cost) * qty, 2) if last is not None else None
        pnl_pct = round((last - avg_cost) / avg_cost * 100.0, 2) if (last and avg_cost > 0) else None
        status = "red" if (pnl is not None and pnl > 0) else ("green" if pnl is not None else "unknown")
        if status == "red":
            red += 1
        holdings.append({
            "code": code,
            "name": p.get("stock_name", ""),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "status": status,
            "market_value": round((last or 0.0) * qty, 2),
        })

    total = len(holdings)
    all_red_rate = round(red / total * 100.0, 2) if total > 0 else 0.0
    return {
        "total": total,
        "red": red,
        "green": total - red,
        "all_red_rate": all_red_rate,
        "holdings": holdings,
    }


async def get_risk_control(user_id: str) -> dict[str, Any]:
    """获取账户当前风控状态（供 API / 前端展示）。"""
    db = get_mongo_db()
    dd = await compute_drawdown(user_id)
    acc_paused, acc_msg = await _is_account_paused(db, user_id)
    result = {
        **dd,
        "account_paused": acc_paused,
        "account_paused_reason": acc_msg,
        "levels": RISK_LEVELS,
        "consecutive_stop_loss_limit": CONSECUTIVE_STOP_LOSS_LIMIT,
    }
    if acc_paused:
        result["level"] = 3
        result["max_position_pct"] = 0.0
    # C3 持仓全红维护
    result["holding_health"] = await compute_holding_health(user_id)
    return result


async def enforce_buy(
    user_id: str, symbol: str, requested_qty: int, price: float
) -> dict[str, Any]:
    """买入前置校验：按账户回撤风控等级约束股数，暂停时拒绝。

    返回 {allowed, qty, reason, level, max_position_pct}。
    """
    db = get_mongo_db()
    dd = await compute_drawdown(user_id)

    # 账户级暂停
    acc_paused, acc_msg = await _is_account_paused(db, user_id)
    if acc_paused:
        return {"allowed": False, "qty": 0, "reason": acc_msg,
                "level": 3, "max_position_pct": 0.0}

    # 标的级暂停
    sym_paused, sym_msg = await _is_symbol_paused(db, user_id, symbol)
    if sym_paused:
        return {"allowed": False, "qty": 0, "reason": sym_msg,
                "level": dd["level"], "max_position_pct": dd["max_position_pct"]}

    max_pct = dd["max_position_pct"]
    level = dd["level"]

    if level == 0:
        return {"allowed": True, "qty": requested_qty, "reason": "",
                "level": 0, "max_position_pct": 1.0}

    # 按风控上限折算可买金额，再折算股数（A股 100 股一手）
    equity = dd["current_equity"]
    max_amount = equity * max_pct
    capped_qty = int(max_amount / price / 100) * 100 if price > 0 else 0
    qty = min(requested_qty, capped_qty)
    reason = (
        f"账户回撤风控：{dd['level_label']}，总仓位上限 {max_pct:.0%}，"
        f"买入股数由 {requested_qty} 降至 {qty}"
    )
    return {"allowed": qty > 0, "qty": qty, "reason": reason,
            "level": level, "max_position_pct": max_pct}


async def record_exit(user_id: str, symbol: str, pnl: float, exit_reason: str = "sell_order") -> dict[str, Any]:
    """卖出后记账：累计连续止损，达到阈值后暂停标的。

    - 亏损卖出（pnl < 0）→ 连续止损次数 +1
    - 盈利卖出（pnl >= 0）→ 连续止损次数清零
    - 连续止损 >= CONSECUTIVE_STOP_LOSS_LIMIT → 暂停该标的 PAUSE_DAYS_ON_SYMBOL_LOSSES 天
    """
    db = get_mongo_db()
    doc = await db[SYMBOL_RISK_COLL].find_one({
        "user_id": user_id, "scope": "symbol", "symbol": symbol,
    })
    base = {"user_id": user_id, "scope": "symbol", "symbol": symbol}
    if pnl < 0:
        consecutive = int((doc or {}).get("consecutive_stop_losses", 0)) + 1
        paused_until = ""
        if consecutive >= CONSECUTIVE_STOP_LOSS_LIMIT:
            paused_until = (now_tz() + timedelta(days=PAUSE_DAYS_ON_SYMBOL_LOSSES)).isoformat()
            logger.warning(
                f"❌ {symbol} 连续止损 {consecutive} 次，暂停交易至 {paused_until}"
            )
        update = {
            "consecutive_stop_losses": consecutive,
            "last_exit_pnl": pnl,
            "last_exit_reason": exit_reason,
            "updated_at": _now_iso(),
        }
        if paused_until:
            update["paused_until"] = paused_until
        if doc:
            await db[SYMBOL_RISK_COLL].update_one({"_id": doc["_id"]}, {"$set": update})
        else:
            await db[SYMBOL_RISK_COLL].insert_one({**base, **update, "created_at": _now_iso()})
        return {"consecutive_stop_losses": consecutive, "paused": bool(paused_until),
                "paused_until": paused_until}
    else:
        # 盈利了结，清空连续止损
        update = {
            "consecutive_stop_losses": 0,
            "last_exit_pnl": pnl,
            "last_exit_reason": exit_reason,
            "paused_until": "",
            "updated_at": _now_iso(),
        }
        if doc:
            await db[SYMBOL_RISK_COLL].update_one({"_id": doc["_id"]}, {"$set": update})
        else:
            await db[SYMBOL_RISK_COLL].insert_one({**base, **update, "created_at": _now_iso()})
        return {"consecutive_stop_losses": 0, "paused": False, "paused_until": ""}