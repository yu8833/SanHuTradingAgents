"""
转债下修博弈策略服务

策略逻辑：可转债在正股下跌到一定程度后，上市公司有下修转股价的动力
（为了避免还钱）。在转债价格接近债底时买入，博弈下修。

散户优势：下修博弈需要理解公司财务和转债条款，有债底保护下行风险有限，
散户资金量足够参与。

数据源：akshare bond_zh_cov（东方财富可转债一览表），通过 convertible_bond_data 模块获取。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class ConvertibleArbitrageService(RetailScreeningBase):
    """转债下修博弈策略"""

    # 转债数据源已接入（通过 akshare bond_zh_cov）
    DATA_SOURCE_CONNECTED = True

    async def scan_convertible_arbitrage(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描转债下修博弈候选

        参数：
            max_bond_price: float = 110  # 转债价格上限
            max_stock_vs_conversion: float = 0.7  # 正股/转股价最大比值（下修动力阈值）
            min_issue_size: float = 1.0  # 最小发行规模（亿元，流动性保障）
            min_score: int = 40  # 最低评分
            limit: int = 50  # 返回条数上限
        """
        start_time = time.time()
        params = params or {}

        max_bond_price = params.get("max_bond_price") or 110
        max_stock_vs_conversion = params.get("max_stock_vs_conversion") or 0.7
        min_issue_size = params.get("min_issue_size")
        if min_issue_size is None:
            min_issue_size = 1.0
        min_score = params.get("min_score", 40)
        limit = params.get("limit", 50)

        try:
            from app.services.retail.convertible_bond_data import (
                get_all_convertible_bonds,
                filter_down_revision_candidates,
            )

            # 获取全市场可转债数据（带缓存）
            all_bonds = await get_all_convertible_bonds()
            if not all_bonds:
                return {
                    "total": 0,
                    "items": [],
                    "took_ms": int((time.time() - start_time) * 1000),
                    "params": params,
                    "scanned_count": 0,
                    "message": "无法获取可转债数据，请稍后重试",
                    "data_source_status": "fetch_failed",
                }

            # 筛选下修博弈候选
            items = filter_down_revision_candidates(
                all_bonds,
                max_bond_price=max_bond_price,
                max_stock_vs_conversion=max_stock_vs_conversion,
                min_issue_size=min_issue_size,
                min_score=min_score,
                limit=limit,
            )

            took_ms = int((time.time() - start_time) * 1000)
            return {
                "total": len(items),
                "items": items,
                "took_ms": took_ms,
                "params": params,
                "scanned_count": len(all_bonds),
                "data_source_status": "connected",
            }

        except Exception as e:
            logger.error(f"❌ 转债扫描失败: {e}", exc_info=True)
            return {
                "total": 0,
                "items": [],
                "took_ms": int((time.time() - start_time) * 1000),
                "params": params,
                "scanned_count": 0,
                "message": f"扫描失败: {str(e)}",
                "data_source_status": "error",
            }

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """回测"""
        params = params or {}

        # 数据接入后使用通用回测引擎
        async def scan_func(date_str: str) -> List[dict]:
            results = await self.scan_convertible_arbitrage(params)
            return results.get("items", [])

        return await self.run_backtest("convertible_arbitrage", scan_func, params)


_service: Optional[ConvertibleArbitrageService] = None


def get_convertible_arbitrage_service() -> ConvertibleArbitrageService:
    global _service
    if _service is None:
        _service = ConvertibleArbitrageService()
    return _service
