"""
Vibe 市场模块数据预热服务。

背景：大盘看板 / 短线情绪 / 概念分析 / 概念轮动 冷启动时需要实时拉取外部数据源
（东财涨停池、同花顺概念、AKShare情绪等），单接口耗时 5-32s。若用户在缓存过期
瞬间访问页面，就会遇到明显卡顿。

方案：定期在后台提前预热这些接口的缓存，使 Redis 中始终有"新鲜但不冷"的数据，
用户请求直接命中缓存（毫秒级），周期性真实抓取的成本由后台任务承担。

实现：
- APScheduler interval 任务驱动（main.py 注册）
- 预热调用走业务 service 的缓存函数（get_dashboard / get_short_term_emotion 等），
  命中未过期缓存时零开销；过期或缺失时才真正触发重建并写回 Redis。
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("webapi")

# 非交易时段时间节流：非交易时段数据变化小，预热频率从交易时段的 5 分钟
# 降为 30 分钟（记录上次实际执行时间，避免无意义的外部数据源请求）。
_NON_TRADING_INTERVAL_SECONDS = 30 * 60
_last_prewarm_ts: float = 0.0


async def prewarm_market_data() -> None:
    """预热 Vibe 市场模块热接口缓存（后台执行，失败不影响主流程）。

    每个接口都经由自身 cached() 去重：缓存未过期时直接跳过（零开销），
    过期/缺失时才真正重建。接口间用 gather 并发，缩短整轮预热耗时。
    """
    global _last_prewarm_ts

    # 非交易时段降频：距上次实际执行不足 30 分钟则跳过本轮；
    # 交易时段维持调度器设定的 5 分钟频率。
    try:
        from app.utils.timezone import now_tz
        from app.utils.trading_time import is_trading_time

        if not is_trading_time(now_tz()):
            now_ts = asyncio.get_event_loop().time()
            if now_ts - _last_prewarm_ts < _NON_TRADING_INTERVAL_SECONDS:
                return
    except Exception:
        # 判断失败时按交易时段处理，保证不因降频逻辑保守而缺失预热
        pass

    try:
        # 延迟导入：避免模块加载期依赖数据库/外部服务未就绪
        from app.services.market_dashboard import get_dashboard
        from app.services.market_overview import (
            get_overview,
            get_short_term_emotion,
            get_turnover_top,
        )
        from app.services.concept_analysis import get_concept_analysis
        from app.services.market_synthesis import get_market_synthesis_cached

        async def _safe(desc: str, coro):
            try:
                await coro
                logger.info(f"🌡️ [prewarm] {desc} 完成")
            except Exception as e:
                logger.warning(f"🌡️ [prewarm] {desc} 失败（忽略）: {e}")

        start = asyncio.get_event_loop().time()
        await asyncio.gather(
            _safe("大盘看板", get_dashboard()),
            _safe("市场总览", get_overview()),
            _safe("短线情绪", get_short_term_emotion()),
            _safe("概念分析", get_concept_analysis()),
            # 综合研判市场级快照（含 LLM 判决）：后台提前重算并回写缓存，
            # 用户访问 /market/synthesis 直接命中缓存秒开，无需前台等 10-60s。
            _safe("综合研判", get_market_synthesis_cached()),
            _safe("成交额Top20", get_turnover_top()),
        )
        el = asyncio.get_event_loop().time() - start
        _last_prewarm_ts = el
        logger.info(f"🌡️ [prewarm] 市场数据预热完成，耗时 {el:.1f}s")
    except Exception as e:
        logger.warning(f"🌡️ [prewarm] 预热任务整体失败（忽略）: {e}")


def register_prewarm_job(scheduler) -> None:
    """向 APScheduler 注册市场数据预热 interval 任务。

    交易时段每 5 分钟预热一次；非交易时段数据变化小，预热频率降为 30 分钟，
    减少无意义的外部数据源请求。启动后 20s 立即预热一轮，避免重启后首个请求冷启动。
    """
    import asyncio

    from apscheduler.triggers.interval import IntervalTrigger

    async def _run_prewarm():
        await prewarm_market_data()

    # 交易时段 5 分钟一次
    scheduler.add_job(
        _run_prewarm,
        IntervalTrigger(minutes=5),
        id="market_data_prewarm_trading",
        name="市场数据预热（交易时段）",
        replace_existing=True,
    )
    logger.info("📈 [prewarm] 市场数据预热任务已注册（交易时段每5分钟）")

    # 启动后延迟 20s 立即预热一轮：服务重启后尽快填热缓存，避免首个请求冷启动
    async def _run_prewarm_startup():
        await asyncio.sleep(20)
        await prewarm_market_data()

    try:
        asyncio.get_running_loop().create_task(_run_prewarm_startup())
    except RuntimeError:
        logger.warning("🌡️ [prewarm] 无运行中事件循环，跳过启动预热（稍后由 interval 任务接管）")