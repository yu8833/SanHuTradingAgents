"""
数据库连接管理模块
增强版本，支持连接池、健康检查和错误恢复
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import MongoClient
from pymongo.database import Database
from redis.asyncio import ConnectionPool, Redis

from .config import settings

logger = logging.getLogger(__name__)

# 全局连接实例
mongo_client: AsyncIOMotorClient | None = None
mongo_db: AsyncIOMotorDatabase | None = None
redis_client: Redis | None = None
redis_pool: ConnectionPool | None = None

# 同步 MongoDB 连接（用于非异步上下文）
_sync_mongo_client: MongoClient | None = None
_sync_mongo_db: Database | None = None


class DatabaseManager:
    """数据库连接管理器"""

    def __init__(self):
        self.mongo_client: AsyncIOMotorClient | None = None
        self.mongo_db: AsyncIOMotorDatabase | None = None
        self.redis_client: Redis | None = None
        self.redis_pool: ConnectionPool | None = None
        self._mongo_healthy = False
        self._redis_healthy = False

    async def init_mongodb(self):
        """初始化MongoDB连接"""
        try:
            logger.info("🔄 正在初始化MongoDB连接...")

            # 创建MongoDB客户端，配置连接池
            # tz_aware=True：BSON datetime 读回即带 UTC 偏移（aware），从源头消灭 naive 二义性。
            # 所有读路径统一经 to_display_iso()/to_config_tz() 归一为配置时区（+08:00）。
            self.mongo_client = AsyncIOMotorClient(
                settings.MONGO_URI,
                maxPoolSize=settings.MONGO_MAX_CONNECTIONS,
                minPoolSize=settings.MONGO_MIN_CONNECTIONS,
                maxIdleTimeMS=30000,  # 30秒空闲超时
                serverSelectionTimeoutMS=settings.MONGO_SERVER_SELECTION_TIMEOUT_MS,  # 服务器选择超时
                connectTimeoutMS=settings.MONGO_CONNECT_TIMEOUT_MS,  # 连接超时
                socketTimeoutMS=settings.MONGO_SOCKET_TIMEOUT_MS,  # 套接字超时
                tz_aware=True,
            )

            # 获取数据库实例
            self.mongo_db = self.mongo_client[settings.MONGO_DB]

            # 测试连接
            await self.mongo_client.admin.command('ping')
            self._mongo_healthy = True

            logger.info("✅ MongoDB连接成功建立")
            logger.info(f"📊 数据库: {settings.MONGO_DB}")
            logger.info(f"🔗 连接池: {settings.MONGO_MIN_CONNECTIONS}-{settings.MONGO_MAX_CONNECTIONS}")
            logger.info(f"⏱️  超时配置: connectTimeout={settings.MONGO_CONNECT_TIMEOUT_MS}ms, socketTimeout={settings.MONGO_SOCKET_TIMEOUT_MS}ms")

        except Exception as e:
            logger.error(f"❌ MongoDB连接失败: {e}")
            self._mongo_healthy = False
            raise

    async def init_redis(self):
        """初始化Redis连接"""
        try:
            logger.info("🔄 正在初始化Redis连接...")

            # 创建Redis连接池
            self.redis_pool = ConnectionPool.from_url(
                settings.REDIS_URL,
                max_connections=settings.REDIS_MAX_CONNECTIONS,
                retry_on_timeout=settings.REDIS_RETRY_ON_TIMEOUT,
                decode_responses=True,
                socket_connect_timeout=5,  # 5秒连接超时
                socket_timeout=10,  # 10秒套接字超时
            )

            # 创建Redis客户端
            self.redis_client = Redis(connection_pool=self.redis_pool)

            # 测试连接
            await self.redis_client.ping()
            self._redis_healthy = True

            logger.info("✅ Redis连接成功建立")
            logger.info(f"🔗 连接池大小: {settings.REDIS_MAX_CONNECTIONS}")

        except Exception as e:
            logger.error(f"❌ Redis连接失败: {e}")
            self._redis_healthy = False
            raise

    async def close_connections(self):
        """关闭所有数据库连接"""
        logger.info("🔄 正在关闭数据库连接...")

        # 关闭MongoDB连接
        if self.mongo_client:
            try:
                self.mongo_client.close()
                self._mongo_healthy = False
                logger.info("✅ MongoDB连接已关闭")
            except Exception as e:
                logger.error(f"❌ 关闭MongoDB连接时出错: {e}")

        # 关闭Redis连接
        if self.redis_client:
            try:
                await self.redis_client.close()
                self._redis_healthy = False
                logger.info("✅ Redis连接已关闭")
            except Exception as e:
                logger.error(f"❌ 关闭Redis连接时出错: {e}")

        # 关闭Redis连接池
        if self.redis_pool:
            try:
                await self.redis_pool.disconnect()
                logger.info("✅ Redis连接池已关闭")
            except Exception as e:
                logger.error(f"❌ 关闭Redis连接池时出错: {e}")

    async def health_check(self) -> dict:
        """数据库健康检查"""
        health_status = {
            "mongodb": {"status": "unknown", "details": None},
            "redis": {"status": "unknown", "details": None}
        }

        # 检查MongoDB
        try:
            if self.mongo_client:
                result = await self.mongo_client.admin.command('ping')
                health_status["mongodb"] = {
                    "status": "healthy",
                    "details": {"ping": result, "database": settings.MONGO_DB}
                }
                self._mongo_healthy = True
            else:
                health_status["mongodb"]["status"] = "disconnected"
        except Exception as e:
            health_status["mongodb"] = {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
            self._mongo_healthy = False

        # 检查Redis
        try:
            if self.redis_client:
                result = await self.redis_client.ping()
                health_status["redis"] = {
                    "status": "healthy",
                    "details": {"ping": result}
                }
                self._redis_healthy = True
            else:
                health_status["redis"]["status"] = "disconnected"
        except Exception as e:
            health_status["redis"] = {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
            self._redis_healthy = False

        return health_status

    @property
    def is_healthy(self) -> bool:
        """检查所有数据库连接是否健康"""
        return self._mongo_healthy and self._redis_healthy


# 全局数据库管理器实例
db_manager = DatabaseManager()


async def init_database():
    """初始化数据库连接"""
    global mongo_client, mongo_db, redis_client, redis_pool

    try:
        # 初始化MongoDB
        await db_manager.init_mongodb()
        mongo_client = db_manager.mongo_client
        mongo_db = db_manager.mongo_db

        # 初始化Redis
        await db_manager.init_redis()
        redis_client = db_manager.redis_client
        redis_pool = db_manager.redis_pool

        logger.info("🎉 所有数据库连接初始化完成")

        # 🔥 初始化数据库视图和索引
        await init_database_views_and_indexes()

    except Exception as e:
        logger.error(f"💥 数据库初始化失败: {e}")
        raise


async def init_database_views_and_indexes():
    """初始化数据库视图和索引"""
    try:
        db = get_mongo_db()

        # 1. 创建股票筛选视图
        await create_stock_screening_view(db)

        # 2. 创建必要的索引
        await create_database_indexes(db)

        logger.info("✅ 数据库视图和索引初始化完成")

    except Exception as e:
        logger.warning(f"⚠️ 数据库视图和索引初始化失败: {e}")
        # 不抛出异常，允许应用继续启动


async def create_stock_screening_view(db):
    """创建股票筛选视图（可反复调用：若已存在会先删除后重建，以确保 pipeline 最新）"""
    try:
        # 若视图已存在，先删除（确保每次发布的 pipeline 变更能生效，避免旧 lookup 逻辑残留）
        collections = await db.list_collection_names()
        if "stock_screening_view" in collections:
            try:
                await db.command("drop", "stock_screening_view")
                logger.info("📋 旧视图 stock_screening_view 已删除，准备重建")
            except Exception as drop_e:
                logger.debug(f"ℹ️ 删除旧视图跳过（可能是系统保留或命名空间非视图）: {drop_e}")

        # 创建视图：将 stock_basic_info、market_quotes 和 stock_financial_data 关联
        pipeline = [
            # 第一步：关联实时行情数据 (market_quotes)
            # 修复 #B2：同时用 symbol 和 code 匹配，避免只写了 symbol 的记录 join 失败
            {
                "$lookup": {
                    "from": "market_quotes",
                    "let": {"stock_code": "$code", "stock_symbol": "$symbol"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$or": [
                                        {"$eq": ["$code", "$$stock_code"]},
                                        {"$eq": ["$symbol", "$$stock_symbol"]}
                                    ]
                                }
                            }
                        },
                        {"$limit": 1}
                    ],
                    "as": "quote_data"
                }
            },
            # 第二步：展开 quote_data 数组
            {
                "$unwind": {
                    "path": "$quote_data",
                    "preserveNullAndEmptyArrays": True
                }
            },
            # 第三步：关联财务数据 (stock_financial_data)
            # 修复 #B2：同时匹配 symbol + code
            {
                "$lookup": {
                    "from": "stock_financial_data",
                    "let": {"stock_code": "$code", "stock_symbol": "$symbol", "stock_source": "$source"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$or": [
                                            {"$eq": ["$code", "$$stock_code"]},
                                            {"$eq": ["$symbol", "$$stock_symbol"]}
                                        ]},
                                        {"$eq": ["$data_source", "$$stock_source"]}
                                    ]
                                }
                            }
                        },
                        {"$sort": {"report_period": -1}},
                        {"$limit": 1}
                    ],
                    "as": "financial_data"
                }
            },
            # 第四步：展开 financial_data 数组
            {
                "$unwind": {
                    "path": "$financial_data",
                    "preserveNullAndEmptyArrays": True
                }
            },
            # 第五步：重新组织字段结构
            {
                "$project": {
                    # 基础信息字段
                    "code": 1,
                    "name": 1,
                    "industry": 1,
                    "area": 1,
                    "market": 1,
                    "list_date": 1,
                    "source": 1,
                    # 市值信息
                    "total_mv": 1,
                    "circ_mv": 1,
                    # 估值指标
                    "pe": 1,
                    "pb": 1,
                    "pe_ttm": 1,
                    "pb_mrq": 1,
                    # 财务指标
                    "roe": "$financial_data.roe",
                    "roa": "$financial_data.roa",
                    "netprofit_margin": "$financial_data.netprofit_margin",
                    "gross_margin": "$financial_data.gross_margin",
                    "report_period": "$financial_data.report_period",
                    # 交易指标
                    "turnover_rate": 1,
                    "volume_ratio": 1,
                    # 实时行情数据
                    "close": "$quote_data.close",
                    "open": "$quote_data.open",
                    "high": "$quote_data.high",
                    "low": "$quote_data.low",
                    "pre_close": "$quote_data.pre_close",
                    "pct_chg": "$quote_data.pct_chg",
                    "amount": "$quote_data.amount",
                    "volume": "$quote_data.volume",
                    "trade_date": "$quote_data.trade_date",
                    # 时间戳
                    "updated_at": 1,
                    "quote_updated_at": "$quote_data.updated_at",
                    "financial_updated_at": "$financial_data.updated_at"
                }
            }
        ]

        # 创建视图
        await db.command({
            "create": "stock_screening_view",
            "viewOn": "stock_basic_info",
            "pipeline": pipeline
        })

        logger.info("✅ 视图 stock_screening_view 创建成功")

    except Exception as e:
        logger.warning(f"⚠️ 创建视图失败: {e}")


async def _safe_create_index(collection, keys, **kwargs):
    """安全创建索引，捕获已存在或选项冲突的异常"""
    try:
        await collection.create_index(keys, **kwargs)
        return True
    except Exception as e:
        # IndexOptionsConflict (code 85) - 索引已存在但选项不同
        # 其他错误也静默跳过，确保初始化不中断
        logger.debug(f"ℹ️ 跳过索引创建 {keys}: {e}")
        return False


async def create_database_indexes(db):
    """创建数据库索引"""
    index_count = 0
    try:
        # stock_basic_info 的索引
        basic_info = db["stock_basic_info"]
        # 修复 #B7：唯一索引改为 (symbol, source) 作为主键，保持向后兼容
        # 注意：_safe_create_index 在已存在但选项不同时会跳过；对重复脏数据的集合创建唯一会失败，
        # 但这是希望暴露问题的信号，避免新增更多重复行。
        if await _safe_create_index(basic_info, [("symbol", 1), ("source", 1)], unique=True):
            index_count += 1
        # code+source 保留为非唯一查询索引（兼容仅按 code 查询的旧代码），
        # 加 sparse 保证 code 字段为 null 的新记录也能正常写入（唯一索引已在 symbol+source 上）
        if await _safe_create_index(basic_info, [("code", 1), ("source", 1)], sparse=True):
            index_count += 1
        if await _safe_create_index(basic_info, [("industry", 1)]):
            index_count += 1
        if await _safe_create_index(basic_info, [("total_mv", -1)]):
            index_count += 1
        if await _safe_create_index(basic_info, [("pe", 1)]):
            index_count += 1
        if await _safe_create_index(basic_info, [("pb", 1)]):
            index_count += 1

        # market_quotes 的索引
        market_quotes = db["market_quotes"]
        if await _safe_create_index(market_quotes, [("code", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(market_quotes, [("pct_chg", -1)]):
            index_count += 1
        if await _safe_create_index(market_quotes, [("amount", -1)]):
            index_count += 1
        if await _safe_create_index(market_quotes, [("updated_at", -1)]):
            index_count += 1

        # analysis_tasks 的索引（分析任务 - 高频查询）
        analysis_tasks = db["analysis_tasks"]
        if await _safe_create_index(analysis_tasks, [("task_id", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(analysis_tasks, [("user_id", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_tasks, [("status", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_tasks, [("batch_id", 1)]):
            index_count += 1
        if await _safe_create_index(analysis_tasks, [("symbol", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_tasks, [("user_id", 1), ("status", 1)]):
            index_count += 1

        # analysis_batches 的索引（分析批次）
        analysis_batches = db["analysis_batches"]
        if await _safe_create_index(analysis_batches, [("batch_id", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(analysis_batches, [("user_id", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_batches, [("status", 1), ("created_at", -1)]):
            index_count += 1

        # analysis_reports 的索引（分析报告 - 高频查询）
        analysis_reports = db["analysis_reports"]
        if await _safe_create_index(analysis_reports, [("task_id", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(analysis_reports, [("analysis_id", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(analysis_reports, [("stock_symbol", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_reports, [("user_id", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(analysis_reports, [("created_at", -1)]):
            index_count += 1

        # notifications 的索引（通知）
        notifications = db["notifications"]
        if await _safe_create_index(notifications, [("user_id", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(notifications, [("user_id", 1), ("status", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(notifications, [("user_id", 1), ("read", 1), ("created_at", -1)]):
            index_count += 1

        # operation_logs 的索引（操作日志）
        operation_logs = db["operation_logs"]
        if await _safe_create_index(operation_logs, [("user_id", 1), ("timestamp", -1)]):
            index_count += 1
        if await _safe_create_index(operation_logs, [("action_type", 1), ("timestamp", -1)]):
            index_count += 1
        if await _safe_create_index(operation_logs, [("timestamp", -1)]):
            index_count += 1
        if await _safe_create_index(operation_logs, [("user_id", 1), ("action_type", 1), ("timestamp", -1)]):
            index_count += 1

        # system_configs 的索引（系统配置）
        system_configs = db["system_configs"]
        if await _safe_create_index(system_configs, [("is_active", 1), ("version", -1)]):
            index_count += 1
        if await _safe_create_index(system_configs, [("config_type", 1), ("version", -1)]):
            index_count += 1
        if await _safe_create_index(system_configs, [("created_at", -1)]):
            index_count += 1

        # usage_records 的索引（使用记录）— 实际集合名为 token_usage
        usage_records = db["token_usage"]
        if await _safe_create_index(usage_records, [("user_id", 1), ("timestamp", -1)]):
            index_count += 1
        if await _safe_create_index(usage_records, [("provider", 1), ("timestamp", -1)]):
            index_count += 1
        if await _safe_create_index(usage_records, [("session_id", 1)]):
            index_count += 1
        if await _safe_create_index(usage_records, [("timestamp", -1)]):
            index_count += 1

        # stock_daily_quotes 的索引（日线数据 - 策略扫描高频查询）
        daily_quotes = db["stock_daily_quotes"]
        # 修复 #B3：先加复合唯一索引，避免三源同步同一天同 period 造成重复插入
        # 注意：如集合中已存在历史脏数据（重复），create_index 会失败并被 _safe_create_index 吞掉。
        # 先创建非唯一查询索引，再创建唯一索引，保证无论如何查询都是快的。
        if await _safe_create_index(daily_quotes, [("code", 1), ("trade_date", -1), ("period", 1)], background=True):
            index_count += 1
        if await _safe_create_index(daily_quotes, [("symbol", 1), ("trade_date", -1), ("period", 1)], background=True):
            index_count += 1
        if await _safe_create_index(daily_quotes, [("trade_date", 1), ("period", 1)], background=True):
            index_count += 1
        if await _safe_create_index(
            daily_quotes,
            [("code", 1), ("trade_date", 1), ("period", 1), ("data_source", 1)],
            unique=True,
            background=True,
        ):
            index_count += 1

        # stock_daily_basic 的索引（每日估值/市值，回测按日对齐查询）
        daily_basic = db["stock_daily_basic"]
        # 回测按 (symbol/code, trade_date) 区间查询，trade_date 范围过滤 + code/symbol 命中
        if await _safe_create_index(daily_basic, [("trade_date", 1), ("code", 1)], background=True):
            index_count += 1
        if await _safe_create_index(daily_basic, [("code", 1), ("trade_date", 1)], unique=True, background=True):
            index_count += 1
        if await _safe_create_index(daily_basic, [("symbol", 1), ("trade_date", 1)], background=True):
            index_count += 1

        # 注意：MongoDB 视图不支持 createIndex，stock_screening_view 无需（也无法）建索引，
        # 其查询性能依赖源集合（stock_basic_info / stock_market_quotes）上的索引。

        # stock_financial_data 的索引（财务数据）
        stock_financial_data = db["stock_financial_data"]
        if await _safe_create_index(stock_financial_data, [("code", 1), ("data_source", 1), ("report_period", -1)]):
            index_count += 1
        if await _safe_create_index(stock_financial_data, [("code", 1), ("report_period", -1)]):
            index_count += 1
        if await _safe_create_index(stock_financial_data, [("symbol", 1), ("report_period", -1)]):
            index_count += 1

        # stock_historical_data 的索引（历史行情数据）
        stock_historical_data = db["stock_historical_data"]
        if await _safe_create_index(stock_historical_data, [("code", 1), ("trade_date", -1)]):
            index_count += 1
        # 修复 #B3：复合唯一索引 + 同步 symbol 维度索引
        if await _safe_create_index(stock_historical_data, [("symbol", 1), ("trade_date", -1)]):
            index_count += 1
        if await _safe_create_index(
            stock_historical_data,
            [("code", 1), ("source", 1), ("trade_date", 1)],
            unique=True,
        ):
            index_count += 1
        if await _safe_create_index(stock_historical_data, [("source", 1), ("trade_date", -1)]):
            index_count += 1
        if await _safe_create_index(stock_historical_data, [("trade_date", -1)]):
            index_count += 1

        # users 的索引（用户表）
        users = db["users"]
        if await _safe_create_index(users, [("username", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(users, [("email", 1)], unique=True, sparse=True):
            index_count += 1

        # favorites 的索引（自选股）— 实际集合名为 user_favorites
        favorites = db["user_favorites"]
        if await _safe_create_index(favorites, [("user_id", 1), ("stock_code", 1)], unique=True):
            index_count += 1
        if await _safe_create_index(favorites, [("user_id", 1), ("created_at", -1)]):
            index_count += 1

        # tags 的索引（标签）— 实际集合名为 user_tags
        tags = db["user_tags"]
        if await _safe_create_index(tags, [("user_id", 1), ("name", 1)], unique=True):
            index_count += 1

        # research_notes 的索引（研究笔记）— 之前缺失
        research_notes = db["research_notes"]
        if await _safe_create_index(research_notes, [("user_id", 1), ("created_at", -1)]):
            index_count += 1
        if await _safe_create_index(research_notes, [("user_id", 1), ("kind", 1)]):
            index_count += 1

        # strategy_backtest_results 的索引（回测结果对比，允许同一策略多条结果并存）
        bt_results = db["strategy_backtest_results"]
        if await _safe_create_index(bt_results, [("strategy_id", 1)]):
            index_count += 1
        if await _safe_create_index(bt_results, [("saved_at", -1)]):
            index_count += 1

        logger.info(f"✅ 数据库索引创建完成（新增 {index_count} 个索引）")

    except Exception as e:
        logger.warning(f"⚠️ 创建索引失败: {e}")


async def close_database():
    """关闭数据库连接"""
    global mongo_client, mongo_db, redis_client, redis_pool

    await db_manager.close_connections()

    # 清空全局变量
    mongo_client = None
    mongo_db = None
    redis_client = None
    redis_pool = None


def get_mongo_client() -> AsyncIOMotorClient:
    """获取MongoDB客户端"""
    if mongo_client is None:
        raise RuntimeError("MongoDB客户端未初始化")
    return mongo_client


def get_mongo_db() -> AsyncIOMotorDatabase:
    """获取MongoDB数据库实例"""
    if mongo_db is None:
        raise RuntimeError("MongoDB数据库未初始化")
    return mongo_db


def get_mongo_db_sync() -> Database:
    """
    获取同步版本的MongoDB数据库实例
    用于非异步上下文（如普通函数调用）
    """
    global _sync_mongo_client, _sync_mongo_db

    if _sync_mongo_db is not None:
        return _sync_mongo_db

    # 创建同步 MongoDB 客户端
    if _sync_mongo_client is None:
        _sync_mongo_client = MongoClient(
            settings.MONGO_URI,
            maxPoolSize=settings.MONGO_MAX_CONNECTIONS,
            minPoolSize=settings.MONGO_MIN_CONNECTIONS,
            maxIdleTimeMS=30000,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
        )

    _sync_mongo_db = _sync_mongo_client[settings.MONGO_DB]
    return _sync_mongo_db


def get_redis_client() -> Redis:
    """获取Redis客户端"""
    if redis_client is None:
        raise RuntimeError("Redis客户端未初始化")
    return redis_client


async def get_database_health() -> dict:
    """获取数据库健康状态"""
    return await db_manager.health_check()


# 兼容性别名
init_db = init_database
close_db = close_database


def get_database():
    """获取数据库实例（使用 settings.MONGO_DB 动态数据库名）"""
    if db_manager.mongo_client is None:
        raise RuntimeError("MongoDB客户端未初始化")
    return db_manager.mongo_client[settings.MONGO_DB]