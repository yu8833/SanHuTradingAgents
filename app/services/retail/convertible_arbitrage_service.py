"""
转债下修博弈策略服务

策略逻辑：可转债在正股下跌到一定程度后，上市公司有下修转股价的动力
（为了避免还钱）。在转债价格接近债底时买入，博弈下修。

散户优势：下修博弈需要理解公司财务和转债条款，有债底保护下行风险有限，
散户资金量足够参与。

注意：当前系统尚未接入转债数据源（集思录/jsl等），本服务提供完整框架，
数据接入后即可运行。当前扫描返回空结果并提示数据源未接入。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.services.retail.retail_screening_base import RetailScreeningBase

logger = logging.getLogger(__name__)


class ConvertibleArbitrageService(RetailScreeningBase):
    """转债下修博弈策略"""

    # 转债数据源是否已接入
    DATA_SOURCE_CONNECTED = False

    async def scan_convertible_arbitrage(
        self, params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        扫描转债下修博弈候选

        参数：
            max_bond_price: float = 110  # 转债价格上限
            min_discount_to_floor: float = 0.05  # 距债底最小折扣
            min_score: int = 40
            limit: int = 50
        """
        start_time = time.time()
        params = params or {}

        if not self.DATA_SOURCE_CONNECTED:
            return {
                "total": 0,
                "items": [],
                "took_ms": int((time.time() - start_time) * 1000),
                "params": params,
                "scanned_count": 0,
                "message": "转债数据源尚未接入。需要接入集思录或同花顺可转债数据API，"
                "获取转债价格、转股价、回售条款等数据后即可运行扫描。",
                "data_source_status": "not_connected",
            }

        # 数据源接入后的扫描逻辑（框架）
        # TODO: 接入转债数据后实现以下逻辑
        # 1. 获取全市场可转债列表及实时价格
        # 2. 筛选转债价格 < max_bond_price
        # 3. 计算债底保护（纯债价值）
        # 4. 筛选距债底折扣 > min_discount_to_floor
        # 5. 判断下修条件：
        #    - 正股价格持续低于转股价70%
        #    - 转债进入回售期或有回售压力
        #    - 公司有下修动力（如转债即将到期/有回售条款）
        # 6. 评分：下修动力 + 债底保护 + 到期时间 + 公司偿债能力

        max_bond_price = params.get("max_bond_price", 110)
        min_discount_to_floor = params.get("min_discount_to_floor", 0.05)
        min_score = params.get("min_score", 40)
        limit = params.get("limit", 50)

        items: List[dict] = []

        # 模拟数据结构（数据接入后替换）
        # items 会包含:
        # {
        #     "bond_code": "128001",
        #     "bond_name": "XX转债",
        #     "bond_price": 102.5,
        #     "bond_floor": 98.0,          # 债底价值
        #     "discount_to_floor": 0.045,   # 距债底折扣
        #     "stock_code": "000001",
        #     "stock_name": "平安银行",
        #     "stock_price": 11.0,
        #     "conversion_price": 15.0,     # 转股价
        #     "conversion_premium": 0.36,   # 转股溢价率
        #     "stock_vs_conversion": -0.27, # 正股/转股价 偏离度
        #     "years_to_maturity": 3.5,     # 剩余年限
        #     "in_put_period": False,       # 是否在回售期
        #     "down_revision_motivation": "high",  # 下修动力
        #     "signal_type": "下修博弈",
        #     "score": 75,
        #     "score_details": {...}
        # }

        took_ms = int((time.time() - start_time) * 1000)
        return {
            "total": len(items),
            "items": items,
            "took_ms": took_ms,
            "params": params,
            "scanned_count": 0,
        }

    async def backtest(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """回测"""
        params = params or {}

        if not self.DATA_SOURCE_CONNECTED:
            return {
                "strategy": "convertible_arbitrage",
                "total_trades": 0,
                "win_rate": 0,
                "avg_return": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "profit_loss_ratio": 0,
                "max_drawdown": 0,
                "sharpe_ratio": 0,
                "calmar_ratio": 0,
                "annualized_return": 0,
                "max_consecutive_losses": 0,
                "total_fees_est": 0,
                "total_return": 0,
                "final_capital": params.get("initial_capital", 1000000),
                "initial_capital": params.get("initial_capital", 1000000),
                "backtest_days": 0,
                "sell_reason_stats": {},
                "daily_results": [],
                "top_trades": [],
                "worst_trades": [],
                "params": params,
                "took_ms": 0,
                "message": "转债数据源尚未接入，无法回测",
                "data_source_status": "not_connected",
            }

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
