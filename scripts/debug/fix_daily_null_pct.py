#!/usr/bin/env python3
"""
一次性修复脚本：修正 stock_daily_quotes 中已存在但 pre_close/pct_chg 为 null 的 CN 日线记录。

背景（F4）：此前 AKShare 历史兜底数据写入 stock_daily_quotes 时 pre_close/change/pct_chg 为 null，
导致被 AKShare 兜底补数的股票日线（K线/涨跌幅）展示为空。

修复逻辑：按每只股票自身的日线序列，用「前一交易日收盘」回算并补写缺失的涨跌字段。

用法（在后端容器内，工作目录为项目根）：
    python -m scripts.debug.fix_daily_null_pct --dry-run --limit 500
    python -m scripts.debug.fix_daily_null_pct --source akshare --limit 100000
参数：
    --source    限定要修复的数据源，如 akshare/tushare/baostock；默认修复所有缺失字段的记录
    --limit     本次最多处理的股票数（默认 50000）
    --dry-run   仅统计，不写入
"""
import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fix_daily_null_pct")

from pymongo import UpdateOne

from app.core.database import get_mongo_db, init_database


async def _ensure_db():
    """独立进程运行时需先初始化数据库连接"""
    try:
        get_mongo_db()
    except RuntimeError:
        await init_database()


def _to_float(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


async def main():
    parser = argparse.ArgumentParser(description="修复 stock_daily_quotes 中 null 的 pre_close/pct_chg")
    parser.add_argument("--source", default=None, help="限定数据源，如 akshare/tushare/baostock；默认全部")
    parser.add_argument("--limit", type=int, default=50000, help="最多处理的股票数（默认 50000）")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写入")
    args = parser.parse_args()

    await _ensure_db()
    db = get_mongo_db()
    coll = db.stock_daily_quotes

    match: dict = {"period": "daily"}
    match["$or"] = [
        {"pct_chg": None}, {"pct_chg": {"$exists": False}},
        {"pre_close": None}, {"pre_close": {"$exists": False}},
    ]
    if args.source:
        match["data_source"] = args.source

    # 找出含缺失记录的股票（按 code 聚合），统计缺失文档数
    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$code", "n": {"$sum": 1}}},
    ]
    grouped = await coll.aggregate(pipeline).to_list(length=None)
    codes = [g["_id"] for g in grouped if g.get("_id")]
    missing_docs = sum(g["n"] for g in grouped)
    if args.limit:
        codes = codes[: args.limit]
    logger.info(
        f"待修复: 股票 {len(codes)} 只, 含 null 涨跌字段的文档 {missing_docs} 条 "
        f"(dry_run={args.dry_run}, source={args.source or 'all'})"
    )

    total_fixed = 0
    total_updated = 0
    bulk_ops = []  # 批量收集更新操作
    chunk_size = 1000  # 每个 bulk_write 批次的更新条数上限

    def _flush(force: bool = False):
        """累积到 chunk_size 或全部结束时提交；超出时自动分批多次 bulk_write"""
        nonlocal total_updated
        if args.dry_run or not bulk_ops:
            bulk_ops.clear()
            return
        # 分批提交，规避单批过大（DocumentTooLarge / 超时）
        for i in range(0, len(bulk_ops), chunk_size):
            chunk = bulk_ops[i:i + chunk_size]
            for attempt in range(3):  # 简单重试，避免瞬时网络抖动丢写
                try:
                    coll.bulk_write(chunk, ordered=False)
                    break
                except Exception as e:
                    logger.warning(f"⚠️ bulk_write 批次({len(chunk)}) 第{attempt+1}次失败（忽略后重试）: {type(e).__name__}: {str(e)[:200]}")
                    if attempt == 2:
                        logger.warning(f"⚠️ 当前批次写入失败，跳过 {len(chunk)} 条")
        total_updated += len(bulk_ops)
        bulk_ops.clear()

    for code in codes:
        rows = await coll.find(
            {"code": code, "period": "daily"},
            {"trade_date": 1, "close": 1, "pre_close": 1, "pct_chg": 1},
        ).sort("trade_date", 1).to_list(length=None)

        # 按 trade_date 归约（同日期多源文档视为同一交易日，close 一致）
        by_date: dict = {}
        for r in rows:
            s = str(r.get("trade_date") or "").replace("-", "").replace("/", "").strip()
            if len(s) != 8 or not s.isdigit():
                continue
            if s not in by_date:
                by_date[s] = {"close": None, "docs": []}
            c = _to_float(r.get("close"))
            if c is not None:
                by_date[s]["close"] = c
            by_date[s]["docs"].append(r)

        last_close = None
        for _day in sorted(by_date.keys()):
            data = by_date[_day]
            cls = data["close"]
            for r in data["docs"]:
                need_pre = _to_float(r.get("pre_close")) is None
                need_pct = _to_float(r.get("pct_chg")) is None
                if not need_pre and not need_pct:
                    continue
                upd: dict = {}
                if need_pre and last_close not in (None, 0):
                    upd["pre_close"] = last_close
                pre = upd.get("pre_close", _to_float(r.get("pre_close")))
                if need_pct and cls is not None and pre not in (None, 0):
                    upd["pct_chg"] = round((cls / pre - 1.0) * 100.0, 2)
                if not upd:
                    continue
                total_fixed += 1
                if not args.dry_run:
                    bulk_ops.append(UpdateOne({"_id": r["_id"]}, {"$set": upd}))
            if cls is not None:
                last_close = cls
        # 每只股票处理完后提交已累积的批次，控制内存与单批大小
        _flush()
    _flush(force=True)

    logger.info(
        f"✅ 完成: 处理股票 {len(codes)} 只, 修复文档 {total_fixed} 条, "
        f"实际写入 {total_updated} 条 (dry_run={args.dry_run})"
    )


if __name__ == "__main__":
    asyncio.run(main())