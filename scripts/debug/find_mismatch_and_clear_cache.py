#!/usr/bin/env python3
"""找出修复后仍不一致的那只股票，并清除 Redis 行情缓存"""
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
        latest_trade_date_str = "2026-07-31"

        logger.info("【查找不一致的股票】")
        async for mq in db["market_quotes"].find({}):
            code = mq.get("code")
            if not code:
                continue
            sq = await db["stock_daily_quotes"].find_one({"code": code, "trade_date": latest_trade_date_str})
            if not sq:
                continue
            amt_mismatch = mq.get("amount") and sq.get("amount") and abs(mq["amount"] - sq["amount"]) > 1
            vol_mismatch = mq.get("volume") and sq.get("volume") and abs(mq["volume"] - sq["volume"]) > 1
            if amt_mismatch or vol_mismatch:
                logger.info(f"  不一致: code={code}")
                logger.info(f"    market_quotes: amount={mq.get('amount')}, volume={mq.get('volume')}, trade_date={mq.get('trade_date')}")
                logger.info(f"    stock_daily_quotes: amount={sq.get('amount')}, volume={sq.get('volume')}")
                logger.info(f"    amount diff: {mq.get('amount') - sq.get('amount') if mq.get('amount') and sq.get('amount') else 'N/A'}")

        # 清除 Redis 行情缓存
        logger.info("\n【清除 Redis 行情缓存】")
        try:
            from app.core.sync_redis import get_sync_redis
            r = get_sync_redis()
            # 删除所有 quotes 相关的缓存 key
            patterns = ["quotes:*", "quote:*", "stock:*:quote", "stock:*", "unified_quotes:*"]
            total_deleted = 0
            for pattern in patterns:
                keys = r.keys(pattern)
                if keys:
                    r.delete(*keys)
                    total_deleted += len(keys)
                    logger.info(f"  删除 {pattern}: {len(keys)} 个 key")
            logger.info(f"  共删除 {total_deleted} 个缓存 key")
        except Exception as e:
            logger.error(f"  清除缓存失败: {e}")

    finally:
        await close_database()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
