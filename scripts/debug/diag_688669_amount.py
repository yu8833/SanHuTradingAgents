#!/usr/bin/env python3
"""
688669 成交额/成交量数据一致性诊断脚本（第一性原理比对）

对比 4 个数据源，定位 amount/volume 单位错误的精确位置：
  S1: Tushare pro.daily() 原始返回（amount=千元, vol=手）
  S2: TushareAdapter.get_kline() 转换后（应为 amount=元, volume=股）
  S3: MongoDB stock_daily_quotes 集合（应为 amount=元, volume=股）
  S4: MongoDB market_quotes 集合（应为 amount=元, volume=股）

用户期望真值（2026-07-31）：成交量 3.96万手, 成交额 2.41亿元
  => volume = 3,960,000 股, amount = 241,000,000 元

用法（容器内执行）：
  docker compose run --rm test python scripts/debug/diag_688669_amount.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# 项目根目录加入 sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

SYMBOL = "688669"
TS_CODE = "688669.SH"
START_DATE = "20260727"
END_DATE = "20260731"


async def s1_tushare_raw():
    """S1: 直接调用 Tushare pro.daily()，获取原始未转换值"""
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN", "").strip().strip('"').strip("'")
    if not token:
        # 尝试从 provider 获取
        try:
            from tradingagents.dataflows.providers.china.tushare import get_tushare_provider

            token = getattr(get_tushare_provider(), "token", None) or ""
        except Exception:
            pass
    if not token:
        logger.error("S1: 未获取到 TUSHARE_TOKEN，无法调用原始 API")
        return []

    ts.set_token(token)
    pro = ts.pro_api()
    df = pro.daily(ts_code=TS_CODE, start_date=START_DATE, end_date=END_DATE)
    if df is None or len(df) == 0:
        logger.error("S1: Tushare daily 返回空")
        return []

    # 按 trade_date 升序
    df = df.sort_values("trade_date").reset_index(drop=True)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "trade_date": str(r["trade_date"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "vol": float(r["vol"]),        # 原始单位：手
            "amount": float(r["amount"]),  # 原始单位：千元
        })
    return rows


def s2_adapter_converted():
    """S2: 调用 TushareAdapter.get_kline()，获取 adapter 转换后的值（同步方法）"""
    from app.services.data_sources.tushare_adapter import TushareAdapter

    adapter = TushareAdapter()
    if not adapter.is_available():
        logger.error("S2: TushareAdapter 不可用")
        return []
    # get_kline 签名: (code, period="day", limit=120, adj=None)，不支持日期范围
    items = adapter.get_kline(SYMBOL, period="day", limit=15)
    if not items:
        logger.error("S2: adapter.get_kline 返回空")
        return []
    # 过滤到目标日期范围 [START_DATE, END_DATE]
    rows = []
    for it in items:
        t = str(it.get("time", ""))
        # trade_date 格式可能是 "20260731" 或 "2026-07-31"
        t_compact = t.replace("-", "")[:8]
        if START_DATE <= t_compact <= END_DATE:
            rows.append({
                "trade_date": t_compact,
                "open": it.get("open"),
                "high": it.get("high"),
                "low": it.get("low"),
                "close": it.get("close"),
                "volume": it.get("volume"),  # 应为 股
                "amount": it.get("amount"),  # 应为 元
            })
    # 按日期升序
    rows.sort(key=lambda x: x["trade_date"])
    return rows


async def s3_stock_daily_quotes():
    """S3: MongoDB stock_daily_quotes 集合"""
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    cursor = db["stock_daily_quotes"].find({
        "code": SYMBOL,
        "trade_date": {"$gte": START_DATE, "$lte": END_DATE},
    }).sort("trade_date", 1)
    rows = []
    async for doc in cursor:
        rows.append({
            "trade_date": str(doc.get("trade_date") or doc.get("date") or ""),
            "open": doc.get("open"),
            "high": doc.get("high"),
            "low": doc.get("low"),
            "close": doc.get("close"),
            "volume": doc.get("volume") or doc.get("vol"),
            "amount": doc.get("amount"),
            "source": doc.get("source") or doc.get("data_source"),
        })
    return rows


async def s4_market_quotes():
    """S4: MongoDB market_quotes 集合"""
    from app.core.database import get_mongo_db

    db = get_mongo_db()
    doc = await db["market_quotes"].find_one({"code": SYMBOL})
    if not doc:
        logger.error("S4: market_quotes 无 688669 记录")
        return None
    return {
        "trade_date": str(doc.get("trade_date") or doc.get("date") or ""),
        "open": doc.get("open"),
        "high": doc.get("high"),
        "low": doc.get("low"),
        "close": doc.get("close"),
        "volume": doc.get("volume") or doc.get("vol"),
        "amount": doc.get("amount"),
        "source": doc.get("source"),
    }


def fmt(v):
    if v is None:
        return "None"
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def fmt_amount_cn(v):
    """把元换算成中文展示"""
    if v is None:
        return "None"
    try:
        n = float(v)
        if n >= 1e8:
            return f"{n/1e8:.4f}亿元"
        if n >= 1e4:
            return f"{n/1e4:.4f}万元"
        return f"{n:.2f}元"
    except Exception:
        return str(v)


def fmt_volume_cn(v):
    """把股换算成中文展示"""
    if v is None:
        return "None"
    try:
        n = float(v)
        if n >= 1e8:
            return f"{n/1e8:.4f}亿股"
        if n >= 1e4:
            return f"{n/1e4:.4f}万股"
        return f"{n:.0f}股"
    except Exception:
        return str(v)


async def main():
    from app.core.database import init_database, close_database

    logger.info("=" * 90)
    logger.info(f"688669 数据一致性诊断（{START_DATE} ~ {END_DATE}）")
    logger.info("用户期望真值（2026-07-31）：成交量 3.96万手=3,960,000股, 成交额 2.41亿元=241,000,000元")
    logger.info("=" * 90)

    s1 = await s1_tushare_raw()
    s2 = s2_adapter_converted()

    await init_database()
    try:
        s3 = await s3_stock_daily_quotes()
        s4 = await s4_market_quotes()
    finally:
        await close_database()

    # ---- S1: Tushare 原始 ----
    logger.info("\n" + "-" * 90)
    logger.info("【S1】Tushare pro.daily() 原始返回（amount=千元, vol=手）")
    logger.info("-" * 90)
    if s1:
        logger.info(f"{'日期':<10} {'close':>10} {'vol(手)':>14} {'amount(千元)':>16}")
        for r in s1:
            logger.info(f"{r['trade_date']:<10} {fmt(r['close']):>10} {fmt(r['vol']):>14} {fmt(r['amount']):>16}")
        last = s1[-1]
        logger.info(f"\n  最新日(2026-07-31) 原始 amount={fmt(last['amount'])} 千元 = {fmt_amount_cn(last['amount']*1000)}")
        logger.info(f"  最新日(2026-07-31) 原始 vol={fmt(last['vol'])} 手 = {fmt_volume_cn(last['vol']*100)}")

    # ---- S2: Adapter 转换后 ----
    logger.info("\n" + "-" * 90)
    logger.info("【S2】TushareAdapter.get_kline() 转换后（应为 amount=元, volume=股）")
    logger.info("-" * 90)
    if s2:
        logger.info(f"{'日期':<10} {'close':>10} {'volume(股)':>16} {'amount(元)':>18}")
        for r in s2:
            logger.info(f"{r['trade_date']:<10} {fmt(r['close']):>10} {fmt(r['volume']):>16} {fmt(r['amount']):>18}")
        last = s2[-1]
        logger.info(f"\n  最新日 amount={fmt(last['amount'])} => {fmt_amount_cn(last['amount'])}")
        logger.info(f"  最新日 volume={fmt(last['volume'])} => {fmt_volume_cn(last['volume'])}")

    # ---- S3: stock_daily_quotes ----
    logger.info("\n" + "-" * 90)
    logger.info("【S3】MongoDB stock_daily_quotes 集合（应为 amount=元, volume=股）")
    logger.info("-" * 90)
    if s3:
        logger.info(f"{'日期':<10} {'close':>10} {'volume':>16} {'amount':>18} {'source':>10}")
        for r in s3:
            logger.info(f"{r['trade_date']:<10} {fmt(r['close']):>10} {fmt(r['volume']):>16} {fmt(r['amount']):>18} {str(r.get('source')):>10}")
        last = s3[-1]
        logger.info(f"\n  最新日 amount={fmt(last['amount'])} => {fmt_amount_cn(last['amount'])}")
        logger.info(f"  最新日 volume={fmt(last['volume'])} => {fmt_volume_cn(last['volume'])}")

    # ---- S4: market_quotes ----
    logger.info("\n" + "-" * 90)
    logger.info("【S4】MongoDB market_quotes 集合（单条最新，应为 amount=元, volume=股）")
    logger.info("-" * 90)
    if s4:
        logger.info(f"  trade_date={s4['trade_date']}")
        logger.info(f"  close={fmt(s4['close'])}")
        logger.info(f"  volume={fmt(s4['volume'])} => {fmt_volume_cn(s4['volume'])}")
        logger.info(f"  amount={fmt(s4['amount'])} => {fmt_amount_cn(s4['amount'])}")
        logger.info(f"  source={s4.get('source')}")

    # ---- 比率分析 ----
    logger.info("\n" + "=" * 90)
    logger.info("【比率分析】以 S1 原始值为基准，计算各源相对 S1 的倍数")
    logger.info("=" * 90)
    if not s1:
        logger.error("S1 为空，无法做比率分析")
        return 1

    # 建立日期索引
    s1_map = {r["trade_date"]: r for r in s1}
    s2_map = {r["trade_date"]: r for r in s2} if s2 else {}
    s3_map = {r["trade_date"]: r for r in s3} if s3 else {}

    logger.info(f"\n{'日期':<10} | {'S1 amt(千元)':>14} | {'S2 amt':>14} {'S2/S1×1000':>12} | {'S3 amt':>14} {'S3/S1×1000':>12}")
    logger.info("-" * 90)
    for d, r1 in sorted(s1_map.items()):
        r2 = s2_map.get(d, {})
        r3 = s3_map.get(d, {})
        a1 = r1.get("amount")
        a2 = r2.get("amount")
        a3 = r3.get("amount")
        ratio2 = (a2 / (a1 * 1000)) if (a1 and a2) else None
        ratio3 = (a3 / (a1 * 1000)) if (a1 and a3) else None
        logger.info(f"{d:<10} | {fmt(a1):>14} | {fmt(a2):>14} {('%.4f' % ratio2) if ratio2 else 'N/A':>12} | {fmt(a3):>14} {('%.4f' % ratio3) if ratio3 else 'N/A':>12}")

    logger.info(f"\n{'日期':<10} | {'S1 vol(手)':>14} | {'S2 vol':>14} {'S2/S1×100':>12} | {'S3 vol':>14} {'S3/S1×100':>12}")
    logger.info("-" * 90)
    for d, r1 in sorted(s1_map.items()):
        r2 = s2_map.get(d, {})
        r3 = s3_map.get(d, {})
        v1 = r1.get("vol")
        v2 = r2.get("volume")
        v3 = r3.get("volume")
        ratio2 = (v2 / (v1 * 100)) if (v1 and v2) else None
        ratio3 = (v3 / (v1 * 100)) if (v1 and v3) else None
        logger.info(f"{d:<10} | {fmt(v1):>14} | {fmt(v2):>14} {('%.4f' % ratio2) if ratio2 else 'N/A':>12} | {fmt(v3):>14} {('%.4f' % ratio3) if ratio3 else 'N/A':>12}")

    # ---- 期望真值对比 ----
    logger.info("\n" + "=" * 90)
    logger.info("【期望真值对比】2026-07-31 应为 volume≈3,960,000股, amount≈241,000,000元")
    logger.info("=" * 90)
    target_date = "20260731"
    r1 = s1_map.get(target_date, {})
    r2 = s2_map.get(target_date, {})
    r3 = s3_map.get(target_date, {})
    logger.info(f"\n  S1 原始 amount(千元): {fmt(r1.get('amount'))}  => ×1000 后: {fmt_amount_cn((r1.get('amount') or 0)*1000)}")
    logger.info(f"  S2 adapter amount(元): {fmt(r2.get('amount'))}  => {fmt_amount_cn(r2.get('amount'))}")
    logger.info(f"  S3 DB amount(元): {fmt(r3.get('amount'))}  => {fmt_amount_cn(r3.get('amount'))}")
    logger.info(f"  S4 market_quotes amount(元): {fmt(s4.get('amount') if s4 else None)}  => {fmt_amount_cn(s4.get('amount') if s4 else None)}")
    logger.info(f"\n  S1 原始 vol(手): {fmt(r1.get('vol'))}  => ×100 后: {fmt_volume_cn((r1.get('vol') or 0)*100)}")
    logger.info(f"  S2 adapter volume(股): {fmt(r2.get('volume'))}  => {fmt_volume_cn(r2.get('volume'))}")
    logger.info(f"  S3 DB volume(股): {fmt(r3.get('volume'))}  => {fmt_volume_cn(r3.get('volume'))}")
    logger.info(f"  S4 market_quotes volume(股): {fmt(s4.get('volume') if s4 else None)}  => {fmt_volume_cn(s4.get('volume') if s4 else None)}")

    # ---- 诊断结论 ----
    logger.info("\n" + "=" * 90)
    logger.info("【诊断结论】")
    logger.info("=" * 90)
    if r1 and r3:
        a1 = r1.get("amount")
        a3 = r3.get("amount")
        if a1 and a3:
            factor = a3 / a1
            logger.info(f"  S3 DB amount / S1 原始 amount = {factor:.2f}")
            if abs(factor - 1000) < 1:
                logger.info("  => DB amount = S1×1000 ✓ 正确（千元→元）")
            elif abs(factor - 1000000) < 100:
                logger.info("  => DB amount = S1×1000000 ❌ 过度转换 1000 倍（被双重×1000）")
            elif abs(factor - 1) < 0.01:
                logger.info("  => DB amount = S1×1 ❌ 未转换（仍是千元）")
            else:
                logger.info(f"  => 异常倍数 {factor:.2f}，需人工分析")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
