"""
QuotesService: 提供A股批量实时快照获取。
- 复用 unified_quotes 统一行情服务（腾讯+AKShare智能选择+缓存）
- 保持返回字段 close/pct_chg/amount 不变，确保调用方无感知
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class QuotesService:
    """行情服务：通过 unified_quotes 获取实时行情数据"""

    async def get_quotes(self, codes: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
        """获取一批股票的近实时快照（最新价、涨跌幅、成交额）。

        内部调用 unified_quotes.get_unified_quotes，复用统一缓存和数据源选择策略。
        返回字段与旧版保持一致：close, pct_chg, amount
        """
        codes = [c.strip() for c in codes if c and c.strip()]
        if not codes:
            return {}

        try:
            # unified_quotes 是同步函数，放到线程中执行
            raw = await asyncio.to_thread(_get_unified_quotes, codes)
            if not raw:
                return {}

            result: Dict[str, Dict[str, Optional[float]]] = {}
            for code, q in raw.items():
                # 腾讯源字段: price, change_pct, amount_wan(万元)
                # 统一映射为: close, pct_chg, amount(元)
                price = q.get("price")
                amount_wan = q.get("amount_wan")
                # amount_wan 是万元，转换为元
                amount = amount_wan * 10000 if amount_wan is not None else None
                result[code] = {
                    "close": price,
                    "pct_chg": q.get("change_pct"),
                    "amount": amount,
                }
            return result
        except Exception as e:
            logger.error(f"获取行情失败: {e}")
            return {}


def _get_unified_quotes(codes: List[str]) -> Dict[str, dict]:
    """同步调用统一行情服务"""
    from app.services.unified_quotes import get_unified_quotes
    return get_unified_quotes(codes)


_quotes_service: Optional[QuotesService] = None


def get_quotes_service() -> QuotesService:
    global _quotes_service
    if _quotes_service is None:
        _quotes_service = QuotesService()
    return _quotes_service
