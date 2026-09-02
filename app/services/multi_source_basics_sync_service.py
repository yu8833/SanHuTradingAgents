"""
Multi-source stock basics synchronization service
- Supports multiple data sources with fallback mechanism
- Priority: Tushare > AKShare > BaoStock 
- Fetches A-share stock basic info with extended financial metrics
- Upserts into MongoDB collection `stock_basic_info`
- Provides unified interface for different data sources
"""
from __future__ import annotations
from app.utils.timezone import now_tz, to_config_tz

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from app.core.database import get_mongo_db
from app.models.stock_models import StockBasicInfoDB, detect_db_extra_fields
from app.services.basics_sync import add_financial_metrics as _add_financial_metrics_util

logger = logging.getLogger(__name__)

# Collection names
COLLECTION_NAME = "stock_basic_info"
STATUS_COLLECTION = "sync_status"
JOB_KEY = "stock_basics_multi_source"


class DataSourcePriority(Enum):
    """数据源优先级枚举"""
    TUSHARE = 1
    AKSHARE = 2
    BAOSTOCK = 3


@dataclass
class SyncStats:
    """同步统计信息"""
    job: str = JOB_KEY
    data_type: str = "stock_basics"  # 添加data_type字段以符合数据库索引要求
    status: str = "idle"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total: int = 0
    inserted: int = 0
    updated: int = 0
    errors: int = 0
    last_trade_date: str | None = None
    data_sources_used: list[str] = field(default_factory=list)
    source_stats: dict[str, dict[str, int]] = field(default_factory=dict)
    message: str | None = None


