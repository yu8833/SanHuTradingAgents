#!/usr/bin/env python3
"""
修复 market_quotes 集合中 amount/volume 单位错误（bug-012 遗留存量数据）

根因：bug-012 修复了 adapter 代码，但 market_quotes 存量数据未被修正。
      所有股票的 amount 被除以 100,000，volume 被乘以 100。
      stock_daily_quotes 数据正确，用作修复数据源。

修复方案：从 stock_daily_quotes 读取最新交易日的正确数据，覆盖 market_quotes。

用法（容器内执行）：
  docker compose run --rm test python scripts/debug/fix_market_quotes_units.py
  docker compose run --rm test python scripts/debug/fix_market_quotes_units.py --dry-run
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def fix_market_quotes(dry_run: bool = False):
    from app.core.database import init_database, get_mongo_db, close_database
    from app.core.numeric_sanitizer import (
        sanitize_amount as _s_amount,
        sanitize_volume as _s_volume,
        sanitize_price as _s_price,
        sanitize_pct_chg as _s_pct,
    )
    from pymongo import UpdateOne

    await init_database()
    try:
        db = get_mongo_db()

        # 1. 找到 stock_daily_quotes 中最新的交易日
        latest_doc = await db["stock_daily_quotes"].find_one(
            {"period": "daily"},
            sort=[("trade_date", -1)]
        )
        if not latest_doc:
            logger.error("❌ stock_daily_quotes 集合为空，无法修复")
            return 1

        latest_trade_date_str = latest_doc.get("trade_date")  # "2026-07-31" 格式
        # market_quotes 用 "20260731" 格式
        latest_trade_date_compact = latest_trade_date_str.replace("-", "") if latest_trade_date_str else ""
        logger.info(f"📊 最新交易日: {latest_trade_date_str} (compact: {latest_trade_date_compact})")

        # 2. 从 stock_daily_quotes 读取该日所有股票的数据
        cursor = db["stock_daily_quotes"].find({
            "trade_date": latest_trade_date_str,
            "period": "daily"
        })
        docs = await cursor.to_list(length=None)
        logger.info(f"📊 stock_daily_quotes 中 {latest_trade_date_str} 共 {len(docs)} 条记录")

        if not docs:
            logger.error("❌ 未找到最新交易日数据")
            return 1

        # 3. 构建 bulk_write 操作
        ops = []
        fixed_count = 0
        skipped = 0
        tz = ZoneInfo("Asia/Shanghai")
        updated_at = datetime.now(tz)

        # 先读取现有 market_quotes 用于对比
        before_sample = {}
        for code in ["688669", "000001", "600519"]:
            mq = await db["market_quotes"].find_one({"code": code})
            if mq:
                before_sample[code] = {"amount": mq.get("amount"), "volume": mq.get("volume")}

        for doc in docs:
            code = doc.get("symbol") or doc.get("code")
            if not code:
                skipped += 1
                continue
            code6 = str(code).zfill(6)

            amount = _s_amount(doc.get("amount"))
            volume = _s_volume(doc.get("volume") or doc.get("vol"))
            close = _s_price(doc.get("close"))
            open_p = _s_price(doc.get("open"))
            high = _s_price(doc.get("high"))
            low = _s_price(doc.get("low"))
            pre_close = _s_price(doc.get("pre_close"))
            pct_chg = _s_pct(doc.get("pct_chg"))

            ops.append(UpdateOne(
                {"code": code6},
                {"$set": {
                    "code": code6,
                    "symbol": code6,
                    "close": close,
                    "pct_chg": pct_chg,
                    "amount": amount,   # 元（正确）
                    "volume": volume,   # 股（正确）
                    "open": open_p,
                    "high": high,
                    "low": low,
                    "pre_close": pre_close,
                    "trade_date": latest_trade_date_compact,
                    "updated_at": updated_at,
                }},
                upsert=True,
            ))
            fixed_count += 1

        logger.info(f"📊 准备修复 {fixed_count} 条记录（跳过 {skipped} 条无效记录）")

        if dry_run:
            logger.info("\n【DRY-RUN 模式】不执行实际写入")
            logger.info("\n修复前后对比（样本）：")
            for code, before in before_sample.items():
                sq = await db["stock_daily_quotes"].find_one({"code": code, "trade_date": latest_trade_date_str})
                if sq:
                    logger.info(f"  {code}:")
                    logger.info(f"    修复前 amount={before['amount']}, volume={before['volume']}")
                    logger.info(f"    修复后 amount={sq.get('amount')} (元), volume={sq.get('volume')} (股)")
            return 0

        # 4. 执行 bulk_write
        if ops:
            result = await db["market_quotes"].bulk_write(ops, ordered=False)
            logger.info(f"✅ 修复完成: matched={result.matched_count}, upserted={len(result.upserted_ids) if result.upserted_ids else 0}, modified={result.modified_count}")

        # 5. 验证修复结果
        logger.info("\n" + "=" * 90)
        logger.info("【修复后验证】")
        logger.info("=" * 90)
        for code in ["688669", "000001", "600519", "300750"]:
            mq = await db["market_quotes"].find_one({"code": code})
            sq = await db["stock_daily_quotes"].find_one({"code": code, "trade_date": latest_trade_date_str})
            if mq and sq:
                amt_match = abs((mq.get("amount") or 0) - (sq.get("amount") or 0)) < 1
                vol_match = abs((mq.get("volume") or 0) - (sq.get("volume") or 0)) < 1
                status = "✅" if (amt_match and vol_match) else "❌"
                logger.info(f"  {code}: {status} market_quotes(amount={mq.get('amount'):,.2f}, volume={mq.get('volume'):,.0f}) vs stock_daily_quotes(amount={sq.get('amount'):,.2f}, volume={sq.get('volume'):,.0f})")

        # 6. 全量一致性检查
        logger.info("\n【全量一致性检查】")
        mismatch_count = 0
        check_total = 0
        async for mq in db["market_quotes"].find({}):
            code = mq.get("code")
            if not code:
                continue
            sq = await db["stock_daily_quotes"].find_one({"code": code, "trade_date": latest_trade_date_str})
            if not sq:
                continue
            check_total += 1
            amt_mismatch = mq.get("amount") and sq.get("amount") and abs(mq["amount"] - sq["amount"]) > 1
            vol_mismatch = mq.get("volume") and sq.get("volume") and abs(mq["volume"] - sq["volume"]) > 1
            if amt_mismatch or vol_mismatch:
                mismatch_count += 1

        logger.info(f"  检查 {check_total} 只股票，不一致: {mismatch_count} 只")
        if mismatch_count == 0:
            logger.info("  ✅ 全部一致！")
        else:
            logger.warning(f"  ⚠️ 仍有 {mismatch_count} 只不一致")

        return 0

    finally:
        await close_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复 market_quotes amount/volume 单位错误")
    parser.add_argument("--dry-run", action="store_true", help="只显示修复前后对比，不实际写入")
    args = parser.parse_args()

    sys.exit(asyncio.run(fix_market_quotes(dry_run=args.dry_run)))
