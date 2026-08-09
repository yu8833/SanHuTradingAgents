#!/usr/bin/env python3
"""
回填每日估值/市值数据（stock_daily_basic）。

供回测按日对齐历史 PE/PB/市值。用于在 cron 之外，按需回填某个回测区间的
历史每日估值数据。

用法：
    python3 scripts/backfill_daily_basic.py [start_date] [end_date]
    # 例：回填 2024-08-01 ~ 2026-08-08 的每日估值
    python3 scripts/backfill_daily_basic.py 2024-08-01 2026-08-08

    # 不带参数则默认回填最近 730 天
    python3 scripts/backfill_daily_basic.py
"""
import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def main(start_date: str, end_date: str, days_back: int) -> None:
    from app.core.database import init_database, close_database
    from app.worker.tushare_sync_service import get_tushare_sync_service

    await init_database()
    try:
        service = await get_tushare_sync_service()
        result = await service.sync_daily_basic_data(
            start_date=start_date,
            end_date=end_date,
            days_back=days_back,
            job_id="backfill_daily_basic",
        )
        logger.info("回填完成: %s", result)
    finally:
        await close_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回填每日估值/市值数据（stock_daily_basic）")
    parser.add_argument("start_date", nargs="?", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("end_date", nargs="?", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument("--days-back", type=int, default=730,
                        help="未指定 start_date 时回溯天数（默认730）")
    args = parser.parse_args()
    asyncio.run(main(args.start_date, args.end_date, args.days_back))