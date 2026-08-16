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

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from app.utils.timezone import now_tz

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
        trade_date: str | None = None,
        auto_remediate: bool = True,
        remediate_source: str = "akshare",
        remediate_batch_size: int = 50,
        remediate_lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        检查指定交易日的历史数据完整性，可选自动补数

        Args:
            trade_date: 交易日期 (YYYY-MM-DD)，None则自动检测最新交易日
            auto_remediate: 是否自动补数
            remediate_source: 补数数据源 ("akshare" / "tushare" / "baostock")
            remediate_batch_size: 补数批次大小
            remediate_lookback_days: 补数回看天数（默认30天，可配置）

        Returns:
            检查结果字典
        """
        db = await self._get_db()
        result = {
            "check_time": now_tz().isoformat(),
            "trade_date": None,
            "expected_count": 0,
            "actual_count": 0,
            "missing_count": 0,
            "missing_codes": [],
            "remediated_count": 0,
            "remediation_errors": [],
            "source_coverage": {},
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

            # 统计各数据源的覆盖情况（用于诊断；actual_codes 不区分 source，
            # 因为补数的目标就是“有数据”即可，下游查询按优先级去重）
            source_stats = {}
            for src in ["tushare", "akshare", "baostock"]:
                src_count = len(await db.stock_daily_quotes.distinct(
                    "code",
                    {"trade_date": trade_date, "period": "daily", "data_source": src}
                ))
                source_stats[src] = src_count
            result["source_coverage"] = source_stats

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
                    missing_codes,
                    trade_date,
                    remediate_source,
                    remediate_batch_size,
                    lookback_days=remediate_lookback_days,
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

    async def _get_latest_trade_date(self, db) -> str | None:
        """获取最新交易日（从 stock_daily_quotes 中查找最新的交易日期）

        空库或异常时返回 None，不回退到今天，避免周末/节假日触发全量误报。
        """
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
            return None

        # 空库时返回 None，让调用方跳过检查
        logger.warning("⚠️ stock_daily_quotes 为空，无法确定最新交易日")
        return None

    async def _get_expected_stock_codes(self, db) -> list[str]:
        """获取应同步的A股股票代码列表（与同步服务一致），按 code 去重"""
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
        # 使用 set 去重：stock_basic_info 按 code + source 存三源，需要按 code 唯一
        unique_codes: set = set()
        async for doc in cursor:
            c = doc.get("code")
            if c:
                unique_codes.add(c)
        return sorted(unique_codes)

    async def _remediate_missing(
        self,
        missing_codes: list[str],
        trade_date: str,
        source: str,
        batch_size: int,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        对缺失数据的股票进行补数

        策略：
        - 优先使用配置的源（akshare/tushare/baostock）
        - 补数范围：缺失日期往前推 lookback_days 天到缺失日期
        - 分批处理，避免内存压力
        - 失败批次重试一次
        - 补数源初始化或同步失败时，自动降级到下一个源：
            akshare   → tushare
            baostock  → akshare → tushare
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
            f"日期={trade_date}, 数据源={source}, 回看天数={lookback_days}"
        )

        # 计算补数日期范围（往前推 lookback_days 天确保覆盖）
        try:
            end_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        except Exception:
            end_dt = now_tz()
        start_date = (end_dt - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # 构建降级链：先尝试配置的源，失败则依次降级
        remediate_sources = [source]
        if source == "akshare":
            remediate_sources.extend(["tushare"])  # akshare 失败降级到 tushare
        elif source == "baostock":
            remediate_sources.extend(["akshare", "tushare"])  # baostock → akshare → tushare

        remaining_codes = list(missing_codes)

        for src in remediate_sources:
            if not remaining_codes:
                break

            # 初始化补数服务（失败则降级到下一个源）
            try:
                service = await self._get_sync_service(src)
            except Exception as e:
                logger.warning(f"⚠️ 补数源 {src} 初始化失败: {e}，尝试降级...")
                result["errors"].append({"source": src, "error": f"初始化失败: {str(e)}"})
                continue

            logger.info(f"🔄 使用 {src} 源补数: {len(remaining_codes)} 只股票")
            src_result = await self._run_remediation_batches(
                src, service, remaining_codes, start_date, trade_date, batch_size, lookback_days
            )

            result["success_count"] += src_result["success_count"]
            result["error_count"] += src_result["error_count"]
            if src_result["errors"]:
                result["errors"].extend(src_result["errors"][:50])

            # 仍有失败的股票 → 降级到下一个源
            if src_result["failed_codes"]:
                remaining_codes = src_result["failed_codes"]
                if src != remediate_sources[-1]:
                    logger.warning(
                        f"⚠️ 源 {src} 有 {len(remaining_codes)} 只股票补数失败，尝试降级到下一个源..."
                    )
            else:
                remaining_codes = []
                break  # 全部成功，不再降级

        logger.info(
            f"✅ 补数完成: 成功 {result['success_count']}/{len(missing_codes)}, "
            f"失败 {result['error_count']}"
        )

        return result

    async def _get_sync_service(self, source: str):
        """获取对应数据源的同步服务（已初始化）"""
        if source == "akshare":
            from app.worker.akshare_sync_service import get_akshare_sync_service
            return await get_akshare_sync_service()
        elif source == "baostock":
            # baostock_sync_service 暂无单例获取函数，直接实例化并异步初始化
            from app.worker.baostock_sync_service import BaoStockSyncService
            service = BaoStockSyncService()
            await service.initialize()
            return service
        else:  # tushare
            from app.worker.tushare_sync_service import get_tushare_sync_service
            return await get_tushare_sync_service()

    async def _sync_one_batch(
        self,
        source: str,
        service,
        batch: list[str],
        start_date: str,
        end_date: str,
        lookback_days: int,
    ) -> dict[str, Any]:
        """执行单批次补数，归一化不同数据源接口差异

        - akshare/tushare: 调用 sync_historical_data(symbols, start_date, end_date, incremental)
        - baostock: 调用 _sync_historical_batch(code_batch, days, end_date, period, incremental)
                   （其 sync_historical_data 不接受 symbols 参数）
        """
        if source == "baostock":
            stats = await service._sync_historical_batch(
                code_batch=batch,
                days=lookback_days,
                end_date=end_date,
                period="daily",
                incremental=False,
            )
            # BaoStockSyncStats: historical_records, errors(list[str])
            error_count = len(stats.errors)
            success_count = max(0, len(batch) - error_count)
            return {
                "success_count": success_count,
                "error_count": error_count,
                "errors": [{"error": e} for e in stats.errors[:10]],
            }

        # akshare / tushare 接口一致
        batch_result = await service.sync_historical_data(
            symbols=batch,
            start_date=start_date,
            end_date=end_date,
            incremental=False,
        )
        return {
            "success_count": batch_result.get("success_count", 0),
            "error_count": batch_result.get("error_count", 0),
            "errors": batch_result.get("errors", []),
        }

    async def _run_remediation_batches(
        self,
        source: str,
        service,
        codes: list[str],
        start_date: str,
        end_date: str,
        batch_size: int,
        lookback_days: int,
    ) -> dict[str, Any]:
        """对给定股票列表分批补数，并对失败批次重试一次

        Returns:
            含 success_count / error_count / errors / failed_codes 的字典；
            failed_codes 为重试后仍失败的股票，供上层降级使用。
        """
        result = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
            "failed_codes": [],
        }

        failed_codes: list[str] = []

        # 主循环：分批补数
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            try:
                batch_result = await self._sync_one_batch(
                    source, service, batch, start_date, end_date, lookback_days
                )
                result["success_count"] += batch_result["success_count"]
                result["error_count"] += batch_result["error_count"]
                if batch_result["errors"]:
                    result["errors"].extend(batch_result["errors"][:10])

                logger.info(
                    f"📈 补数进度: {min(i + batch_size, len(codes))}/{len(codes)}, "
                    f"本批成功: {batch_result['success_count']}"
                )

                # 批次间延迟，避免API限流
                if i + batch_size < len(codes):
                    await asyncio.sleep(1.0)

            except Exception as e:
                logger.error(f"❌ 补数批次 {i}-{i+len(batch)} 失败: {e}")
                failed_codes.extend(batch)
                result["errors"].append({"batch": f"{i}-{i+len(batch)}", "error": str(e)})

        # 对失败的股票进行一次重试
        if failed_codes:
            logger.info(f"🔄 对 {len(failed_codes)} 只失败的股票进行重试...")
            for i in range(0, len(failed_codes), batch_size):
                batch = failed_codes[i:i + batch_size]
                try:
                    batch_result = await self._sync_one_batch(
                        source, service, batch, start_date, end_date, lookback_days
                    )
                    result["success_count"] += batch_result["success_count"]
                    result["error_count"] += batch_result["error_count"]
                    if batch_result["errors"]:
                        result["errors"].extend(batch_result["errors"][:10])
                except Exception as e:
                    logger.error(f"❌ 重试批次 {i}-{i+len(batch)} 仍失败: {e}")
                    # 重试仍失败：计入 error_count 并交给上层降级
                    result["failed_codes"].extend(batch)
                    result["error_count"] += len(batch)
                    result["errors"].append(
                        {"batch": f"retry-{i}-{i+len(batch)}", "error": str(e)}
                    )

        return result

    async def _save_check_result(self, db, result: dict):
        """保存检查结果到 MongoDB"""
        try:
            # 复制一份，避免修改原始引用
            save_doc = dict(result)
            # 确保 check_time 是字符串（MongoDB 也可以存 datetime，但读取时需处理）
            await db[self.check_collection].insert_one(save_doc)
        except Exception as e:
            logger.warning(f"保存完整性检查结果失败（不影响主流程）: {e}")

    async def get_latest_check_result(self) -> dict | None:
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
_integrity_service: DataIntegrityService | None = None


async def get_data_integrity_service() -> DataIntegrityService:
    global _integrity_service
    if _integrity_service is None:
        _integrity_service = DataIntegrityService()
    return _integrity_service
