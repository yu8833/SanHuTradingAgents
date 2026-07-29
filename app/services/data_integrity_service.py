"""
数据完整性检查与自动补数服务

核心功能：
1. 检查 stock_daily_quotes 中最新交易日的数据完整性
2. 识别缺失股票并用备用数据源自动补数
3. 记录完整性检查结果到 MongoDB
4. 提供API查询接口

调用时机：
- Tushare/AKShare 历史同步完成后自动触发
- 每天19:00定时执行兜底检查
- 手动通过API触发
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from app.core.database import get_mongo_db

logger = logging.getLogger(__name__)


class DataIntegrityService:
    """数据完整性检查与自动补数服务"""

    def __init__(self):
        self.db = None
        self.check_collection = "data_integrity_checks"

    async def _get_db(self):
        if self.db is None:
            self.db = get_mongo_db()
        return self.db

    async def check_historical_completeness(
        self,
        trade_date: Optional[str] = None,
        auto_remediate: bool = True,
        remediate_source: str = "akshare",
        remediate_batch_size: int = 50,
    ) -> Dict[str, Any]:
        """
        检查指定交易日的历史数据完整性，可选自动补数

        Args:
            trade_date: 交易日期 (YYYY-MM-DD)，None则自动检测最新交易日
            auto_remediate: 是否自动补数
            remediate_source: 补数数据源 ("akshare" / "tushare")
            remediate_batch_size: 补数批次大小

        Returns:
            检查结果字典
        """
        db = await self._get_db()
        result = {
            "check_time": datetime.utcnow().isoformat(),
            "trade_date": None,
            "expected_count": 0,
            "actual_count": 0,
            "missing_count": 0,
            "missing_codes": [],
            "remediated_count": 0,
            "remediation_errors": [],
            "status": "unknown",
        }

        try:
            # 1. 确定交易日期
            if not trade_date:
                trade_date = await self._get_latest_trade_date(db)
            if not trade_date:
                logger.warning("⚠️ 无法确定最新交易日，跳过完整性检查")
                result["status"] = "no_trade_date"
                return result

            result["trade_date"] = trade_date
            logger.info(f"🔍 开始检查 {trade_date} 的历史数据完整性...")

            # 2. 获取应同步的股票列表（与同步服务一致的过滤逻辑）
            expected_codes = await self._get_expected_stock_codes(db)
            result["expected_count"] = len(expected_codes)

            if not expected_codes:
                logger.warning("⚠️ stock_basic_info 中没有找到A股股票")
                result["status"] = "no_expected_stocks"
                return result

            # 3. 查询实际有数据的股票
            actual_cursor = db.stock_daily_quotes.distinct(
                "code",
                {"trade_date": trade_date, "period": "daily"}
            )
            actual_codes = set(await actual_cursor)
            result["actual_count"] = len(actual_codes)

            # 4. 计算缺失
            expected_set = set(expected_codes)
            missing_codes = list(expected_set - actual_codes)
            result["missing_count"] = len(missing_codes)
            result["missing_codes"] = missing_codes[:200]  # 最多记录200个

            completeness = (len(actual_codes) / len(expected_codes)) * 100 if expected_codes else 0
            logger.info(
                f"📊 完整性检查结果: {trade_date} - "
                f"期望 {len(expected_codes)} 只, 实际 {len(actual_codes)} 只, "
                f"缺失 {len(missing_codes)} 只, 完整度 {completeness:.1f}%"
            )

            # 5. 自动补数
            if auto_remediate and missing_codes:
                remediation_result = await self._remediate_missing(
                    missing_codes, trade_date, remediate_source, remediate_batch_size
                )
                result["remediated_count"] = remediation_result["success_count"]
                result["remediation_errors"] = remediation_result["errors"][:50]
            elif missing_codes:
                logger.info(f"ℹ️ 自动补数未启用，{len(missing_codes)} 只股票缺失数据")

            # 6. 确定状态
            if result["missing_count"] == 0:
                result["status"] = "complete"
            elif result["remediated_count"] > 0:
                remaining = result["missing_count"] - result["remediated_count"]
                result["status"] = "remediated" if remaining == 0 else "partial"
            else:
                result["status"] = "incomplete"

            # 7. 持久化检查结果
            await self._save_check_result(db, result)

            return result

        except Exception as e:
            logger.error(f"❌ 完整性检查失败: {e}", exc_info=True)
            result["status"] = "error"
            result["error"] = str(e)
            await self._save_check_result(db, result)
            return result

    async def _get_latest_trade_date(self, db) -> Optional[str]:
        """获取最新交易日（从 stock_daily_quotes 中查找最新的交易日期）"""
        try:
            pipeline = [
                {"$match": {"period": "daily"}},
                {"$group": {"_id": "$trade_date"}},
                {"$sort": {"_id": -1}},
                {"$limit": 1},
            ]
            cursor = db.stock_daily_quotes.aggregate(pipeline)
            docs = await cursor.to_list(length=1)
            if docs:
                return docs[0]["_id"]
        except Exception as e:
            logger.warning(f"获取最新交易日失败: {e}")

        # 回退：使用今天
        return datetime.now().strftime("%Y-%m-%d")

    async def _get_expected_stock_codes(self, db) -> List[str]:
        """获取应同步的A股股票代码列表（与同步服务一致）"""
        cursor = db.stock_basic_info.find(
            {
                "$and": [
                    {
                        "$or": [
                            {"market_info.market": "CN"},
                            {"category": "stock_cn"},
                            {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}},
                        ]
                    },
                    {
                        "$or": [
                            {"status": {"$ne": "D"}},
                            {"status": {"$exists": False}},
                        ]
                    },
                ]
            },
            {"code": 1},
        )
        return [doc["code"] async for doc in cursor]

    async def _remediate_missing(
        self,
        missing_codes: List[str],
        trade_date: str,
        source: str,
        batch_size: int,
    ) -> Dict[str, Any]:
        """
        对缺失数据的股票进行补数

        策略：
        - 优先使用 AKShare（不受Tushare限流影响）
        - 补数范围：缺失日期往前推30天到缺失日期
        - 分批处理，避免内存压力
        """
        result = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
        }

        if not missing_codes:
            return result

        logger.info(
            f"🔧 开始自动补数: {len(missing_codes)} 只股票, "
            f"日期={trade_date}, 数据源={source}"
        )

        # 计算补数日期范围（往前推30天确保覆盖）
        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except Exception:
            end_dt = datetime.now()
        start_date = (end_dt - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            if source == "akshare":
                from app.worker.akshare_sync_service import get_akshare_sync_service
                service = await get_akshare_sync_service()
            else:
                from app.worker.tushare_sync_service import get_tushare_sync_service
                service = await get_tushare_sync_service()

            # 分批补数
            for i in range(0, len(missing_codes), batch_size):
                batch = missing_codes[i:i + batch_size]
                try:
                    if source == "akshare":
                        batch_result = await service.sync_historical_data(
                            symbols=batch,
                            start_date=start_date,
                            end_date=trade_date,
                            incremental=False,
                        )
                    else:
                        batch_result = await service.sync_historical_data(
                            symbols=batch,
                            start_date=start_date,
                            end_date=trade_date,
                            incremental=False,
                        )

                    result["success_count"] += batch_result.get("success_count", 0)
                    result["error_count"] += batch_result.get("error_count", 0)
                    if batch_result.get("errors"):
                        result["errors"].extend(batch_result["errors"][:10])

                    logger.info(
                        f"📈 补数进度: {min(i + batch_size, len(missing_codes))}/{len(missing_codes)}, "
                        f"本批成功: {batch_result.get('success_count', 0)}"
                    )

                    # 批次间延迟，避免API限流
                    if i + batch_size < len(missing_codes):
                        await asyncio.sleep(1.0)

                except Exception as e:
                    logger.error(f"❌ 补数批次 {i}-{i+len(batch)} 失败: {e}")
                    result["error_count"] += len(batch)
                    result["errors"].append({"batch": f"{i}-{i+len(batch)}", "error": str(e)})

            logger.info(
                f"✅ 补数完成: 成功 {result['success_count']}/{len(missing_codes)}, "
                f"失败 {result['error_count']}"
            )

        except Exception as e:
            logger.error(f"❌ 补数服务初始化失败: {e}", exc_info=True)
            result["errors"].append({"error": f"补数服务初始化失败: {str(e)}"})

        return result

    async def _save_check_result(self, db, result: Dict):
        """保存检查结果到 MongoDB"""
        try:
            # 复制一份，避免修改原始引用
            save_doc = dict(result)
            # 确保 check_time 是字符串（MongoDB 也可以存 datetime，但读取时需处理）
            await db[self.check_collection].insert_one(save_doc)
        except Exception as e:
            logger.warning(f"保存完整性检查结果失败（不影响主流程）: {e}")

    async def get_latest_check_result(self) -> Optional[Dict]:
        """获取最近一次完整性检查结果"""
        try:
            db = await self._get_db()
            doc = await db[self.check_collection].find_one(
                {}, sort=[("check_time", -1)]
            )
            if doc:
                doc.pop("_id", None)
                # 确保 check_time 可序列化
                ct = doc.get("check_time")
                if isinstance(ct, datetime):
                    doc["check_time"] = ct.isoformat()
            return doc
        except Exception as e:
            logger.error(f"获取检查结果失败: {e}")
            return None


# 单例
_integrity_service: Optional[DataIntegrityService] = None


async def get_data_integrity_service() -> DataIntegrityService:
    global _integrity_service
    if _integrity_service is None:
        _integrity_service = DataIntegrityService()
    return _integrity_service
