#!/usr/bin/env python3
"""
688669 实时行情数据源诊断：直接调用各数据源的 get_realtime_quotes，对比原始返回值
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
# 正确值（来自 stock_daily_quotes，已验证正确）
CORRECT_AMOUNT = 241288490.0   # 元
CORRECT_VOLUME = 3960524.0     # 股
CORRECT_CLOSE = 58.60


def show(name, quotes_map):
    if not quotes_map:
        logger.info(f"  {name}: 无数据")
        return
    q = quotes_map.get(SYMBOL)
    if not q:
        logger.info(f"  {name}: 无 {SYMBOL} 记录（共 {len(quotes_map)} 只股票）")
        return
    amt = q.get("amount")
    vol = q.get("volume")
    close = q.get("close")
    logger.info(f"  {name}:")
    logger.info(f"    close={close}")
    logger.info(f"    amount={amt}  (正确={CORRECT_AMOUNT}, 比率={amt/CORRECT_AMOUNT if amt else 'N/A':.6f})")
    logger.info(f"    volume={vol}  (正确={CORRECT_VOLUME}, 比率={vol/CORRECT_VOLUME if vol else 'N/A':.6f})")


def main():
    logger.info("=" * 90)
    logger.info(f"688669 实时行情数据源诊断")
    logger.info(f"正确值: amount={CORRECT_AMOUNT:,.0f}元, volume={CORRECT_VOLUME:,.0f}股, close={CORRECT_CLOSE}")
    logger.info("=" * 90)

    # 1. Tushare rt_k
    logger.info("\n【1】TushareAdapter.get_realtime_quotes() (rt_k 接口)")
    try:
        from app.services.data_sources.tushare_adapter import TushareAdapter
        adapter = TushareAdapter()
        if adapter.is_available():
            data = adapter.get_realtime_quotes()
            show("tushare_rt_k", data)
        else:
            logger.info("  Tushare 不可用")
    except Exception as e:
        logger.error(f"  Tushare 失败: {e}")

    # 2. AKShare sina
    logger.info("\n【2】AKShareAdapter.get_realtime_quotes(source='sina')")
    try:
        from app.services.data_sources.akshare_adapter import AKShareAdapter
        adapter = AKShareAdapter()
        if adapter.is_available():
            data = adapter.get_realtime_quotes(source="sina", timeout=60)
            show("akshare_sina", data)
        else:
            logger.info("  AKShare 不可用")
    except Exception as e:
        logger.error(f"  AKShare sina 失败: {e}")

    # 3. AKShare eastmoney
    logger.info("\n【3】AKShareAdapter.get_realtime_quotes(source='eastmoney')")
    try:
        from app.services.data_sources.akshare_adapter import AKShareAdapter
        adapter = AKShareAdapter()
        if adapter.is_available():
            data = adapter.get_realtime_quotes(source="eastmoney", timeout=60)
            show("akshare_eastmoney", data)
        else:
            logger.info("  AKShare 不可用")
    except Exception as e:
        logger.error(f"  AKShare eastmoney 失败: {e}")

    # 4. AKShare 原始接口直调（不经过 adapter 转换）
    logger.info("\n【4】AKShare 原始接口直调（不经过 adapter 转换，看真实单位）")
    try:
        import akshare as ak

        # 4a. 东方财富
        logger.info("\n  【4a】ak.stock_zh_a_spot_em() (东方财富)")
        df_em = ak.stock_zh_a_spot_em()
        if df_em is not None and not df_em.empty:
            row = df_em[df_em["代码"] == SYMBOL]
            if len(row) > 0:
                r = row.iloc[0]
                logger.info(f"    列名: {list(df_em.columns)}")
                logger.info(f"    代码={r.get('代码')}, 最新价={r.get('最新价')}")
                for col in df_em.columns:
                    if any(k in col for k in ["成交", "amount", "volume", "vol"]):
                        logger.info(f"    {col} = {r.get(col)}")
            else:
                logger.info(f"    未找到 {SYMBOL}")

        # 4b. 新浪
        logger.info("\n  【4b】ak.stock_zh_a_spot() (新浪)")
        df_sina = ak.stock_zh_a_spot()
        if df_sina is not None and not df_sina.empty:
            # 新浪代码列可能带前缀
            code_col = "代码" if "代码" in df_sina.columns else "symbol" if "symbol" in df_sina.columns else None
            if code_col:
                row = df_sina[df_sina[code_col].astype(str).str.contains(SYMBOL)]
                if len(row) > 0:
                    r = row.iloc[0]
                    logger.info(f"    列名: {list(df_sina.columns)}")
                    for col in df_sina.columns:
                        if any(k in col for k in ["成交", "amount", "volume", "vol"]):
                            logger.info(f"    {col} = {r.get(col)}")
                else:
                    logger.info(f"    未找到 {SYMBOL}")
    except Exception as e:
        logger.error(f"  AKShare 原始接口失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
