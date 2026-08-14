import logging
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.database import get_mongo_db
from app.core.response import ok
from app.routers.auth_db import get_current_user
from app.services.paper_executor import execute_market_order

router = APIRouter(prefix="/paper", tags=["paper"])
logger = logging.getLogger("webapi")


class PlaceOrderRequest(BaseModel):
    code: str = Field(..., description="股票代码（支持A股/港股/美股）")
    side: Literal["buy", "sell"]
    quantity: int = Field(..., gt=0)
    market: str | None = Field(None, description="市场类型 (CN/HK/US)，不传则自动识别")
    # 可选：关联的分析ID，便于从分析页面一键下单后追踪
    analysis_id: str | None = None
    # 散户策略元数据（买入时写入 paper_positions，用于退出信号监控和策略表现统计）
    strategy: str | None = Field(None, description="策略类型（extreme_reversal/turnaround/small_cap_value/convertible_arbitrage）")
    stop_loss_price: float | None = Field(None, description="止损价")
    take_profit_price: float | None = Field(None, description="止盈价")
    thesis: str | None = Field(None, description="投资逻辑")
    stock_name: str | None = Field(None, description="股票名称")


async def _get_or_create_account(user_id: str) -> dict[str, Any]:
    """获取或创建账户（多货币）"""
    db = get_mongo_db()
    acc = await db["paper_accounts"].find_one({"user_id": user_id})
    if not acc:
        now = datetime.now().isoformat()
        acc = {
            "user_id": user_id,
            # 多货币现金账户
            "cash": {
                "CNY": INITIAL_CASH_BY_MARKET["CNY"],
                "HKD": INITIAL_CASH_BY_MARKET["HKD"],
                "USD": INITIAL_CASH_BY_MARKET["USD"]
            },
            # 多货币已实现盈亏
            "realized_pnl": {
                "CNY": 0.0,
                "HKD": 0.0,
                "USD": 0.0
            },
            # 账户设置
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


async def _get_last_price(code: str, market: str) -> float | None:
    """
    获取股票最新价格（支持多市场）

    Args:
        code: 股票代码
        market: 市场类型 (CN/HK/US)

    Returns:
        最新价格，如果获取失败返回 None
    """
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
                    logger.debug(f"✅ 从 market_quotes 获取价格: {code} = {price}")
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
                    logger.debug(f"✅ 从 stock_basic_info 获取价格: {code} = {price}")
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
                # 尝试多个可能的价格字段
                price = quote.get("price") or quote.get("current_price") or quote.get("close")
                if price and float(price) > 0:
                    logger.debug(f"✅ 从 ForeignStockService 获取{market}价格: {code} = {price}")
                    return float(price)
        except Exception as e:
            logger.error(f"❌ 获取{market}股价格失败 {code}: {e}")
            return None

    logger.error(f"❌ 无法获取股票价格: {code} (market={market})")
    return None


@router.get("/account", response_model=dict)
async def get_account(current_user: dict = Depends(get_current_user)):
    """获取或创建纸上账户，返回资金与持仓估值汇总（支持多市场）"""
    db = get_mongo_db()
    acc = await _get_or_create_account(current_user["id"])

    # 聚合持仓估值（按货币分类）—— 只统计未平仓持仓
    positions = await db["paper_positions"].find({
        "user_id": current_user["id"],
        "quantity": {"$gt": 0}
    }).to_list(None)

    positions_value_by_currency = {
        "CNY": 0.0,
        "HKD": 0.0,
        "USD": 0.0
    }

    detailed_positions: list[dict[str, Any]] = []
    for p in positions:
        code = p.get("code")
        market = p.get("market", "CN")
        currency = p.get("currency", "CNY")
        qty = int(p.get("quantity", 0))
        avg_cost = float(p.get("avg_cost", 0.0))
        available_qty = p.get("available_qty", qty)

        # 获取最新价
        last = await _get_last_price(code, market)
        mkt_value = round((last or 0.0) * qty, 2)
        positions_value_by_currency[currency] += mkt_value

        detailed_positions.append({
            "code": code,
            "market": market,
            "currency": currency,
            "quantity": qty,
            "available_qty": available_qty,
            "avg_cost": avg_cost,
            "last_price": last,
            "market_value": mkt_value,
            "unrealized_pnl": None if last is None else round((last - avg_cost) * qty, 2)
        })

    # 计算总资产（按货币分别显示）
    cash = acc.get("cash", {})
    realized_pnl = acc.get("realized_pnl", {})

    # 兼容旧格式（单一现金）
    if not isinstance(cash, dict):
        cash = {"CNY": float(cash), "HKD": 0.0, "USD": 0.0}
    if not isinstance(realized_pnl, dict):
        realized_pnl = {"CNY": float(realized_pnl), "HKD": 0.0, "USD": 0.0}

    summary = {
        "cash": {
            "CNY": round(float(cash.get("CNY", 0.0)), 2),
            "HKD": round(float(cash.get("HKD", 0.0)), 2),
            "USD": round(float(cash.get("USD", 0.0)), 2)
        },
        "realized_pnl": {
            "CNY": round(float(realized_pnl.get("CNY", 0.0)), 2),
            "HKD": round(float(realized_pnl.get("HKD", 0.0)), 2),
            "USD": round(float(realized_pnl.get("USD", 0.0)), 2)
        },
        "positions_value": positions_value_by_currency,
        "equity": {
            "CNY": round(float(cash.get("CNY", 0.0)) + positions_value_by_currency["CNY"], 2),
            "HKD": round(float(cash.get("HKD", 0.0)) + positions_value_by_currency["HKD"], 2),
            "USD": round(float(cash.get("USD", 0.0)) + positions_value_by_currency["USD"], 2)
        },
        "updated_at": acc.get("updated_at"),
    }

    return ok({"account": summary, "positions": detailed_positions})


@router.get("/risk", response_model=dict)
async def get_risk_status(current_user: dict = Depends(get_current_user)):
    """账户级回撤风控状态（教材5.2账户级止损 + 连续止损暂停）。

    返回当前周/月回撤、风控等级、总仓位上限、账户/标的暂停状态。
    """
    from app.services.retail.drawdown_risk_control import get_risk_control
    risk = await get_risk_control(current_user["id"])
    return ok({"risk": risk})


@router.post("/order", response_model=dict)
async def place_order(payload: PlaceOrderRequest, current_user: dict = Depends(get_current_user)):
    """提交市价单，按最新价即时成交（支持多市场）。

    核心逻辑复用 `execute_market_order`（见 app/services/paper_executor.py），
    与「三买三卖·监控中心」待确认指令共用同一成交入口。
    """
    try:
        order = await execute_market_order(
            user_id=current_user["id"],
            code=payload.code,
            side=payload.side,
            quantity=payload.quantity,
            market=payload.market,
            analysis_id=payload.analysis_id,
            strategy=payload.strategy,
            stop_loss_price=payload.stop_loss_price,
            take_profit_price=payload.take_profit_price,
            thesis=payload.thesis,
            stock_name=payload.stock_name,
        )
        return ok({"order": order})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/positions", response_model=dict)
async def list_positions(
    status: str | None = None,
    current_user: dict = Depends(get_current_user)
):
    """获取持仓列表（支持多市场）

    Args:
        status: 持仓状态筛选。open=未平仓(quantity>0)，closed=已平仓(quantity=0)，all=全部
    """
    db = get_mongo_db()
    query: dict[str, Any] = {"user_id": current_user["id"]}
    if status == "open":
        query["quantity"] = {"$gt": 0}
    elif status == "closed":
        query["quantity"] = 0
    # status == "all" 或未传：不过滤（兼容旧调用方）
    if status is None:
        query["quantity"] = {"$gt": 0}

    items = await db["paper_positions"].find(query).sort("updated_at", -1).to_list(None)
    enriched: list[dict[str, Any]] = []
    for p in items:
        code = p.get("code")
        market = p.get("market", "CN")
        currency = p.get("currency", "CNY")
        qty = int(p.get("quantity", 0))
        available_qty = p.get("available_qty", qty)
        avg_cost = float(p.get("avg_cost", 0.0))

        last = await _get_last_price(code, market)
        mkt = round((last or 0.0) * qty, 2)
        enriched.append({
            "id": str(p.get("_id", "")),
            "code": code,
            "market": market,
            "currency": currency,
            "quantity": qty,
            "available_qty": available_qty,
            "avg_cost": avg_cost,
            "last_price": last,
            "market_value": mkt,
            "unrealized_pnl": None if last is None else round((last - avg_cost) * qty, 2),
            # 策略与平仓元数据（用于交易复盘）
            "strategy": p.get("strategy", "default"),
            "stock_name": p.get("stock_name", ""),
            "buy_date": p.get("buy_date"),
            "thesis": p.get("thesis"),
            "stop_loss_price": p.get("stop_loss_price"),
            "take_profit_price": p.get("take_profit_price"),
            "status": p.get("status", "open" if qty > 0 else "closed"),
            "exit_price": p.get("exit_price"),
            "exit_date": p.get("exit_date"),
            "exit_reason": p.get("exit_reason"),
            "realized_pnl": p.get("realized_pnl"),
            "created_at": p.get("created_at"),
            "updated_at": p.get("updated_at"),
        })
    return ok({"items": enriched})


@router.get("/orders", response_model=dict)
async def list_orders(limit: int = Query(50, ge=1, le=200), current_user: dict = Depends(get_current_user)):
    db = get_mongo_db()
    cursor = db["paper_orders"].find({"user_id": current_user["id"]}).sort("created_at", -1).limit(limit)
    items = await cursor.to_list(None)
    # 去除 _id
    cleaned = [{k: v for k, v in it.items() if k != "_id"} for it in items]
    return ok({"items": cleaned})


@router.post("/reset", response_model=dict)
async def reset_account(confirm: bool = Query(False), current_user: dict = Depends(get_current_user)):
    """重置账户（支持多货币）"""
    if not confirm:
        raise HTTPException(status_code=400, detail="请设置 confirm=true 以确认重置")
    db = get_mongo_db()
    await db["paper_accounts"].delete_many({"user_id": current_user["id"]})
    await db["paper_positions"].delete_many({"user_id": current_user["id"]})
    await db["paper_orders"].delete_many({"user_id": current_user["id"]})
    await db["paper_trades"].delete_many({"user_id": current_user["id"]})
    # 重新创建账户
    acc = await _get_or_create_account(current_user["id"])
    return ok({"message": "账户已重置", "cash": acc.get("cash", {})})


# ==================== 交易复盘 ====================

_REVIEW_RESULT_OPTIONS = [
    "executed", "stop_loss_timely", "chasing_high",
    "cut_loss_early", "missed", "other",
]


class ReviewNoteIn(BaseModel):
    """复盘笔记（新增/更新共用）。trade_id 可空，表示自由记录。"""
    trade_id: str | None = None
    code: str | None = None
    name: str | None = None
    strategy: str | None = None
    result: str | None = None
    lesson: str | None = None
    improvement: str | None = None
    tags: list[str] = Field(default_factory=list)


@router.get("/review/trades", response_model=dict)
async def review_trades(current_user: dict = Depends(get_current_user)):
    """已平仓交易周期汇总（含盈亏），供交易复盘 · 交易记录面板。

    以 paper_trades 成交流水为基础，同一 code 按时间配对一买一卖形成完整周期：
    先出现 buy，后出现 sell，则为一笔已平仓周期，计算盈亏金额/盈亏率/持仓天数。
    """
    db = get_mongo_db()
    trades = await db["paper_trades"].find(
        {"user_id": current_user["id"]}
    ).sort("timestamp", 1).to_list(None)

    open_pos: dict[str, dict] = {}  # code -> buy 记录（等待平仓）
    cycles: list[dict] = []
    for t in trades:
        code = str(t.get("code") or "")
        side = t.get("side")
        if not code:
            continue
        if side == "buy":
            open_pos[code] = t
        elif side == "sell":
            buy = open_pos.pop(code, None)
            if buy is None:
                continue
            buy_price = float(buy.get("price") or 0)
            sell_price = float(t.get("price") or 0)
            qty = int(t.get("quantity") or 0)
            pnl = float(t.get("pnl") or 0)
            cycles.append({
                "code": code,
                "name": t.get("stock_name") or buy.get("stock_name") or "",
                "strategy": t.get("strategy") or buy.get("strategy") or "",
                "buy_price": round(buy_price, 3),
                "sell_price": round(sell_price, 3),
                "quantity": qty,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl / (buy_price * qty) * 100, 2) if (buy_price * qty) else 0.0,
                "buy_time": buy.get("timestamp"),
                "sell_time": t.get("timestamp"),
            })
    # 按卖出时间倒序
    cycles.sort(key=lambda c: c.get("sell_time") or "", reverse=True)
    return ok({"items": cycles, "total": len(cycles)})


