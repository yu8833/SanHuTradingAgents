"""
仓位管理模块

散户最大的问题是仓位管理，而不是选股。本模块根据策略类型、账户规模、
当前持仓和相关性约束，输出具体的建议买入股数。

核心原则：
- 不同策略有不同的波动率特征，对应不同的单只仓位上限和总仓位上限
- 相关性控制：同行业、同主题持仓不能过度集中
- 使用半 Kelly 公式，避免全 Kelly 的激进性
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    """散户策略类型"""

    EXTREME_REVERSAL = "extreme_reversal"  # 极端情绪反转
    TURNAROUND = "turnaround"  # 困境反转
    SMALL_CAP_VALUE = "small_cap_value"  # 小盘价值
    CONVERTIBLE_ARBITRAGE = "convertible_arbitrage"  # 转债下修博弈
    DEFAULT = "default"  # 默认/未指定策略


# 每种策略的风控参数
# 单只仓位上限 / 总仓位上限 / 单只最大亏损容忍度
STRATEGY_RISK_PARAMS: dict[StrategyType, dict[str, float]] = {
    StrategyType.EXTREME_REVERSAL: {
        "max_single_position": 0.05,  # 单只≤5%，高波动
        "max_total_position": 0.30,  # 总仓位≤30%
        "max_single_loss": 0.05,  # 单只最大亏损5%即止损
        "kelly_fraction": 0.5,  # 半Kelly
    },
    StrategyType.TURNAROUND: {
        "max_single_position": 0.10,  # 单只≤10%
        "max_total_position": 0.40,  # 总仓位≤40%
        "max_single_loss": 0.10,
        "kelly_fraction": 0.5,
    },
    StrategyType.SMALL_CAP_VALUE: {
        "max_single_position": 0.08,  # 单只≤8%
        "max_total_position": 0.60,  # 总仓位≤60%
        "max_single_loss": 0.08,
        "kelly_fraction": 0.5,
    },
    StrategyType.CONVERTIBLE_ARBITRAGE: {
        "max_single_position": 0.15,  # 单只≤15%，有债底保护
        "max_total_position": 0.50,  # 总仓位≤50%
        "max_single_loss": 0.05,
        "kelly_fraction": 0.5,
    },
    StrategyType.DEFAULT: {
        "max_single_position": 0.08,
        "max_total_position": 0.40,
        "max_single_loss": 0.08,
        "kelly_fraction": 0.5,
    },
}


@dataclass
class Holding:
    """当前持仓信息（简化版，用于仓位计算）"""

    symbol: str
    industry: str  # 行业分类
    theme: str  # 主题分类（用于相关性控制）
    market_value: float  # 当前市值（元）
    position_ratio: float  # 当前仓位占比（0-1）


@dataclass
class PositionAdvice:
    """仓位建议输出"""

    symbol: str
    strategy: StrategyType
    # 建议买入数量
    suggested_shares: int
    # 建议买入金额（元）
    suggested_amount: float
    # 建议买入后该股仓位占比
    target_position_ratio: float
    # 建议买入后组合总仓位占比
    total_position_ratio_after: float
    # 是否触发风控限制
    blocked: bool
    # 阻断原因（若 blocked=True）
    block_reasons: list[str] = field(default_factory=list)
    # 风控提示
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy.value,
            "suggested_shares": self.suggested_shares,
            "suggested_amount": round(self.suggested_amount, 2),
            "target_position_ratio": round(self.target_position_ratio, 4),
            "total_position_ratio_after": round(self.total_position_ratio_after, 4),
            "blocked": self.blocked,
            "block_reasons": self.block_reasons,
            "warnings": self.warnings,
        }


class PositionSizer:
    """
    仓位管理器

    根据策略类型、账户规模、当前持仓，计算建议买入股数。
    综合考虑：单只仓位上限、总仓位上限、行业集中度、主题集中度。
    """

    # 行业集中度上限：同行业持仓不超过总资产的30%
    MAX_INDUSTRY_CONCENTRATION = 0.30
    # 主题集中度上限：同主题持仓不超过总资产的20%
    MAX_THEME_CONCENTRATION = 0.20
    # 单笔交易不超过当日成交额的5%（流动性约束，由调用方传入）
    MAX_LIQUIDITY_RATIO = 0.05
    # A股最小交易单位
    LOT_SIZE = 100

    def __init__(self, account_size: float, holdings: list[Holding]):
        """
        Args:
            account_size: 账户总资产（元），包含现金+持仓市值
            holdings: 当前持仓列表
        """
        if account_size <= 0:
            raise ValueError("账户总资产必须大于0")
        self.account_size = account_size
        self.holdings = holdings or []
        self.total_holding_value = sum(h.market_value for h in self.holdings)
        self.current_total_ratio = (
            self.total_holding_value / self.account_size
            if self.account_size > 0
            else 0.0
        )

    def calculate(
        self,
        symbol: str,
        strategy: StrategyType,
        price: float,
        win_rate: float = 0.55,
        profit_loss_ratio: float = 1.5,
        industry: str = "未知",
        theme: str = "未知",
        daily_volume_amount: float | None = None,
    ) -> PositionAdvice:
        """
        计算建议买入股数

        Args:
            symbol: 股票代码
            strategy: 策略类型
            price: 当前股价
            win_rate: 该策略历史胜率（0-1）
            profit_loss_ratio: 该策略历史盈亏比
            industry: 行业分类（用于相关性控制）
            theme: 主题分类（用于相关性控制）
            daily_volume_amount: 当日成交额（元），用于流动性约束

        Returns:
            PositionAdvice 仓位建议
        """
        params = STRATEGY_RISK_PARAMS.get(strategy, STRATEGY_RISK_PARAMS[StrategyType.DEFAULT])
        block_reasons: list[str] = []
        warnings: list[str] = []

        if price <= 0:
            return PositionAdvice(
                symbol=symbol,
                strategy=strategy,
                suggested_shares=0,
                suggested_amount=0.0,
                target_position_ratio=0.0,
                total_position_ratio_after=self.current_total_ratio,
                blocked=True,
                block_reasons=["股价无效"],
            )

        # 1. 总仓位上限检查
        if self.current_total_ratio >= params["max_total_position"]:
            block_reasons.append(
                f"总仓位已达 {self.current_total_ratio:.1%}，超过策略上限 {params['max_total_position']:.0%}"
            )

        # 2. 行业集中度检查
        industry_ratio = self._calc_concentration(industry, by="industry")
        if industry_ratio >= self.MAX_INDUSTRY_CONCENTRATION:
            block_reasons.append(
                f"行业 '{industry}' 持仓占比 {industry_ratio:.1%}，超过上限 {self.MAX_INDUSTRY_CONCENTRATION:.0%}"
            )

        # 3. 主题集中度检查
        theme_ratio = self._calc_concentration(theme, by="theme")
        if theme_ratio >= self.MAX_THEME_CONCENTRATION:
            block_reasons.append(
                f"主题 '{theme}' 持仓占比 {theme_ratio:.1%}，超过上限 {self.MAX_THEME_CONCENTRATION:.0%}"
            )

        # 4. 同股不重复加仓（极端反转策略允许，其他策略阻断）
        if strategy != StrategyType.EXTREME_REVERSAL:
            existing = next((h for h in self.holdings if h.symbol == symbol), None)
            if existing is not None:
                block_reasons.append(f"已持有 {symbol}，该策略不允许加仓")

        if block_reasons:
            return PositionAdvice(
                symbol=symbol,
                strategy=strategy,
                suggested_shares=0,
                suggested_amount=0.0,
                target_position_ratio=0.0,
                total_position_ratio_after=self.current_total_ratio,
                blocked=True,
                block_reasons=block_reasons,
            )

        # 5. 计算理论仓位（半Kelly）
        kelly_ratio = self._kelly(win_rate, profit_loss_ratio)
        if kelly_ratio <= 0:
            # 胜率或盈亏比不支持开仓
            return PositionAdvice(
                symbol=symbol,
                strategy=strategy,
                suggested_shares=0,
                suggested_amount=0.0,
                target_position_ratio=0.0,
                total_position_ratio_after=self.current_total_ratio,
                blocked=True,
                block_reasons=[
                    f"策略期望收益为负（胜率{win_rate:.0%}/盈亏比{profit_loss_ratio}），不建议开仓"
                ],
            )
        kelly_position = kelly_ratio * params["kelly_fraction"]

        # 6. 仓位上限取最小值：Kelly建议 / 单只上限 / 剩余可投额度
        remaining_capacity = max(
            0.0, params["max_total_position"] - self.current_total_ratio
        )
        max_by_single = params["max_single_position"]
        target_ratio = min(kelly_position, max_by_single, remaining_capacity)

        if target_ratio <= 0:
            return PositionAdvice(
                symbol=symbol,
                strategy=strategy,
                suggested_shares=0,
                suggested_amount=0.0,
                target_position_ratio=0.0,
                total_position_ratio_after=self.current_total_ratio,
                blocked=True,
                block_reasons=["剩余可投额度不足"],
            )

        # 7. 计算金额和股数
        target_amount = target_ratio * self.account_size

        # 8. 流动性约束
        if daily_volume_amount and daily_volume_amount > 0:
            max_by_liquidity = daily_volume_amount * self.MAX_LIQUIDITY_RATIO
            if target_amount > max_by_liquidity:
                warnings.append(
                    f"受流动性约束，买入金额从 {target_amount:.0f}元 降至 {max_by_liquidity:.0f}元（当日成交额5%）"
                )
                target_amount = max_by_liquidity
                target_ratio = target_amount / self.account_size

        # 9. 转换为股数（A股100股整手）
        suggested_shares = int(target_amount / price / self.LOT_SIZE) * self.LOT_SIZE
        if suggested_shares <= 0:
            return PositionAdvice(
                symbol=symbol,
                strategy=strategy,
                suggested_shares=0,
                suggested_amount=0.0,
                target_position_ratio=0.0,
                total_position_ratio_after=self.current_total_ratio,
                blocked=True,
                block_reasons=["计算股数不足1手（100股），资金不够"],
            )

        actual_amount = suggested_shares * price
        actual_ratio = actual_amount / self.account_size
        total_after = self.current_total_ratio + actual_ratio

        # 10. 风控提示
        if actual_ratio >= max_by_single * 0.8:
            warnings.append(f"该股仓位 {actual_ratio:.1%} 接近单只上限 {max_by_single:.0%}")
        if total_after >= params["max_total_position"] * 0.9:
            warnings.append(
                f"买入后总仓位 {total_after:.1%} 接近策略上限 {params['max_total_position']:.0%}"
            )

        return PositionAdvice(
            symbol=symbol,
            strategy=strategy,
            suggested_shares=suggested_shares,
            suggested_amount=actual_amount,
            target_position_ratio=actual_ratio,
            total_position_ratio_after=total_after,
            blocked=False,
            warnings=warnings,
        )

    def _kelly(self, win_rate: float, profit_loss_ratio: float) -> float:
        """
        Kelly公式：f = (b*p - q) / b
        p=胜率, q=1-p, b=盈亏比

        Returns:
            建议仓位比例（0-1），<=0 表示不应开仓
        """
        if win_rate <= 0 or win_rate >= 1:
            return 0.0
        if profit_loss_ratio <= 0:
            return 0.0
        p = win_rate
        q = 1 - p
        b = profit_loss_ratio
        f = (b * p - q) / b
        return max(0.0, min(f, 1.0))

    def _calc_concentration(self, key: str, by: str) -> float:
        """计算按行业或主题分组的持仓集中度"""
        if not key or key == "未知":
            return 0.0
        total = sum(
            h.market_value
            for h in self.holdings
            if (h.industry if by == "industry" else h.theme) == key
        )
        return total / self.account_size if self.account_size > 0 else 0.0
