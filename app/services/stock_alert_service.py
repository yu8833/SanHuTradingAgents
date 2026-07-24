"""
个股预警服务

支持价格预警（突破/跌破阈值）和涨跌幅预警。
预警规则存储在 stock_alerts 集合，由 scheduler 定时检查并触发通知。
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from bson import ObjectId

from app.core.database import get_mongo_db
from app.services.notifications_service import get_notifications_service
from app.models.notification import NotificationCreate

logger = logging.getLogger(__name__)


# 预警类型
ALERT_TYPE_PRICE_ABOVE = "price_above"       # 价格上穿
ALERT_TYPE_PRICE_BELOW = "price_below"       # 价格下穿
ALERT_TYPE_PCT_UP = "pct_up"                 # 日涨幅超过
ALERT_TYPE_PCT_DOWN = "pct_down"             # 日跌幅超过
ALERT_TYPE_VOLUME_SURGE = "volume_surge"     # 成交量放大
ALERT_TYPE_TURNOVER_HIGH = "turnover_high"   # 换手率超
ALERT_TYPE_AMPLITUDE_HIGH = "amplitude_high" # 振幅超
ALERT_TYPE_CONSECUTIVE_UP = "consecutive_up" # 连涨天数
ALERT_TYPE_CONSECUTIVE_DOWN = "consecutive_down" # 连跌天数


class AlertRule(BaseModel):
    """预警规则"""
    id: Optional[str] = None
    user_id: str
    code: str                    # 股票代码
    stock_name: str = ""
    alert_type: str              # price_above/price_below/pct_up/pct_down
    threshold: float             # 阈值（价格或百分比）
    note: Optional[str] = None
    enabled: bool = True
    triggered: bool = False      # 是否已触发（触发后置true，避免重复推送；重置后可再次触发）
    triggered_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AlertRuleCreate(BaseModel):
    code: str
    stock_name: str = ""
    alert_type: str = Field(..., description="price_above/price_below/pct_up/pct_down")
    threshold: float
    note: Optional[str] = None


class AlertRuleUpdate(BaseModel):
    threshold: Optional[float] = None
    note: Optional[str] = None
    enabled: Optional[bool] = None
    triggered: Optional[bool] = None  # 手动重置时设为 False


class StockAlertService:
    """个股预警服务"""

    def __init__(self):
        self.db = None
        self.collection_name = "stock_alerts"

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    def _serialize(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        if doc is None:
            return None
        result = dict(doc)
        if "_id" in result:
            result["id"] = str(result["_id"])
            del result["_id"]
        return result

    async def create_alert(self, user_id: str, rule: AlertRuleCreate) -> Dict[str, Any]:
        """创建预警规则"""
        try:
            db = await self._get_db()
            now_iso = datetime.utcnow().isoformat()
            doc = {
                "user_id": user_id,
                "code": rule.code,
                "stock_name": rule.stock_name,
                "alert_type": rule.alert_type,
                "threshold": rule.threshold,
                "note": rule.note,
                "enabled": True,
                "triggered": False,
                "triggered_at": None,
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            result = await db[self.collection_name].insert_one(doc)
            doc["_id"] = result.inserted_id
            logger.info(f"✅ 创建预警: user={user_id}, code={rule.code}, type={rule.alert_type}")
            return self._serialize(doc)
        except Exception as e:
            logger.error(f"❌ 创建预警失败: {e}", exc_info=True)
            raise

    async def get_alerts(self, user_id: str, code: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取用户的预警规则"""
        try:
            db = await self._get_db()
            query: Dict[str, Any] = {"user_id": user_id}
            if code:
                query["code"] = code
            cursor = db[self.collection_name].find(query).sort("created_at", -1)
            docs = await cursor.to_list(length=None)
            return [self._serialize(d) for d in docs]
        except Exception as e:
            logger.error(f"❌ 获取预警列表失败: {e}", exc_info=True)
            raise

    async def update_alert(self, alert_id: str, updates: AlertRuleUpdate) -> Optional[Dict[str, Any]]:
        """更新预警规则"""
        try:
            db = await self._get_db()
            filtered = {k: v for k, v in updates.model_dump(exclude_none=True).items() if v is not None}
            if not filtered:
                doc = await db[self.collection_name].find_one({"_id": ObjectId(alert_id)})
                return self._serialize(doc)
            filtered["updated_at"] = datetime.utcnow().isoformat()
            result = await db[self.collection_name].find_one_and_update(
                {"_id": ObjectId(alert_id)},
                {"$set": filtered},
                return_document=True,
            )
            return self._serialize(result)
        except Exception as e:
            logger.error(f"❌ 更新预警失败: {e}", exc_info=True)
            raise

    async def delete_alert(self, alert_id: str) -> bool:
        """删除预警规则"""
        try:
            db = await self._get_db()
            result = await db[self.collection_name].delete_one({"_id": ObjectId(alert_id)})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"❌ 删除预警失败: {e}", exc_info=True)
            raise

    async def check_and_trigger(self):
        """
        定时检查所有启用的预警规则，触发条件时推送通知。

        逻辑：
        1. 获取所有 enabled=True 且 triggered=False 的规则
        2. 按 code 分组，批量获取最新价/涨跌幅
        3. 逐条检查是否满足触发条件
        4. 满足则推送通知并标记 triggered=True
        """
        try:
            db = await self._get_db()
            cursor = db[self.collection_name].find({
                "enabled": True,
                "triggered": False,
            })
            rules = await cursor.to_list(length=None)
            if not rules:
                return

            # 按 code 分组
            code_set = set(r["code"] for r in rules)
            prices = await self._batch_get_prices(list(code_set))
            if not prices:
                logger.warning("预警检查：无法获取行情数据")
                return

            notif_service = get_notifications_service()
            triggered_count = 0

            for rule in rules:
                code = rule["code"]
                price_info = prices.get(code)
                if not price_info:
                    continue

                current_price = price_info.get("close")
                pct_chg = price_info.get("pct_chg")
                if current_price is None or current_price <= 0:
                    continue

                alert_type = rule["alert_type"]
                threshold = rule["threshold"]
                should_trigger = False
                desc = ""

                if alert_type == ALERT_TYPE_PRICE_ABOVE and current_price >= threshold:
                    should_trigger = True
                    desc = f"价格上穿阈值：现价 {current_price:.2f} ≥ {threshold:.2f}"
                elif alert_type == ALERT_TYPE_PRICE_BELOW and current_price <= threshold:
                    should_trigger = True
                    desc = f"价格下穿阈值：现价 {current_price:.2f} ≤ {threshold:.2f}"
                elif alert_type == ALERT_TYPE_PCT_UP and pct_chg is not None and pct_chg >= threshold:
                    should_trigger = True
                    desc = f"日涨幅超阈值：{pct_chg:.2f}% ≥ {threshold:.2f}%"
                elif alert_type == ALERT_TYPE_PCT_DOWN and pct_chg is not None and pct_chg <= -threshold:
                    should_trigger = True
                    desc = f"日跌幅超阈值：{pct_chg:.2f}% ≤ -{threshold:.2f}%"
                elif alert_type == ALERT_TYPE_VOLUME_SURGE:
                    # 成交量放大：需要近5日均量数据
                    vol = price_info.get("volume", 0)
                    avg_vol_5 = price_info.get("avg_volume_5", 0)
                    if avg_vol_5 > 0 and vol > 0:
                        vol_ratio = vol / avg_vol_5
                        if vol_ratio >= threshold:
                            should_trigger = True
                            desc = f"成交量放大：今日{vol:.0f} / 5日均量{avg_vol_5:.0f} = {vol_ratio:.1f}倍 ≥ {threshold:.1f}倍"
                elif alert_type == ALERT_TYPE_TURNOVER_HIGH:
                    turnover = price_info.get("turnover_rate", 0)
                    if turnover is not None and turnover >= threshold:
                        should_trigger = True
                        desc = f"换手率超阈值：{turnover:.2f}% ≥ {threshold:.2f}%"
                elif alert_type == ALERT_TYPE_AMPLITUDE_HIGH:
                    amplitude = price_info.get("amplitude", 0)
                    if amplitude is not None and amplitude >= threshold:
                        should_trigger = True
                        desc = f"振幅超阈值：{amplitude:.2f}% ≥ {threshold:.2f}%"
                elif alert_type in (ALERT_TYPE_CONSECUTIVE_UP, ALERT_TYPE_CONSECUTIVE_DOWN):
                    # 连涨/连跌：需要历史K线数据
                    consecutive_days = price_info.get("consecutive_days", 0)
                    if alert_type == ALERT_TYPE_CONSECUTIVE_UP and consecutive_days > 0 and consecutive_days >= threshold:
                        should_trigger = True
                        desc = f"连续上涨：已连涨{consecutive_days}天 ≥ {threshold:.0f}天"
                    elif alert_type == ALERT_TYPE_CONSECUTIVE_DOWN and consecutive_days < 0 and abs(consecutive_days) >= threshold:
                        should_trigger = True
                        desc = f"连续下跌：已连跌{abs(consecutive_days)}天 ≥ {threshold:.0f}天"

                if not should_trigger:
                    continue

                # 推送通知
                stock_name = rule.get("stock_name", code)
                title = f"【预警触发】{stock_name} {code}"
                content = desc
                if rule.get("note"):
                    content += f"\n备注: {rule['note']}"

                try:
                    await notif_service.create_and_publish(
                        payload=NotificationCreate(
                            user_id=rule["user_id"],
                            type="alert",
                            title=title,
                            content=content,
                            link=f"/stocks/{code}",
                            source="stock_alert",
                            severity="warning",
                            metadata={
                                "code": code,
                                "alert_type": alert_type,
                                "threshold": threshold,
                                "current_price": current_price,
                                "pct_chg": pct_chg,
                                "alert_id": str(rule["_id"]),
                            },
                        )
                    )
                    triggered_count += 1
                except Exception as e:
                    logger.error(f"推送预警通知失败 code={code}: {e}")

                # 标记已触发
                await db[self.collection_name].update_one(
                    {"_id": rule["_id"]},
                    {"$set": {
                        "triggered": True,
                        "triggered_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat(),
                    }}
                )

            if triggered_count > 0:
                logger.info(f"✅ 预警检查完成: 检查 {len(rules)} 条规则, 触发 {triggered_count} 条")

        except Exception as e:
            logger.error(f"❌ 预警检查失败: {e}", exc_info=True)

    async def _batch_get_prices(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """批量获取股票最新价和涨跌幅"""
        if not codes:
            return {}
        try:
            from app.services.quotes_service import get_quotes_service
            quotes = await get_quotes_service().get_quotes(codes)
            result = {}
            for code, q in quotes.items():
                close = q.get("close")
                pct_chg = q.get("pct_chg")
                if close is None:
                    # 兼容字段
                    close = q.get("price") or q.get("current_price")
                result[code] = {"close": close, "pct_chg": pct_chg}
            return result
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
            return {}


# 全局实例
stock_alert_service = StockAlertService()
