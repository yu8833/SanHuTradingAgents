"""
QuotesService: 提供A股批量实时快照获取。
- 复用 unified_quotes 统一行情服务（腾讯+AKShare智能选择+缓存）
- 保持返回字段 close/pct_chg/amount 不变，确保调用方无感知
- 🔥 新增：透传 fetched_at, source, age_seconds 元信息
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class QuotesService:
    """行情服务：通过 unified_quotes 获取实时行情数据"""

    async def get_quotes(self, codes: list[str]) -> dict[str, dict[str, float | None]]:
        """获取一批股票的近实时快照（最新价、涨跌幅、成交额）。

        内部调用 unified_quotes.get_unified_quotes，复用统一缓存和数据源选择策略。
        返回字段：close, pct_chg, amount, fetched_at, source, age_seconds
        """
        codes = [c.strip() for c in codes if c and c.strip()]
        if not codes:
            return {}

        try:
            # unified_quotes 是同步函数，放到线程中执行
            raw = await asyncio.to_thread(_get_unified_quotes, codes)
            if not raw:
                return {}

            # 计算数据龄（秒）
            now = datetime.now()

            result: dict[str, dict[str, float | None]] = {}
            for code, q in raw.items():
                # 腾讯源字段: price, change_pct, amount_wan(万元)
                # 统一映射为: close, pct_chg, amount(元)
                price = q.get("price")
                amount_wan = q.get("amount_wan")
                # amount_wan 是万元，转换为元
                amount = amount_wan * 10000 if amount_wan is not None else None

                # 计算 age_seconds
                fetched_at = q.get("fetched_at", now.isoformat())
                try:
                    fetched_time = datetime.fromisoformat(fetched_at)
                    age_seconds = (now - fetched_time).total_seconds()
                except (ValueError, TypeError):
                    age_seconds = 0

                result[code] = {
                    "close": price,
                    "pct_chg": q.get("change_pct"),
                    "amount": amount,
                    # 🔥 新增元信息
                    "fetched_at": fetched_at,
                    "source": q.get("source", "unknown"),
                    "age_seconds": age_seconds,
                    "data_timestamp": q.get("data_timestamp"),
                }
            return result
        except Exception as e:
            logger.error(f"获取行情失败: {e}")
            return {}


def _get_unified_quotes(codes: list[str]) -> dict[str, dict]:
    """同步调用统一行情服务"""
    from app.services.unified_quotes import get_unified_quotes
    return get_unified_quotes(codes)


_quotes_service: QuotesService | None = None


def get_quotes_service() -> QuotesService:
    global _quotes_service
    if _quotes_service is None:
        _quotes_service = QuotesService()
    return _quotes_service
