"""
持仓追踪服务（统一数据源版）

以 paper_positions 作为单一持仓数据源（与模拟交易系统共用），
以 paper_trades 作为策略表现统计来源。

字段映射（paper_positions ↔ API 输出）：
  code        → symbol        （API 对外用 symbol）
  avg_cost    → cost_price
  quantity    → quantity
  market      → market        （CN/HK/US）
  currency    → currency
  strategy / stop_loss_price / take_profit_price / thesis / buy_date / stock_name
  作为可选元数据字段存储在 paper_positions 文档上。

策略表现统计：从 paper_trades 的卖出记录（side=sell, pnl）计算胜率/盈亏比。
"""

import logging
from datetime import datetime
from typing import Any
from app.utils.timezone import now_tz

from bson import ObjectId
from pydantic import BaseModel

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


class Position(BaseModel):
    """持仓数据模型"""
    id: str | None = None
    user_id: str
    symbol: str                      # 股票代码，如 "600519"（paper_positions 用 code 字段存储）
    stock_name: str                  # 股票名称
    quantity: int                    # 持股数量
    cost_price: float                # 成本价（paper_positions 用 avg_cost 字段存储）
    position_ratio: float            # 仓位占比 (0-1)
    buy_date: str                    # 买入日期
    notes: str | None = None      # 备注
    # 散户策略扩展字段（作为元数据存储在 paper_positions 上）
    strategy: str | None = "default"
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    thesis: str | None = None
    status: str | None = "open"
    exit_price: float | None = None
    exit_date: str | None = None
    exit_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionUpdate(BaseModel):
    """持仓更新模型"""
    quantity: int | None = None
    cost_price: float | None = None
    position_ratio: float | None = None
    notes: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    thesis: str | None = None


