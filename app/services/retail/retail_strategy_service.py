"""
散户策略服务

将仓位管理、退出规则、市场环境过滤三个模块组合成统一的门面服务，
提供完整的"买什么+买多少+何时卖+当前什么环境"能力。
"""

import logging
from datetime import datetime
from typing import List, Optional

from app.services.retail.position_sizer import (
    PositionSizer,
    PositionAdvice,
    Holding,
    StrategyType,
)
from app.services.retail.exit_rule_engine import (
    ExitRuleEngine,
    ExitSignal,
    HoldingContext,
)
from app.services.retail.market_regime_detector import (
    MarketRegimeDetector,
    MarketRegime,
)

logger = logging.getLogger(__name__)


class RetailStrategyService:
    """
    散户策略门面服务

    对外提供三个核心能力：
    1. 仓位建议（calculate_position）
    2. 退出信号（check_exits）
    3. 市场环境与策略激活建议（detect_regime）
    """

    def __init__(self):
        self.position_sizer_factory = PositionSizer
        self.exit_engine = ExitRuleEngine()
        self.regime_detector = MarketRegimeDetector()

    # ---- 仓位建议 ----

    def calculate_position(
        self,
        account_size: float,
        holdings: List[dict],
        symbol: str,
        strategy: StrategyType,
        price: float,
        win_rate: float = 0.55,
        profit_loss_ratio: float = 1.5,
        industry: str = "未知",
        theme: str = "未知",
        daily_volume_amount: Optional[float] = None,
    ) -> PositionAdvice:
        """
        计算仓位建议

        Args:
            account_size: 账户总资产（元）
            holdings: 当前持仓列表，每项 dict 含 symbol/industry/theme/market_value/position_ratio
            symbol: 目标股票代码
            strategy: 策略类型
            price: 当前股价
            win_rate: 策略历史胜率
            profit_loss_ratio: 策略历史盈亏比
            industry: 行业
            theme: 主题
            daily_volume_amount: 当日成交额（元）

        Returns:
            PositionAdvice
        """
        holding_objs = [
            Holding(
                symbol=h.get("symbol", ""),
                industry=h.get("industry", "未知"),
                theme=h.get("theme", "未知"),
                market_value=float(h.get("market_value", 0)),
                position_ratio=float(h.get("position_ratio", 0)),
            )
            for h in (holdings or [])
        ]
        sizer = self.position_sizer_factory(account_size, holding_objs)
        return sizer.calculate(
            symbol=symbol,
            strategy=strategy,
            price=price,
            win_rate=win_rate,
            profit_loss_ratio=profit_loss_ratio,
            industry=industry,
            theme=theme,
            daily_volume_amount=daily_volume_amount,
        )

    # ---- 退出信号 ----

    def check_exits(self, holdings: List[dict]) -> List[ExitSignal]:
        """
        批量检查持仓退出信号

        Args:
            holdings: 持仓列表，每项 dict 含
                symbol/strategy/buy_price/buy_date/current_price
                可选: current_ma/thesis_invalid/thesis_invalid_reason

        Returns:
            List[ExitSignal]
        """
        contexts: List[HoldingContext] = []
        for h in holdings or []:
            try:
                strategy = StrategyType(h.get("strategy", "default"))
            except ValueError:
                strategy = StrategyType.DEFAULT
            try:
                buy_date = datetime.fromisoformat(h["buy_date"])
            except (KeyError, ValueError, TypeError):
                # 无效日期默认为今天
                buy_date = datetime.now()
            contexts.append(
                HoldingContext(
                    symbol=h.get("symbol", ""),
                    strategy=strategy,
                    buy_price=float(h.get("buy_price", 0)),
                    buy_date=buy_date,
                    current_price=float(h.get("current_price", 0)),
                    current_ma=h.get("current_ma"),
                    thesis_invalid=bool(h.get("thesis_invalid", False)),
                    thesis_invalid_reason=h.get("thesis_invalid_reason", ""),
                )
            )
        return self.exit_engine.evaluate_batch(contexts)

    # ---- 市场环境 ----

    def detect_regime(
        self,
        index_price: float,
        index_ma250: float,
        volatility_percentile: float,
        breadth_ratio: float,
        margin_balance_change_pct: float,
        turnover_ratio: float,
        turnover_ma20: float,
    ) -> MarketRegime:
        """
        检测市场环境并输出策略激活建议

        数据由调用方提供（可来自 market_overview / quotes 服务）。
        """
        return self.regime_detector.detect(
            index_price=index_price,
            index_ma250=index_ma250,
            volatility_percentile=volatility_percentile,
            breadth_ratio=breadth_ratio,
            margin_balance_change_pct=margin_balance_change_pct,
            turnover_ratio=turnover_ratio,
            turnover_ma20=turnover_ma20,
        )

    async def detect_regime_auto(self) -> tuple:
        """
        自动采集数据并检测市场环境

        Returns:
            tuple: (MarketRegime, raw_data: dict)
            raw_data 包含采集到的7个原始指标，便于前端展示数据来源
        """
        from app.services.retail.market_data_collector import collect_market_regime_data
        data = await collect_market_regime_data()
        regime = self.regime_detector.detect(**data)
        return regime, data


# 单例
_service: Optional[RetailStrategyService] = None


def get_retail_strategy_service() -> RetailStrategyService:
    """获取散户策略服务单例"""
    global _service
    if _service is None:
        _service = RetailStrategyService()
    return _service