@router.get("/review/notes", response_model=dict)
async def list_review_notes(current_user: dict = Depends(get_current_user)):
    """复盘笔记列表（按更新时间倒序）。"""
    db = get_mongo_db()
    items = await db["trade_reviews"].find(
        {"user_id": current_user["id"]}
    ).sort("updated_at", -1).to_list(None)
    cleaned = [{k: v for k, v in it.items() if k != "_id"} for it in items]
    return ok({"items": cleaned})


@router.post("/review/notes", response_model=dict)
async def create_review_note(payload: ReviewNoteIn, current_user: dict = Depends(get_current_user)):
    """新增复盘笔记。"""
    db = get_mongo_db()
    now = datetime.now().isoformat()
    doc = {
        "user_id": current_user["id"],
        "trade_id": payload.trade_id,
        "code": payload.code,
        "name": payload.name,
        "strategy": payload.strategy,
        "result": payload.result,
        "lesson": payload.lesson,
        "improvement": payload.improvement,
        "tags": payload.tags or [],
        "created_at": now,
        "updated_at": now,
    }
    res = await db["trade_reviews"].insert_one(doc)
    return ok({"id": str(res.inserted_id)})


@router.put("/review/notes/{note_id}", response_model=dict)
async def update_review_note(note_id: str, payload: ReviewNoteIn,
                             current_user: dict = Depends(get_current_user)):
    """更新复盘笔记。"""
    db = get_mongo_db()
    from bson import ObjectId
    upd = {k: v for k, v in payload.model_dump().items() if v is not None}
    upd["updated_at"] = datetime.now().isoformat()
    res = await db["trade_reviews"].update_one(
        {"_id": ObjectId(note_id), "user_id": current_user["id"]},
        {"$set": upd},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="复盘笔记不存在")
    return ok({"message": "已更新"})


