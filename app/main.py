"""
TradingAgents-CN v1.0.0-preview FastAPI Backend
主应用程序入口

Copyright (c) 2025 hsliuping. All rights reserved.
版权所有 (c) 2025 hsliuping。保留所有权利。

This software is proprietary and confidential. Unauthorized copying, distribution,
or use of this software, via any medium, is strictly prohibited.
本软件为专有和机密软件。严禁通过任何媒介未经授权复制、分发或使用本软件。

For commercial licensing, please contact: hsliup@163.com
商业许可咨询，请联系：hsliup@163.com
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logging_config import setup_logging

# 港股和美股改为按需获取+缓存模式，不再需要定时同步任务
# from app.worker.hk_sync_service import ...
# from app.worker.us_sync_service import ...
from app.middleware.operation_log_middleware import OperationLogMiddleware
from app.routers import (
    akshare_init,
    analysis,
    baostock_init,
    cache,
    config,
    database,
    favorites,
    financial_data,
    health,
    historical_data,
    internal_messages,
    logs,
    model_capabilities,
    multi_period_sync,
    multi_source_sync,
    news_data,
    operation_logs,
    portfolio,
    queue,
    reports,
    retail,
    screening,
    social_media,
    sse,
    tags,
    tushare_init,
    usage_statistics,
)
from app.routers import auth_db as auth
from app.routers import multi_market_stocks as multi_market_stocks_router
from app.routers import notifications as notifications_router
from app.routers import paper as paper_router
from app.routers import scheduler as scheduler_router
from app.routers import stock_data as stock_data_router
from app.routers import stock_sync as stock_sync_router
from app.routers import stocks as stocks_router
from app.routers import sync as sync_router
from app.routers import vibe_research as vibe_router
from app.routers import websocket_notifications as websocket_notifications_router
from app.services.multi_source_basics_sync_service import MultiSourceBasicsSyncService
from app.services.quotes_ingestion_service import QuotesIngestionService
from app.services.scheduler_service import set_scheduler_instance
from app.worker.akshare_sync_service import (
    run_akshare_basic_info_sync,
    run_akshare_financial_sync,
    run_akshare_historical_sync,
    run_akshare_quotes_sync,
    run_akshare_status_check,
)
from app.worker.baostock_sync_service import (
    run_baostock_basic_info_sync,
    run_baostock_daily_quotes_sync,
    run_baostock_historical_sync,
    run_baostock_status_check,
)
from app.worker.tushare_sync_service import (
    run_tushare_daily_basic_sync,
    run_tushare_dividend_sync,
    run_tushare_financial_sync,
    run_tushare_historical_sync,
    run_tushare_status_check,
)


def get_version() -> str:
    """从 VERSION 文件读取版本号"""
    try:
        version_file = Path(__file__).parent.parent / "VERSION"
        if version_file.exists():
            return version_file.read_text(encoding='utf-8').strip()
    except Exception:
        pass
    return "1.0.0"  # 默认版本号


async def _print_config_summary(logger):
    """显示配置摘要"""
    try:
        logger.info("=" * 70)
        logger.info("📋 TradingAgents-CN Configuration Summary")
        logger.info("=" * 70)

        # .env 文件路径信息
        import os
        from pathlib import Path
        
        current_dir = Path.cwd()
        logger.info(f"📁 Current working directory: {current_dir}")
        
        # 检查可能的 .env 文件位置
        env_files_to_check = [
            current_dir / ".env",
            current_dir / "app" / ".env",
            Path(__file__).parent.parent / ".env",  # 项目根目录
        ]
        
        logger.info("🔍 Checking .env file locations:")
        env_file_found = False
        for env_file in env_files_to_check:
            if env_file.exists():
                logger.info(f"  ✅ Found: {env_file} (size: {env_file.stat().st_size} bytes)")
                env_file_found = True
                # 显示文件的前几行（隐藏敏感信息）
                try:
                    with open(env_file, encoding='utf-8') as f:
                        lines = f.readlines()[:5]  # 只读前5行
                        logger.info("     Preview (first 5 lines):")
                        for i, line in enumerate(lines, 1):
                            # 隐藏包含密码、密钥等敏感信息的行
                            if any(keyword in line.upper() for keyword in ['PASSWORD', 'SECRET', 'KEY', 'TOKEN']):
                                logger.info(f"       {i}: {line.split('=')[0]}=***")
                            else:
                                logger.info(f"       {i}: {line.strip()}")
                except Exception as e:
                    logger.warning(f"     Could not preview file: {e}")
            else:
                logger.info(f"  ❌ Not found: {env_file}")
        
        if not env_file_found:
            logger.warning("⚠️  No .env file found in checked locations")
        
        # Pydantic Settings 配置加载状态
        logger.info("⚙️  Pydantic Settings Configuration:")
        logger.info(f"  • Settings class: {settings.__class__.__name__}")
        logger.info(f"  • Config source: {getattr(settings.model_config, 'env_file', 'Not specified')}")
        logger.info(f"  • Encoding: {getattr(settings.model_config, 'env_file_encoding', 'Not specified')}")
        
        # 显示一些关键配置值的来源（环境变量 vs 默认值）
        key_settings = ['HOST', 'PORT', 'DEBUG', 'MONGODB_HOST', 'REDIS_HOST']
        logger.info("  • Key settings sources:")
        for setting_name in key_settings:
            env_var_name = setting_name
            env_value = os.getenv(env_var_name)
            config_value = getattr(settings, setting_name, None)
            if env_value is not None:
                logger.info(f"    - {setting_name}: from environment variable ({config_value})")
            else:
                logger.info(f"    - {setting_name}: using default value ({config_value})")
        
        # 环境信息
        env = "Production" if settings.is_production else "Development"
        logger.info(f"Environment: {env}")

        # 数据库连接
        logger.info(f"MongoDB: {settings.MONGODB_HOST}:{settings.MONGODB_PORT}/{settings.MONGODB_DATABASE}")
        logger.info(f"Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}")

        # 代理配置
        import os
        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            logger.info("Proxy Configuration:")
            if settings.HTTP_PROXY:
                logger.info(f"  HTTP_PROXY: {settings.HTTP_PROXY}")
            if settings.HTTPS_PROXY:
                logger.info(f"  HTTPS_PROXY: {settings.HTTPS_PROXY}")
            if settings.NO_PROXY:
                # 只显示前3个域名
                no_proxy_list = settings.NO_PROXY.split(',')
                if len(no_proxy_list) <= 3:
                    logger.info(f"  NO_PROXY: {settings.NO_PROXY}")
                else:
                    logger.info(f"  NO_PROXY: {','.join(no_proxy_list[:3])}... ({len(no_proxy_list)} domains)")
            logger.info("  ✅ Proxy environment variables set successfully")
        else:
            logger.info("Proxy: Not configured (direct connection)")

        # 检查大模型配置
        try:
            from app.services.config_service import config_service
            config = await config_service.get_system_config()
            if config and config.llm_configs:
                enabled_llms = [llm for llm in config.llm_configs if llm.enabled]
                logger.info(f"Enabled LLMs: {len(enabled_llms)}")
                if enabled_llms:
                    for llm in enabled_llms[:3]:  # 只显示前3个
                        logger.info(f"  • {llm.provider}: {llm.model_name}")
                    if len(enabled_llms) > 3:
                        logger.info(f"  • ... and {len(enabled_llms) - 3} more")
                else:
                    logger.warning("⚠️  No LLM enabled. Please configure at least one LLM in Web UI.")
            else:
                logger.warning("⚠️  No LLM configured. Please configure at least one LLM in Web UI.")
        except Exception as e:
            logger.warning(f"⚠️  Failed to check LLM configs: {e}")

        # 检查数据源配置
        try:
            if config and config.data_source_configs:
                enabled_sources = [ds for ds in config.data_source_configs if ds.enabled]
                logger.info(f"Enabled Data Sources: {len(enabled_sources)}")
                if enabled_sources:
                    for ds in enabled_sources[:3]:  # 只显示前3个
                        logger.info(f"  • {ds.type.value}: {ds.name}")
                    if len(enabled_sources) > 3:
                        logger.info(f"  • ... and {len(enabled_sources) - 3} more")
            else:
                logger.info("Data Sources: Using default (AKShare)")
        except Exception as e:
            logger.warning(f"⚠️  Failed to check data source configs: {e}")

        logger.info("=" * 70)
    except Exception as e:
        logger.error(f"Failed to print config summary: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    setup_logging()
    logger = logging.getLogger("app.main")

    # 验证启动配置
    try:
        from app.core.startup_validator import validate_startup_config
        validate_startup_config()
    except Exception as e:
        logger.error(f"配置验证失败: {e}")
        raise

    await init_db()

    # 清理僵尸回测任务：后端进程被重启/崩溃时，守护线程被杀，
    # Redis 中会残留"running"但永无进度的任务，前端据此外推出离谱 ETA。
    # 启动时自动将这些长时间无更新的任务标记为 failure，避免误导用户。
    try:
        from app.strategy_system.task_manager import cleanup_stale_tasks
        _cleaned = cleanup_stale_tasks()
        if _cleaned:
            logger.info(f"🧹 启动时清理 {_cleaned} 个僵尸回测任务（标记为失败）")
    except Exception as _e:
        logger.warning(f"⚠️ 僵尸回测任务清理失败（不影响主流程）: {_e}")

    #  配置桥接：将统一配置写入环境变量，供 TradingAgents 核心库使用
    try:
        from app.core.config_bridge import bridge_config_to_env
        bridge_config_to_env()
    except Exception as e:
        logger.warning(f"⚠️  配置桥接失败: {e}")
        logger.warning("⚠️  TradingAgents 将使用 .env 文件中的配置")

    # Apply dynamic settings (log_level, enable_monitoring) from ConfigProvider
    try:
        from app.services.config_provider import (
            provider as config_provider,  # local import to avoid early DB init issues
        )
        eff = await config_provider.get_effective_system_settings()
        desired_level = str(eff.get("log_level", "INFO")).upper()
        setup_logging(log_level=desired_level)
        for name in ("webapi", "worker", "uvicorn", "fastapi"):
            logging.getLogger(name).setLevel(desired_level)
        try:
            from app.middleware.operation_log_middleware import set_operation_log_enabled
            set_operation_log_enabled(bool(eff.get("enable_monitoring", True)))
        except Exception:
            pass
    except Exception as e:
        logging.getLogger("webapi").warning(f"Failed to apply dynamic settings: {e}")

    # 显示配置摘要
    await _print_config_summary(logger)

    logger.info("TradingAgents FastAPI backend started")

    # 启动期：若需要在休市时补充上一交易日收盘快照
    if settings.QUOTES_BACKFILL_ON_STARTUP:
        try:
            qi = QuotesIngestionService()
            await qi.ensure_indexes()
            await qi.backfill_last_close_snapshot_if_needed()
            # 启动期：校验 market_quotes 数据一致性，自动修复单位异常（bug-012 遗留防护）
            await qi.verify_and_repair_market_quotes()
        except Exception as e:
            logger.warning(f"Startup backfill failed (ignored): {e}")

    # 启动每日定时任务：可配置
    scheduler: AsyncIOScheduler | None = None
    try:
        pass
    except Exception:
        pass  # 可选依赖
    try:
        scheduler = AsyncIOScheduler(
            timezone=settings.TIMEZONE,
            job_defaults={
                'misfire_grace_time': 300,  # 5分钟容错，避免任务堆积时被丢弃
                'coalesce': True,           # 合并堆积的触发，只执行一次
            }
        )

        # 使用多数据源同步服务（支持自动切换）
        multi_source_service = MultiSourceBasicsSyncService()

        # 根据 TUSHARE_ENABLED 配置决定优先数据源
        # 如果 Tushare 被禁用，系统会自动使用其他可用数据源（AKShare/BaoStock）
        preferred_sources = None  # None 表示使用默认优先级顺序

        if settings.TUSHARE_ENABLED:
            # Tushare 启用时，优先使用 Tushare
            preferred_sources = ["tushare", "akshare", "baostock"]
            logger.info("📊 股票基础信息同步优先数据源: Tushare > AKShare > BaoStock")
        else:
            # Tushare 禁用时，使用 AKShare 和 BaoStock
            preferred_sources = ["akshare", "baostock"]
            logger.info("📊 股票基础信息同步优先数据源: AKShare > BaoStock (Tushare已禁用)")

        # 立即在启动后尝试一次（不阻塞）
        async def run_sync_with_sources():
            await multi_source_service.run_full_sync(force=False, preferred_sources=preferred_sources)

        asyncio.create_task(run_sync_with_sources())

        # 配置调度：优先使用 CRON，其次使用 HH:MM
        if settings.SYNC_STOCK_BASICS_ENABLED:
            if settings.SYNC_STOCK_BASICS_CRON:
                # 如果提供了cron表达式
                scheduler.add_job(
                    lambda: multi_source_service.run_full_sync(force=False, preferred_sources=preferred_sources),
                    CronTrigger.from_crontab(settings.SYNC_STOCK_BASICS_CRON, timezone=settings.TIMEZONE),
                    id="basics_sync_service",
                    name="股票基础信息同步（多数据源）"
                )
                logger.info(f"📅 Stock basics sync scheduled by CRON: {settings.SYNC_STOCK_BASICS_CRON} ({settings.TIMEZONE})")
            else:
                hh, mm = (settings.SYNC_STOCK_BASICS_TIME or "06:30").split(":")
                scheduler.add_job(
                    lambda: multi_source_service.run_full_sync(force=False, preferred_sources=preferred_sources),
                    CronTrigger(hour=int(hh), minute=int(mm), timezone=settings.TIMEZONE),
                    id="basics_sync_service",
                    name="股票基础信息同步（多数据源）"
                )
                logger.info(f"📅 Stock basics sync scheduled daily at {settings.SYNC_STOCK_BASICS_TIME} ({settings.TIMEZONE})")

        # 实时行情入库任务（每N秒），内部自判交易时段
        if settings.QUOTES_INGEST_ENABLED:
            quotes_ingestion = QuotesIngestionService()
            await quotes_ingestion.ensure_indexes()

            # 付费 Tushare 用户自动切换到高频采集，免费用户使用配置值
            ingest_interval = settings.QUOTES_INGEST_INTERVAL_SECONDS
            if settings.QUOTES_AUTO_DETECT_TUSHARE_PERMISSION:
                try:
                    is_premium = quotes_ingestion._check_tushare_permission()
                    if is_premium:
                        # premium/vip 用户：有 rt_k 权限，使用 30 秒高频采集
                        ingest_interval = min(settings.QUOTES_INGEST_INTERVAL_SECONDS, 30)
                        logger.info(f"✅ 检测到 Tushare rt_k 权限（premium/vip），实时行情采集间隔调整为 {ingest_interval}s")
                    elif settings.TUSHARE_ENABLED and settings.TUSHARE_TIER.lower() not in ("free", ""):
                        # standard/basic 付费用户：无 rt_k 权限，但走 AKShare 可用更短间隔（60秒）
                        ingest_interval = min(settings.QUOTES_INGEST_INTERVAL_SECONDS, 60)
                        logger.info(f"✅ Tushare {settings.TUSHARE_TIER} 付费用户（无 rt_k），走 AKShare 采集间隔调整为 {ingest_interval}s")
                    else:
                        logger.info(f"ℹ️ Tushare 免费用户，保持配置的采集间隔 {ingest_interval}s")
                except Exception as e:
                    logger.warning(f"Tushare 权限检测失败，使用配置间隔 {ingest_interval}s: {e}")

            scheduler.add_job(
                quotes_ingestion.run_once,  # coroutine function; AsyncIOScheduler will await it
                IntervalTrigger(seconds=ingest_interval, timezone=settings.TIMEZONE),
                id="quotes_ingestion_service",
                name="实时行情入库服务"
            )
            logger.info(f"⏱ 实时行情入库任务已启动: 每 {ingest_interval}s")

        # 监控中心规则评估任务（每 N 秒，基于已入库行情）
        if settings.MONITOR_ENABLED:
            from app.services.monitor_service import monitor_service
            await monitor_service.ensure_indexes()
            scheduler.add_job(
                monitor_service.run_evaluation,
                IntervalTrigger(seconds=settings.MONITOR_INTERVAL_SECONDS, timezone=settings.TIMEZONE),
                id="monitor_rule_evaluation",
                name="监控中心规则评估"
            )
            logger.info(f"⏱ 监控中心规则评估已启动: 每 {settings.MONITOR_INTERVAL_SECONDS}s")

        # Tushare统一数据同步任务配置
        logger.info("🔄 配置Tushare统一数据同步任务...")

        if settings.TUSHARE_UNIFIED_ENABLED:
            # --- 方案 B-1：删除 tushare_basic_info_sync（每天 02:00）
            # 原因：与 basics_sync_service（每天 06:30 多源版）做同一件事：
            # 从 Tushare 拉 stock_list + daily_basic 写 stock_basic_info 表。
            # 保留 basics_sync_service（多源 fallback 更健壮），删掉这个重复版本。

            # --- 方案 B-2：删除 tushare_quotes_sync（盘中每分钟）
            # 原因：与 quotes_ingestion_service（每 1 分钟 interval 版）功能重复，
            # 且历史运行记录显示一直是 paused（tushare_quotes_sync_enabled=false），
            # 实际行情入库走的是 quotes_ingestion_service。

            # 历史数据同步任务（核心保留：日K同步的主来源）
            if settings.TUSHARE_HISTORICAL_SYNC_ENABLED:
                scheduler.add_job(
                    run_tushare_historical_sync,
                    CronTrigger.from_crontab(settings.TUSHARE_HISTORICAL_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="tushare_historical_sync",
                    name="历史数据同步（Tushare）",
                    kwargs={"incremental": True}
                )
                logger.info(f"📊 Tushare历史数据同步已配置: {settings.TUSHARE_HISTORICAL_SYNC_CRON}")
            else:
                logger.info(f"⏭️ Tushare历史数据同步跳过（未启用）: {settings.TUSHARE_HISTORICAL_SYNC_CRON}")

            # 财务数据同步任务
            if settings.TUSHARE_FINANCIAL_SYNC_ENABLED:
                scheduler.add_job(
                    run_tushare_financial_sync,
                    CronTrigger.from_crontab(settings.TUSHARE_FINANCIAL_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="tushare_financial_sync",
                    name="财务数据同步（Tushare）"
                )
                logger.info(f"💰 Tushare财务数据同步已配置: {settings.TUSHARE_FINANCIAL_SYNC_CRON}")
            else:
                logger.info(f"⏭️ Tushare财务数据同步跳过（未启用）: {settings.TUSHARE_FINANCIAL_SYNC_CRON}")

            # 分红送配数据同步任务
            if settings.TUSHARE_DIVIDEND_SYNC_ENABLED:
                scheduler.add_job(
                    run_tushare_dividend_sync,
                    CronTrigger.from_crontab(settings.TUSHARE_DIVIDEND_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="tushare_dividend_sync",
                    name="分红数据同步（Tushare）"
                )
                logger.info(f"💰 Tushare分红数据同步已配置: {settings.TUSHARE_DIVIDEND_SYNC_CRON}")
            else:
                logger.info(f"⏭️ Tushare分红数据同步跳过（未启用）: {settings.TUSHARE_DIVIDEND_SYNC_CRON}")

            # 每日估值/市值数据同步任务（为回测提供按日 PE/PB/市值）
            if settings.TUSHARE_DAILY_BASIC_SYNC_ENABLED:
                scheduler.add_job(
                    run_tushare_daily_basic_sync,
                    CronTrigger.from_crontab(settings.TUSHARE_DAILY_BASIC_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="tushare_daily_basic_sync",
                    name="每日估值数据同步（Tushare）",
                    kwargs={"days_back": settings.TUSHARE_DAILY_BASIC_SYNC_DAYS_BACK}
                )
                logger.info(f"📈 Tushare每日估值数据同步已配置: {settings.TUSHARE_DAILY_BASIC_SYNC_CRON}")
            else:
                logger.info(f"⏭️ Tushare每日估值数据同步跳过（未启用）: {settings.TUSHARE_DAILY_BASIC_SYNC_CRON}")

            # 状态检查任务（保留，频率在 config.py 已为每小时，后续可降频）
            if settings.TUSHARE_STATUS_CHECK_ENABLED:
                scheduler.add_job(
                    run_tushare_status_check,
                    CronTrigger.from_crontab(settings.TUSHARE_STATUS_CHECK_CRON, timezone=settings.TIMEZONE),
                    id="tushare_status_check",
                    name="数据源状态检查（Tushare）"
                )
                logger.info(f"🔍 Tushare状态检查已配置: {settings.TUSHARE_STATUS_CHECK_CRON}")
            else:
                logger.info(f"⏭️ Tushare状态检查跳过（未启用）: {settings.TUSHARE_STATUS_CHECK_CRON}")
        else:
            logger.info("⏭️ Tushare统一数据源未启用，跳过Tushare定时任务注册（仅保留基础同步服务 basics_sync_service）")

        # AKShare统一数据同步任务配置
        logger.info("🔄 配置AKShare统一数据同步任务...")

        # 🐛 精简方案-A：未启用就不注册（原 add_job + pause_job 导致 /tasks 出现 5 个永远 paused 的任务）
        if settings.AKSHARE_UNIFIED_ENABLED:
            # 基础信息同步任务
            if settings.AKSHARE_BASIC_INFO_SYNC_ENABLED:
                scheduler.add_job(
                    run_akshare_basic_info_sync,
                    CronTrigger.from_crontab(settings.AKSHARE_BASIC_INFO_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="akshare_basic_info_sync",
                    name="股票基础信息同步（AKShare）",
                    kwargs={"force_update": False}
                )
                logger.info(f"📅 AKShare基础信息同步已配置: {settings.AKSHARE_BASIC_INFO_SYNC_CRON}")
            else:
                logger.info(f"⏭️ AKShare基础信息同步跳过（未启用）: {settings.AKSHARE_BASIC_INFO_SYNC_CRON}")

            # 实时行情同步任务
            if settings.AKSHARE_QUOTES_SYNC_ENABLED:
                scheduler.add_job(
                    run_akshare_quotes_sync,
                    CronTrigger.from_crontab(settings.AKSHARE_QUOTES_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="akshare_quotes_sync",
                    name="实时行情同步（AKShare）"
                )
                logger.info(f"📈 AKShare行情同步已配置: {settings.AKSHARE_QUOTES_SYNC_CRON}")
            else:
                logger.info(f"⏭️ AKShare行情同步跳过（未启用）: {settings.AKSHARE_QUOTES_SYNC_CRON}")

            # 历史数据同步任务
            if settings.AKSHARE_HISTORICAL_SYNC_ENABLED:
                scheduler.add_job(
                    run_akshare_historical_sync,
                    CronTrigger.from_crontab(settings.AKSHARE_HISTORICAL_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="akshare_historical_sync",
                    name="历史数据同步（AKShare）",
                    kwargs={"incremental": True}
                )
                logger.info(f"📊 AKShare历史数据同步已配置: {settings.AKSHARE_HISTORICAL_SYNC_CRON}")
            else:
                logger.info(f"⏭️ AKShare历史数据同步跳过（未启用）: {settings.AKSHARE_HISTORICAL_SYNC_CRON}")

            # 财务数据同步任务
            if settings.AKSHARE_FINANCIAL_SYNC_ENABLED:
                scheduler.add_job(
                    run_akshare_financial_sync,
                    CronTrigger.from_crontab(settings.AKSHARE_FINANCIAL_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="akshare_financial_sync",
                    name="财务数据同步（AKShare）"
                )
                logger.info(f"💰 AKShare财务数据同步已配置: {settings.AKSHARE_FINANCIAL_SYNC_CRON}")
            else:
                logger.info(f"⏭️ AKShare财务数据同步跳过（未启用）: {settings.AKSHARE_FINANCIAL_SYNC_CRON}")

            # 状态检查任务
            if settings.AKSHARE_STATUS_CHECK_ENABLED:
                scheduler.add_job(
                    run_akshare_status_check,
                    CronTrigger.from_crontab(settings.AKSHARE_STATUS_CHECK_CRON, timezone=settings.TIMEZONE),
                    id="akshare_status_check",
                    name="数据源状态检查（AKShare）"
                )
                logger.info(f"🔍 AKShare状态检查已配置: {settings.AKSHARE_STATUS_CHECK_CRON}")
            else:
                logger.info(f"⏭️ AKShare状态检查跳过（未启用）: {settings.AKSHARE_STATUS_CHECK_CRON}")
        else:
            logger.info("⏭️ AKShare统一数据源未启用，跳过所有AKShare定时任务注册")

        # BaoStock统一数据同步任务配置
        logger.info("🔄 配置BaoStock统一数据同步任务...")

        if settings.BAOSTOCK_UNIFIED_ENABLED:
            # 基础信息同步任务
            if settings.BAOSTOCK_BASIC_INFO_SYNC_ENABLED:
                scheduler.add_job(
                    run_baostock_basic_info_sync,
                    CronTrigger.from_crontab(settings.BAOSTOCK_BASIC_INFO_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="baostock_basic_info_sync",
                    name="股票基础信息同步（BaoStock）"
                )
                logger.info(f"📋 BaoStock基础信息同步已配置: {settings.BAOSTOCK_BASIC_INFO_SYNC_CRON}")
            else:
                logger.info(f"⏭️ BaoStock基础信息同步跳过（未启用）: {settings.BAOSTOCK_BASIC_INFO_SYNC_CRON}")

            # 日K线同步任务（注意：BaoStock不支持实时行情）
            if settings.BAOSTOCK_DAILY_QUOTES_SYNC_ENABLED:
                scheduler.add_job(
                    run_baostock_daily_quotes_sync,
                    CronTrigger.from_crontab(settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="baostock_daily_quotes_sync",
                    name="日K线数据同步（BaoStock）"
                )
                logger.info(f"📈 BaoStock日K线同步已配置: {settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON} (注意：BaoStock不支持实时行情)")
            else:
                logger.info(f"⏭️ BaoStock日K线同步跳过（未启用）: {settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON}")

            # 历史数据同步任务
            if settings.BAOSTOCK_HISTORICAL_SYNC_ENABLED:
                scheduler.add_job(
                    run_baostock_historical_sync,
                    CronTrigger.from_crontab(settings.BAOSTOCK_HISTORICAL_SYNC_CRON, timezone=settings.TIMEZONE),
                    id="baostock_historical_sync",
                    name="历史数据同步（BaoStock）"
                )
                logger.info(f"📊 BaoStock历史数据同步已配置: {settings.BAOSTOCK_HISTORICAL_SYNC_CRON}")
            else:
                logger.info(f"⏭️ BaoStock历史数据同步跳过（未启用）: {settings.BAOSTOCK_HISTORICAL_SYNC_CRON}")

            # 状态检查任务
            if settings.BAOSTOCK_STATUS_CHECK_ENABLED:
                scheduler.add_job(
                    run_baostock_status_check,
                    CronTrigger.from_crontab(settings.BAOSTOCK_STATUS_CHECK_CRON, timezone=settings.TIMEZONE),
                    id="baostock_status_check",
                    name="数据源状态检查（BaoStock）"
                )
                logger.info(f"🔍 BaoStock状态检查已配置: {settings.BAOSTOCK_STATUS_CHECK_CRON}")
            else:
                logger.info(f"⏭️ BaoStock状态检查跳过（未启用）: {settings.BAOSTOCK_STATUS_CHECK_CRON}")
        else:
            logger.info("⏭️ BaoStock统一数据源未启用，跳过所有BaoStock定时任务注册")

        # ==================== 数据完整性检查定时任务 ====================
        logger.info("🔄 配置数据完整性检查任务...")

        async def run_data_integrity_check():
            """APScheduler任务：数据完整性检查与自动补数"""
            try:
                from app.services.data_integrity_service import get_data_integrity_service
                service = await get_data_integrity_service()
                result = await service.check_historical_completeness(
                    auto_remediate=settings.DATA_INTEGRITY_AUTO_REMEDIATE,
                    remediate_source=settings.DATA_INTEGRITY_REMEDIATE_SOURCE,
                )
                logger.info(
                    f"🔍 [APScheduler] 数据完整性检查完成: "
                    f"状态={result.get('status')}, "
                    f"交易日期={result.get('trade_date')}, "
                    f"期望={result.get('expected_count')}, "
                    f"实际={result.get('actual_count')}, "
                    f"缺失={result.get('missing_count')}, "
                    f"补数={result.get('remediated_count')}"
                )
                return result
            except Exception as e:
                logger.error(f"❌ [APScheduler] 数据完整性检查失败: {e}")
                raise

        scheduler.add_job(
            run_data_integrity_check,
            CronTrigger.from_crontab(settings.DATA_INTEGRITY_CHECK_CRON, timezone=settings.TIMEZONE),
            id="data_integrity_check",
            name="数据完整性检查与自动补数",
        )
        if not settings.DATA_INTEGRITY_CHECK_ENABLED:
            scheduler.pause_job("data_integrity_check")
            logger.info(f"⏸️ 数据完整性检查已添加但暂停: {settings.DATA_INTEGRITY_CHECK_CRON}")
        else:
            logger.info(f"🔍 数据完整性检查已配置: {settings.DATA_INTEGRITY_CHECK_CRON}")

        # 新闻数据同步任务配置
        logger.info("🔄 配置新闻数据同步任务...")

        from app.worker.news_data_sync_service import get_news_data_sync_service

        async def run_news_sync():
            """运行新闻同步任务 - 同步自选股新闻和市场新闻（统一使用NewsDataSyncService）"""
            try:
                logger.info("📰 开始新闻数据同步（自选股 + 市场新闻）...")
                
                sync_service = await get_news_data_sync_service()
                
                # 1. 同步自选股新闻（多数据源）
                try:
                    from app.services.favorites_service import favorites_service
                    favorites = await favorites_service.get_user_favorites("guest")
                    favorite_codes = [fav.get("stock_code", "") for fav in favorites if fav.get("stock_code")]
                    
                    if favorite_codes:
                        logger.info(f"📋 开始同步 {len(favorite_codes)} 只自选股新闻...")
                        total_saved = 0
                        for code in favorite_codes:
                            try:
                                result = await sync_service.sync_stock_news(
                                    symbol=code,
                                    data_sources=["akshare", "tushare", "realtime"],
                                    hours_back=24,
                                    max_news_per_source=settings.NEWS_SYNC_MAX_PER_SOURCE
                                )
                                total_saved += result.successful_saves
                            except Exception as e:
                                logger.warning(f"⚠️ 自选股 {code} 新闻同步失败: {e}")
                        logger.info(f"✅ 自选股新闻同步完成: 共保存{total_saved}条")
                    else:
                        logger.info("ℹ️  没有自选股，跳过自选股新闻同步")
                except Exception as e:
                    logger.error(f"❌ 自选股新闻同步异常: {e}")
                
                # 2. 同步市场新闻（多数据源）
                try:
                    market_result = await sync_service.sync_market_news(
                        data_sources=["akshare", "tushare", "realtime"],
                        hours_back=24,
                        max_news_per_source=settings.NEWS_SYNC_MAX_PER_SOURCE
                    )
                    logger.info(
                        f"✅ 市场新闻同步完成: "
                        f"成功保存{market_result.successful_saves}条, "
                        f"失败{market_result.failed_saves}条, "
                        f"去重跳过{market_result.duplicate_skipped}条"
                    )
                except Exception as e:
                    logger.error(f"❌ 市场新闻同步异常: {e}")
                
            except Exception as e:
                logger.error(f"❌ 新闻同步失败: {e}", exc_info=True)

        # ==================== 港股/美股数据配置 ====================
        # 港股和美股采用按需获取+缓存模式，不再配置定时同步任务
        logger.info("🇭🇰 港股数据采用按需获取+缓存模式")
        logger.info("🇺🇸 美股数据采用按需获取+缓存模式")

        scheduler.add_job(
            run_news_sync,
            CronTrigger.from_crontab(settings.NEWS_SYNC_CRON, timezone=settings.TIMEZONE),
            id="news_sync",
            name="新闻数据同步（自选股 + 市场新闻）"
        )
        if not settings.NEWS_SYNC_ENABLED:
            scheduler.pause_job("news_sync")
            logger.info(f"⏸️ 新闻数据同步已添加但暂停: {settings.NEWS_SYNC_CRON}")
        else:
            logger.info(f"📰 新闻数据同步已配置（自选股 + 市场新闻）: {settings.NEWS_SYNC_CRON}")

        # ==================== 散户策略定时任务（退出扫描 + 环境检测） ====================
        try:
            from app.services.retail.scheduler_jobs import register_retail_jobs
            register_retail_jobs(scheduler, settings)
            logger.info("✅ 散户策略定时任务注册完成")
        except Exception as e:
            logger.error(f"🚨 散户策略定时任务注册失败，退出信号扫描/预警检查等功能将不可用: {e}", exc_info=True)

        # ==================== ΔG 景气度数据季度刷新 ====================
        # 每月1日凌晨5:00从 Tushare fina_indicator 拉取全 A 股最近 8 个季度的财务指标，
        # 计算 ΔG（环比差值）用于戴维斯双杀象限判断。
        # 财报披露时间：Q1季报4月底、Q2中报8月底、Q3季报10月底、Q4年报次年4月底，
        # 每月执行可确保财报披露后及时更新。
        async def run_dg_prosperity_sync():
            """运行 ΔG 景气度数据季度刷新"""
            try:
                from app.services.dg_prosperity_service import get_dg_prosperity_service
                logger.info("📊 [APScheduler] 开始 ΔG 景气度数据季度刷新...")
                service = get_dg_prosperity_service()
                result = await service.refresh_quarterly()
                logger.info(
                    f"📊 [APScheduler] ΔG 景气度刷新完成: "
                    f"更新={result.get('updated_count')}, "
                    f"失败={result.get('failed_count')}, "
                    f"总数={result.get('total_count')}, "
                    f"季度={result.get('quarters')}"
                )
                return result
            except Exception as e:
                logger.error(f"❌ [APScheduler] ΔG 景气度刷新失败: {e}", exc_info=True)
                raise

        scheduler.add_job(
            run_dg_prosperity_sync,
            CronTrigger.from_crontab(settings.DG_PROSPERITY_SYNC_CRON, timezone=settings.TIMEZONE),
            id="dg_prosperity_sync",
            name="ΔG景气度数据季度刷新",
        )
        if not settings.DG_PROSPERITY_SYNC_ENABLED:
            scheduler.pause_job("dg_prosperity_sync")
            logger.info(f"⏸️ ΔG景气度刷新已添加但暂停: {settings.DG_PROSPERITY_SYNC_CRON}")
        else:
            logger.info(f"📊 ΔG景气度刷新已配置: {settings.DG_PROSPERITY_SYNC_CRON}")

        # 设置调度器实例到服务中，以便API可以管理任务
        # 注意：必须在 scheduler.start() 之前设置，避免 start 与 set 之间的窗口期 API 无可用实例
        set_scheduler_instance(scheduler)

        scheduler.start()

        # 🔥 bug-018：APScheduler 内存 job store 不会补跑启动前错过的 cron job。
        # 场景：后端于工作日 20:00 才启动（容器重建、服务重启等），已错过当日历史同步 cron（18:30/19:30/20:30/21:30），
        # 导致当日日K无法同步，Dashboard 数据新鲜度显示"历史K线过期 1 天"直到次日 cron 才会修复。
        # 修复：启动时若当天为工作日且当前时间已过 cron 时间，则立即跑一次增量同步（延迟 30s，等初始化完成后）。
        try:
            from datetime import datetime, timedelta

            _now = datetime.now()
            _tz = settings.TIMEZONE
            # 需要补跑的 (job_id, cron_expr, run_func, kwargs)
            _catchup_candidates = []
            if settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_HISTORICAL_SYNC_ENABLED:
                _catchup_candidates.append(
                    ("tushare_historical_sync_catchup", settings.TUSHARE_HISTORICAL_SYNC_CRON,
                     run_tushare_historical_sync, {"incremental": True})
                )
            if settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_HISTORICAL_SYNC_ENABLED:
                _catchup_candidates.append(
                    ("akshare_historical_sync_catchup", settings.AKSHARE_HISTORICAL_SYNC_CRON,
                     run_akshare_historical_sync, {"incremental": True})
                )
            if settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_DAILY_QUOTES_SYNC_ENABLED:
                _catchup_candidates.append(
                    ("baostock_daily_quotes_sync_catchup", settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON,
                     run_baostock_daily_quotes_sync, {})
                )
            if settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_HISTORICAL_SYNC_ENABLED:
                _catchup_candidates.append(
                    ("baostock_historical_sync_catchup", settings.BAOSTOCK_HISTORICAL_SYNC_CRON,
                     run_baostock_historical_sync, {"incremental": True})
                )

            _catchup_jobs_added = 0

            # 🔧 bug-018 加固：启动补跑去放大。
            # 问题：后端每重启一次、只要当天已过 cron 时间就再补跑一次"全量"历史同步，
            # 反复重启就会反复全量同步（实测 43 次 catchup），造成"一遍一遍无意义地同步"。
            # 修复：补跑前先查该同步今天是否已经成功过（常规 cron 或本次补跑均可），成功则跳过。
            async def _already_synced_today(_job_ids: list[str]) -> bool:
                try:
                    from app.core.database import get_mongo_db
                    _db = get_mongo_db()
                    _today_s = _now.strftime('%Y-%m-%d')
                    for _jid2 in _job_ids:
                        _hit = await _db["scheduler_executions"].find_one(
                            {"job_id": _jid2, "status": "success"},
                            sort=[("timestamp", -1)],
                        )
                        if _hit:
                            _ts = _hit.get("timestamp")
                            if _ts and str(_ts).startswith(_today_s):
                                return True
                except Exception as _e2:
                    logger.warning(f"⚠️ 查询当天同步是否已成功失败 [{_job_ids}]: {_e2}")
                return False

            for _jid, _cron, _func, _kwargs in _catchup_candidates:
                try:
                    # 用 CronTrigger 反推"上一次应触发时间"：
                    # 1. next_fire 从 now 往后算下一次触发点
                    # 2. prev_fire = next_fire 往前回退一个 cron 周期
                    _trigger = CronTrigger.from_crontab(_cron, timezone=_tz)
                    _next_fire = _trigger.get_next_fire_time(None, _now)
                    if _next_fire is None:
                        continue
                    # 简化：如果 next_fire 的小时:分钟 == cron 的小时:分钟，且 next_fire 日期晚于今天，
                    # 说明今天的 cron 已经过去。直接解析 cron 表达式取 hour/min 比较。
                    # cron 格式：分 时 日 月 周
                    _parts = _cron.split()
                    if len(_parts) >= 2 and _parts[0].isdigit() and _parts[1].isdigit():
                        _cron_hour = int(_parts[1])
                        _cron_min = int(_parts[0])
                        # 检查今天是否是 cron 的 weekday 匹配日（cron 周字段 1-5 = 周一到周五）
                        from app.utils.trading_time import is_trading_day
                        _today_is_match = is_trading_day(_now)
                        if _today_is_match and (_now.hour > _cron_hour or (_now.hour == _cron_hour and _now.minute >= _cron_min)):
                            # 今天是 cron 生效日，且当前时间已过 cron 时间 → 判断是否已同步，未同步才补跑
                            _regular_id = _jid[:-len("_catchup")] if _jid.endswith("_catchup") else _jid
                            if await _already_synced_today([_regular_id, _jid]):
                                logger.info(
                                    f"⏭️ 启动时发现错过历史同步 cron [{_cron}]，但当天已同步成功，跳过补跑（job_id={_jid}）"
                                )
                                continue
                            _delay_sec = 30 + _catchup_jobs_added * 60
                            scheduler.add_job(
                                _func,
                                trigger="date",
                                run_date=_now + timedelta(seconds=_delay_sec),
                                id=_jid,
                                name=f"启动补跑-{_cron}",
                                kwargs=_kwargs,
                                replace_existing=True,
                                misfire_grace_time=600,
                            )
                            logger.info(
                                f"⏰ 启动时发现错过历史同步 cron [{_cron}]，"
                                f"将在 {_delay_sec}s 后补跑一次（job_id={_jid}，"
                                f"cron 时间={_cron_hour:02d}:{_cron_min:02d}，当前={_now.strftime('%H:%M')}）"
                            )
                            _catchup_jobs_added += 1
                except Exception as _e:
                    logger.warning(f"⚠️ 判断历史同步是否需要补跑失败 [{_cron}]: {_e}")
        except Exception as _e:
            logger.warning(f"⚠️ 启动时历史同步补跑逻辑异常，跳过（不影响主流程）: {_e}")

        # ==================== ΔG 景气度数据启动补跑 ====================
        # ΔG 为月度任务，补跑条件：dg_prosperity 集合为空 或 最近一次更新超过 35 天
        # 延迟 120s 启动，避开历史同步补跑窗口（30-90s）
        if settings.DG_PROSPERITY_SYNC_ENABLED:
            try:
                from app.core.database import get_mongo_db

                _db = get_mongo_db()
                _dg_count = await _db["dg_prosperity"].count_documents({})
                _need_catchup = False
                if _dg_count == 0:
                    _need_catchup = True
                    logger.info("📊 ΔG 数据为空，启动时将补跑刷新")
                else:
                    _latest = await _db["dg_prosperity"].find_one(
                        sort=[("updated_at", -1)]
                    )
                    if _latest and _latest.get("updated_at"):
                        try:
                            _updated_str = _latest["updated_at"]
                            # updated_at 是 ISO 格式字符串
                            from datetime import datetime as _dt
                            _updated_at = _dt.fromisoformat(_updated_str)
                            _days_since = (_now - _updated_at).days
                            if _days_since > 35:
                                _need_catchup = True
                                logger.info(
                                    f"📊 ΔG 数据已过期（最后更新: {_updated_str}，"
                                    f"距今 {_days_since} 天），启动时将补跑刷新"
                                )
                        except Exception:
                            # updated_at 格式异常，保守起见补跑
                            _need_catchup = True
                            logger.info("📊 ΔG 数据 updated_at 格式异常，启动时将补跑刷新")

                if _need_catchup:
                    scheduler.add_job(
                        run_dg_prosperity_sync,
                        trigger="date",
                        run_date=_now + timedelta(seconds=120),
                        id="dg_prosperity_sync_catchup",
                        name="启动补跑-ΔG景气度刷新",
                        replace_existing=True,
                        misfire_grace_time=600,
                    )
                    logger.info("⏰ ΔG 景气度补跑任务已安排，将在 120s 后执行")
            except Exception as _e:
                logger.warning(f"⚠️ ΔG 启动补跑逻辑异常，跳过（不影响主流程）: {_e}")

        # 确保 SchedulerService 在启动时初始化（注册事件监听器和僵尸检测）
        # 否则只有在首次调用 /api/scheduler/* 时才会创建，可能导致事件监听器永不注册
        try:
            from app.services.scheduler_service import get_scheduler_service
            get_scheduler_service()
            logger.info("✅ 调度器服务已初始化（事件监听器+僵尸检测已注册）")
        except Exception as e:
            logger.error(f"❌ 调度器服务初始化失败: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"❌ 调度器启动失败: {e}", exc_info=True)
        raise  # 抛出异常，阻止应用启动

    try:
        yield
    finally:
        # 关闭时清理
        if scheduler:
            # 关闭前记录正在运行的任务，避免 wait=False 导致任务被静默中断
            try:
                running_jobs = scheduler.get_jobs()
                for job in running_jobs:
                    if job.next_run_time is None:
                        logger.warning(f"⚠️ 服务关闭时任务 {job.id} 仍在运行，将被中断")
            except Exception:
                pass
            try:
                scheduler.shutdown(wait=False)
                logger.info("🛑 Scheduler stopped")
            except Exception as e:
                logger.warning(f"Scheduler shutdown error: {e}")

        # 关闭 UserService MongoDB 连接
        try:
            from app.services.user_service import user_service
            user_service.close()
        except Exception as e:
            logger.warning(f"UserService cleanup error: {e}")

        await close_db()
        logger.info("TradingAgents FastAPI backend stopped")


# 创建FastAPI应用
app = FastAPI(
    title="股票分析系统 API",
    description="股票分析与批量队列系统 API",
    version=get_version(),
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan
)

# 安全中间件
if not settings.DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS
    )

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# 操作日志中间件
app.add_middleware(OperationLogMiddleware)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()

    # 跳过健康检查和静态文件请求的日志
    if request.url.path in ["/health", "/favicon.ico"] or request.url.path.startswith("/static"):
        response = await call_next(request)
        return response

    # 使用webapi logger记录请求
    logger = logging.getLogger("webapi")
    logger.info(f"🔄 {request.method} {request.url.path} - 开始处理")

    response = await call_next(request)
    process_time = time.time() - start_time

    # 记录请求完成
    status_emoji = "✅" if response.status_code < 400 else "❌"
    logger.info(f"{status_emoji} {request.method} {request.url.path} - 状态: {response.status_code} - 耗时: {process_time:.3f}s")

    return response


# 全局异常处理
# 请求ID/Trace-ID 中间件（需作为最外层，放在函数式中间件之后）
from app.middleware.request_id import RequestIDMiddleware

app.add_middleware(RequestIDMiddleware)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "data": None,
            "message": "服务器内部错误，请稍后重试",
            "code": 500,
            "request_id": getattr(request.state, "request_id", None)
        }
    )


# 测试端点 - 验证中间件是否工作
@app.get("/api/test-log")
async def test_log():
    """测试日志中间件是否工作"""
    print("🧪 测试端点被调用 - 这条消息应该出现在控制台")
    return {"message": "测试成功", "timestamp": time.time()}

# 注册路由
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(auth.router, prefix="/api/auth", tags=["authentication"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
# 已废弃：quick_analysis 模块的 GET /{stock_code} 通配路由会遮蔽 /api/favorites、
# /api/notifications 等单段路径，且功能已由 /api/analysis/single (mode=quick) 替代。
# 如需恢复，请将通配路径改为 /api/quick/{stock_code} 后再注册。
# app.include_router(quick_analysis.router, prefix="/api", tags=["quick-analysis"])
app.include_router(reports.router, tags=["reports"])
app.include_router(screening.router, prefix="/api/screening", tags=["screening"])
app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
app.include_router(favorites.router, prefix="/api", tags=["favorites"])
app.include_router(stocks_router.router, prefix="/api", tags=["stocks"])
app.include_router(multi_market_stocks_router.router, prefix="/api", tags=["multi-market"])
app.include_router(stock_data_router.router, tags=["stock-data"])
app.include_router(stock_sync_router.router, tags=["stock-sync"])
app.include_router(tags.router, prefix="/api", tags=["tags"])
app.include_router(config.router, prefix="/api", tags=["config"])
app.include_router(model_capabilities.router, tags=["model-capabilities"])
app.include_router(usage_statistics.router, tags=["usage-statistics"])
app.include_router(database.router, prefix="/api/system", tags=["database"])
app.include_router(cache.router, tags=["cache"])
app.include_router(operation_logs.router, prefix="/api/system", tags=["operation_logs"])
app.include_router(logs.router, prefix="/api/system", tags=["logs"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["portfolio"])
app.include_router(retail.router, prefix="/api/retail", tags=["retail"])
# 个股预警
from app.routers import stock_alerts as stock_alerts_router

app.include_router(stock_alerts_router.router, prefix="/api/stock", tags=["stock-alerts"])
# 监控中心
from app.routers import monitor as monitor_router

app.include_router(monitor_router.router, tags=["monitor"])
# 新增：系统配置只读摘要
from app.routers import system_config as system_config_router

app.include_router(system_config_router.router, prefix="/api/system", tags=["system"])

# 通知模块（REST + SSE）
app.include_router(notifications_router.router, prefix="/api", tags=["notifications"])

# 🔥 WebSocket 通知模块（替代 SSE + Redis PubSub）
app.include_router(websocket_notifications_router.router, prefix="/api", tags=["websocket"])

# 定时任务管理
app.include_router(scheduler_router.router, tags=["scheduler"])

app.include_router(sse.router, prefix="/api/stream", tags=["streaming"])
app.include_router(sync_router.router)
app.include_router(multi_source_sync.router)
app.include_router(paper_router.router, prefix="/api", tags=["paper"])
app.include_router(tushare_init.router, tags=["tushare-init"])
app.include_router(akshare_init.router, tags=["akshare-init"])
app.include_router(baostock_init.router, tags=["baostock-init"])
app.include_router(historical_data.router, tags=["historical-data"])
app.include_router(multi_period_sync.router, tags=["multi-period-sync"])
app.include_router(financial_data.router, tags=["financial-data"])
app.include_router(news_data.router, tags=["news-data"])
# 社媒舆情和内部消息路由
app.include_router(social_media.router, tags=["social-media"])
app.include_router(internal_messages.router, tags=["internal-messages"])
app.include_router(vibe_router.router, tags=["vibe-research"])
# 策略系统（筛选 + 回测）
from app.routers import strategy as strategy_router

app.include_router(strategy_router.router, tags=["strategy"])


@app.get("/")
async def root():
    """根路径，返回API信息"""
    print("🏠 根路径被访问")
    return {
        "name": "股票分析系统 API",
        "version": get_version(),
        "status": "running",
        "docs_url": "/docs" if settings.DEBUG else None
    }


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
        reload_dirs=["app"] if settings.DEBUG else None,
        reload_excludes=[
            "__pycache__",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".git",
            ".pytest_cache",
            "*.log",
            "*.tmp"
        ] if settings.DEBUG else None,
        reload_includes=["*.py"] if settings.DEBUG else None
    )