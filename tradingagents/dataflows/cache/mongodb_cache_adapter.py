"""MongoDB 缓存适配器 - 真实实现

提供K线数据、股票基础信息、财务数据和新闻的MongoDB缓存能力。
优先从缓存读取，避免每次都调用外部API导致超时。
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import pandas as pd

logger = logging.getLogger(__name__)


class MongoCacheAdapter:
    """真实的 MongoDB 缓存适配器"""

    def __init__(self):
        self._db = None

    @property
    def db(self):
        """惰性获取MongoDB同步连接"""
        if self._db is None:
            try:
                from app.core.database import get_mongo_db_sync
                self._db = get_mongo_db_sync()
            except Exception as e:
                logger.warning(f"⚠️ 获取MongoDB同步连接失败: {e}")
                return None
        return self._db

    def get_historical_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        period: str = "daily"
    ) -> Optional[pd.DataFrame]:
        """
        从MongoDB缓存获取历史K线数据

        Args:
            code: 股票代码（6位数字）
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            period: daily/weekly/monthly/5min/15min/30min/60min

        Returns:
            DataFrame or None
        """
        if self.db is None:
            return None

        try:
            # 确定集合名称
            collection_map = {
                "daily": "stock_daily_data",
                "weekly": "stock_weekly_data",
                "monthly": "stock_monthly_data",
                "5min": "stock_5min_data",
                "15min": "stock_15min_data",
                "30min": "stock_30min_data",
                "60min": "stock_60min_data",
            }
            coll_name = collection_map.get(period, "stock_daily_data")
            coll = self.db[coll_name]

            # 构建查询条件
            query = {
                "code": str(code).zfill(6),
                "trade_date": {"$gte": start_date, "$lte": end_date}
            }

            # 尝试查询
            cursor = coll.find(query).sort("trade_date", 1)
            records = list(cursor)

            if not records:
                # 尝试其他字段名
                query2 = {
                    "symbol": str(code).zfill(6),
                    "trade_date": {"$gte": start_date, "$lte": end_date}
                }
                cursor = coll.find(query2).sort("trade_date", 1)
                records = list(cursor)

            if not records:
                # 尝试 date 字段
                query3 = {
                    "code": str(code).zfill(6),
                    "date": {"$gte": start_date, "$lte": end_date}
                }
                cursor = coll.find(query3).sort("date", 1)
                records = list(cursor)

            if not records:
                logger.info(f"📊 MongoDB缓存无K线数据: {code}, period={period}")
                return None

            # 转换为DataFrame
            df = pd.DataFrame(records)

            # 标准化列名
            column_map = {
                "trade_date": "trade_date",
                "date": "trade_date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
                "vol": "volume",
                "amount": "amount",
                "turnover_rate": "turnover_rate",
                "pct_chg": "pct_chg",
                "change": "pct_chg",
            }

            # 重命名列
            for old, new in column_map.items():
                if old in df.columns and new not in df.columns:
                    df = df.rename(columns={old: new})

            # 确保必要字段存在
            required = ["open", "high", "low", "close"]
            for col in required:
                if col not in df.columns:
                    logger.warning(f"⚠️ MongoDB K线数据缺少字段: {col}")
                    return None

            # 转换数值
            for col in ["open", "high", "low", "close", "volume", "amount"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            logger.info(f"✅ MongoDB缓存命中: {code}, period={period}, {len(df)}条")
            return df

        except Exception as e:
            logger.error(f"❌ MongoDB获取K线数据失败: {e}")
            return None

    def save_historical_data(
        self,
        code: str,
        period: str,
        items: List[Dict],
        source: str = "akshare"
    ) -> bool:
        """
        保存K线数据到MongoDB缓存

        Args:
            code: 股票代码
            period: daily/weekly/monthly/5min等
            items: K线数据列表
            source: 数据来源

        Returns:
            bool: 是否保存成功
        """
        if self.db is None or not items:
            return False

        try:
            collection_map = {
                "daily": "stock_daily_data",
                "weekly": "stock_weekly_data",
                "monthly": "stock_monthly_data",
                "5min": "stock_5min_data",
                "15min": "stock_15min_data",
                "30min": "stock_30min_data",
                "60min": "stock_60min_data",
            }
            coll_name = collection_map.get(period, "stock_daily_data")
            coll = self.db[coll_name]

            code6 = str(code).zfill(6)
            now = datetime.now()

            # 批量upsert
            from pymongo import UpdateOne
            operations = []
            for item in items:
                trade_date = str(item.get("time", item.get("trade_date", "")))
                if not trade_date:
                    continue

                doc = {
                    "code": code6,
                    "trade_date": trade_date,
                    "open": float(item.get("open", 0)),
                    "high": float(item.get("high", 0)),
                    "low": float(item.get("low", 0)),
                    "close": float(item.get("close", 0)),
                    "volume": float(item.get("volume", 0) or 0),
                    "amount": float(item.get("amount", 0) or 0),
                    "source": source,
                    "updated_at": now,
                }

                operations.append(UpdateOne(
                    {"code": code6, "trade_date": trade_date},
                    {"$set": doc},
                    upsert=True
                ))

            if operations:
                result = coll.bulk_write(operations)
                logger.info(f"✅ MongoDB缓存保存: {code}, period={period}, {len(operations)}条")
                return True

            return False

        except Exception as e:
            logger.error(f"❌ MongoDB保存K线数据失败: {e}")
            return False

    def get_stock_basic_info(self, code: str) -> Optional[Dict]:
        """获取股票基础信息"""
        if self.db is None:
            return None

        try:
            coll = self.db["stock_basic"]
            doc = coll.find_one({"code": str(code).zfill(6)})
            if not doc:
                doc = coll.find_one({"symbol": str(code).zfill(6)})
            return doc
        except Exception as e:
            logger.error(f"❌ MongoDB获取股票基础信息失败: {e}")
            return None

    def get_financial_data(self, code: str, report_type: str = "annual") -> Optional[pd.DataFrame]:
        """获取财务数据"""
        if self.db is None:
            return None

        try:
            coll = self.db["stock_financial_data"]
            query = {"code": str(code).zfill(6)}
            if report_type:
                query["report_type"] = report_type

            cursor = coll.find(query).sort("report_date", -1).limit(10)
            records = list(cursor)

            if not records:
                return None

            return pd.DataFrame(records)
        except Exception as e:
            logger.error(f"❌ MongoDB获取财务数据失败: {e}")
            return None

    def get_news(self, code: str, days: int = 30, limit: int = 50) -> List[Dict]:
        """从MongoDB获取缓存的新闻数据"""
        if self.db is None:
            return []

        try:
            coll = self.db["stock_news"]
            code6 = str(code).zfill(6)

            # 计算日期范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)

            query = {
                "symbol": code6,
                "publish_time": {"$gte": start_date.strftime("%Y-%m-%d")}
            }

            cursor = coll.find(query).sort("publish_time", -1).limit(limit)
            return list(cursor)
        except Exception as e:
            logger.error(f"❌ MongoDB获取新闻失败: {e}")
            return []


def get_mongodb_cache_adapter(*args, **kwargs) -> MongoCacheAdapter:
    """获取 MongoDB 缓存适配器"""
    return MongoCacheAdapter()