class PortfolioService:
    """持仓追踪服务类（统一数据源：paper_positions + paper_trades）"""

    def __init__(self):
        self.db = None
        self.collection_name = "paper_positions"       # 持仓数据源
        self.trades_collection_name = "paper_trades"   # 交易记录（表现统计）

    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    # ------------------------------------------------------------------
    # 序列化：paper_positions 文档 → API 输出格式
    # ------------------------------------------------------------------
    def _serialize_position(self, doc: dict[str, Any]) -> dict[str, Any]:
        """
        将 paper_positions 文档序列化为 API 输出格式。
        字段映射：code→symbol, avg_cost→cost_price
        """
        if doc is None:
            return None
        result = dict(doc)
        if "_id" in result:
            result["id"] = str(result["_id"])
            del result["_id"]

        # 核心字段映射
        if "code" in result and "symbol" not in result:
            result["symbol"] = result["code"]
        if "avg_cost" in result and "cost_price" not in result:
            result["cost_price"] = result["avg_cost"]

        # 确保 stock_name 存在（paper_positions 可能没有）
        if not result.get("stock_name"):
            result["stock_name"] = result.get("symbol", result.get("code", ""))

        # 确保 buy_date 存在
        if not result.get("buy_date"):
            ts = result.get("updated_at")
            if isinstance(ts, datetime):
                result["buy_date"] = ts.strftime("%Y-%m-%d")
            elif isinstance(ts, str):
                result["buy_date"] = ts[:10]
            else:
                result["buy_date"] = now_tz().strftime("%Y-%m-%d")

        # 时间格式化
        if "created_at" in result and isinstance(result["created_at"], datetime):
            result["created_at"] = result["created_at"].isoformat()
        if "updated_at" in result and isinstance(result["updated_at"], datetime):
            result["updated_at"] = result["updated_at"].isoformat()

        # paper_positions 没有 status 字段，用 quantity>0 推断
        if not result.get("status"):
            result["status"] = "open" if int(result.get("quantity", 0)) > 0 else "closed"

        # 兼容字段
        result.setdefault("position_ratio", 0.0)
        result.setdefault("strategy", "default")
        result.setdefault("exit_price", None)
        result.setdefault("exit_date", None)
        result.setdefault("exit_reason", None)

        return result

    async def create_position(self, position: Position) -> Position:
        """
        添加持仓（写入 paper_positions，附带策略元数据）

        注意：此方法直接创建持仓记录，不经过模拟交易的下单流程（不扣减资金）。
        适用于策略选股后手动记录持仓，或从实盘导入持仓。
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            now = now_tz()
            now_iso = now.isoformat()

            # 检查是否已有同代码持仓（合并而非重复创建）
            existing = await collection.find_one({
                "user_id": position.user_id,
                "code": position.symbol,
            })

            if existing:
                # 合并：加权平均成本
                old_qty = int(existing.get("quantity", 0))
                old_cost = float(existing.get("avg_cost", 0.0))
                new_qty = old_qty + position.quantity
                new_avg = round(
                    (old_cost * old_qty + position.cost_price * position.quantity) / new_qty, 4
                ) if new_qty > 0 else position.cost_price

                updates = {
                    "quantity": new_qty,
                    "available_qty": new_qty,  # 手动创建不受T+1限制
                    "avg_cost": new_avg,
                    "stock_name": position.stock_name or existing.get("stock_name", ""),
                    "buy_date": position.buy_date or existing.get("buy_date"),
                    "strategy": position.strategy or existing.get("strategy", "default"),
                    "stop_loss_price": position.stop_loss_price or existing.get("stop_loss_price"),
                    "take_profit_price": position.take_profit_price or existing.get("take_profit_price"),
                    "thesis": position.thesis or existing.get("thesis"),
                    "updated_at": now_iso,
                }
                result = await collection.find_one_and_update(
                    {"_id": existing["_id"]},
                    {"$set": updates},
                    return_document=True,
                )
                logger.info(f"✅ 合并持仓成功: user_id={position.user_id}, code={position.symbol}")
                return self._serialize_position(result)

            # 新建持仓
            doc = {
                "user_id": position.user_id,
                "code": position.symbol,
                "market": "CN",       # 默认A股，外部可后续更新
                "currency": "CNY",
                "quantity": position.quantity,
                "available_qty": position.quantity,
                "frozen_qty": 0,
                "avg_cost": position.cost_price,
                "stock_name": position.stock_name,
                "buy_date": position.buy_date,
                "position_ratio": position.position_ratio,
                "notes": position.notes,
                "strategy": position.strategy or "default",
                "stop_loss_price": position.stop_loss_price,
                "take_profit_price": position.take_profit_price,
                "thesis": position.thesis,
                "created_at": now,
                "updated_at": now_iso,
            }

            result = await collection.insert_one(doc)
            doc["_id"] = result.inserted_id

            logger.info(f"✅ 创建持仓成功: user_id={position.user_id}, code={position.symbol}")
            return self._serialize_position(doc)

        except Exception as e:
            logger.error(f"❌ 创建持仓失败: {e}", exc_info=True)
            raise Exception(f"创建持仓失败: {str(e)}")

    async def get_positions(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户所有持仓（quantity > 0 的未平仓持仓）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            cursor = collection.find({
                "user_id": user_id,
                "quantity": {"$gt": 0},
            }).sort("updated_at", -1)
            positions = await cursor.to_list(length=None)

            return [self._serialize_position(p) for p in positions]

        except Exception as e:
            logger.error(f"❌ 获取持仓列表失败: {e}", exc_info=True)
            raise Exception(f"获取持仓列表失败: {str(e)}")

    async def update_position(self, position_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """
        更新持仓元数据（止损/止盈/投资逻辑等）

        注意：quantity/cost_price 的更新受限——paper_positions 的核心字段
        由模拟交易系统管理，此方法仅更新策略元数据。
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            # 允许更新的字段（策略元数据 + 基本信息）
            allowed_fields = {"quantity", "cost_price", "position_ratio", "notes",
                              "stop_loss_price", "take_profit_price", "thesis",
                              "strategy", "stock_name", "buy_date"}
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

            # cost_price → avg_cost 映射
            if "cost_price" in filtered_updates:
                filtered_updates["avg_cost"] = filtered_updates.pop("cost_price")

            if not filtered_updates:
                doc = await collection.find_one({"_id": ObjectId(position_id)})
                return self._serialize_position(doc)

            filtered_updates["updated_at"] = now_tz().isoformat()

            result = await collection.find_one_and_update(
                {"_id": ObjectId(position_id)},
                {"$set": filtered_updates},
                return_document=True
            )

            if result:
                logger.info(f"✅ 更新持仓成功: position_id={position_id}")
            else:
                logger.warning(f"⚠️ 更新持仓未找到: position_id={position_id}")

            return self._serialize_position(result)

        except Exception as e:
            logger.error(f"❌ 更新持仓失败: {e}", exc_info=True)
            raise Exception(f"更新持仓失败: {str(e)}")

    async def delete_position(self, position_id: str) -> bool:
        """删除持仓记录（仅用于手动管理，模拟交易卖出时自动删除）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            result = await collection.delete_one({"_id": ObjectId(position_id)})

            if result.deleted_count > 0:
                logger.info(f"✅ 删除持仓成功: position_id={position_id}")
                return True
            else:
                logger.warning(f"⚠️ 删除持仓未找到: position_id={position_id}")
                return False

        except Exception as e:
            logger.error(f"❌ 删除持仓失败: {e}", exc_info=True)
            raise Exception(f"删除持仓失败: {str(e)}")

    async def close_position(
        self,
        position_id: str,
        exit_price: float,
        exit_date: str | None = None,
        exit_reason: str = ""
    ) -> dict[str, Any] | None:
        """
        平仓（将数量归零，保留元数据用于历史追踪）

        注意：模拟交易系统通过卖出订单自动管理平仓。
        此方法用于手动标记平仓（如策略退出信号触发后手动操作）。
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            if exit_date is None:
                exit_date = now_tz().strftime("%Y-%m-%d")

            updates = {
                "quantity": 0,
                "available_qty": 0,
                "exit_price": exit_price,
                "exit_date": exit_date,
                "exit_reason": exit_reason,
                "status": "closed",
                "updated_at": now_tz().isoformat(),
            }

            result = await collection.find_one_and_update(
                {"_id": ObjectId(position_id), "quantity": {"$gt": 0}},
                {"$set": updates},
                return_document=True
            )

            if result:
                logger.info(f"✅ 平仓成功: position_id={position_id}, exit_price={exit_price}, reason={exit_reason}")
            else:
                logger.warning(f"⚠️ 平仓未找到或已平仓: position_id={position_id}")

            return self._serialize_position(result)

        except Exception as e:
            logger.error(f"❌ 平仓失败: {e}", exc_info=True)
            raise Exception(f"平仓失败: {str(e)}")

    async def get_open_positions(self, user_id: str) -> list[dict[str, Any]]:
        """获取用户所有未平仓持仓（quantity > 0）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]
            cursor = collection.find({
                "user_id": user_id,
                "quantity": {"$gt": 0},
            }).sort("updated_at", -1)
            positions = await cursor.to_list(length=None)
            return [self._serialize_position(p) for p in positions]
        except Exception as e:
            logger.error(f"❌ 获取未平仓持仓失败: {e}", exc_info=True)
            raise Exception(f"获取未平仓持仓失败: {str(e)}")

    async def get_positions_by_strategy(
        self, user_id: str, strategy: str
    ) -> list[dict[str, Any]]:
        """按策略类型获取持仓"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]
            cursor = collection.find({
                "user_id": user_id,
                "strategy": strategy,
                "quantity": {"$gt": 0},
            }).sort("updated_at", -1)
            positions = await cursor.to_list(length=None)
            return [self._serialize_position(p) for p in positions]
        except Exception as e:
            logger.error(f"❌ 按策略获取持仓失败: {e}", exc_info=True)
            raise Exception(f"按策略获取持仓失败: {str(e)}")

    async def get_closed_positions(
        self, user_id: str, strategy: str | None = None
    ) -> list[dict[str, Any]]:
        """
        获取已平仓记录（用于策略表现统计）

        数据来源：paper_trades 中 side=sell 的记录，每条含 pnl。
        如指定 strategy，则按交易记录上的 strategy 字段过滤。
        """
        try:
            db = await self._get_db()
            query: dict[str, Any] = {
                "user_id": user_id,
                "side": "sell",
                "pnl": {"$ne": 0.0},
            }
            if strategy:
                query["strategy"] = strategy

            cursor = db[self.trades_collection_name].find(query).sort("timestamp", -1)
            trades = await cursor.to_list(length=None)

            # 序列化交易记录为"已平仓持仓"格式
            closed = []
            for t in trades:
                closed.append({
                    "code": t.get("code"),
                    "symbol": t.get("code"),
                    "stock_name": t.get("stock_name", t.get("code", "")),
                    "exit_price": t.get("price"),
                    "cost_price": 0.0,  # 需要从买入记录匹配，此处简化
                    "quantity": t.get("quantity"),
                    "exit_date": (t.get("timestamp", "") or "")[:10],
                    "exit_reason": t.get("exit_reason", ""),
                    "strategy": t.get("strategy", "default"),
                    "pnl": t.get("pnl", 0.0),
                    "id": str(t.get("_id", "")),
                })
            return closed
        except Exception as e:
            logger.error(f"❌ 获取已平仓持仓失败: {e}", exc_info=True)
            raise Exception(f"获取已平仓持仓失败: {str(e)}")

    async def get_strategy_performance(
        self, user_id: str, strategy: str | None = None
    ) -> dict[str, Any]:
        """
        获取策略表现统计（胜率/盈亏比/平均收益等）

        数据来源：paper_trades 卖出记录的 pnl 字段。
        用于反馈到仓位管理的 win_rate/profit_loss_ratio 参数。
        """
        try:
            db = await self._get_db()
            query: dict[str, Any] = {
                "user_id": user_id,
                "side": "sell",
            }
            if strategy:
                query["strategy"] = strategy

            cursor = db[self.trades_collection_name].find(query)
            trades = await cursor.to_list(length=None)

            if not trades:
                return {
                    "strategy": strategy or "all",
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_loss_ratio": 0,
                    "avg_return": 0,
                }

            # 用 pnl 计算胜率/盈亏比
            pnls = [float(t.get("pnl", 0.0)) for t in trades if t.get("pnl") is not None]
            if not pnls:
                return {
                    "strategy": strategy or "all",
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_loss_ratio": 0,
                    "avg_return": 0,
                }

            winning = [p for p in pnls if p > 0]
            losing = [p for p in pnls if p <= 0]
            win_rate = len(winning) / len(pnls) if pnls else 0
            avg_win = sum(winning) / len(winning) if winning else 0
            avg_loss = sum(losing) / len(losing) if losing else 0
            pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            return {
                "strategy": strategy or "all",
                "total_trades": len(pnls),
                "win_rate": round(win_rate, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "profit_loss_ratio": round(pl_ratio, 4),
                "avg_return": round(sum(pnls) / len(pnls), 4),
            }
        except Exception as e:
            logger.error(f"❌ 获取策略表现失败: {e}", exc_info=True)
            raise Exception(f"获取策略表现失败: {str(e)}")

    async def import_positions(self, positions: list[Position]) -> int:
        """批量导入持仓（写入 paper_positions，附带策略元数据）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            if not positions:
                return 0

            now = now_tz()
            now_iso = now.isoformat()
            docs = []
            for position in positions:
                docs.append({
                    "user_id": position.user_id,
                    "code": position.symbol,
                    "market": "CN",
                    "currency": "CNY",
                    "quantity": position.quantity,
                    "available_qty": position.quantity,
                    "frozen_qty": 0,
                    "avg_cost": position.cost_price,
                    "stock_name": position.stock_name,
                    "buy_date": position.buy_date,
                    "position_ratio": position.position_ratio,
                    "notes": position.notes,
                    "strategy": position.strategy or "default",
                    "stop_loss_price": position.stop_loss_price,
                    "take_profit_price": position.take_profit_price,
                    "thesis": position.thesis,
                    "created_at": now,
                    "updated_at": now_iso,
                })

            result = await collection.insert_many(docs)
            success_count = len(result.inserted_ids)

            logger.info(f"✅ 批量导入持仓成功: 成功{success_count}条")
            return success_count

        except Exception as e:
            logger.error(f"❌ 批量导入持仓失败: {e}", exc_info=True)
            raise Exception(f"批量导入持仓失败: {str(e)}")

    async def get_position_summary(self, user_id: str) -> dict[str, Any]:
        """获取持仓汇总（持仓数量、总成本、市值、盈亏等）"""
        try:
            positions = await self.get_positions(user_id)

            if not positions:
                return {
                    "total_positions": 0,
                    "total_cost": 0.0,
                    "total_quantity": 0,
                    "positions": [],
                    "profit_loss": 0.0,
                    "profit_loss_rate": 0.0
                }

            total_cost = 0.0
            total_quantity = 0
            positions_with_value = []

            for pos in positions:
                cost = pos["quantity"] * pos["cost_price"]
                total_cost += cost
                total_quantity += pos["quantity"]
                positions_with_value.append({
                    **pos,
                    "cost": cost
                })

            total_market_value = 0.0
            total_profit_loss = 0.0

            try:
                from app.services.quotes_service import get_quotes_service
                quotes_service = get_quotes_service()

                symbols = [p["symbol"] for p in positions_with_value]
                quotes = await quotes_service.get_quotes(symbols)

                for pos in positions_with_value:
                    symbol = pos["symbol"]
                    if symbol in quotes:
                        quote = quotes[symbol]
                        current_price = quote.get("close", 0)
                        market_value = pos["quantity"] * current_price
                        cost = pos["cost"]
                        profit_loss = market_value - cost
                        profit_loss_rate = (profit_loss / cost * 100) if cost > 0 else 0

                        pos["current_price"] = current_price
                        pos["market_value"] = market_value
                        pos["profit_loss"] = profit_loss
                        pos["profit_loss_rate"] = profit_loss_rate

                        total_market_value += market_value
                        total_profit_loss += profit_loss
                    else:
                        pos["current_price"] = None
                        pos["market_value"] = cost
                        pos["profit_loss"] = 0
                        pos["profit_loss_rate"] = 0
            except Exception as e:
                logger.warning(f"⚠️ 获取行情失败，使用成本计算: {e}")
                for pos in positions_with_value:
                    pos["current_price"] = None
                    pos["market_value"] = pos["cost"]
                    pos["profit_loss"] = 0
                    pos["profit_loss_rate"] = 0

            profit_loss_rate = (total_profit_loss / total_cost * 100) if total_cost > 0 else 0

            return {
                "total_positions": len(positions),
                "total_cost": round(total_cost, 2),
                "total_market_value": round(total_market_value, 2),
                "total_quantity": total_quantity,
                "total_profit_loss": round(total_profit_loss, 2),
                "profit_loss_rate": round(profit_loss_rate, 2),
                "positions": positions_with_value
            }

        except Exception as e:
            logger.error(f"❌ 获取持仓汇总失败: {e}", exc_info=True)
            raise Exception(f"获取持仓汇总失败: {str(e)}")


# 创建全局实例
portfolio_service = PortfolioService()
