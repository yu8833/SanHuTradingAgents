"""
退出规则引擎

"会买是徒弟，会卖是师傅"。散户亏钱的主因之一是会买不会卖。
本引擎为每个散户策略绑定明确的退出条件，对持仓进行持续监控，
触发条件时主动推送退出信号。

三类退出条件：
1. 止盈退出（thesis 兑现）—— 逻辑兑现，落袋为安
2. 止损退出（thesis 证伪）—— 逻辑破坏，立即止损
3. 时间止损（机会成本）—— 超过持仓周期无进展，释放资金
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from app.services.retail.position_sizer import StrategyType

logger = logging.getLogger(__name__)


class ExitReason(str, Enum):
    """退出原因分类"""

    TAKE_PROFIT = "take_profit"  # 止盈
    STOP_LOSS = "stop_loss"  # 止损
    TIME_STOP = "time_stop"  # 时间止损
    THESIS_INVALID = "thesis_invalid"  # 投资逻辑证伪
    NONE = "none"  # 无退出信号


# 每个策略的退出规则参数
# 持仓周期上限（天）/ 止盈涨幅 / 止损跌幅 / 均线止盈回撤
EXIT_RULES: dict = {
    StrategyType.EXTREME_REVERSAL: {
        "max_hold_days": 5,
        "take_profit_pct": 0.20,  # 反弹20%止盈
        "stop_loss_pct": 0.05,  # 买入后继续跌5%止损
        "use_moving_average_exit": True,  # 反弹到均线附近止盈
        "ma_period": 10,
    },
    StrategyType.TURNAROUND: {
        "max_hold_days": 90,
        "take_profit_pct": 0.50,  # 困境反转成功，涨幅50%止盈
        "stop_loss_pct": 0.10,  # 拐点判断错误，止损10%
        "use_moving_average_exit": False,
        "ma_period": 20,
    },
    StrategyType.SMALL_CAP_VALUE: {
        "max_hold_days": 180,
        "take_profit_pct": 0.40,  # 估值修复40%止盈
        "stop_loss_pct": 0.08,  # 基本面恶化止损8%
        "use_moving_average_exit": False,
        "ma_period": 60,
    },
    StrategyType.CONVERTIBLE_ARBITRAGE: {
        "max_hold_days": 120,
        "take_profit_pct": 0.30,  # 下修成功后转股价值提升30%止盈
        "stop_loss_pct": 0.05,  # 信用风险暴露止损5%
        "use_moving_average_exit": False,
        "ma_period": 20,
    },
    StrategyType.DEFAULT: {
        "max_hold_days": 30,
        "take_profit_pct": 0.15,
        "stop_loss_pct": 0.08,
        "use_moving_average_exit": False,
        "ma_period": 20,
    },
}


@dataclass
class HoldingContext:
    """持仓上下文（用于退出判断）"""

    symbol: str
    strategy: StrategyType
    buy_price: float  # 买入价
    buy_date: datetime  # 买入日期
    current_price: float  # 当前价
    # 可选的辅助数据
    current_ma: Optional[float] = None  # 当前均线价格（如启用均线止盈）
    # 投资逻辑是否证伪（由上层业务判断，如业绩拐点未出现）
    thesis_invalid: bool = False
    thesis_invalid_reason: str = ""


@dataclass
class ExitSignal:
    """退出信号"""

    symbol: str
    should_exit: bool
    reason: ExitReason
    # 建议卖出比例（0-1），1=全部卖出
    suggested_sell_ratio: float
    # 触发的具体条件描述
    detail: str = ""
    # 当前盈亏比例
    current_pnl_pct: float = 0.0
    # 持仓天数
    holding_days: int = 0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "should_exit": self.should_exit,
            "reason": self.reason.value,
            "suggested_sell_ratio": round(self.suggested_sell_ratio, 4),
            "detail": self.detail,
            "current_pnl_pct": round(self.current_pnl_pct, 4),
            "holding_days": self.holding_days,
        }


class ExitRuleEngine:
    """
    退出规则引擎

    对持仓进行持续监控，根据策略类型和持仓数据输出退出信号。
    """

    def evaluate(self, ctx: HoldingContext) -> ExitSignal:
        """
        评估单个持仓是否触发退出条件

        Args:
            ctx: 持仓上下文

        Returns:
            ExitSignal 退出信号
        """
        rules = EXIT_RULES.get(
            ctx.strategy, EXIT_RULES[StrategyType.DEFAULT]
        )
        now = datetime.now()
        holding_days = (now - ctx.buy_date).days
        pnl_pct = self._calc_pnl(ctx.buy_price, ctx.current_price)

        # 1. 投资逻辑证伪（最高优先级，立即全部退出）
        if ctx.thesis_invalid:
            return ExitSignal(
                symbol=ctx.symbol,
                should_exit=True,
                reason=ExitReason.THESIS_INVALID,
                suggested_sell_ratio=1.0,
                detail=f"投资逻辑证伪：{ctx.thesis_invalid_reason}",
                current_pnl_pct=pnl_pct,
                holding_days=holding_days,
            )

        # 2. 止损退出（第二优先级）
        stop_loss_pct = rules["stop_loss_pct"]
        if pnl_pct <= -stop_loss_pct:
            return ExitSignal(
                symbol=ctx.symbol,
                should_exit=True,
                reason=ExitReason.STOP_LOSS,
                suggested_sell_ratio=1.0,
                detail=f"亏损 {pnl_pct:.1%} 触发止损线 -{stop_loss_pct:.0%}",
                current_pnl_pct=pnl_pct,
                holding_days=holding_days,
            )

        # 3. 止盈退出
        take_profit_pct = rules["take_profit_pct"]
        if pnl_pct >= take_profit_pct:
            # 分批止盈：达到目标涨幅，先卖一半锁定利润
            return ExitSignal(
                symbol=ctx.symbol,
                should_exit=True,
                reason=ExitReason.TAKE_PROFIT,
                suggested_sell_ratio=0.5,
                detail=f"盈利 {pnl_pct:.1%} 达到止盈目标 {take_profit_pct:.0%}，建议先卖出50%锁定利润",
                current_pnl_pct=pnl_pct,
                holding_days=holding_days,
            )

        # 4. 均线止盈（极端反转策略特有：反弹到均线附近止盈）
        if (
            rules.get("use_moving_average_exit")
            and ctx.current_ma is not None
            and ctx.current_ma > 0
        ):
            # 价格从下方反弹到均线上方3%以内，视为接近均线
            ma_diff = (ctx.current_price - ctx.current_ma) / ctx.current_ma
            if -0.03 <= ma_diff <= 0.03 and pnl_pct > 0:
                return ExitSignal(
                    symbol=ctx.symbol,
                    should_exit=True,
                    reason=ExitReason.TAKE_PROFIT,
                    suggested_sell_ratio=1.0,
                    detail=f"价格反弹至{rules['ma_period']}日均线附近（偏离{ma_diff:+.1%}），反弹逻辑兑现",
                    current_pnl_pct=pnl_pct,
                    holding_days=holding_days,
                )

        # 5. 时间止损
        max_hold_days = rules["max_hold_days"]
        if holding_days >= max_hold_days:
            return ExitSignal(
                symbol=ctx.symbol,
                should_exit=True,
                reason=ExitReason.TIME_STOP,
                suggested_sell_ratio=1.0,
                detail=f"持仓 {holding_days} 天超过策略周期上限 {max_hold_days} 天，释放资金",
                current_pnl_pct=pnl_pct,
                holding_days=holding_days,
            )

        # 6. 无退出信号
        return ExitSignal(
            symbol=ctx.symbol,
            should_exit=False,
            reason=ExitReason.NONE,
            suggested_sell_ratio=0.0,
            current_pnl_pct=pnl_pct,
            holding_days=holding_days,
        )

    def evaluate_batch(
        self, holdings: List[HoldingContext]
    ) -> List[ExitSignal]:
        """批量评估持仓退出信号"""
        return [self.evaluate(h) for h in holdings]

    def _calc_pnl(self, buy_price: float, current_price: float) -> float:
        """计算盈亏比例"""
        if buy_price <= 0:
            return 0.0
        return (current_price - buy_price) / buy_price
