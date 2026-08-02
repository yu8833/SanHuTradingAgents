"""
散户策略定时任务

1. 持仓退出信号扫描：盘中定时检查所有用户的未平仓持仓，触发退出信号时推送通知
2. 市场环境检测：每日盘前检测市场环境，环境变化时通知用户

通知通过 NotificationsService.create_and_publish 发送，内部自动触发 WebSocket 推送。
"""

import logging
from datetime import datetime

from app.core.database import get_mongo_db
from app.models.notification import NotificationCreate
from app.services.notifications_service import get_notifications_service
from app.services.portfolio_service import portfolio_service
from app.services.retail.retail_strategy_service import get_retail_strategy_service

logger = logging.getLogger(__name__)

# 缓存上次市场环境摘要，用于检测变化
_last_regime_summary: str | None = None


def _is_trading_day() -> bool:
    """交易日判断（排除周末和节假日，使用统一的 trading_time 模块）"""
    from app.utils.trading_time import is_trading_day

    return is_trading_day(datetime.now())


async def _get_all_user_ids_with_open_positions() -> list[str]:
    """获取所有有未平仓持仓的用户ID"""
    try:
        db = get_mongo_db()
        # 统一数据源：paper_positions（quantity > 0 即未平仓）
        user_ids = await db["paper_positions"].distinct("user_id", {"quantity": {"$gt": 0}})
        return [str(uid) for uid in user_ids if uid]
    except Exception as e:
        logger.error(f"获取有持仓的用户列表失败: {e}")
        return []


async def _get_position_current_prices(symbols: list[str]) -> dict[str, float]:
    """批量获取持仓当前价"""
    if not symbols:
        return {}
    try:
        from app.services.quotes_service import get_quotes_service
        quotes = await get_quotes_service().get_quotes(symbols)
        return {
            code: q["close"]
            for code, q in quotes.items()
            if q.get("close") is not None
        }
    except Exception as e:
        logger.error(f"获取持仓当前价失败: {e}")
        return {}


# 退出原因 -> 中文标签
_REASON_LABELS = {
    "thesis_invalid": "逻辑证伪",
    "stop_loss": "止损",
    "take_profit": "止盈",
    "time_stop": "时间止损",
    "none": "无信号",
}


async def check_all_users_exit_signals():
    """
    持仓退出信号扫描任务

    遍历所有有未平仓持仓的用户，获取实时行情，调用退出规则引擎，
    对触发退出信号的持仓推送通知（自动触发 WebSocket）。
    """
    logger.info("🔍 开始扫描持仓退出信号...")

    if not _is_trading_day():
        logger.info("⏭️ 非交易日，跳过退出信号扫描")
        return

    try:
        user_ids = await _get_all_user_ids_with_open_positions()
        if not user_ids:
            logger.info("⏭️ 没有未平仓持仓，跳过")
            return

        retail_service = get_retail_strategy_service()
        notif_service = get_notifications_service()

        total_checked = 0
        total_signals = 0
        total_notified = 0

        for user_id in user_ids:
            try:
                positions = await portfolio_service.get_open_positions(user_id)
                if not positions:
                    continue

                # 批量获取行情
                symbols = [p["symbol"] for p in positions if p.get("symbol")]
                prices = await _get_position_current_prices(symbols)
                if not prices:
                    logger.warning(f"用户 {user_id} 的持仓无法获取行情，跳过")
                    continue

                # 构造退出检查输入
                holdings_to_check: list[dict] = []
                position_map: dict[str, dict] = {}
                for p in positions:
                    symbol = p["symbol"]
                    current_price = prices.get(symbol)
                    if not current_price or current_price <= 0:
                        continue
                    holdings_to_check.append({
                        "symbol": symbol,
                        "strategy": p.get("strategy", "default"),
                        "buy_price": p.get("cost_price", 0),
                        "buy_date": p.get("buy_date", datetime.now().strftime("%Y-%m-%d")),
                        "current_price": current_price,
                    })
                    position_map[symbol] = p

                if not holdings_to_check:
                    continue

                signals = retail_service.check_exits(holdings_to_check)
                total_checked += len(signals)

                exit_signals = [s for s in signals if s.should_exit]
                total_signals += len(exit_signals)

                for sig in exit_signals:
                    pos = position_map.get(sig.symbol, {})
                    stock_name = pos.get("stock_name", sig.symbol)
                    reason_label = _REASON_LABELS.get(sig.reason.value, sig.reason.value)
                    severity = "error" if sig.reason.value in ("stop_loss", "thesis_invalid") else "warning"

                    title = f"【{reason_label}】{stock_name} 需要卖出"
                    content = (
                        f"{sig.detail}\n"
                        f"当前盈亏: {sig.current_pnl_pct:+.2%} | "
                        f"持仓天数: {sig.holding_days}天 | "
                        f"建议卖出: {sig.suggested_sell_ratio * 100:.0f}%"
                    )

                    try:
                        await notif_service.create_and_publish(
                            payload=NotificationCreate(
                                user_id=user_id,
                                type="alert",
                                title=title,
                                content=content,
                                link="/screening/retail-center",
                                source="retail_exit_scanner",
                                severity=severity,
                                metadata={
                                    "symbol": sig.symbol,
                                    "reason": sig.reason.value,
                                    "suggested_sell_ratio": sig.suggested_sell_ratio,
                                    "current_pnl_pct": sig.current_pnl_pct,
                                    "holding_days": sig.holding_days,
                                    "position_id": pos.get("id"),
                                },
                            )
                        )
                        total_notified += 1
                    except Exception as e:
                        logger.error(f"推送退出信号通知失败: user={user_id}, symbol={sig.symbol}, error={e}")

            except Exception as e:
                logger.error(f"处理用户 {user_id} 持仓退出检查失败: {e}", exc_info=True)
                continue

        logger.info(
            f"✅ 退出信号扫描完成: 检查 {total_checked} 个持仓, "
            f"触发 {total_signals} 个退出信号, 推送 {total_notified} 条通知"
        )

    except Exception as e:
        logger.error(f"❌ 持仓退出信号扫描失败: {e}", exc_info=True)


