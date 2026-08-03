#!/usr/bin/env python3
"""
检查 market_quotes 中多只股票的 amount/volume 错误模式
对比 market_quotes vs stock_daily_quotes（正确数据源）
"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main():
    from app.core.database import init_database, get_mongo_db, close_database

    await init_database()
    try:
        db = get_mongo_db()

        # 取 market_quotes 中 10 只股票（含 688669）
        sample_codes = ["688669", "000001", "600519", "300750", "000002", "601318", "002594", "600036", "000858", "002475"]

        logger.info("=" * 110)
        logger.info(f"{'code':<8} {'mq_amt':>14} {'sq_amt':>14} {'amt_ratio':>10} | {'mq_vol':>14} {'sq_vol':>14} {'vol_ratio':>10}")
        logger.info("=" * 110)

        for code in sample_codes:
            # market_quotes
            mq = await db["market_quotes"].find_one({"code": code})
            # stock_daily_quotes (最新交易日)
            sq = await db["stock_daily_quotes"].find_one(
                {"code": code, "trade_date": "2026-07-31"},
                sort=[("trade_date", -1)]
            )
            if not sq:
                # 尝试其他日期格式
                sq = await db["stock_daily_quotes"].find_one(
                    {"code": code},
                    sort=[("trade_date", -1)]
                )

            mq_amt = mq.get("amount") if mq else None
            mq_vol = mq.get("volume") if mq else None
            sq_amt = sq.get("amount") if sq else None
            sq_vol = sq.get("volume") if sq else None

            amt_ratio = (mq_amt / sq_amt) if (mq_amt and sq_amt) else None
            vol_ratio = (mq_vol / sq_vol) if (mq_vol and sq_vol) else None

            def fmt(v):
                if v is None:
                    return "N/A"
                return f"{v:,.2f}"

            def fmt_ratio(v):
                return f"{v:.6f}" if v is not None else "N/A"

            logger.info(
                f"{code:<8} {fmt(mq_amt):>16} {fmt(sq_amt):>16} {fmt_ratio(amt_ratio):>10} | "
                f"{fmt(mq_vol):>16} {fmt(sq_vol):>16} {fmt_ratio(vol_ratio):>10}"
            )

        # 统计 market_quotes 中有多少条记录的 amount 明显异常（< 100 或 > 1e15）
        logger.info("\n" + "=" * 110)
        logger.info("【market_quotes 异常统计】")
        logger.info("=" * 110)
        total = await db["market_quotes"].count_documents({})
        too_small = await db["market_quotes"].count_documents({"amount": {"$lt": 100, "$ne": None}})
        too_big = await db["market_quotes"].count_documents({"amount": {"$gt": 1e15}})
        none_amt = await db["market_quotes"].count_documents({"amount": None})
        logger.info(f"  总记录数: {total}")
        logger.info(f"  amount < 100 (疑似万元/千元单位): {too_small}")
        logger.info(f"  amount > 1e15 (疑似过度放大): {too_big}")
        logger.info(f"  amount = None: {none_amt}")

        # 同样统计 volume 异常
        vol_too_big = await db["market_quotes"].count_documents({"volume": {"$gt": 1e12}})
        logger.info(f"  volume > 1e12 (疑似过度放大): {vol_too_big}")

    finally:
        await close_database()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
