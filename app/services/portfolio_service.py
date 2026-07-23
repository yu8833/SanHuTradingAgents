"""
持仓追踪服务
提供持仓的增删改查、批量导入和汇总统计功能。
支持散户策略绑定、止盈止损价、持仓状态机、平仓记录。
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from bson import ObjectId

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


class Position(BaseModel):
    """持仓数据模型"""
    id: Optional[str] = None
    user_id: str
    symbol: str                      # 股票代码，如 "600519.SH"
    stock_name: str                  # 股票名称，如 "贵州茅台"
    quantity: int                    # 持股数量
    cost_price: float                # 成本价
    position_ratio: float            # 仓位占比 (0-1)
    buy_date: str                    # 买入日期
    notes: Optional[str] = None      # 备注
    # 散户策略扩展字段
    strategy: Optional[str] = "default"  # 策略类型（extreme_reversal/turnaround/small_cap_value/convertible_arbitrage/default）
    stop_loss_price: Optional[float] = None   # 止损价（买入时锁定）
    take_profit_price: Optional[float] = None  # 止盈价
    thesis: Optional[str] = None     # 投资逻辑（用于判断 thesis 证伪）
    status: Optional[str] = "open"   # 持仓状态（open/closed）
    exit_price: Optional[float] = None   # 平仓价
    exit_date: Optional[str] = None     # 平仓日期
    exit_reason: Optional[str] = None   # 平仓原因
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionUpdate(BaseModel):
    """持仓更新模型"""
    quantity: Optional[int] = None
    cost_price: Optional[float] = None
    position_ratio: Optional[float] = None
    notes: Optional[str] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    thesis: Optional[str] = None


class PortfolioService:
    """持仓追踪服务类"""

    def __init__(self):
        self.db = None
        self.collection_name = "user_positions"

    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _serialize_position(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """序列化持仓文档"""
        if doc is None:
            return None
        result = dict(doc)
        if "_id" in result:
            result["id"] = str(result["_id"])
            del result["_id"]
        if "created_at" in result and isinstance(result["created_at"], datetime):
            result["created_at"] = result["created_at"].isoformat()
        if "updated_at" in result and isinstance(result["updated_at"], datetime):
            result["updated_at"] = result["updated_at"].isoformat()
        return result

    async def create_position(self, position: Position) -> Position:
        """
        添加持仓

        Args:
            position: 持仓数据

        Returns:
            创建后的持仓对象
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            now = datetime.utcnow()
            doc = {
                "user_id": position.user_id,
                "symbol": position.symbol,
                "stock_name": position.stock_name,
                "quantity": position.quantity,
                "cost_price": position.cost_price,
                "position_ratio": position.position_ratio,
                "buy_date": position.buy_date,
                "notes": position.notes,
                "strategy": position.strategy or "default",
                "stop_loss_price": position.stop_loss_price,
                "take_profit_price": position.take_profit_price,
                "thesis": position.thesis,
                "status": "open",
                "exit_price": None,
                "exit_date": None,
                "exit_reason": None,
                "created_at": now,
                "updated_at": now
            }

            result = await collection.insert_one(doc)
            doc["_id"] = result.inserted_id

            logger.info(f"✅ 创建持仓成功: user_id={position.user_id}, symbol={position.symbol}")
            return self._serialize_position(doc)

        except Exception as e:
            logger.error(f"❌ 创建持仓失败: {e}", exc_info=True)
            raise Exception(f"创建持仓失败: {str(e)}")

    async def get_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """
        获取用户所有持仓

        Args:
            user_id: 用户ID

        Returns:
            持仓列表
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            cursor = collection.find({"user_id": user_id}).sort("created_at", -1)
            positions = await cursor.to_list(length=None)

            return [self._serialize_position(p) for p in positions]

        except Exception as e:
            logger.error(f"❌ 获取持仓列表失败: {e}", exc_info=True)
            raise Exception(f"获取持仓列表失败: {str(e)}")

    async def update_position(self, position_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        更新持仓

        Args:
            position_id: 持仓ID
            updates: 更新字段字典

        Returns:
            更新后的持仓对象
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            # 过滤不允许更新的字段
            allowed_fields = {"quantity", "cost_price", "position_ratio", "notes",
                              "stop_loss_price", "take_profit_price", "thesis"}
            filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

            if not filtered_updates:
                # 没有有效更新字段，返回当前持仓
                doc = await collection.find_one({"_id": ObjectId(position_id)})
                return self._serialize_position(doc)

            filtered_updates["updated_at"] = datetime.utcnow()

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
        """
        删除持仓

        Args:
            position_id: 持仓ID

        Returns:
            是否删除成功
        """
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
        exit_date: Optional[str] = None,
        exit_reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        平仓（不删除记录，标记为closed，保留历史用于策略表现统计）

        Args:
            position_id: 持仓ID
            exit_price: 平仓价
            exit_date: 平仓日期（默认今天）
            exit_reason: 平仓原因

        Returns:
            更新后的持仓对象
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            if exit_date is None:
                exit_date = datetime.now().strftime("%Y-%m-%d")

            updates = {
                "status": "closed",
                "exit_price": exit_price,
                "exit_date": exit_date,
                "exit_reason": exit_reason,
                "updated_at": datetime.utcnow()
            }

            result = await collection.find_one_and_update(
                {"_id": ObjectId(position_id), "status": "open"},
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

    async def get_open_positions(self, user_id: str) -> List[Dict[str, Any]]:
        """获取用户所有未平仓持仓（status=open）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]
            cursor = collection.find(
                {"user_id": user_id, "status": "open"}
            ).sort("created_at", -1)
            positions = await cursor.to_list(length=None)
            return [self._serialize_position(p) for p in positions]
        except Exception as e:
            logger.error(f"❌ 获取未平仓持仓失败: {e}", exc_info=True)
            raise Exception(f"获取未平仓持仓失败: {str(e)}")

    async def get_positions_by_strategy(
        self, user_id: str, strategy: str
    ) -> List[Dict[str, Any]]:
        """按策略类型获取持仓"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]
            cursor = collection.find(
                {"user_id": user_id, "strategy": strategy, "status": "open"}
            ).sort("created_at", -1)
            positions = await cursor.to_list(length=None)
            return [self._serialize_position(p) for p in positions]
        except Exception as e:
            logger.error(f"❌ 按策略获取持仓失败: {e}", exc_info=True)
            raise Exception(f"按策略获取持仓失败: {str(e)}")

    async def get_closed_positions(
        self, user_id: str, strategy: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取已平仓持仓（用于策略表现统计）"""
        try:
            db = await self._get_db()
            collection = db[self.collection_name]
            query = {"user_id": user_id, "status": "closed"}
            if strategy:
                query["strategy"] = strategy
            cursor = collection.find(query).sort("exit_date", -1)
            positions = await cursor.to_list(length=None)
            return [self._serialize_position(p) for p in positions]
        except Exception as e:
            logger.error(f"❌ 获取已平仓持仓失败: {e}", exc_info=True)
            raise Exception(f"获取已平仓持仓失败: {str(e)}")

    async def get_strategy_performance(
        self, user_id: str, strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取策略表现统计（胜率/盈亏比/平均收益等）
        用于反馈到仓位管理的 win_rate/profit_loss_ratio 参数
        """
        try:
            closed = await self.get_closed_positions(user_id, strategy)
            if not closed:
                return {
                    "strategy": strategy or "all",
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_loss_ratio": 0,
                    "avg_return": 0,
                }

            returns = []
            for p in closed:
                if p.get("exit_price") and p.get("cost_price") and p["cost_price"] > 0:
                    ret = (p["exit_price"] - p["cost_price"]) / p["cost_price"]
                    returns.append(ret)

            if not returns:
                return {
                    "strategy": strategy or "all",
                    "total_trades": 0,
                    "win_rate": 0,
                    "avg_win": 0,
                    "avg_loss": 0,
                    "profit_loss_ratio": 0,
                    "avg_return": 0,
                }

            import numpy as np
            winning = [r for r in returns if r > 0]
            losing = [r for r in returns if r <= 0]
            win_rate = len(winning) / len(returns)
            avg_win = float(np.mean(winning)) if winning else 0
            avg_loss = float(np.mean(losing)) if losing else 0
            pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

            return {
                "strategy": strategy or "all",
                "total_trades": len(returns),
                "win_rate": round(win_rate, 4),
                "avg_win": round(avg_win, 4),
                "avg_loss": round(avg_loss, 4),
                "profit_loss_ratio": round(pl_ratio, 4),
                "avg_return": round(float(np.mean(returns)), 4),
            }
        except Exception as e:
            logger.error(f"❌ 获取策略表现失败: {e}", exc_info=True)
            raise Exception(f"获取策略表现失败: {str(e)}")

    async def import_positions(self, positions: List[Position]) -> int:
        """
        批量导入持仓

        Args:
            positions: 持仓列表

        Returns:
            成功导入的数量
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            if not positions:
                return 0

            now = datetime.utcnow()
            docs = []
            for position in positions:
                docs.append({
                    "user_id": position.user_id,
                    "symbol": position.symbol,
                    "stock_name": position.stock_name,
                    "quantity": position.quantity,
                    "cost_price": position.cost_price,
                    "position_ratio": position.position_ratio,
                    "buy_date": position.buy_date,
                    "notes": position.notes,
                    "strategy": position.strategy or "default",
                    "stop_loss_price": position.stop_loss_price,
                    "take_profit_price": position.take_profit_price,
                    "thesis": position.thesis,
                    "status": "open",
                    "exit_price": None,
                    "exit_date": None,
                    "exit_reason": None,
                    "created_at": now,
                    "updated_at": now
                })

            result = await collection.insert_many(docs)
            success_count = len(result.inserted_ids)

            logger.info(f"✅ 批量导入持仓成功: 成功{success_count}条")
            return success_count

        except Exception as e:
            logger.error(f"❌ 批量导入持仓失败: {e}", exc_info=True)
            raise Exception(f"批量导入持仓失败: {str(e)}")

    async def get_position_summary(self, user_id: str) -> Dict[str, Any]:
        """
        获取持仓汇总

        Args:
            user_id: 用户ID

        Returns:
            汇总信息，包括持仓数量、总成本、市值、盈亏等
        """
        try:
            db = await self._get_db()
            collection = db[self.collection_name]

            # 获取用户所有持仓
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

            # 计算汇总数据
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

            # 获取实时行情计算市值和盈亏
            total_market_value = 0.0
            total_profit_loss = 0.0

            try:
                from app.services.quotes_service import get_quotes_service
                quotes_service = get_quotes_service()

                # 批量获取行情
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

            # 计算总盈亏率
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
