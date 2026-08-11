"""
Tushare数据同步服务
负责将Tushare数据同步到MongoDB标准化集合
"""
import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import settings
from app.core.database import get_mongo_db
from app.core.rate_limiter import get_tushare_rate_limiter
from app.services.historical_data_service import get_historical_data_service
from app.services.data_sources.tushare_adapter import TushareAdapter
from app.services.news_data_service import get_news_data_service
from app.services.stock_data_service import get_stock_data_service
from app.utils.timezone import now_tz
from tradingagents.dataflows.providers.china.tushare import TushareProvider

logger = logging.getLogger(__name__)

# UTC+8 时区
UTC_8 = timezone(timedelta(hours=8))

# 模块级同步 MongoDB 客户端单例（供 _update_progress 使用）
# 避免每次进度更新都新建 MongoClient 连接，减少连接开销与事件循环阻塞。
_sync_mongo_client = None


def _get_sync_db():
    """获取同步 MongoDB 数据库单例"""
    global _sync_mongo_client
    if _sync_mongo_client is None:
        from pymongo import MongoClient

        _sync_mongo_client = MongoClient(settings.MONGO_URI)
    return _sync_mongo_client[settings.MONGO_DB]


def _to_float(v):
    """安全转 float，失败返回 None。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_date(d) -> str:
    """将 yyyymmdd / yyyy-mm-dd 归一到 yyyy-mm-dd，非法返回空串。"""
    if not d:
        return ""
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if len(s) >= 10 else s


def _compact_date(d: str) -> str:
    """将 yyyy-mm-dd 转成 Tushare 接口需要的 yyyymmdd。"""
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return s
    parts = s.replace("/", "-").split("-")
    if len(parts) == 3:
        return f"{parts[0]}{parts[1]}{parts[2]}"
    return s[:8]


def get_utc8_now():
    """
    获取 UTC+8 当前时间（naive datetime）

    注意：返回 naive datetime（不带时区信息），MongoDB 会按原样存储本地时间值
    这样前端可以直接添加 +08:00 后缀显示
    """
    return now_tz().replace(tzinfo=None)


class TushareSyncService:
    """
    Tushare数据同步服务
    负责将Tushare数据同步到MongoDB标准化集合
    """
    
    def __init__(self):
        self.provider = TushareProvider()
        self.stock_service = get_stock_data_service()
        self.historical_service = None  # 延迟初始化
        self.news_service = None  # 延迟初始化
        self.db = get_mongo_db()
        self.settings = settings

        # 同步配置
        self.batch_size = 100  # 批量处理大小
        self.rate_limit_delay = 0.1  # API调用间隔(秒) - 已弃用，使用rate_limiter
        self.max_retries = 3  # 最大重试次数

        # 速率限制器（从环境变量读取配置）
        tushare_tier = getattr(settings, "TUSHARE_TIER", "standard")  # free/basic/standard/premium/vip
        safety_margin = float(getattr(settings, "TUSHARE_RATE_LIMIT_SAFETY_MARGIN", "0.8"))
        self.rate_limiter = get_tushare_rate_limiter(tier=tushare_tier, safety_margin=safety_margin)
    
    async def initialize(self):
        """初始化同步服务"""
        try:
            # Provider 在 __init__ 中已调用 _initialize() 进行了初始连接
            # 这里只需要确保 provider 可用，若不可用则重试一次
            if not self.provider.is_available():
                logger.warning("[TushareSyncService] Provider 初始不可用，正在重试连接...")
                success = await self.provider.connect()
                if not success:
                    raise RuntimeError("❌ Tushare连接失败，请检查 token 配置")

            # 初始化历史数据服务
            self.historical_service = await get_historical_data_service()

            # 初始化新闻数据服务
            self.news_service = await get_news_data_service()

            logger.info("✅ Tushare同步服务初始化完成")
        except Exception as e:
            logger.error(f"❌ Tushare同步服务初始化失败: {e}", exc_info=True)
            raise
    
    # ==================== 基础信息同步 ====================
    
    async def sync_stock_basic_info(self, force_update: bool = False, job_id: str = None) -> dict[str, Any]:
        """
        同步股票基础信息

        Args:
            force_update: 是否强制更新所有数据
            job_id: 任务ID（用于进度跟踪）

        Returns:
            同步结果统计
        """
        logger.info("🔄 开始同步股票基础信息...")

        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "start_time": datetime.now(),
            "errors": []
        }
        
        try:
            # 1. 从Tushare获取股票列表
            stock_list = await self.provider.get_stock_list(market="CN")
            if not stock_list:
                logger.error("❌ 无法获取股票列表")
                return stats
            
            stats["total_processed"] = len(stock_list)
            logger.info(f"📊 获取到 {len(stock_list)} 只股票信息")

            # 2. 批量处理
            for i in range(0, len(stock_list), self.batch_size):
                # 检查是否需要退出
                if job_id and await self._should_stop(job_id):
                    logger.warning(f"⚠️ 任务 {job_id} 收到停止信号，正在退出...")
                    stats["stopped"] = True
                    break

                batch = stock_list[i:i + self.batch_size]
                batch_stats = await self._process_basic_info_batch(batch, force_update)

                # 更新统计
                stats["success_count"] += batch_stats["success_count"]
                stats["error_count"] += batch_stats["error_count"]
                stats["skipped_count"] += batch_stats["skipped_count"]
                stats["errors"].extend(batch_stats["errors"])

                # 进度日志和进度更新
                progress = min(i + self.batch_size, len(stock_list))
                progress_percent = int((progress / len(stock_list)) * 100)
                logger.info(f"📈 基础信息同步进度: {progress}/{len(stock_list)} ({progress_percent}%) "
                           f"(成功: {stats['success_count']}, 错误: {stats['error_count']})")

                # 更新任务进度
                if job_id:
                    await self._update_progress(
                        job_id,
                        progress_percent,
                        f"已处理 {progress}/{len(stock_list)} 只股票"
                    )

                # API限流
                if i + self.batch_size < len(stock_list):
                    await asyncio.sleep(self.rate_limit_delay)
            
            # 3. 完成统计
            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()
            
            logger.info(f"✅ 股票基础信息同步完成: "
                       f"总计 {stats['total_processed']} 只, "
                       f"成功 {stats['success_count']} 只, "
                       f"错误 {stats['error_count']} 只, "
                       f"跳过 {stats['skipped_count']} 只, "
                       f"耗时 {stats['duration']:.2f} 秒")
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ 股票基础信息同步失败: {e}")
            stats["errors"].append({"error": str(e), "context": "sync_stock_basic_info"})
            return stats
    
    async def _process_basic_info_batch(self, batch: list[dict[str, Any]], force_update: bool) -> dict[str, Any]:
        """处理基础信息批次"""
        batch_stats = {
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "errors": []
        }
        
        for stock_info in batch:
            try:
                # 🔥 先转换为字典格式（如果是Pydantic模型）
                if hasattr(stock_info, 'model_dump'):
                    stock_data = stock_info.model_dump()
                elif hasattr(stock_info, 'dict'):
                    stock_data = stock_info.dict()
                else:
                    stock_data = stock_info

                code = stock_data["code"]

                # 检查是否需要更新
                if not force_update:
                    existing = await self.stock_service.get_stock_basic_info(code)
                    if existing:
                        # 🔥 existing 也可能是 Pydantic 模型，需要安全获取属性
                        existing_dict = existing.model_dump() if hasattr(existing, 'model_dump') else (existing.dict() if hasattr(existing, 'dict') else existing)
                        if self._is_data_fresh(existing_dict.get("updated_at"), hours=24):
                            batch_stats["skipped_count"] += 1
                            continue

                # 更新到数据库（指定数据源为 tushare）
                success = await self.stock_service.update_stock_basic_info(code, stock_data, source="tushare")
                if success:
                    batch_stats["success_count"] += 1
                else:
                    batch_stats["error_count"] += 1
                    batch_stats["errors"].append({
                        "code": code,
                        "error": "数据库更新失败",
                        "context": "update_stock_basic_info"
                    })

            except Exception as e:
                batch_stats["error_count"] += 1
                # 🔥 安全获取 code（处理 Pydantic 模型和字典）
                try:
                    if hasattr(stock_info, 'code'):
                        code = stock_info.code
                    elif hasattr(stock_info, 'model_dump'):
                        code = stock_info.model_dump().get("code", "unknown")
                    elif hasattr(stock_info, 'dict'):
                        code = stock_info.dict().get("code", "unknown")
                    else:
                        code = stock_info.get("code", "unknown")
                except Exception:
                    code = "unknown"

                batch_stats["errors"].append({
                    "code": code,
                    "error": str(e),
                    "context": "_process_basic_info_batch"
                })
        
        return batch_stats
    
    # ==================== 实时行情同步 ====================
    
    async def sync_realtime_quotes(self, symbols: list[str] = None, force: bool = False) -> dict[str, Any]:
        """
        同步实时行情数据

        策略：
        - 如果指定了少量股票（≤10只），自动切换到 AKShare 接口（避免浪费 Tushare rt_k 配额）
        - 如果指定了大量股票或全市场，使用 Tushare 批量接口一次性获取

        Args:
            symbols: 指定股票代码列表，为空则同步所有股票；如果指定了股票列表，则只保存这些股票的数据
            force: 是否强制执行（跳过交易时间检查），默认 False

        Returns:
            同步结果统计
        """
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": datetime.now(),
            "errors": [],
            "stopped_by_rate_limit": False,
            "skipped_non_trading_time": False,
            "switched_to_akshare": False  # 是否切换到 AKShare
        }

        try:
            # 检查是否在交易时间（手动同步时可以跳过检查）
            if not force and not self._is_trading_time():
                logger.info("⏸️ 当前不在交易时间，跳过实时行情同步（使用 force=True 可强制执行）")
                stats["skipped_non_trading_time"] = True
                return stats

            # 🔥 策略选择：少量股票切换到 AKShare，大量股票或全市场用 Tushare 批量接口
            USE_AKSHARE_THRESHOLD = 10  # 少于等于10只股票时切换到 AKShare

            if symbols and len(symbols) <= USE_AKSHARE_THRESHOLD:
                # 🔥 自动切换到 AKShare（避免浪费 Tushare rt_k 配额，每小时只能调用2次）
                logger.info(
                    f"💡 股票数量 ≤{USE_AKSHARE_THRESHOLD} 只，自动切换到 AKShare 接口"
                    f"（避免浪费 Tushare rt_k 配额，每小时只能调用2次）"
                )
                logger.info(f"🎯 使用 AKShare 同步 {len(symbols)} 只股票的实时行情: {symbols}")

                # 调用 AKShare 服务
                from app.worker.akshare_sync_service import get_akshare_sync_service
                akshare_service = await get_akshare_sync_service()

                if not akshare_service:
                    logger.error("❌ AKShare 服务不可用，回退到 Tushare 批量接口")
                    # 回退到 Tushare 批量接口
                    quotes_map = await self.provider.get_realtime_quotes_batch()
                    if quotes_map and symbols:
                        quotes_map = {symbol: quotes_map[symbol] for symbol in symbols if symbol in quotes_map}
                else:
                    # 使用 AKShare 同步
                    akshare_result = await akshare_service.sync_realtime_quotes(
                        symbols=symbols,
                        force=force
                    )
                    stats["switched_to_akshare"] = True
                    stats["success_count"] = akshare_result.get("success_count", 0)
                    stats["error_count"] = akshare_result.get("error_count", 0)
                    stats["total_processed"] = akshare_result.get("total_processed", 0)
                    stats["errors"] = akshare_result.get("errors", [])
                    stats["end_time"] = datetime.now()
                    stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

                    logger.info(
                        f"✅ AKShare 实时行情同步完成: "
                        f"总计 {stats['total_processed']} 只, "
                        f"成功 {stats['success_count']} 只, "
                        f"错误 {stats['error_count']} 只, "
                        f"耗时 {stats['duration']:.2f} 秒"
                    )
                    return stats
            else:
                # 使用 Tushare 批量接口一次性获取全市场行情
                if symbols:
                    logger.info(f"📊 使用 Tushare 批量接口同步 {len(symbols)} 只股票的实时行情（从全市场数据中筛选）")
                else:
                    logger.info("📊 使用 Tushare 批量接口同步全市场实时行情...")

                logger.info("📡 调用 rt_k 批量接口获取全市场实时行情...")
                quotes_map = await self.provider.get_realtime_quotes_batch()

                if not quotes_map:
                    logger.warning("⚠️ 未获取到实时行情数据")
                    return stats

                logger.info(f"✅ 获取到 {len(quotes_map)} 只股票的实时行情")

                # 🔥 如果指定了股票列表，只处理这些股票
                if symbols:
                    # 过滤出指定的股票
                    filtered_quotes_map = {symbol: quotes_map[symbol] for symbol in symbols if symbol in quotes_map}

                    # 检查是否有股票未找到
                    missing_symbols = [s for s in symbols if s not in quotes_map]
                    if missing_symbols:
                        logger.warning(f"⚠️ 以下股票未在实时行情中找到: {missing_symbols}")

                    quotes_map = filtered_quotes_map
                    logger.info(f"🔍 过滤后保留 {len(quotes_map)} 只指定股票的行情")

            if not quotes_map:
                logger.warning("⚠️ 未获取到任何实时行情数据")
                return stats

            stats["total_processed"] = len(quotes_map)

            # 批量保存到数据库
            success_count = 0
            error_count = 0

            for symbol, quote_data in quotes_map.items():
                try:
                    # 保存到数据库
                    result = await self.stock_service.update_market_quotes(symbol, quote_data)
                    if result:
                        success_count += 1
                    else:
                        error_count += 1
                        stats["errors"].append({
                            "code": symbol,
                            "error": "更新数据库失败",
                            "context": "sync_realtime_quotes"
                        })
                except Exception as e:
                    error_count += 1
                    stats["errors"].append({
                        "code": symbol,
                        "error": str(e),
                        "context": "sync_realtime_quotes"
                    })

            stats["success_count"] = success_count
            stats["error_count"] = error_count

            # 完成统计
            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

            logger.info(f"✅ 实时行情同步完成: "
                      f"总计 {stats['total_processed']} 只, "
                      f"成功 {stats['success_count']} 只, "
                      f"错误 {stats['error_count']} 只, "
                      f"耗时 {stats['duration']:.2f} 秒")

            return stats

        except Exception as e:
            # 检查是否为限流错误
            error_msg = str(e)
            if self._is_rate_limit_error(error_msg):
                stats["stopped_by_rate_limit"] = True
                logger.error(f"❌ 实时行情同步失败（API限流）: {e}")
            else:
                logger.error(f"❌ 实时行情同步失败: {e}")

            stats["errors"].append({"error": str(e), "context": "sync_realtime_quotes"})
            return stats

    # 🔥 已废弃：不再使用 Tushare 单只接口（rt_k 每小时只能调用2次，太宝贵）
    # 少量股票（≤10只）自动切换到 AKShare 接口
    # async def _get_quotes_individually(self, symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    #     """
    #     使用单只接口逐个获取股票实时行情（已废弃）
    #
    #     Args:
    #         symbols: 股票代码列表
    #
    #     Returns:
    #         Dict[symbol, quote_data]
    #     """
    #     quotes_map = {}
    #
    #     for symbol in symbols:
    #         try:
    #             quote_data = await self.provider.get_stock_quotes(symbol)
    #             if quote_data:
    #                 quotes_map[symbol] = quote_data
    #                 logger.info(f"✅ 获取 {symbol} 实时行情成功")
    #             else:
    #                 logger.warning(f"⚠️ 未获取到 {symbol} 的实时行情")
    #         except Exception as e:
    #             logger.error(f"❌ 获取 {symbol} 实时行情失败: {e}")
    #             continue
    #
    #     logger.info(f"✅ 单只接口获取完成，成功 {len(quotes_map)}/{len(symbols)} 只")
    #     return quotes_map

    async def _process_quotes_batch(self, batch: list[str]) -> dict[str, Any]:
        """处理行情批次"""
        batch_stats = {
            "success_count": 0,
            "error_count": 0,
            "errors": [],
            "rate_limit_hit": False
        }

        # 并发获取行情数据
        tasks = []
        for symbol in batch:
            task = self._get_and_save_quotes(symbol)
            tasks.append(task)

        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_msg = str(result)
                batch_stats["error_count"] += 1
                batch_stats["errors"].append({
                    "code": batch[i],
                    "error": error_msg,
                    "context": "_process_quotes_batch"
                })

                # 检测 API 限流错误
                if self._is_rate_limit_error(error_msg):
                    batch_stats["rate_limit_hit"] = True
                    logger.warning(f"⚠️ 检测到 API 限流错误: {error_msg}")

            elif result:
                batch_stats["success_count"] += 1
            else:
                batch_stats["error_count"] += 1
                batch_stats["errors"].append({
                    "code": batch[i],
                    "error": "获取行情数据失败",
                    "context": "_process_quotes_batch"
                })

        return batch_stats

    def _is_rate_limit_error(self, error_msg: str) -> bool:
        """检测是否为 API 限流错误"""
        rate_limit_keywords = [
            "每分钟最多访问",
            "每分钟最多",
            "rate limit",
            "too many requests",
            "访问频率",
            "请求过于频繁"
        ]
        error_msg_lower = error_msg.lower()
        return any(keyword in error_msg_lower for keyword in rate_limit_keywords)

    def _is_trading_time(self) -> bool:
        """
        判断当前是否在交易时间（排除周末和节假日）

        委托给统一的 app.utils.trading_time.is_strict_trading_time
        """
        from app.utils.trading_time import is_strict_trading_time

        return is_strict_trading_time()

    async def _get_and_save_quotes(self, symbol: str) -> bool:
        """获取并保存单个股票行情"""
        try:
            quotes = await self.provider.get_stock_quotes(symbol)
            if quotes:
                # 转换为字典格式（如果是Pydantic模型）
                if hasattr(quotes, 'model_dump'):
                    quotes_data = quotes.model_dump()
                elif hasattr(quotes, 'dict'):
                    quotes_data = quotes.dict()
                else:
                    quotes_data = quotes

                return await self.stock_service.update_market_quotes(symbol, quotes_data)
            return False
        except Exception as e:
            error_msg = str(e)
            # 检测限流错误，直接抛出让上层处理
            if self._is_rate_limit_error(error_msg):
                logger.error(f"❌ 获取 {symbol} 行情失败（限流）: {e}")
                raise  # 抛出限流错误
            logger.error(f"❌ 获取 {symbol} 行情失败: {e}")
            return False

    # ==================== 历史数据同步 ====================

    async def sync_historical_data(
        self,
        symbols: list[str] = None,
        start_date: str = None,
        end_date: str = None,
        incremental: bool = True,
        all_history: bool = False,
        period: str = "daily",
        job_id: str = None
    ) -> dict[str, Any]:
        """
        同步历史数据

        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            incremental: 是否增量同步
            all_history: 是否同步所有历史数据
            period: 数据周期 (daily/weekly/monthly)
            job_id: 任务ID（用于进度跟踪）

        Returns:
            同步结果统计
        """
        period_name = {"daily": "日线", "weekly": "周线", "monthly": "月线"}.get(period, period)
        logger.info(f"🔄 开始同步{period_name}历史数据...")

        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "total_records": 0,
            "start_time": datetime.now(),
            "errors": []
        }

        try:
            # 1. 获取股票列表（排除退市股票）
            if symbols is None:
                # 查询所有A股股票（兼容不同的数据结构），排除退市股票
                # 优先使用 market_info.market，降级到 category 字段
                cursor = self.db.stock_basic_info.find(
                    {
                        "$and": [
                            {
                                "$or": [
                                    {"market_info.market": "CN"},  # 新数据结构
                                    {"category": "stock_cn"},      # 旧数据结构
                                    {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}  # 按市场类型
                                ]
                            },
                            # 排除退市股票
                            {
                                "$or": [
                                    {"status": {"$ne": "D"}},  # status 不是 D（退市）
                                    {"status": {"$exists": False}}  # 或者 status 字段不存在
                                ]
                            }
                        ]
                    },
                    {"code": 1}
                )
                symbols = [doc["code"] async for doc in cursor]
                logger.info(f"📋 从 stock_basic_info 获取到 {len(symbols)} 只股票（已排除退市股票）")

            stats["total_processed"] = len(symbols)

            # 2. 确定全局结束日期
            if not end_date:
                end_date = datetime.now().strftime('%Y-%m-%d')

            # 3. 确定全局起始日期（仅用于日志显示）
            global_start_date = start_date
            if not global_start_date:
                if all_history:
                    global_start_date = "1990-01-01"
                elif incremental:
                    global_start_date = "各股票最后日期"
                else:
                    global_start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

            logger.info(f"📊 历史数据同步: 结束日期={end_date}, 股票数量={len(symbols)}, 模式={'增量' if incremental else '全量'}")

            # 连续失败熔断：API 完全不可用时避免逐只尝试全部股票
            consecutive_failures = 0
            MAX_CONSECUTIVE_FAILURES = 20  # 连续失败20次后终止

            # 真增量：最近一个"理应已有K线数据"的交易日（仅增量模式用于跳过已最新股票）
            latest_settled = self._latest_settled_trade_day() if (incremental and not all_history) else ""

            # 4. 批量处理
            for i, symbol in enumerate(symbols):
                # 记录单个股票开始时间
                stock_start_time = datetime.now()

                try:
                    # 检查是否需要退出
                    if job_id and await self._should_stop(job_id):
                        logger.warning(f"⚠️ 任务 {job_id} 收到停止信号，正在退出...")
                        stats["stopped"] = True
                        break

                    # 确定该股票的起始日期（先于速率限制与API，便于"真增量"跳过）
                    symbol_start_date = start_date
                    if not symbol_start_date:
                        if all_history:
                            symbol_start_date = "1990-01-01"
                        elif incremental:
                            # 增量同步：获取该股票的最后日期
                            symbol_start_date = await self._get_last_sync_date(symbol)
                            logger.debug(f"📅 {symbol}: 从 {symbol_start_date} 开始同步")
                        else:
                            symbol_start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

                    # 真增量跳过：最后同步日已覆盖最近应有数据交易日 → 无需调API
                    if incremental and latest_settled and symbol_start_date and symbol_start_date > latest_settled:
                        stats["skipped_count"] += 1
                        consecutive_failures = 0
                        logger.debug(f"⏭️ {symbol}: 已是最新（最后同步 {symbol_start_date}），跳过API")
                        if job_id and ((i + 1) % 50 == 0 or (i + 1) == len(symbols)):
                            progress_percent = int(((i + 1) / len(symbols)) * 100)
                            await self._update_progress(
                                job_id, progress_percent,
                                f"正在检查最新状态 {symbol} ({i + 1}/{len(symbols)}，已跳过 {stats['skipped_count']} 只最新)…"
                            )
                        continue

                    # 速率限制
                    await self.rate_limiter.acquire()

                    # 记录请求参数
                    logger.debug(
                        f"🔍 {symbol}: 请求{period_name}数据 "
                        f"start={symbol_start_date}, end={end_date}, period={period}"
                    )

                    # ⏱️ 性能监控：API 调用
                    api_start = datetime.now()
                    df = await self.provider.get_historical_data(symbol, symbol_start_date, end_date, period=period)
                    api_duration = (datetime.now() - api_start).total_seconds()

                    if df is not None and not df.empty:
                        # ⏱️ 性能监控：数据保存
                        save_start = datetime.now()
                        records_saved = await self._save_historical_data(symbol, df, period=period)
                        save_duration = (datetime.now() - save_start).total_seconds()

                        stats["success_count"] += 1
                        stats["total_records"] += records_saved

                        # 计算单个股票耗时
                        stock_duration = (datetime.now() - stock_start_time).total_seconds()
                        logger.info(
                            f"✅ {symbol}: 保存 {records_saved} 条{period_name}记录，"
                            f"总耗时 {stock_duration:.2f}秒 "
                            f"(API: {api_duration:.2f}秒, 保存: {save_duration:.2f}秒)"
                        )
                    else:
                        stock_duration = (datetime.now() - stock_start_time).total_seconds()
                        logger.warning(
                            f"⚠️ {symbol}: 无{period_name}数据 "
                            f"(start={symbol_start_date}, end={end_date})，耗时 {stock_duration:.2f}秒"
                        )

                    # API 调用成功（无论有无数据），重置连续失败计数
                    consecutive_failures = 0

                    # 每个股票都更新进度
                    progress_percent = int(((i + 1) / len(symbols)) * 100)

                    # 更新任务进度
                    if job_id:
                        await self._update_progress(
                            job_id,
                            progress_percent,
                            f"正在同步 {symbol} ({i + 1}/{len(symbols)})"
                        )

                    # 每50个股票输出一次详细日志
                    if (i + 1) % 50 == 0 or (i + 1) == len(symbols):
                        logger.info(f"📈 {period_name}数据同步进度: {i + 1}/{len(symbols)} ({progress_percent}%) "
                                   f"(成功: {stats['success_count']}, 记录: {stats['total_records']})")

                        # 输出速率限制器统计
                        limiter_stats = self.rate_limiter.get_stats()
                        logger.info(f"   速率限制: {limiter_stats['current_calls']}/{limiter_stats['max_calls']}次, "
                                   f"等待次数: {limiter_stats['total_waits']}, "
                                   f"总等待时间: {limiter_stats['total_wait_time']:.1f}秒")

                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    stats["error_count"] += 1
                    stats["errors"].append({
                        "code": symbol,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "context": f"sync_historical_data_{period}",
                        "traceback": error_details
                    })
                    logger.error(
                        f"❌ {symbol} {period_name}数据同步失败\n"
                        f"   参数: start={symbol_start_date if 'symbol_start_date' in locals() else 'N/A'}, "
                        f"end={end_date}, period={period}\n"
                        f"   错误类型: {type(e).__name__}\n"
                        f"   错误信息: {str(e)}\n"
                        f"   堆栈跟踪:\n{error_details}"
                    )

                    # 连续失败熔断：API 完全不可用时避免逐只尝试全部股票
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(f"🚨 连续 {MAX_CONSECUTIVE_FAILURES} 只股票同步失败，终止同步")
                        stats["stopped"] = True
                        stats["stop_reason"] = f"连续 {MAX_CONSECUTIVE_FAILURES} 次失败"
                        break

            # 4. 完成统计
            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

            logger.info(f"✅ {period_name}数据同步完成: "
                       f"股票 {stats['success_count']}/{stats['total_processed']}, "
                       f"跳过最新 {stats['skipped_count']}, "
                       f"记录 {stats['total_records']} 条, "
                       f"错误 {stats['error_count']} 个, "
                       f"耗时 {stats['duration']:.2f} 秒")

            return stats

        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logger.error(
                f"❌ 历史数据同步失败（外层异常）\n"
                f"   错误类型: {type(e).__name__}\n"
                f"   错误信息: {str(e)}\n"
                f"   堆栈跟踪:\n{error_details}"
            )
            stats["errors"].append({
                "error": str(e),
                "error_type": type(e).__name__,
                "context": "sync_historical_data",
                "traceback": error_details
            })
            return stats

    async def _save_historical_data(self, symbol: str, df, period: str = "daily") -> int:
        """保存历史数据到数据库"""
        try:
            if self.historical_service is None:
                self.historical_service = await get_historical_data_service()

            # 使用统一历史数据服务保存（指定周期）
            saved_count = await self.historical_service.save_historical_data(
                symbol=symbol,
                data=df,
                data_source="tushare",
                market="CN",
                period=period
            )

            return saved_count

        except Exception as e:
            logger.error(f"❌ 保存{period}数据失败 {symbol}: {e}")
            return 0

    async def _get_last_sync_date(self, symbol: str = None) -> str:
        """
        获取最后同步日期

        Args:
            symbol: 股票代码，如果提供则返回该股票的最后日期+1天

        Returns:
            日期字符串 (YYYY-MM-DD)
        """
        try:
            if self.historical_service is None:
                self.historical_service = await get_historical_data_service()

            if symbol:
                # 获取特定股票的最新日期
                latest_date = await self.historical_service.get_latest_date(symbol, "tushare")
                if latest_date:
                    # 返回最后日期的下一天（避免重复同步）
                    try:
                        last_date_obj = datetime.strptime(latest_date, '%Y-%m-%d')
                        next_date = last_date_obj + timedelta(days=1)
                        return next_date.strftime('%Y-%m-%d')
                    except Exception:
                        # 如果日期格式不对，直接返回
                        return latest_date
                else:
                    # 🔥 没有历史数据时，从上市日期开始全量同步
                    stock_info = await self.db.stock_basic_info.find_one(
                        {"code": symbol},
                        {"list_date": 1}
                    )
                    if stock_info and stock_info.get("list_date"):
                        list_date = stock_info["list_date"]
                        # 处理不同的日期格式
                        if isinstance(list_date, str):
                            # 格式可能是 "20100101" 或 "2010-01-01"
                            if len(list_date) == 8 and list_date.isdigit():
                                return f"{list_date[:4]}-{list_date[4:6]}-{list_date[6:]}"
                            else:
                                return list_date
                        else:
                            return list_date.strftime('%Y-%m-%d')

                    # 如果没有上市日期，从1990年开始
                    logger.warning(f"⚠️ {symbol}: 未找到上市日期，从1990-01-01开始同步")
                    return "1990-01-01"

            # 默认返回30天前（确保不漏数据）
            return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

        except Exception as e:
            logger.error(f"❌ 获取最后同步日期失败 {symbol}: {e}")
            # 出错时返回30天前，确保不漏数据
            return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')

    def _latest_settled_trade_day(self) -> str:
        """返回最近一个"理应已有K线数据"的交易日（YYYY-MM-DD）。

        用于真增量跳过：晚间 cron（TUSHARE_HISTORICAL_SYNC_CRON=18:30）才会拉取当日K线；
        在 18:30 之前的启动补跑/白天同步里，当日K线尚未落地，理应只有上一交易日的完整数据，
        因此回退到上一交易日，避免为尚未发布的当日K线空跑全市场。

        格式统一为 YYYY-MM-DD，可直接与 _get_last_sync_date 返回的字符串做字典序比较。
        """
        try:
            from app.utils.trading_time import get_latest_trade_day, is_trading_day

            now = datetime.now()
            target = get_latest_trade_day(now)
            # 交易日当日 18:30 前，当日K线未落地，回退到上一交易日
            if is_trading_day(now) and (now.hour, now.minute) < (18, 30):
                cursor = target - timedelta(days=1)
                while not is_trading_day(cursor):
                    cursor -= timedelta(days=1)
                target = cursor
            return target.strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"⚠️ 计算最近应有数据交易日失败，退化为不跳过: {e}")
            return ""

    # ==================== 财务数据同步 ====================

    async def sync_financial_data(self, symbols: list[str] = None, limit: int = 20, job_id: str = None) -> dict[str, Any]:
        """
        同步财务数据

        Args:
            symbols: 股票代码列表，None表示同步所有股票
            limit: 获取财报期数，默认20期（约5年数据）
            job_id: 任务ID（用于进度跟踪）
        """
        logger.info(f"🔄 开始同步财务数据 (获取最近 {limit} 期)...")

        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": datetime.now(),
            "errors": []
        }

        try:
            # 获取股票列表
            if symbols is None:
                cursor = self.db.stock_basic_info.find(
                    {
                        "$or": [
                            {"market_info.market": "CN"},  # 新数据结构
                            {"category": "stock_cn"},      # 旧数据结构
                            {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}  # 按市场类型
                        ]
                    },
                    {"code": 1}
                )
                symbols = [doc["code"] async for doc in cursor]
                logger.info(f"📋 从 stock_basic_info 获取到 {len(symbols)} 只股票")

            stats["total_processed"] = len(symbols)
            logger.info(f"📊 需要同步 {len(symbols)} 只股票财务数据")

            # 并发控制：信号量限制同时进行的请求数（实际调用频率仍受速率限制器约束）
            semaphore = asyncio.Semaphore(20)

            async def _process_one(symbol: str):
                try:
                    # 速率限制
                    await self.rate_limiter.acquire()

                    # 获取财务数据（指定获取期数）
                    financial_data = await self.provider.get_financial_data(symbol, limit=limit)

                    if financial_data:
                        # 保存财务数据
                        success = await self._save_financial_data(symbol, financial_data)
                        return symbol, "success" if success else "error", "" if success else "保存财务数据失败"
                    else:
                        logger.warning(f"⚠️ {symbol}: 无财务数据")
                        return symbol, "success", ""
                except Exception as e:
                    logger.error(f"❌ {symbol} 财务数据同步失败: {e}")
                    return symbol, "error", str(e)

            async def _run(symbol: str):
                async with semaphore:
                    return await _process_one(symbol)

            # 分批并发处理
            BATCH = 50
            processed = 0
            for i in range(0, len(symbols), BATCH):
                batch = symbols[i:i + BATCH]
                results = await asyncio.gather(
                    *[_run(s) for s in batch],
                    return_exceptions=True
                )
                for r in results:
                    if isinstance(r, Exception):
                        stats["error_count"] += 1
                        stats["errors"].append({
                            "code": "?",
                            "error": str(r),
                            "context": "sync_financial_data"
                        })
                        continue
                    symbol, status, err = r
                    if status == "success":
                        stats["success_count"] += 1
                    else:
                        stats["error_count"] += 1
                        stats["errors"].append({
                            "code": symbol,
                            "error": err or "同步失败",
                            "context": "sync_financial_data"
                        })

                processed += len(batch)
                progress = int(processed / len(symbols) * 100)
                logger.info(f"📈 财务数据同步进度: {processed}/{len(symbols)} ({progress}%) "
                            f"(成功: {stats['success_count']}, 错误: {stats['error_count']})")

                # 更新任务进度
                if job_id:
                    from app.services.scheduler_service import TaskCancelledException, update_job_progress
                    try:
                        await update_job_progress(
                            job_id=job_id,
                            progress=progress,
                            message=f"正在同步财务数据 {processed}/{len(symbols)}",
                            current_item=batch[-1],
                            total_items=len(symbols),
                            processed_items=processed
                        )
                    except TaskCancelledException:
                        # 任务被取消，记录并退出
                        logger.warning(f"⚠️ 财务数据同步任务被用户取消 (已处理 {processed}/{len(symbols)})")
                        stats["end_time"] = datetime.now()
                        stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()
                        stats["cancelled"] = True
                        raise

            # 完成统计
            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

            logger.info(f"✅ 财务数据同步完成: "
                       f"成功 {stats['success_count']}/{stats['total_processed']}, "
                       f"错误 {stats['error_count']} 个, "
                       f"耗时 {stats['duration']:.2f} 秒")

            return stats

        except Exception as e:
            logger.error(f"❌ 财务数据同步失败: {e}")
            stats["errors"].append({"error": str(e), "context": "sync_financial_data"})
            return stats

    async def _save_financial_data(self, symbol: str, financial_data) -> bool:
        """保存财务数据。

        兼容两种输入：
        - str：旧版 get_fundamentals 返回的格式化文本，需先解析；
        - dict：单期财务数据；
        - list[dict]：多期财务数据（Tushare fina_indicator 新实现），逐期 upsert。
        """
        try:
            # 兼容旧文本格式（get_fundamentals 返回文本）
            if isinstance(financial_data, str):
                financial_data = self._parse_financial_text(symbol, financial_data)
                if not financial_data:
                    logger.warning(f"⚠️ {symbol} 财务数据文本解析后为空，跳过保存")
                    return False

            if isinstance(financial_data, list):
                # 多期数据：过滤空条目，逐期保存（report_period 由每期记录自带）
                financial_data = [d for d in financial_data if isinstance(d, dict)]
                if not financial_data:
                    logger.warning(f"⚠️ {symbol} 财务数据列表为空，跳过保存")
                    return False
                report_period = None
            elif isinstance(financial_data, dict):
                report_period = financial_data.get("report_period")
            else:
                logger.warning(f"⚠️ {symbol} 财务数据类型异常: {type(financial_data)}, 跳过保存")
                return False

            # 使用统一的财务数据服务
            from app.services.financial_data_service import get_financial_data_service

            financial_service = await get_financial_data_service()

            # 保存财务数据
            saved_count = await financial_service.save_financial_data(
                symbol=symbol,
                financial_data=financial_data,
                data_source="tushare",
                market="CN",
                report_period=report_period,
                report_type=financial_data[-1].get("report_type", "quarterly")
                if isinstance(financial_data, list) else financial_data.get("report_type", "quarterly")
            )

            return saved_count > 0

        except Exception as e:
            logger.error(f"❌ 保存 {symbol} 财务数据失败: {e}")
            return False

    # ==================== 分红数据同步 ====================

    async def sync_dividend_data(self, symbols: list[str] = None, job_id: str = None) -> dict[str, Any]:
        """同步分红送配数据到 stock_dividend 集合。

        每条公告记录一个文档（按 code+ann_date upsert），供筛选策略计算股息率与分红稳定性。
        """
        logger.info("🔄 开始同步分红送配数据...")

        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "record_count": 0,
            "start_time": datetime.now(),
            "errors": []
        }

        try:
            # 获取股票列表
            if symbols is None:
                cursor = self.db.stock_basic_info.find(
                    {
                        "$or": [
                            {"market_info.market": "CN"},
                            {"category": "stock_cn"},
                            {"market": {"$in": ["主板", "创业板", "科创板", "北交所"]}}
                        ]
                    },
                    {"code": 1}
                )
                symbols = [doc["code"] async for doc in cursor]

            stats["total_processed"] = len(symbols)
            logger.info(f"📋 需要同步 {len(symbols)} 只股票的分红数据")

            # 并发控制：信号量限制同时进行的请求数（实际调用频率仍受速率限制器约束）
            semaphore = asyncio.Semaphore(20)

            async def _process_one(symbol: str):
                try:
                    await self.rate_limiter.acquire()
                    records = await self.provider.get_dividend_data(symbol)
                    if records:
                        saved = await self._save_dividend_data(symbol, records)
                        if saved > 0:
                            return symbol, "success", saved
                        return symbol, "error", "分红数据保存失败"
                    # 无分红记录（如新股），计入成功但跳过
                    return symbol, "success", 0
                except Exception as e:
                    logger.error(f"❌ {symbol} 分红数据同步失败: {e}")
                    return symbol, "error", str(e)

            async def _run(symbol: str):
                async with semaphore:
                    return await _process_one(symbol)

            # 分批并发处理
            BATCH = 50
            processed = 0
            for i in range(0, len(symbols), BATCH):
                batch = symbols[i:i + BATCH]
                results = await asyncio.gather(
                    *[_run(s) for s in batch],
                    return_exceptions=True
                )
                for r in results:
                    if isinstance(r, Exception):
                        stats["error_count"] += 1
                        stats["errors"].append({
                            "code": "?",
                            "error": str(r),
                            "context": "sync_dividend_data"
                        })
                        continue
                    symbol, status, payload = r
                    if status == "success":
                        stats["success_count"] += 1
                        if isinstance(payload, int):
                            stats["record_count"] += payload
                    else:
                        stats["error_count"] += 1
                        stats["errors"].append({
                            "code": symbol,
                            "error": payload or "同步失败",
                            "context": "sync_dividend_data"
                        })

                processed += len(batch)
                progress = int(processed / len(symbols) * 100)
                logger.info(f"📈 分红数据同步进度: {processed}/{len(symbols)} ({progress}%) "
                            f"(成功: {stats['success_count']}, 记录: {stats['record_count']}, "
                            f"错误: {stats['error_count']})")
                if job_id:
                    await self._update_progress(
                        job_id,
                        progress,
                        f"正在同步分红数据 {processed}/{len(symbols)}"
                    )

            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

            logger.info(f"✅ 分红数据同步完成: "
                       f"成功 {stats['success_count']}/{stats['total_processed']}, "
                       f"记录 {stats['record_count']} 条, "
                       f"错误 {stats['error_count']} 个, "
                       f"耗时 {stats['duration']:.2f} 秒")

            return stats

        except Exception as e:
            logger.error(f"❌ 分红数据同步失败(外层): {e}")
            stats["errors"].append({"error": str(e), "context": "sync_dividend_data"})
            return stats

    async def _save_dividend_data(self, symbol: str, records: list[dict]) -> int:
        """保存单只股票的分红记录到 stock_dividend 集合（按 code+ann_date upsert）。"""
        if not records:
            return 0

        from pymongo import UpdateOne

        ops = []
        saved = 0
        for r in records:
            ann_date = _norm_date(r.get("ann_date"))
            if not ann_date:
                continue
            doc = {
                "symbol": symbol,
                "code": symbol,
                "ts_code": r.get("ts_code") or "",
                "ann_date": ann_date,
                "end_date": _norm_date(r.get("end_date")),
                "div_proc": r.get("div_proc") or "",
                "stk_div": _to_float(r.get("stk_div")),
                "cash_div": _to_float(r.get("cash_div")),
                "cash_div_tax": _to_float(r.get("cash_div_tax")),
                "record_date": _norm_date(r.get("record_date")),
                "ex_date": _norm_date(r.get("ex_date")),
                "pay_date": _norm_date(r.get("pay_date")),
                "data_source": "tushare",
                "updated_at": get_utc8_now(),
            }
            ops.append(UpdateOne(
                {"code": symbol, "ann_date": ann_date},
                {"$set": doc},
                upsert=True,
            ))

        if ops:
            await self.db.stock_dividend.bulk_write(ops, ordered=False)
            saved = len(ops)
        return saved

    # ==================== 每日估值/市值数据同步 ====================

    def _get_trade_days_blocking(self, start: str, end: str) -> list[str]:
        """用 Tushare trade_cal 获取 [start, end] 内的交易日（YYYY-MM-DD 升序）。

        阻塞式：供 asyncio.to_thread 调用。
        """
        import tushare as ts
        token = getattr(self.provider, "token", None)
        if not token:
            import os
            token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
        if not token:
            logger.warning("Tushare token 缺失，无法获取交易日历")
            return []
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.trade_cal(
            exchange="SSE",
            start_date=_compact_date(start),
            end_date=_compact_date(end),
            is_open="1",
        )
        if df is None or getattr(df, "empty", True):
            return []
        days = []
        for val in df["cal_date"]:
            s = str(val)
            if len(s) == 8 and s.isdigit():
                days.append(f"{s[:4]}-{s[4:6]}-{s[6:]}")
        return sorted(days)

    async def sync_daily_basic_data(
        self,
        start_date: str = None,
        end_date: str = None,
        days_back: int = 730,
        job_id: str = None,
    ) -> dict[str, Any]:
        """同步每日估值/市值数据（Tushare daily_basic）到 stock_daily_basic 集合。

        按交易日逐日拉取全市场 daily_basic，按 (code, trade_date) upsert 入库，
        供回测按日对齐历史 PE/PB/市值，替代"最新快照逐日广播"。

        - 默认同步最近 days_back 天（实际只请求交易日）；
        - 已同步的交易日自动跳过（增量）；
        - 单位约定：total_mv/circ_mv 由万元转为亿元（与 stock_basic_info 一致）。

        Args:
            start_date: 起始日期 YYYY-MM-DD（默认 now - days_back 天）
            end_date: 结束日期 YYYY-MM-DD（默认今天）
            days_back: 未指定 start_date 时回溯天数
            job_id: 任务ID（用于进度跟踪）
        """
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "total_records": 0,
            "start_time": datetime.now(),
            "errors": [],
        }

        end = _norm_date(end_date) or datetime.now().strftime("%Y-%m-%d")
        start = _norm_date(start_date) or (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        if not start or not end or start > end:
            logger.error(f"❌ 每日估值同步日期区间非法: {start} ~ {end}")
            return {"error": f"invalid date range: {start} ~ {end}"}

        logger.info(f"🔄 开始同步每日估值数据: {start} ~ {end}")

        # 1) 获取交易日历
        try:
            trade_days = await asyncio.to_thread(self._get_trade_days_blocking, start, end)
        except Exception as e:
            logger.error(f"❌ 获取交易日历失败: {e}")
            return {"error": str(e)}
        if not trade_days:
            logger.warning(f"⚠️ {start}~{end} 区间无交易日")
            return stats
        stats["total_processed"] = len(trade_days)

        # 2) 已同步交易日（增量跳过）
        synced: set[str] = set()
        cursor = self.db.stock_daily_basic.find(
            {"trade_date": {"$gte": start, "$lte": end}}, {"trade_date": 1}
        )
        async for doc in cursor:
            d = str(doc.get("trade_date") or "")
            if d:
                synced.add(d)

        # 3) 逐日拉取并入库
        adapter = TushareAdapter()
        from pymongo import UpdateOne

        for i, td in enumerate(trade_days):
            if job_id and await self._should_stop(job_id):
                logger.warning(f"⚠️ 任务 {job_id} 收到停止信号，正在退出...")
                stats["stopped"] = True
                break

            if td in synced:
                stats["skipped_count"] += 1
                continue

            await self.rate_limiter.acquire()
            try:
                df = await asyncio.to_thread(adapter.get_daily_basic, _compact_date(td))
                if df is None or getattr(df, "empty", True):
                    stats["error_count"] += 1
                    continue
            except Exception as e:
                stats["error_count"] += 1
                stats["errors"].append({"date": td, "error": str(e)})
                logger.error(f"❌ {td} 拉取 daily_basic 失败: {e}")
                continue

            ops = []
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code") or "")
                if "." not in ts_code:
                    continue
                code = ts_code.split(".")[0]
                total_mv = _to_float(row.get("total_mv"))
                circ_mv = _to_float(row.get("circ_mv"))
                doc = {
                    "symbol": code,
                    "code": code,
                    "ts_code": ts_code,
                    "trade_date": td,
                    # 市值单位：万元 -> 亿元（与 stock_basic_info 保持一致）
                    "total_mv": round(total_mv / 10000.0, 6) if total_mv is not None else None,
                    "circ_mv": round(circ_mv / 10000.0, 6) if circ_mv is not None else None,
                    "pe": _to_float(row.get("pe")),
                    "pb": _to_float(row.get("pb")),
                    "ps": _to_float(row.get("ps")),
                    "pe_ttm": _to_float(row.get("pe_ttm")),
                    "pb_mrq": _to_float(row.get("pb_mrq")),
                    "ps_ttm": _to_float(row.get("ps_ttm")),
                    "turnover_rate": _to_float(row.get("turnover_rate")),
                    "volume_ratio": _to_float(row.get("volume_ratio")),
                    "total_share": _to_float(row.get("total_share")),
                    "float_share": _to_float(row.get("float_share")),
                    "data_source": "tushare",
                    "updated_at": get_utc8_now(),
                }
                ops.append(UpdateOne(
                    {"code": code, "trade_date": td},
                    {"$set": doc},
                    upsert=True,
                ))

            if ops:
                await self.db.stock_daily_basic.bulk_write(ops, ordered=False)
                stats["success_count"] += 1
                stats["total_records"] += len(ops)

            if job_id and ((i + 1) % 5 == 0 or (i + 1) == len(trade_days)):
                await self._update_progress(
                    job_id,
                    int(((i + 1) / len(trade_days)) * 100),
                    f"正在同步每日估值 {td} ({i + 1}/{len(trade_days)})…",
                )

        stats["finished_at"] = datetime.now().isoformat()
        logger.info(f"✅ 每日估值数据同步完成: 交易日={stats['total_processed']}, "
                    f"入库={stats['success_count']}, 跳过={stats['skipped_count']}, "
                    f"记录={stats['total_records']}, 失败={stats['error_count']}")
        return stats

    @staticmethod
    def _parse_financial_text(symbol: str, text: str) -> dict[str, Any]:
        """将 get_fundamentals 返回的格式化文本解析为结构化 dict。

        文本格式示例：
            Name: 贵州茅台
            Price: 1689.00
            PE (TTM): 30.5
            PE (Static): 32.1
            PB: 12.3
            ...
        """
        result: dict[str, Any] = {"symbol": symbol, "data_source": "tushare"}

        for line in text.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            # 按第一个冒号分割
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()

            # 映射常见字段
            if key == "name":
                result["name"] = val
            elif key in ("price", "current_price"):
                with contextlib.suppress(ValueError):
                    result["current_price"] = float(val)
            elif "pe_ttm" in key or key == "pe (ttm)":
                with contextlib.suppress(ValueError):
                    result["pe_ttm"] = float(val)
            elif "pe_static" in key or key == "pe (static)":
                with contextlib.suppress(ValueError):
                    result["pe_static"] = float(val)
            elif key == "pb":
                with contextlib.suppress(ValueError):
                    result["pb"] = float(val)
            elif key == "roe":
                with contextlib.suppress(ValueError):
                    result["roe"] = float(val)
            elif "total_mv" in key or "总市值" in key:
                with contextlib.suppress(ValueError):
                    result["total_mv"] = float(val.replace("亿", "").strip())
            elif "circ_mv" in key or "流通市值" in key:
                with contextlib.suppress(ValueError):
                    result["circ_mv"] = float(val.replace("亿", "").strip())
            elif "turnover" in key or "换手" in key:
                with contextlib.suppress(ValueError):
                    result["turnover_rate"] = float(val.replace("%", "").strip())
            elif "volume" in key or "成交量" in key:
                with contextlib.suppress(ValueError):
                    result["volume"] = float(val)
            elif "amount" in key or "成交额" in key:
                with contextlib.suppress(ValueError):
                    result["amount"] = float(val)

        # 生成默认 report_period（当前季度末）
        from datetime import datetime
        now = datetime.now()
        quarter_month = ((now.month - 1) // 3) * 3 + 1  # 1/4/7/10
        result["report_period"] = f"{now.year}{quarter_month:02d}30"
        result["report_type"] = "quarterly"
        result["raw_text"] = text[:2000]  # 保留原始文本前2000字符用于调试

        return result

    # ==================== 辅助方法 ====================

    def _is_data_fresh(self, updated_at: datetime, hours: int = 24) -> bool:
        """检查数据是否新鲜"""
        if not updated_at:
            return False

        threshold = datetime.now() - timedelta(hours=hours)
        return updated_at > threshold

    async def get_sync_status(self) -> dict[str, Any]:
        """获取同步状态"""
        try:
            # 统计各集合的数据量
            basic_info_count = await self.db.stock_basic_info.count_documents({})
            quotes_count = await self.db.market_quotes.count_documents({})

            # 获取最新更新时间
            latest_basic = await self.db.stock_basic_info.find_one(
                {},
                sort=[("updated_at", -1)]
            )
            latest_quotes = await self.db.market_quotes.find_one(
                {},
                sort=[("updated_at", -1)]
            )

            return {
                "provider_connected": self.provider.is_available(),
                "collections": {
                    "stock_basic_info": {
                        "count": basic_info_count,
                        "latest_update": latest_basic.get("updated_at") if (latest_basic and isinstance(latest_basic, dict)) else None
                    },
                    "market_quotes": {
                        "count": quotes_count,
                        "latest_update": latest_quotes.get("updated_at") if (latest_quotes and isinstance(latest_quotes, dict)) else None
                    }
                },
                "status_time": datetime.now()
            }

        except Exception as e:
            logger.error(f"❌ 获取同步状态失败: {e}")
            return {"error": str(e)}

    # ==================== 新闻数据同步 ====================

    async def sync_news_data(
        self,
        symbols: list[str] = None,
        hours_back: int = 24,
        max_news_per_stock: int = 20,
        force_update: bool = False,
        job_id: str = None
    ) -> dict[str, Any]:
        """
        同步新闻数据

        Args:
            symbols: 股票代码列表，为None时获取所有股票
            hours_back: 回溯小时数，默认24小时
            max_news_per_stock: 每只股票最大新闻数量
            force_update: 是否强制更新
            job_id: 任务ID（用于进度跟踪）

        Returns:
            同步结果统计
        """
        logger.info("🔄 开始同步新闻数据...")

        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "news_count": 0,
            "start_time": datetime.now(),
            "errors": []
        }

        try:
            # 1. 获取股票列表
            if symbols is None:
                stock_list = await self.stock_service.get_all_stocks()
                symbols = [stock["code"] for stock in stock_list]

            if not symbols:
                logger.warning("⚠️ 没有找到需要同步新闻的股票")
                return stats

            stats["total_processed"] = len(symbols)
            logger.info(f"📊 需要同步 {len(symbols)} 只股票的新闻")

            # 2. 批量处理
            for i in range(0, len(symbols), self.batch_size):
                # 检查是否需要退出
                if job_id and await self._should_stop(job_id):
                    logger.warning(f"⚠️ 任务 {job_id} 收到停止信号，正在退出...")
                    stats["stopped"] = True
                    break

                batch = symbols[i:i + self.batch_size]
                batch_stats = await self._process_news_batch(
                    batch, hours_back, max_news_per_stock
                )

                # 更新统计
                stats["success_count"] += batch_stats["success_count"]
                stats["error_count"] += batch_stats["error_count"]
                stats["news_count"] += batch_stats["news_count"]
                stats["errors"].extend(batch_stats["errors"])

                # 进度日志和进度更新
                progress = min(i + self.batch_size, len(symbols))
                progress_percent = int((progress / len(symbols)) * 100)
                logger.info(f"📈 新闻同步进度: {progress}/{len(symbols)} ({progress_percent}%) "
                           f"(成功: {stats['success_count']}, 新闻: {stats['news_count']})")

                # 更新任务进度
                if job_id:
                    await self._update_progress(
                        job_id,
                        progress_percent,
                        f"已处理 {progress}/{len(symbols)} 只股票，获取 {stats['news_count']} 条新闻"
                    )

                # API限流
                if i + self.batch_size < len(symbols):
                    await asyncio.sleep(self.rate_limit_delay)

            # 3. 完成统计
            stats["end_time"] = datetime.now()
            stats["duration"] = (stats["end_time"] - stats["start_time"]).total_seconds()

            logger.info(f"✅ 新闻数据同步完成: "
                       f"总计 {stats['total_processed']} 只股票, "
                       f"成功 {stats['success_count']} 只, "
                       f"获取 {stats['news_count']} 条新闻, "
                       f"错误 {stats['error_count']} 只, "
                       f"耗时 {stats['duration']:.2f} 秒")

            return stats

        except Exception as e:
            logger.error(f"❌ 新闻数据同步失败: {e}")
            stats["errors"].append({"error": str(e), "context": "sync_news_data"})
            return stats

    async def _process_news_batch(
        self,
        batch: list[str],
        hours_back: int,
        max_news_per_stock: int
    ) -> dict[str, Any]:
        """处理新闻批次（并发拉取，避免逐只串行导致的低效与长耗时）"""
        batch_stats = {
            "success_count": 0,
            "error_count": 0,
            "news_count": 0,
            "errors": []
        }

        # 并发控制：信号量限制同时进行的请求数，避免瞬时请求过多
        semaphore = asyncio.Semaphore(20)

        async def _process_one(symbol: str):
            try:
                # 从Tushare获取新闻数据
                news_data = await self.provider.get_stock_news(
                    symbol=symbol,
                    limit=max_news_per_stock,
                    hours_back=hours_back
                )

                if news_data:
                    # 保存新闻数据
                    saved_count = await self.news_service.save_news_data(
                        news_data=news_data,
                        data_source="tushare",
                        market="CN"
                    )
                    logger.debug(f"✅ {symbol} 新闻同步成功: {saved_count}条")
                    return "success", saved_count
                else:
                    logger.debug(f"⚠️ {symbol} 未获取到新闻数据")
                    return "success", 0  # 没有新闻也算成功

            except Exception as e:
                return "error", f"{symbol}: {str(e)}"

        async def _run(symbol: str):
            async with semaphore:
                status, payload = await _process_one(symbol)
                # API 限流：成功/失败后适度休眠，避免高频请求与"失败雪崩"
                await asyncio.sleep(0.2 if status == "success" else 1.0)
                return symbol, status, payload

        results = await asyncio.gather(*[_run(s) for s in batch], return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                batch_stats["error_count"] += 1
                batch_stats["errors"].append(str(r))
                logger.error(f"❌ 新闻同步失败: {r}")
                continue
            symbol, status, payload = r
            if status == "success":
                batch_stats["success_count"] += 1
                batch_stats["news_count"] += payload
            else:
                batch_stats["error_count"] += 1
                batch_stats["errors"].append(payload)
                logger.error(f"❌ {symbol} 新闻同步失败: {payload}")

        return batch_stats

    # ==================== 进度跟踪辅助方法 ====================

    async def _should_stop(self, job_id: str) -> bool:
        """
        检查任务是否应该停止

        Args:
            job_id: 任务ID

        Returns:
            是否应该停止
        """
        try:
            # 查询执行记录，检查 cancel_requested 标记
            execution = await self.db.scheduler_executions.find_one(
                {"job_id": job_id, "status": "running"},
                sort=[("timestamp", -1)]
            )

            return bool(execution and execution.get("cancel_requested"))

        except Exception as e:
            logger.error(f"❌ 检查任务停止标记失败: {e}")
            return False

    async def _update_progress(self, job_id: str, progress: int, message: str):
        """
        更新任务进度

        Args:
            job_id: 任务ID
            progress: 进度百分比 (0-100)
            message: 进度消息
        """
        try:
            from app.services.scheduler_service import TaskCancelledException

            logger.info(f"📊 [进度更新] 开始更新任务 {job_id} 进度: {progress}% - {message}")

            # 使用模块级单例同步客户端（避免每次调用都新建 MongoClient）
            sync_db = _get_sync_db()

            # 查找最新的 running 记录
            execution = sync_db.scheduler_executions.find_one(
                {"job_id": job_id, "status": "running"},
                sort=[("timestamp", -1)]
            )

            if not execution:
                logger.warning(f"⚠️ 未找到任务 {job_id} 的执行记录")
                return

            # 检查是否收到取消请求
            if execution.get("cancel_requested"):
                raise TaskCancelledException(f"任务 {job_id} 已被用户取消")

            # 更新进度（使用 UTC+8 时间）
            sync_db.scheduler_executions.update_one(
                {"_id": execution["_id"]},
                {
                    "$set": {
                        "progress": progress,
                        "progress_message": message,
                        "updated_at": get_utc8_now()
                    }
                }
            )

            logger.info(f"✅ 任务 {job_id} 进度更新成功: {progress}% - {message}")

        except Exception as e:
            if type(e).__name__ == "TaskCancelledException":
                raise
            logger.error(f"❌ 更新任务进度失败: {e}", exc_info=True)


# 全局同步服务实例
_tushare_sync_service = None

async def get_tushare_sync_service() -> TushareSyncService:
    """获取Tushare同步服务实例"""
    global _tushare_sync_service
    if _tushare_sync_service is None:
        _tushare_sync_service = TushareSyncService()
        await _tushare_sync_service.initialize()
    return _tushare_sync_service


# APScheduler兼容的任务函数
async def run_tushare_basic_info_sync(force_update: bool = False):
    """APScheduler任务：同步股票基础信息"""
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_stock_basic_info(force_update, job_id="tushare_basic_info_sync")
        logger.info(f"✅ Tushare基础信息同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare基础信息同步失败: {e}")
        raise


async def run_tushare_quotes_sync(force: bool = False):
    """
    APScheduler任务：同步实时行情

    Args:
        force: 是否强制执行（跳过交易时间检查），默认 False
    """
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_realtime_quotes(force=force)
        logger.info(f"✅ Tushare行情同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare行情同步失败: {e}")
        raise


async def run_tushare_historical_sync(incremental: bool = True):
    """APScheduler任务：同步历史数据"""
    logger.info(f"🚀 [APScheduler] 开始执行 Tushare 历史数据同步任务 (incremental={incremental})")
    # 🔧 交易日门控：非交易日（周末/法定节假日）直接跳过，避免节假日全量拉取 0 条新数据浪费资源。
    # 注意：cron 表达式 `1-5` 只排除周末，无法识别 A 股法定节假日，必须在函数内再校验一次。
    try:
        from app.utils.trading_time import is_trading_day
        if not is_trading_day(datetime.now()):
            logger.info("⏭️ [APScheduler] 非交易日，跳过 Tushare 历史数据同步")
            return {
                "skipped": "non_trading_day",
                "total_processed": 0,
                "success_count": 0,
                "error_count": 0,
                "total_records": 0,
            }
    except Exception as _e:
        logger.warning(f"⚠️ [APScheduler] 交易日判断异常，继续执行同步: {_e}")
    try:
        service = await get_tushare_sync_service()
        logger.info("✅ [APScheduler] Tushare 同步服务已初始化")
        result = await service.sync_historical_data(incremental=incremental, job_id="tushare_historical_sync")
        logger.info(f"✅ [APScheduler] Tushare历史数据同步完成: {result}")

        # 同步完成后自动执行完整性检查和补数
        try:
            from app.services.data_integrity_service import get_data_integrity_service
            integrity_service = await get_data_integrity_service()
            integrity_result = await integrity_service.check_historical_completeness(
                auto_remediate=settings.DATA_INTEGRITY_AUTO_REMEDIATE,
                remediate_source=settings.DATA_INTEGRITY_REMEDIATE_SOURCE,
            )
            logger.info(f"🔍 [完整性检查] Tushare同步后检查结果: {integrity_result.get('status')} "
                       f"(期望: {integrity_result.get('expected_count')}, "
                       f"实际: {integrity_result.get('actual_count')}, "
                       f"缺失: {integrity_result.get('missing_count')}, "
                       f"补数: {integrity_result.get('remediated_count')})")
        except Exception as ie:
            logger.warning(f"⚠️ 同步后完整性检查失败（不影响同步结果）: {ie}")

        return result
    except Exception as e:
        logger.error(f"❌ [APScheduler] Tushare历史数据同步失败: {e}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        raise


async def run_tushare_financial_sync():
    """APScheduler任务：同步财务数据（获取最近20期，约5年）"""
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_financial_data(limit=20, job_id="tushare_financial_sync")  # 获取最近20期（约5年数据）
        logger.info(f"✅ Tushare财务数据同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare财务数据同步失败: {e}")
        raise


async def run_tushare_dividend_sync():
    """APScheduler任务：同步分红送配数据"""
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_dividend_data(job_id="tushare_dividend_sync")
        logger.info(f"✅ Tushare分红数据同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare分红数据同步失败: {e}")
        raise


async def run_tushare_daily_basic_sync(days_back: int = 730):
    """APScheduler任务：同步每日估值/市值数据（Tushare daily_basic）。

    默认同步最近 days_back 天（增量，已同步交易日自动跳过），
    供回测按日对齐历史 PE/PB/市值。
    """
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_daily_basic_data(
            days_back=days_back, job_id="tushare_daily_basic_sync"
        )
        logger.info(f"✅ Tushare每日估值数据同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare每日估值数据同步失败: {e}")
        raise


async def run_tushare_status_check():
    """APScheduler任务：检查同步状态"""
    try:
        service = await get_tushare_sync_service()
        result = await service.get_sync_status()
        logger.info(f"✅ Tushare状态检查完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare状态检查失败: {e}")
        return {"error": str(e)}


async def run_tushare_news_sync(hours_back: int = 24, max_news_per_stock: int = 20):
    """APScheduler任务：同步新闻数据"""
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_news_data(
            hours_back=hours_back,
            max_news_per_stock=max_news_per_stock,
            job_id="tushare_news_sync"
        )
        logger.info(f"✅ Tushare新闻数据同步完成: {result}")
        return result
    except Exception as e:
        logger.error(f"❌ Tushare新闻数据同步失败: {e}")
        raise