@router.delete("/review/notes/{note_id}", response_model=dict)
async def delete_review_note(note_id: str, current_user: dict = Depends(get_current_user)):
    """删除复盘笔记。"""
    db = get_mongo_db()
    from bson import ObjectId
    res = await db["trade_reviews"].delete_one(
        {"_id": ObjectId(note_id), "user_id": current_user["id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="复盘笔记不存在")
    return ok({"message": "已删除"})


@router.get("/review/stats", response_model=dict)
async def review_stats(current_user: dict = Depends(get_current_user)):
    """复盘统计：胜率、盈亏比、归因占比。"""
    db = get_mongo_db()
    cycles_resp = await review_trades(current_user)
    cycles = cycles_resp["data"]["items"]
    wins = [c for c in cycles if c["pnl"] > 0]
    losses = [c for c in cycles if c["pnl"] < 0]
    total_pnl = sum(c["pnl"] for c in cycles)
    win_sum = sum(c["pnl"] for c in wins)
    loss_sum = abs(sum(c["pnl"] for c in losses))

    notes = await db["trade_reviews"].find(
        {"user_id": current_user["id"], "result": {"$ne": None}}
    ).to_list(None)
    attribution: dict[str, int] = {}
    for n in notes:
        r = n.get("result")
        if r:
            attribution[r] = attribution.get(r, 0) + 1

    return ok({
        "total_cycles": len(cycles),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(cycles), 4) if cycles else 0.0,
        "profit_loss_ratio": round(win_sum / loss_sum, 4) if loss_sum else 0.0,
        "total_pnl": round(total_pnl, 2),
        "attribution": attribution,
        "result_options": _REVIEW_RESULT_OPTIONS,
    })