class MultiSourceBasicsSyncService:
    """多数据源股票基础信息同步服务"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._running = False
        self._last_status: dict[str, Any] | None = None

    async def get_status(self) -> dict[str, Any]:
        """获取同步状态

        智能处理逻辑：
        1. 对 running 状态始终检查数据库实际情况（不盲目信任内存缓存）
        2. 如果 running 超过30分钟仍未完成，视为过期
        3. 如果 running 但计数器为0但数据库有数据，用实际数据填充
        4. 已完成状态（success/error）可以信任缓存
        """
        db = get_mongo_db()
        doc = await db[STATUS_COLLECTION].find_one({"job": JOB_KEY})

        if doc:
            doc.pop("_id", None)

            # 检查是否为过期的 running 状态
            # 或者: running 状态但所有计数器都是0（同步还没开始更新计数器）
            if doc.get("status") == "running":
                try:
                    # 获取数据库中的实际数据量
                    actual_total = await db[COLLECTION_NAME].count_documents({})

                    # 检查 started_at 时间（兼容存量字符串与新 datetime 双形态）
                    started = to_config_tz(doc.get("started_at"))
                    elapsed = 0
                    if started is not None:
                        try:
                            elapsed = (now_tz() - started).total_seconds()
                        except Exception:
                            elapsed = 0

                    STALE_THRESHOLD = 1800  # 30分钟
                    counters_all_zero = (doc.get("total", 0) == 0 and doc.get("inserted", 0) == 0)

                    # 两种情况需要用实际数据:
                    # 1. 状态是 running 但超过30分钟还没完成（过期/僵死）
                    # 2. 状态是 running 且计数器都是0，但数据库有实际数据
                    should_use_actual = (
                        (elapsed > STALE_THRESHOLD) or
                        (counters_all_zero and actual_total > 0)
                    )

                    if should_use_actual:
                        reason = "过期任务" if elapsed > STALE_THRESHOLD else "数据库有实际数据"
                        logger.warning(f"检测到需要使用实际统计数据的同步状态（{reason}），当前计数器: total={doc.get('total', 0)}, 实际数据: {actual_total}")

                        # 获取已使用的数据源
                        sources_present = []
                        try:
                            pipeline = [
                                {"$group": {"_id": "$source", "count": {"$sum": 1}}}
                            ]
                            source_counts = await db[COLLECTION_NAME].aggregate(pipeline).to_list(length=10)
                            for sc in source_counts:
                                if sc.get("_id") and sc["_id"] is not None:
                                    sources_present.append(sc["_id"])
                        except Exception:
                            pass

                        # 如果是过期状态，更新为 success；如果是新任务但有旧数据，保持 running 但填充实际总数
                        if elapsed > STALE_THRESHOLD:
                            doc["status"] = "success" if actual_total > 0 else "never_run"
                            if not doc.get("finished_at"):
                                doc["finished_at"] = now_tz()

                        # 填充实际数据统计
                        doc["total"] = actual_total
                        doc["inserted"] = actual_total
                        doc["data_sources_used"] = sources_present
                        doc["message"] = f"使用数据库实际统计数据（{reason}）"

                        # 更新数据库中的状态记录
                        await self._persist_status(db, doc.copy())

                except Exception as e:
                    logger.warning(f"处理同步状态时出错: {e}")

            # 确保所有必要字段都有默认值
            default_status = SyncStats().__dict__
            for key, value in default_status.items():
                if key not in doc or doc[key] is None:
                    doc[key] = value

            self._last_status = doc
            return doc

        # 数据库中没有记录，检查是否有实际数据（说明之前用其他方式同步过）
        actual_total = await db[COLLECTION_NAME].count_documents({})
        if actual_total > 0:
            logger.info(f"检测到 {actual_total} 条已存在的数据，使用现有数据作为基础")

            # 获取已使用的数据源
            sources_present = []
            try:
                pipeline = [
                    {"$group": {"_id": "$source", "count": {"$sum": 1}}}
                ]
                source_counts = await db[COLLECTION_NAME].aggregate(pipeline).to_list(length=10)
                for sc in source_counts:
                    if sc.get("_id") and sc["_id"] is not None:
                        sources_present.append(sc["_id"])
            except Exception:
                pass

            # 创建基于现有数据的状态记录
            existing_status = SyncStats()
            existing_status.status = "success"
            existing_status.total = actual_total
            existing_status.inserted = actual_total
            existing_status.updated = 0
            existing_status.errors = 0
            existing_status.data_sources_used = sources_present
            existing_status.message = f"已存在 {actual_total} 条股票基础信息（来自数据源: {', '.join(sources_present) if sources_present else 'unknown'}）"
            existing_status.finished_at = now_tz()
            existing_status.started_at = existing_status.finished_at

            status_dict = existing_status.__dict__
            await self._persist_status(db, status_dict.copy())
            return status_dict

        # 没有数据也没有状态记录，返回默认 never_run
        default_status = SyncStats()
        default_status.status = "never_run"
        return default_status.__dict__

    async def _persist_status(self, db: AsyncIOMotorDatabase, stats: dict[str, Any]) -> None:
        """持久化同步状态"""
        stats["job"] = JOB_KEY

        # 使用 upsert 来避免重复键错误
        # 基于 data_type 和 job 进行更新或插入
        filter_query = {
            "data_type": stats.get("data_type", "stock_basics"),
            "job": JOB_KEY
        }

        await db[STATUS_COLLECTION].update_one(
            filter_query,
            {"$set": stats},
            upsert=True
        )

        self._last_status = {k: v for k, v in stats.items() if k != "_id"}

    async def _execute_bulk_write_with_retry(
        self,
        db: AsyncIOMotorDatabase,
        operations: list,
        max_retries: int = 3
    ) -> tuple[int, int]:
        """
        执行批量写入，带重试机制

        Args:
            db: MongoDB数据库实例
            operations: 批量操作列表
            max_retries: 最大重试次数

        Returns:
            (新增数量, 更新数量)
        """
        inserted = 0
        updated = 0
        retry_count = 0

        while retry_count < max_retries:
            try:
                result = await db[COLLECTION_NAME].bulk_write(operations, ordered=False)
                inserted = result.upserted_count
                updated = result.modified_count
                logger.debug(f"✅ 批量写入成功: 新增 {inserted}, 更新 {updated}")
                return inserted, updated

            except asyncio.TimeoutError as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # 指数退避：2秒、4秒、8秒
                    logger.warning(f"⚠️ 批量写入超时 (第{retry_count}次重试)，等待{wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ 批量写入失败，已重试{max_retries}次: {e}")
                    return 0, 0

            except Exception as e:
                logger.error(f"❌ 批量写入失败: {e}")
                return 0, 0

        return inserted, updated

    async def run_full_sync(self, force: bool = False, preferred_sources: list[str] = None) -> dict[str, Any]:
        """
        运行完整同步

        Args:
            force: 是否强制运行（即使已在运行中）
            preferred_sources: 优先使用的数据源列表
        """
        async with self._lock:
            if self._running and not force:
                logger.info("Multi-source stock basics sync already running; skip start")
                return await self.get_status()
            self._running = True

        db = get_mongo_db()
        stats = SyncStats()
        stats.started_at = now_tz()
        stats.status = "running"
        await self._persist_status(db, stats.__dict__.copy())

        try:
            # Step 1: 获取数据源管理器
            from app.services.data_sources.manager import DataSourceManager
            manager = DataSourceManager()
            available_adapters = manager.get_available_adapters()

            if not available_adapters:
                raise RuntimeError("No available data sources found")

            logger.info(f"Available data sources: {[adapter.name for adapter in available_adapters]}")

            # 如果指定了优先数据源，记录日志
            if preferred_sources:
                logger.info(f"Using preferred data sources: {preferred_sources}")

            # Step 2: 尝试从数据源获取股票列表
            stock_df, source_used = await asyncio.to_thread(
                manager.get_stock_list_with_fallback, preferred_sources
            )
            if stock_df is None or getattr(stock_df, "empty", True):
                raise RuntimeError("All data sources failed to provide stock list")

            stats.data_sources_used.append(f"stock_list:{source_used}")
            logger.info(f"Successfully fetched {len(stock_df)} stocks from {source_used}")

            # Step 3: 获取最新交易日期和财务数据
            latest_trade_date = await asyncio.to_thread(
                manager.find_latest_trade_date_with_fallback, preferred_sources
            )
            stats.last_trade_date = latest_trade_date

            daily_data_map = {}
            daily_source = ""
            if latest_trade_date:
                daily_df, daily_source = await asyncio.to_thread(
                    manager.get_daily_basic_with_fallback, latest_trade_date, preferred_sources
                )
                if daily_df is not None and not daily_df.empty:
                    for _, row in daily_df.iterrows():
                        ts_code = row.get("ts_code")
                        if ts_code:
                            daily_data_map[ts_code] = row.to_dict()
                    stats.data_sources_used.append(f"daily_data:{daily_source}")

            # Step 5: 处理和更新数据（分批处理）
            ops = []
            inserted = updated = errors = 0
            batch_size = 500  # 🔥 每批处理 500 只股票，避免超时
            total_stocks = len(stock_df)

            logger.info(f"🚀 开始处理 {total_stocks} 只股票，数据源: {source_used}")

            for idx, (_, row) in enumerate(stock_df.iterrows(), 1):
                try:
                    # 提取基础信息
                    name = row.get("name") or ""
                    area = row.get("area") or ""
                    industry = row.get("industry") or ""
                    market = row.get("market") or ""
                    list_date = row.get("list_date") or ""
                    ts_code = row.get("ts_code") or ""

                    # 提取6位股票代码
                    if isinstance(ts_code, str) and "." in ts_code:
                        code = ts_code.split(".")[0]
                    else:
                        symbol = row.get("symbol") or ""
                        code = str(symbol).zfill(6) if symbol else ""

                    # 根据 ts_code 判断交易所
                    if isinstance(ts_code, str):
                        if ts_code.endswith(".SH"):
                            sse = "上海证券交易所"
                        elif ts_code.endswith(".SZ"):
                            sse = "深圳证券交易所"
                        elif ts_code.endswith(".BJ"):
                            sse = "北京证券交易所"
                        else:
                            sse = "未知"
                    else:
                        sse = "未知"

                    category = "stock_cn"

                    # 获取财务数据
                    daily_metrics = {}
                    if isinstance(ts_code, str) and ts_code in daily_data_map:
                        daily_metrics = daily_data_map[ts_code]

                    # 生成 full_symbol（确保不为空）
                    full_symbol = ts_code if ts_code else self._generate_full_symbol(code)

                    # 🔥 确定数据源标识
                    # 根据实际使用的数据源设置 source 字段
                    # 注意：不再使用 "multi_source" 作为默认值，必须有明确的数据源
                    if not source_used:
                        logger.warning(f"⚠️ 股票 {code} 没有明确的数据源，跳过")
                        errors += 1
                        continue
                    data_source = source_used

                    # 构建文档
                    doc = {
                        "code": code,
                        "symbol": code,  # 添加 symbol 字段（标准化字段）
                        "name": name,
                        "area": area,
                        "industry": industry,
                        "market": market,
                        "list_date": list_date,
                        "sse": sse,
                        "full_symbol": full_symbol,  # 添加 full_symbol 字段
                        "category": category,
                        "source": data_source,  # 🔥 使用实际数据源
                        "updated_at": now_tz(),
                    }

                    # 添加财务指标
                    self._add_financial_metrics(doc, daily_metrics)

                    # P4-11：写入前做字段白名单漂移检测（仅告警，不影响数据与写入）
                    detect_db_extra_fields(StockBasicInfoDB, doc, context=f"stock_basic_info code={code}")

                    # 🔥 使用 (code, source) 联合查询条件
                    ops.append(UpdateOne({"code": code, "source": data_source}, {"$set": doc}, upsert=True))

                except Exception as e:
                    logger.error(f"Error processing stock {row.get('ts_code', 'unknown')}: {e}")
                    errors += 1

                # 🔥 分批执行数据库操作
                if len(ops) >= batch_size or idx == total_stocks:
                    if ops:
                        progress_pct = (idx / total_stocks) * 100
                        logger.info(f"📝 执行批量写入: {len(ops)} 条记录 ({idx}/{total_stocks}, {progress_pct:.1f}%)")

                        batch_inserted, batch_updated = await self._execute_bulk_write_with_retry(db, ops)

                        if batch_inserted > 0 or batch_updated > 0:
                            inserted += batch_inserted
                            updated += batch_updated
                            logger.info(f"✅ 批量写入完成: 新增 {batch_inserted}, 更新 {batch_updated} | 累计: 新增 {inserted}, 更新 {updated}, 错误 {errors}")
                        else:
                            errors += len(ops)
                            logger.warning(f"⚠️ 批量写入失败，标记 {len(ops)} 条记录为错误")

                        ops = []  # 清空操作列表

            # Step 7: 更新统计信息
            stats.total = total_stocks  # 🔥 使用总股票数
            stats.inserted = inserted
            stats.updated = updated
            stats.errors = errors
            stats.status = "success" if errors == 0 else "success_with_errors"
            stats.finished_at = now_tz()

            await self._persist_status(db, stats.__dict__.copy())
            logger.info(
                f"✅ Multi-source sync finished: total={stats.total} inserted={inserted} "
                f"updated={updated} errors={errors} sources={stats.data_sources_used}"
            )
            return stats.__dict__

        except Exception as e:
            stats.status = "failed"
            stats.message = str(e)
            stats.finished_at = now_tz()
            await self._persist_status(db, stats.__dict__.copy())
            logger.exception(f"Multi-source sync failed: {e}")
            return stats.__dict__
        finally:
            async with self._lock:
                self._running = False



    def _add_financial_metrics(self, doc: dict, daily_metrics: dict) -> None:
        """委托到 basics_sync.processing.add_financial_metrics"""
        return _add_financial_metrics_util(doc, daily_metrics)

    def _generate_full_symbol(self, code: str) -> str:
        """
        根据股票代码生成完整标准化代码

        Args:
            code: 6位股票代码

        Returns:
            完整标准化代码，如果无法识别则返回原始代码（确保不为空）
        """
        # 确保 code 不为空
        if not code:
            return ""

        # 标准化为字符串并去除空格
        code = str(code).strip()

        # 如果长度不是 6，返回原始代码
        if len(code) != 6:
            return code

        # 根据代码前缀判断交易所
        # 沪市：60/68/90、北交所新代码段：92 需优先于 9 判定
        if code.startswith(('60', '68', '90')):  # 上海证券交易所
            return f"{code}.SS"
        elif code.startswith(('00', '30', '20')):  # 深圳证券交易所
            return f"{code}.SZ"
        elif code.startswith(('8', '4', '92')):  # 北京证券交易所（含 920 新代码段）
            return f"{code}.BJ"
        else:
            # 无法识别的代码，返回原始代码（确保不为空）
            return code if code else ""


# 全局服务实例
_multi_source_sync_service = None

def get_multi_source_sync_service() -> MultiSourceBasicsSyncService:
    """获取多数据源同步服务实例"""
    global _multi_source_sync_service
    if _multi_source_sync_service is None:
        _multi_source_sync_service = MultiSourceBasicsSyncService()
    return _multi_source_sync_service