async def _get_market_regime_data() -> dict | None:
    """
    获取市场环境检测所需的数据（自动采集）

    委托给 market_data_collector 服务，自动获取：
    - 沪深300当前价 + MA250 + 波动率分位
    - 市场宽度（涨跌家数占比）
    - 融资余额近5日变化
    - 全市场换手率及20日均值
    """
    try:
        from app.services.retail.market_data_collector import collect_market_regime_data
        return await collect_market_regime_data()
    except Exception as e:
        logger.error(f"获取市场环境数据失败: {e}")
        return None


async def detect_market_regime_daily():
    """每日盘前检测市场环境，环境变化时通知所有持仓用户。"""
    global _last_regime_summary

    logger.info("🌍 开始检测市场环境...")

    if not _is_trading_day():
        logger.info("⏭️ 非交易日，跳过市场环境检测")
        return

    try:
        data = await _get_market_regime_data()
        if data is None:
            logger.warning("⏭️ 无法获取市场环境数据，跳过")
            return

        retail_service = get_retail_strategy_service()
        regime = retail_service.detect_regime(**data)
        regime_dict = regime.to_dict()
        current_summary = regime_dict.get("summary", "")

        logger.info(f"📊 当前市场环境: {current_summary}")

        # 环境变化时通知
        if _last_regime_summary is not None and _last_regime_summary != current_summary:
            try:
                user_ids = await _get_all_user_ids_with_open_positions()
                notif_service = get_notifications_service()

                trend_labels = {"bull": "牛市", "bear": "熊市", "range": "震荡市"}
                trend = regime_dict.get("trend", "range")
                active_strategies = regime_dict.get("active_strategies", [])
                strategy_text = "、".join(active_strategies) if active_strategies else "暂无推荐"

                title = f"市场环境变化：转入{trend_labels.get(trend, trend)}"
                content = f"{current_summary}\n当前推荐策略：{strategy_text}"

                notified = 0
                for uid in user_ids:
                    try:
                        await notif_service.create_and_publish(
                            payload=NotificationCreate(
                                user_id=uid,
                                type="system",
                                title=title,
                                content=content,
                                link="/screening/retail-center",
                                source="retail_regime_detector",
                                severity="warning",
                                metadata=regime_dict,
                            )
                        )
                        notified += 1
                    except Exception as e:
                        logger.error(f"推送环境变化通知失败: user={uid}, error={e}")

                logger.info(f"📢 市场环境变化通知已推送给 {notified} 个用户")
            except Exception as e:
                logger.error(f"推送市场环境变化通知失败: {e}")

        _last_regime_summary = current_summary
        logger.info("✅ 市场环境检测完成")

    except Exception as e:
        logger.error(f"❌ 市场环境检测失败: {e}", exc_info=True)


def register_retail_jobs(scheduler, settings):
    """
    注册散户策略定时任务

    Args:
        scheduler: APScheduler 调度器实例
        settings: 应用配置（取 TIMEZONE）
    """
    from apscheduler.triggers.cron import CronTrigger

    tz = settings.TIMEZONE

    # 1. 持仓退出信号扫描：工作日 9:30-14:59 每30分钟 + 15:00 收盘前
    scheduler.add_job(
        check_all_users_exit_signals,
        CronTrigger.from_crontab("*/30 9-14 * * 1-5", timezone=tz),
        id="retail_exit_check",
        name="散户持仓退出信号扫描（盘中每30分钟）",
        replace_existing=True,
    )
    scheduler.add_job(
        check_all_users_exit_signals,
        CronTrigger.from_crontab("0 15 * * 1-5", timezone=tz),
        id="retail_exit_check_close",
        name="散户持仓收盘退出扫描",
        replace_existing=True,
    )

    # 2. 市场环境检测：工作日 9:30
    scheduler.add_job(
        detect_market_regime_daily,
        CronTrigger.from_crontab("30 9 * * 1-5", timezone=tz),
        id="retail_regime_detect",
        name="散户市场环境检测（每日9:30）",
        replace_existing=True,
    )

    # 3. 个股预警检查：工作日 9:30-15:00 每10分钟
    scheduler.add_job(
        _check_stock_alerts_wrapper,
        CronTrigger.from_crontab("*/10 9-14 * * 1-5", timezone=tz),
        id="stock_alert_check",
        name="个股预警检查（盘中每10分钟）",
        replace_existing=True,
    )
    scheduler.add_job(
        _check_stock_alerts_wrapper,
        CronTrigger.from_crontab("0 15 * * 1-5", timezone=tz),
        id="stock_alert_check_close",
        name="个股预警收盘检查",
        replace_existing=True,
    )

    logger.info("📊 散户策略定时任务已注册: 退出扫描(盘中每30分钟+收盘) + 环境检测(每日9:30) + 个股预警(每10分钟)")


async def _check_stock_alerts_wrapper():
    """个股预警检查包装器"""
    try:
        from app.services.stock_alert_service import stock_alert_service
        await stock_alert_service.check_and_trigger()
    except Exception as e:
        logger.error(f"❌ 个股预警检查失败: {e}", exc_info=True)
