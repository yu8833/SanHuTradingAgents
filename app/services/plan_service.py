"""当日交易计划（P2）。

设计文档《第六章·交易工具与日常流程》§4 缺口2：
- 新建 daily_plans 集合：{标的, 方向, 触发价, 仓位反算, 止损位, 卖出条件, 状态(待执行/已执行/取消)}
- 复用 SSE 实时行情：价格触达计划价位时前端高亮/推送提醒（见 evaluate_plans）
- 执行后自动关联 paper_trades，形成"计划→成交→复盘"链路
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import get_mongo_db
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

COLLECTION = "daily_plans"

# 计划方向
DIRECTION_BUY = "buy"
DIRECTION_SELL = "sell"

# 计划状态
STATUS_PENDING = "pending"
STATUS_EXECUTED = "executed"
STATUS_CANCELLED = "cancelled"

_STATUS_LABELS = {
    "pending": "待执行", "executed": "已执行", "cancelled": "已取消",
}


def _today() -> str:
    return now_tz().strftime("%Y-%m-%d")


def _serialize(doc: dict) -> dict:
    _id = doc.pop("_id", None)
    if _id is not None:
        doc["id"] = str(_id)
    # 三态：confirmed=False=待确认 / True=已确认（存量旧计划无该字段视为已确认）
    doc.setdefault("confirmed", True)
    doc["status_label"] = _STATUS_LABELS.get(doc.get("status"), doc.get("status", ""))
    return doc


async def _resolve_stock_name(code: str, name: str = "") -> str:
    """股票名称为空/为代码时自动补全真实名称。"""
    if name and name != code:
        return name
    try:
        db = get_mongo_db()
        doc = await db["stock_basic_info"].find_one(
            {"code": code}, projection={"_id": 0, "name": 1}
        )
        if doc and doc.get("name"):
            return doc["name"]
    except Exception:
        pass
    return name or code


async def _position_sizing(user_id: str, code: str, price: float, strategy: str = "default") -> dict | None:
    """买入计划仓位反算：用纸上账户 CNY 权益 + 默认策略（半Kelly 等）。失败返回 None 不阻塞。"""
    try:
        from app.services.retail.position_sizer import PositionSizer, StrategyType
        db = get_mongo_db()
        acc = await db["paper_accounts"].find_one({"user_id": user_id})
        cash = acc.get("cash", {}) if acc else {}
        if not isinstance(cash, dict):
            cash = {"CNY": float(cash), "HKD": 0.0, "USD": 0.0}
        equity_cny = float(cash.get("CNY", 0.0) or 0.0)
        if equity_cny <= 0:
            return None

        holdings_raw = await db["paper_positions"].find({
            "user_id": user_id, "quantity": {"$gt": 0}
        }).to_list(None)
        holdings = []
        for h in holdings_raw:
            qty = int(h.get("quantity", 0))
            cost = float(h.get("avg_cost", 0.0) or 0.0)
            if qty > 0 and cost > 0:
                holdings.append({
                    "symbol": h.get("code", ""),
                    "industry": h.get("industry", "未知"),
                    "theme": h.get("theme", "未知"),
                    "market_value": qty * cost,
                    "position_ratio": (qty * cost) / equity_cny,
                })

        sizer = PositionSizer(equity_cny, holdings)
        try:
            strategy_enum = StrategyType(strategy)
        except (ValueError, TypeError):
            strategy_enum = StrategyType.DEFAULT
        advice = sizer.calculate(
            symbol=code,
            strategy=strategy_enum,
            price=price,
        )
        d = advice.to_dict()
        return {
            "account_size": round(equity_cny, 2),
            "suggested_shares": d["suggested_shares"],
            "suggested_amount": d["suggested_amount"],
            "target_position_ratio": d["target_position_ratio"],
            "blocked": d["blocked"],
            "block_reasons": d["block_reasons"],
            "warnings": d["warnings"],
        }
    except Exception as e:
        logger.warning(f"仓位反算失败(不阻塞建计划): {e}")
        return None


async def create_plan(user_id: str, data: dict) -> dict:
    """创建当日交易计划。buy 计划自动反算仓位。"""
    db = get_mongo_db()
    code = (data.get("code") or "").strip()
    direction = data.get("direction") or DIRECTION_BUY
    if not code:
        raise ValueError("标的代码不能为空")
    if direction not in (DIRECTION_BUY, DIRECTION_SELL):
        raise ValueError(f"方向非法: {direction}")

    plan_date = (data.get("date") or _today())
    name = await _resolve_stock_name(code, data.get("name", ""))

    trigger_price = data.get("trigger_price")
    position = data.get("position")
    # 买入且未显式给仓位 → 自动反算
    if direction == DIRECTION_BUY and not position and trigger_price:
        position = await _position_sizing(user_id, code, float(trigger_price), data.get("strategy", "default"))

    doc = {
        "user_id": user_id,
        "date": plan_date,
        "code": code,
        "name": name,
        "direction": direction,
        "direction_label": "买入" if direction == DIRECTION_BUY else "卖出",
        "trigger_price": trigger_price,
        "position": position,
        "stop_loss": data.get("stop_loss"),
        "sell_condition": data.get("sell_condition"),
        "status": STATUS_PENDING,
        # 三态确认：False=待确认（候选/卖出观测写库后需在当日计划中确认），True=已确认。
        # 手动添加计划视为已确认；盘中"可执行/触达提醒"仅对 confirmed=True 的计划生效。
        "confirmed": bool(data.get("confirmed", False)),
        "executed_trade_id": None,
        # 5.4 来源标签：{type, ref, label}，标注该条计划的来源（已验证信号/候选池/手动），便于审计与人工可改
        "source": data.get("source"),
        "notes": data.get("notes"),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    res = await db[COLLECTION].insert_one(doc)
    doc["_id"] = res.inserted_id
    return _serialize(doc)


async def list_plans(user_id: str, plan_date: str | None = None, status: str | None = None) -> list[dict]:
    """计划列表：默认当日，可指定日期/状态。"""
    try:
        db = get_mongo_db()
        q: dict = {"user_id": user_id}
        if plan_date:
            q["date"] = plan_date
        elif not plan_date:
            q["date"] = _today()
        if status:
            q["status"] = status
        docs = await db[COLLECTION].find(q).sort("created_at", 1).to_list(None)
        return [_serialize(d) for d in docs]
    except Exception as e:
        logger.error(f"计划列表读取失败: {e}", exc_info=True)
        return []


async def update_plan_status(user_id: str, plan_id: str, status: str,
                             executed_trade_id: str | None = None) -> dict | None:
    """更新计划状态：待执行 → 已执行/已取消。已执行可关联 paper_trades 成交记录。"""
    db = get_mongo_db()
    from bson import ObjectId
    if not ObjectId.is_valid(plan_id):
        return None
    try:
        update = {
            "status": status,
            "updated_at": datetime.utcnow(),
        }
        if status == STATUS_EXECUTED and executed_trade_id:
            update["executed_trade_id"] = executed_trade_id
        res = await db[COLLECTION].find_one_and_update(
            {"_id": ObjectId(plan_id), "user_id": user_id},
            {"$set": update},
            return_document=True,
        )
        return _serialize(res) if res else None
    except Exception as e:
        logger.error(f"计划状态更新失败: {e}", exc_info=True)
        return None


async def update_plan_detail(user_id: str, plan_id: str, fields: dict) -> dict | None:
    """改价 / 改止损 / 改卖出条件（5.4 人工可改）：字段级更新并重算仓位。

    buy 计划改触发价后重新反算仓位；sell 计划不反算仓位。
    """
    db = get_mongo_db()
    from bson import ObjectId
    if not ObjectId.is_valid(plan_id):
        return None
    try:
        existing = await db[COLLECTION].find_one({"_id": ObjectId(plan_id), "user_id": user_id})
        if not existing:
            return None

        allowed = {"trigger_price", "stop_loss", "sell_condition", "name", "notes", "source", "confirmed"}
        update = {
            k: v for k, v in fields.items()
            if k in allowed and v is not None
        }
        direction = fields.get("direction") or existing.get("direction")
        # buy 且改了触发价 → 自动重算仓位
        if (direction == DIRECTION_BUY and update.get("trigger_price") is not None
                and existing.get("trigger_price") != update["trigger_price"]):
            new_pos = await _position_sizing(
                user_id, existing.get("code", ""), float(update["trigger_price"]),
                existing.get("strategy", "default"),
            )
            if new_pos:
                update["position"] = new_pos

        if not update:
            return _serialize(dict(existing))
        update["updated_at"] = datetime.utcnow()
        res = await db[COLLECTION].find_one_and_update(
            {"_id": ObjectId(plan_id), "user_id": user_id},
            {"$set": update},
            return_document=True,
        )
        return _serialize(res) if res else None
    except Exception as e:
        logger.error(f"计划详情更新失败: {e}", exc_info=True)
        return None


async def delete_plan(user_id: str, plan_id: str) -> bool:
    """删除计划（5.4 人工删除，仅允许删除未执行的计划）。"""
    db = get_mongo_db()
    from bson import ObjectId
    if not ObjectId.is_valid(plan_id):
        return False
    try:
        res = await db[COLLECTION].delete_one(
            {"_id": ObjectId(plan_id), "user_id": user_id, "status": STATUS_PENDING}
        )
        return bool(res.deleted_count)
    except Exception as e:
        logger.error(f"计划删除失败: {e}", exc_info=True)
        return False


async def auto_associate_trade(user_id: str, code: str, direction: str, trade_id: str,
                               plan_date: str | None = None) -> dict | None:
    """成交后自动关联当日待执行计划（设计文档 §4 缺口2："执行后自动关联 paper_trades"）。

    按 用户+代码+方向+当日 匹配 pending 计划，标记 executed 并写入 executed_trade_id，
    形成"计划→成交→复盘"链路。无匹配返回 None；失败不抛出（不阻塞成交主流程）。
    """
    try:
        db = get_mongo_db()
        plan = await db[COLLECTION].find_one_and_update(
            {
                "user_id": user_id,
                "code": code,
                "direction": direction,
                "status": STATUS_PENDING,
                "date": plan_date or _today(),
            },
            {"$set": {
                "status": STATUS_EXECUTED,
                "executed_trade_id": trade_id,
                "updated_at": datetime.utcnow(),
            }},
            return_document=True,
        )
        if plan:
            logger.info(f"📌 计划→成交自动关联: plan={plan.get('_id')} trade={trade_id} {code} {direction}")
        return _serialize(plan) if plan else None
    except Exception as e:
        logger.error(f"计划自动关联失败（不影响成交）: {e}", exc_info=True)
        return None


def _check_triggered(direction: str, trigger_price: float | None, last_price: float | None) -> bool:
    """价格触达判断：买入=回落至触发价以下；卖出=涨至触发价以上。"""
    if last_price is None or trigger_price is None:
        return False
    try:
        last_f, tp_f = float(last_price), float(trigger_price)
    except (TypeError, ValueError):
        return False
    if direction == DIRECTION_BUY:
        return last_f <= tp_f
    return last_f >= tp_f


async def evaluate_plans(user_id: str, quotes: dict[str, float], plan_date: str | None = None) -> list[dict]:
    """对照实时行情评估当日待执行计划：价格触达触发价则标记 triggered。

    Args:
        quotes: {code: 最新价}
        plan_date: 计划日期，默认当日

    Returns:
        当日待执行计划列表，每条附 triggered: bool + last_price。
    """
    plans = await list_plans(user_id, plan_date=plan_date or _today(), status=STATUS_PENDING)
    out = []
    for p in plans:
        code = p.get("code", "")
        last = quotes.get(code)
        p["last_price"] = last
        p["triggered"] = _check_triggered(p.get("direction"), p.get("trigger_price"), last)
        out.append(p)
    return out


async def get_today_summary(user_id: str) -> dict:
    """当日计划摘要（作战室引导条：待执行/已执行/取消 计数）。"""
    try:
        db = get_mongo_db()
        q = {"user_id": user_id, "date": _today()}
        counts = {"pending": 0, "executed": 0, "cancelled": 0}
        for d in await db[COLLECTION].find(q, projection={"status": 1}).to_list(None):
            s = d.get("status")
            if s in counts:
                counts[s] += 1
        return counts
    except Exception as e:
        logger.error(f"当日计划摘要失败: {e}", exc_info=True)
        return {"pending": 0, "executed": 0, "cancelled": 0}
