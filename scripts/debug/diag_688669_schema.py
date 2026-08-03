#!/usr/bin/env python3
"""
688669 增强诊断：查看 stock_daily_quotes 实际结构和 market_quotes 完整记录
"""

import asyncio
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SYMBOL = "688669"


async def main():
    from app.core.database import init_database, get_mongo_db, close_database

    await init_database()
    try:
        db = get_mongo_db()

        # 1. stock_daily_quotes: 不限日期，查 688669 所有记录（只取最近 10 条）
        logger.info("=" * 90)
        logger.info("【1】stock_daily_quotes 中 688669 的最近 10 条记录（不限日期）")
        logger.info("=" * 90)
        cursor = db["stock_daily_quotes"].find({"code": SYMBOL}).sort("trade_date", -1).limit(10)
        count = 0
        async for doc in cursor:
            count += 1
            logger.info(f"\n--- 记录 {count} ---")
            for k, v in doc.items():
                if k == "_id":
                    continue
                logger.info(f"  {k}: {v}")
        if count == 0:
            logger.info("  ❌ 无记录！尝试用 symbol 字段查询...")
            cursor2 = db["stock_daily_quotes"].find({"symbol": SYMBOL}).sort("trade_date", -1).limit(5)
            async for doc in cursor2:
                logger.info(f"  symbol查询命中: trade_date={doc.get('trade_date')}, code={doc.get('code')}, amount={doc.get('amount')}, volume={doc.get('volume')}")

        # 2. stock_daily_quotes: 统计总量
        total = await db["stock_daily_quotes"].count_documents({"code": SYMBOL})
        logger.info(f"\n  stock_daily_quotes 中 code={SYMBOL} 总记录数: {total}")
        total_symbol = await db["stock_daily_quotes"].count_documents({"symbol": SYMBOL})
        logger.info(f"  stock_daily_quotes 中 symbol={SYMBOL} 总记录数: {total_symbol}")

        # 3. 查看任意一条记录的字段名（用于确认 schema）
        logger.info("\n" + "=" * 90)
        logger.info("【2】stock_daily_quotes 任意一条记录的字段名（确认 schema）")
        logger.info("=" * 90)
        any_doc = await db["stock_daily_quotes"].find_one({"code": SYMBOL})
        if any_doc:
            logger.info(f"  字段列表: {list(any_doc.keys())}")
            logger.info(f"  trade_date 样例: {any_doc.get('trade_date')} (类型: {type(any_doc.get('trade_date')).__name__})")
            logger.info(f"  date 字段: {any_doc.get('date')}")
        else:
            logger.info("  无记录")
            # 看看集合里随便一条记录的字段名
            any_any = await db["stock_daily_quotes"].find_one()
            if any_any:
                logger.info(f"  集合任意记录字段: {list(any_any.keys())}")
                logger.info(f"  样例 code={any_any.get('code')}, symbol={any_any.get('symbol')}, trade_date={any_any.get('trade_date')}")

        # 4. market_quotes: 688669 完整记录
        logger.info("\n" + "=" * 90)
        logger.info("【3】market_quotes 中 688669 的完整记录（所有字段）")
        logger.info("=" * 90)
        doc = await db["market_quotes"].find_one({"code": SYMBOL})
        if doc:
            for k, v in doc.items():
                if k == "_id":
                    continue
                logger.info(f"  {k}: {v}")
        else:
            logger.info("  ❌ 无记录")

        # 5. 对比验证：amount 是否 ≈ volume × close / 100 （如果 volume 被当成了手）
        logger.info("\n" + "=" * 90)
        logger.info("【4】market_quotes 数据关系验证")
        logger.info("=" * 90)
        if doc:
            amt = doc.get("amount")
            vol = doc.get("volume") or doc.get("vol")
            close = doc.get("close")
            logger.info(f"  amount={amt}")
            logger.info(f"  volume={vol}")
            logger.info(f"  close={close}")
            if amt and vol and close:
                # 正确关系：amount(元) ≈ volume(股) × close(元)
                logger.info(f"\n  正确关系 amount ≈ volume × close = {vol * close:,.2f}")
                logger.info(f"  实际 amount / (volume × close) = {amt / (vol * close):.6f}")
                # 如果 volume 实际是手（未×100），则 amount ≈ volume × 100 × close
                logger.info(f"  若 volume 是手: amount ≈ volume × 100 × close = {vol * 100 * close:,.2f}")
                logger.info(f"  实际 amount / (volume × 100 × close) = {amt / (vol * 100 * close):.6f}")

        # 6. 检查 stock_daily_quotes 中其他股票的 amount 量级（抽样）
        logger.info("\n" + "=" * 90)
        logger.info("【5】stock_daily_quotes 抽样 5 条（任意股票），看 amount/volume 量级")
        logger.info("=" * 90)
        sample_cursor = db["stock_daily_quotes"].find({}, {"_id": 0}).sort("trade_date", -1).limit(5)
        async for s in sample_cursor:
            logger.info(f"  code={s.get('code')}, date={s.get('trade_date')}, close={s.get('close')}, volume={s.get('volume')}, amount={s.get('amount')}, source={s.get('data_source')}")

    finally:
        await close_database()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
