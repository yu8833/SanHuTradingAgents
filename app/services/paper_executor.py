"""纸面交易执行器 — 供 paper 路由与「三买三卖·监控中心」待确认指令复用。

把 paper 下单的核心逻辑（市场识别/资金/持仓/手续费/止损预警）从路由中抽出，
保持单一事实来源：`execute_market_order` 是唯一的成交入口。
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


# 每个市场的初始资金配置
INITIAL_CASH_BY_MARKET = {
    "CNY": 1_000_000.0,   # A股：100万人民币
    "HKD": 1_000_000.0,   # 港股：100万港币
    "USD": 100_000.0      # 美股：10万美元
}


def detect_market_and_code(code: str) -> tuple[str, str]:
    """检测股票代码的市场类型并标准化代码。

    Returns:
        (market, normalized_code): 市场类型和标准化后的代码
            - CN: A股（6位数字）
            - HK: 港股（4-5位数字或带.HK后缀）
            - US: 美股（字母代码）
    """
    code = code.strip().upper()

    # 港股：带 .HK 后缀
    if code.endswith('.HK'):
        return ('HK', code[:-3].zfill(5))

    # 美股：纯字母
    if re.match(r'^[A-Z]+$', code):
        return ('US', code)

    # 港股：4-5位数字
    if re.match(r'^\d{4,5}$', code):
        return ('HK', code.zfill(5))

    # A股：6位数字
    if re.match(r'^\d{6}$', code):
        return ('CN', code)

    # 默认当作A股，补齐6位
    return ('CN', code.zfill(6))


def zfill_code(code: str) -> str:
    s = str(code).strip()
    if len(s) == 6 and s.isdigit():
        return s
    return s.zfill(6)


async def get_or_create_account(user_id: str) -> dict[str, Any]:
    """获取或创建账户（多货币）"""
    db = get_mongo_db()
    acc = await db["paper_accounts"].find_one({"user_id": user_id})
    if not acc:
        now = datetime.now().isoformat()
        acc = {
            "user_id": user_id,
            "cash": {
                "CNY": INITIAL_CASH_BY_MARKET["CNY"],
                "HKD": INITIAL_CASH_BY_MARKET["HKD"],
                "USD": INITIAL_CASH_BY_MARKET["USD"]
            },
            "realized_pnl": {
                "CNY": 0.0, "HKD": 0.0, "USD": 0.0
            },
            "settings": {
                "auto_currency_conversion": False,
                "default_market": "CN"
            },
            "created_at": now,
            "updated_at": now,
        }
        await db["paper_accounts"].insert_one(acc)
    else:
        # 兼容旧账户结构：如果 cash 或 realized_pnl 仍为标量，迁移为多货币对象
        updates: dict[str, Any] = {}
        try:
            cash_val = acc.get("cash")
            if not isinstance(cash_val, dict):
                base_cash = float(cash_val or 0.0)
                updates["cash"] = {"CNY": base_cash, "HKD": 0.0, "USD": 0.0}

            pnl_val = acc.get("realized_pnl")
            if not isinstance(pnl_val, dict):
                base_pnl = float(pnl_val or 0.0)
                updates["realized_pnl"] = {"CNY": base_pnl, "HKD": 0.0, "USD": 0.0}

            if updates:
                updates["updated_at"] = datetime.now().isoformat()
                await db["paper_accounts"].update_one({"user_id": user_id}, {"$set": updates})
                # 重新读取迁移后的账户
                acc = await db["paper_accounts"].find_one({"user_id": user_id})
        except Exception as e:
            logger.error(f"❌ 账户结构迁移失败 user_id={user_id}: {e}")
    return acc


async def _get_market_rules(market: str) -> dict[str, Any] | None:
    """获取市场规则配置"""
    db = get_mongo_db()
    rules_doc = await db["paper_market_rules"].find_one({"market": market})
    if rules_doc:
        return rules_doc.get("rules", {})
    return None


def _calculate_commission(market: str, side: str, amount: float, rules: dict[str, Any]) -> float:
    """计算手续费"""
    if not rules or "commission" not in rules:
        return 0.0

    commission_config = rules["commission"]
    commission = 0.0

    # 佣金
    comm_rate = commission_config.get("rate", 0.0)
    comm_min = commission_config.get("min", 0.0)
    commission += max(amount * comm_rate, comm_min)

    # 印花税（仅卖出）
    if side == "sell" and "stamp_duty_rate" in commission_config:
        commission += amount * commission_config["stamp_duty_rate"]

    # 其他费用（港股）
    if market == "HK":
        if "transaction_levy_rate" in commission_config:
            commission += amount * commission_config["transaction_levy_rate"]
        if "trading_fee_rate" in commission_config:
            commission += amount * commission_config["trading_fee_rate"]
        if "settlement_fee_rate" in commission_config:
            commission += amount * commission_config["settlement_fee_rate"]

    # SEC费用（美股，仅卖出）
    if market == "US" and side == "sell" and "sec_fee_rate" in commission_config:
        commission += amount * commission_config["sec_fee_rate"]

    return round(commission, 2)


async def _get_available_quantity(user_id: str, code: str, market: str) -> int:
    """获取可用数量（考虑T+1限制）"""
    db = get_mongo_db()
    pos = await db["paper_positions"].find_one({"user_id": user_id, "code": code})

    if not pos:
        return 0

    total_qty = pos.get("quantity", 0)

    # A股T+1：今天买入的不能卖出
    if market == "CN":
        # 获取市场规则
        rules = await _get_market_rules(market)
        if rules and rules.get("t_plus", 0) > 0:
            # 查询今天的买入数量
            today = datetime.now().date().isoformat()
            pipeline = [
                {"$match": {
                    "user_id": user_id,
                    "code": code,
                    "side": "buy",
                    "timestamp": {"$gte": today}
                }},
                {"$group": {"_id": None, "total": {"$sum": "$quantity"}}}
            ]
            today_buy = await db["paper_trades"].aggregate(pipeline).to_list(1)
            today_buy_qty = today_buy[0]["total"] if today_buy else 0
            return max(0, total_qty - today_buy_qty)

    # 港股/美股T+0：全部可用
    return total_qty


async def get_last_price(code: str, market: str) -> float | None:
    """获取股票最新价格（支持多市场）"""
    db = get_mongo_db()

    # A股：从数据库获取
    if market == "CN":
        # 1. 尝试从 market_quotes 获取
        q = await db["market_quotes"].find_one(
            {"$or": [{"code": code}, {"symbol": code}]},
            {"_id": 0, "close": 1}
        )
        if q and q.get("close") is not None:
            try:
                price = float(q["close"])
                if price > 0:
                    return price
            except Exception as e:
                logger.warning(f"⚠️ market_quotes 价格转换失败 {code}: {e}")

        # 2. 回退到 stock_basic_info 的 current_price
        basic_info = await db["stock_basic_info"].find_one(
            {"$or": [{"code": code}, {"symbol": code}]},
            {"_id": 0, "current_price": 1}
        )
        if basic_info and basic_info.get("current_price") is not None:
            try:
                price = float(basic_info["current_price"])
                if price > 0:
                    return price
            except Exception as e:
                logger.warning(f"⚠️ stock_basic_info 价格转换失败 {code}: {e}")

        logger.error(f"❌ 无法从数据库获取A股价格: {code}")
        return None

    # 港股/美股：使用 ForeignStockService
    elif market in ['HK', 'US']:
        try:
            from app.services.foreign_stock_service import ForeignStockService
            db = get_mongo_db()
            service = ForeignStockService(db=db)
            quote = await service.get_quote(market, code, force_refresh=False)
            if quote:
                price = quote.get("price") or quote.get("current_price") or quote.get("close")
                if price and float(price) > 0:
                    return float(price)
        except Exception as e:
            logger.error(f"❌ 获取{market}股价格失败 {code}: {e}")
            return None

    logger.error(f"❌ 无法获取股票价格: {code} (market={market})")
    return None


async def execute_market_order(
    user_id: str,
    code: str,
    side: str,          # "buy" | "sell"
    quantity: int,
    market: str | None = None,
    analysis_id: str | None = None,
    strategy: str | None = None,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
    thesis: str | None = None,
    stock_name: str | None = None,
) -> dict[str, Any]:
    """执行市价单，按最新价即时成交（支持多市场）。返回 order 文档。

    与 paper 路由共用同一套逻辑，供「三买三卖·监控中心」待确认指令执行复用。
    """
    db = get_mongo_db()

    # 1. 识别市场类型
    if market:
        market = market.upper()
        normalized_code = code
    else:
        market, normalized_code = detect_market_and_code(code)

    side = str(side).lower()
    qty = int(quantity)

    # 2. 确定货币
    currency_map = {"CN": "CNY", "HK": "HKD", "US": "USD"}
    currency = currency_map.get(market, "CNY")

    # 3. 获取账户
    acc = await get_or_create_account(user_id)

    # 4. 获取价格
    price = await get_last_price(normalized_code, market)
    if price is None or price <= 0:
        raise ValueError(f"无法获取股票 {normalized_code} ({market}) 的最新价格")

    # 5. 计算金额
    notional = round(price * qty, 2)

    # 6. 获取市场规则并计算手续费
    rules = await _get_market_rules(market)
    commission = _calculate_commission(market, side, notional, rules) if rules else 0.0
    total_cost = notional + commission

    # 7. 获取持仓
    pos = await db["paper_positions"].find_one({"user_id": user_id, "code": normalized_code})

    now_iso = datetime.now().isoformat()
    realized_pnl_delta = 0.0

    # 8. 执行买卖逻辑
    if side == "buy":
        cash = acc.get("cash", {})
        if isinstance(cash, dict):
            available_cash = float(cash.get(currency, 0.0))
        else:
            available_cash = float(cash) if currency == "CNY" else 0.0

        if available_cash < total_cost:
            raise ValueError(f"可用{currency}不足：需要 {total_cost:.2f}，可用 {available_cash:.2f}")

        new_cash = round(available_cash - total_cost, 2)
        await db["paper_accounts"].update_one(
            {"user_id": user_id},
            {"$set": {f"cash.{currency}": new_cash, "updated_at": now_iso}}
        )

        if not pos:
            new_pos = {
                "user_id": user_id,
                "code": normalized_code,
                "market": market,
                "currency": currency,
                "quantity": qty,
                "available_qty": qty if market != "CN" else 0,  # A股T+1，今天买入不可用
                "frozen_qty": 0,
                "avg_cost": price,
                "updated_at": now_iso,
                "strategy": strategy or "default",
                "stop_loss_price": stop_loss_price,
                "take_profit_price": take_profit_price,
                "thesis": thesis,
                "stock_name": stock_name or "",
                "buy_date": datetime.now().strftime("%Y-%m-%d"),
            }
            await db["paper_positions"].insert_one(new_pos)
        else:
            old_qty = int(pos.get("quantity", 0))
            old_cost = float(pos.get("avg_cost", 0.0))
            new_qty = old_qty + qty
            new_avg = round((old_cost * old_qty + price * qty) / new_qty, 4) if new_qty > 0 else price

            if market == "CN":
                new_available = pos.get("available_qty", old_qty)
            else:
                new_available = new_qty

            update_set = {
                "quantity": new_qty,
                "available_qty": new_available,
                "avg_cost": new_avg,
                "updated_at": now_iso,
            }
            if strategy:
                update_set["strategy"] = strategy
            if stop_loss_price is not None:
                update_set["stop_loss_price"] = stop_loss_price
            if take_profit_price is not None:
                update_set["take_profit_price"] = take_profit_price
            if thesis:
                update_set["thesis"] = thesis
            if stock_name:
                update_set["stock_name"] = stock_name

            await db["paper_positions"].update_one(
                {"_id": pos["_id"]},
                {"$set": update_set}
            )

    else:  # sell
        available_qty = await _get_available_quantity(user_id, normalized_code, market)
        if available_qty < qty:
            raise ValueError(f"可用持仓不足：需要 {qty}，可用 {available_qty}")

        old_qty = int(pos.get("quantity", 0))
        avg_cost = float(pos.get("avg_cost", 0.0))
        new_qty = old_qty - qty
        pnl = round((price - avg_cost) * qty, 2)
        realized_pnl_delta = pnl

        net_proceeds = notional - commission
        await db["paper_accounts"].update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    f"cash.{currency}": net_proceeds,
                    f"realized_pnl.{currency}": realized_pnl_delta
                },
                "$set": {"updated_at": now_iso}
            }
        )

        if new_qty == 0:
            await db["paper_positions"].update_one(
                {"_id": pos["_id"]},
                {"$set": {
                    "quantity": 0,
                    "available_qty": 0,
                    "frozen_qty": 0,
                    "status": "closed",
                    "exit_price": price,
                    "exit_date": datetime.now().strftime("%Y-%m-%d"),
                    "exit_reason": "sell_order",
                    "realized_pnl": pnl,
                    "updated_at": now_iso,
                }}
            )
        else:
            new_available = max(0, pos.get("available_qty", old_qty) - qty)
            await db["paper_positions"].update_one(
                {"_id": pos["_id"]},
                {"$set": {
                    "quantity": new_qty,
                    "available_qty": new_available,
                    "updated_at": now_iso
                }}
            )

    # 9. 记录订单与成交（即成）
    order_doc = {
        "user_id": user_id,
        "code": normalized_code,
        "market": market,
        "currency": currency,
        "side": side,
        "quantity": qty,
        "price": price,
        "amount": notional,
        "commission": commission,
        "status": "filled",
        "created_at": now_iso,
        "filled_at": now_iso,
    }
    if analysis_id:
        order_doc["analysis_id"] = analysis_id
    await db["paper_orders"].insert_one(order_doc)

    trade_doc = {
        "user_id": user_id,
        "code": normalized_code,
        "market": market,
        "currency": currency,
        "side": side,
        "quantity": qty,
        "price": price,
        "amount": notional,
        "commission": commission,
        "pnl": realized_pnl_delta if side == "sell" else 0.0,
        "timestamp": now_iso,
    }
    if pos:
        if pos.get("strategy"):
            trade_doc["strategy"] = pos["strategy"]
        if pos.get("stock_name"):
            trade_doc["stock_name"] = pos["stock_name"]
    if analysis_id:
        trade_doc["analysis_id"] = analysis_id
    await db["paper_trades"].insert_one(trade_doc)

    # 自动管理止损预警：买入时创建，清仓时删除
    try:
        from app.services.stock_alert_service import ALERT_TYPE_PRICE_BELOW, AlertRuleCreate, stock_alert_service
        stock_name_eff = stock_name or (pos.get("stock_name") if pos else "") or ""

        if side == "buy":
            effective_stop_loss = stop_loss_price
            if effective_stop_loss is None and pos and pos.get("stop_loss_price") is not None:
                effective_stop_loss = pos.get("stop_loss_price")
            if effective_stop_loss is not None and effective_stop_loss > 0:
                await db["stock_alerts"].delete_many({
                    "user_id": user_id,
                    "code": normalized_code,
                    "alert_type": ALERT_TYPE_PRICE_BELOW,
                    "note": {"$regex": "^自动止损"},
                })
                await stock_alert_service.create_alert(
                    user_id,
                    AlertRuleCreate(
                        code=normalized_code,
                        stock_name=stock_name_eff,
                        alert_type=ALERT_TYPE_PRICE_BELOW,
                        threshold=float(effective_stop_loss),
                        note="自动止损预警（持仓成本监控）",
                    ),
                )
        elif side == "sell":
            cur_qty_after = (int(pos.get("quantity", 0)) - qty) if pos else 0
            if cur_qty_after <= 0:
                await db["stock_alerts"].delete_many({
                    "user_id": user_id,
                    "code": normalized_code,
                    "alert_type": ALERT_TYPE_PRICE_BELOW,
                    "note": {"$regex": "^自动止损"},
                })
    except Exception as alert_err:
        logger.warning(f"⚠️ 自动止损预警管理失败（不影响交易）: {alert_err}")

    return {k: v for k, v in order_doc.items() if k != "_id"}