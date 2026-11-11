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
from datetime import datetime
from enum import Enum
from app.utils.timezone import now_tz

from app.services.retail.position_sizer import StrategyType

logger = logging.getLogger(__name__)


class ExitReason(str, Enum):
    """退出原因分类"""

    TAKE_PROFIT = "take_profit"  # 止盈
    STOP_LOSS = "stop_loss"  # 止损
    TIME_STOP = "time_stop"  # 时间止损
    THESIS_INVALID = "thesis_invalid"  # 投资逻辑证伪
    FALSE_BREAKOUT = "false_breakout"  # 假突破
    MA_BREAK = "ma_break"  # 跌破移动止盈线（MA5）
    SIGNAL = "signal"  # 三买三卖卖点（S1/S2/S3/SafetyNet/TrailingStop）
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
    current_ma: float | None = None  # 当前均线价格（如启用均线止盈）
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
    # 统一判定附加信息（供驾驶舱 05 / 模拟交易持仓追踪共用）
    state: str = "normal"  # exit | warn | normal
    reasons: list[dict] = field(default_factory=list)  # [{kind: exit|warn, text}]
    stop_loss_line: float | None = None
    trailing_line: float | None = None
    t1_locked: bool = False
    signal_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "should_exit": self.should_exit,
            "reason": self.reason.value,
            "suggested_sell_ratio": round(self.suggested_sell_ratio, 4),
            "detail": self.detail,
            "current_pnl_pct": round(self.current_pnl_pct, 4),
            "holding_days": self.holding_days,
            "state": self.state,
            "reasons": self.reasons,
            "stop_loss_line": self.stop_loss_line,
            "trailing_line": self.trailing_line,
            "t1_locked": self.t1_locked,
            "signal_type": self.signal_type,
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
        now = now_tz()
        # 钳制为非负：naive 时间戳按 UTC 解释可能使“当日买入”瞬时得出 -1 天
        holding_days = max(0, (now - ctx.buy_date).days)
        # 现价缺失/为 0（停牌或行情源异常）时不判定离场：否则会被算成 -100% 触发无条件止损
        if not ctx.current_price or ctx.current_price <= 0 or ctx.buy_price <= 0:
            return ExitSignal(
                symbol=ctx.symbol,
                should_exit=False,
                reason=ExitReason.NONE,
                suggested_sell_ratio=0.0,
                detail="现价或成本缺失（停牌/行情异常），暂不判定离场",
                current_pnl_pct=0.0,
                holding_days=holding_days,
            )
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
        self, holdings: list[HoldingContext]
    ) -> list[ExitSignal]:
        """批量评估持仓退出信号"""
        return [self.evaluate(h) for h in holdings]

    def _calc_pnl(self, buy_price: float, current_price: float) -> float:
        """计算盈亏比例"""
        if buy_price <= 0:
            return 0.0
        return (current_price - buy_price) / buy_price


# ---------------------------------------------------------------------------
# 统一离场判定（驾驶舱 05 与模拟交易持仓追踪共用）
#
# 口径（用户拍板）：
#   - 兜底止损 8%（交易计划给定了止损价时优先用计划价）
#   - 假突破：跌回触发价 98% 以下
#   - 移动止盈线：收盘跌破 MA5（盘中仅预警）
#   - 时间止损：持仓超过 30 天无进展 → 预警释放资金
#   - 止盈：浮盈 15% 卖一半
#   - 均线止盈：价格回到 MA20 附近（±3%）且已有浮盈 → 离场
#   - 三买三卖卖点 S1/S2/S3/SafetyNet/TrailingStop 直接消费，不重复实现
# ---------------------------------------------------------------------------
UNIFIED_EXIT_PARAMS = {
    "stop_loss_pct": 0.08,  # 兜底止损：成本 -8%
    "false_breakout_buffer": 0.02,  # 假突破缓冲：触发价 -2%
    "ma_period": 5,  # 移动止盈线：MA5
    "max_hold_days": 30,  # 时间止损（自然日）
    "take_profit_pct": 0.15,  # 止盈目标：+15%
    "take_profit_sell_ratio": 0.5,  # 止盈先卖一半
    "ma_take_profit_period": 20,  # 均线止盈：MA20
    "ma_take_profit_band": 0.03,  # 均线止盈容差 ±3%
}

# 三买三卖卖点优先级（高 → 低）
SIGNAL_PRIORITY = {"S3": 5, "SafetyNet": 4, "S2": 3, "S1": 2, "TrailingStop": 1}
# 卖点默认卖出比例（信号自身未给出时使用）
SIGNAL_DEFAULT_RATIO = {"S3": 1.0, "SafetyNet": 0.5, "S2": 0.67, "S1": 0.33, "TrailingStop": 1.0}
SIGNAL_LABELS = {
    "S3": "S3 清仓卖出",
    "SafetyNet": "SafetyNet 安全网",
    "S2": "S2 主减仓",
    "S1": "S1 减仓预警",
    "TrailingStop": "TrailingStop 移动止损",
}


@dataclass
class PositionExitContext:
    """统一离场判定输入（两种持仓来源各自填充可用字段）。"""

    symbol: str
    buy_price: float
    current_price: float | None
    buy_date: str | datetime | None = None
    trade_date: str | None = None  # YYYY-MM-DD，默认今天
    trigger_price: float | None = None  # 突破买点触发价（假突破判定）
    stop_loss_price: float | None = None  # 交易计划止损价（优先于默认 -8%）
    take_profit_price: float | None = None  # 交易计划止盈价（优先于默认 +15%）
    ma5: float | None = None
    ma20: float | None = None
    is_intraday: bool = False
    signal: dict | None = None  # {signal_type, sell_pct, trigger_price, reasons}


def _to_date_str(value: str | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value or "")[:10]


def _holding_days(buy_date: str | datetime | None, trade_date: str) -> int:
    try:
        d0 = datetime.strptime(_to_date_str(buy_date), "%Y-%m-%d")
        d1 = datetime.strptime(trade_date, "%Y-%m-%d")
        return max((d1 - d0).days, 0)
    except (ValueError, TypeError):
        return 0


def _pick_signal(signal: dict | None) -> tuple[str | None, float, list[str]]:
    """取最高优先级卖点；返回 (signal_type, sell_pct, reasons)。"""
    if not signal:
        return None, 0.0, []
    signal_type = signal.get("signal_type")
    if signal_type not in SIGNAL_PRIORITY:
        return None, 0.0, []
    try:
        ratio = float(signal.get("sell_pct") or SIGNAL_DEFAULT_RATIO.get(signal_type, 0.0))
    except (TypeError, ValueError):
        ratio = SIGNAL_DEFAULT_RATIO.get(signal_type, 0.0)
    return signal_type, ratio, [str(r) for r in (signal.get("reasons") or [])]


def evaluate_unified_exit(ctx: PositionExitContext) -> ExitSignal:
    """统一离场判定（纯函数，便于两种持仓来源共用与单测）。

    输出 ExitSignal：should_exit / reason / suggested_sell_ratio / state / reasons。
    T+1 约束：买入当日所有离场信号降级为预警（state=warn）。
    """
    p = UNIFIED_EXIT_PARAMS
    trade_date = ctx.trade_date or now_tz().strftime("%Y-%m-%d")
    buy_date_str = _to_date_str(ctx.buy_date)
    holding_days = _holding_days(ctx.buy_date, trade_date)
    t1_locked = bool(buy_date_str and buy_date_str == trade_date)
    buy_price = float(ctx.buy_price or 0)
    price = ctx.current_price

    stop_loss_line = None
    if buy_price > 0:
        default_stop = buy_price * (1 - p["stop_loss_pct"])
        if ctx.stop_loss_price and ctx.stop_loss_price > 0:
            # 计划止损价与 8% 兜底取更紧的一条（价高者优先触发）
            stop_loss_line = round(max(float(ctx.stop_loss_price), default_stop), 3)
        else:
            stop_loss_line = round(default_stop, 3)
    trailing_line = round(float(ctx.ma5), 3) if ctx.ma5 else None

    def _signal(
        *,
        should_exit: bool,
        reason: ExitReason,
        ratio: float,
        detail: str,
        reasons: list[dict],
        signal_type: str | None = None,
        pnl: float | None = None,
    ) -> ExitSignal:
        return ExitSignal(
            symbol=ctx.symbol,
            should_exit=should_exit,
            reason=reason,
            suggested_sell_ratio=ratio,
            detail=detail,
            current_pnl_pct=pnl if pnl is not None else 0.0,
            holding_days=holding_days,
            state="exit" if should_exit else "normal",
            reasons=reasons,
            stop_loss_line=stop_loss_line,
            trailing_line=trailing_line,
            t1_locked=t1_locked,
            signal_type=signal_type,
        )

    if price is None or price <= 0 or buy_price <= 0:
        return _signal(
            should_exit=False,
            reason=ExitReason.NONE,
            ratio=0.0,
            detail="实时价/成本缺失（停牌或行情异常），无法判定",
            reasons=[],
        )

    price = float(price)
    pnl = price / buy_price - 1
    exits: list[dict] = []
    warns: list[dict] = []
    reason = ExitReason.NONE
    ratio = 0.0
    signal_type: str | None = None

    # 1) 兜底止损（计划止损价优先，否则 -8%）
    if stop_loss_line is not None and price <= stop_loss_line:
        exits.append(
            {
                "kind": "exit",
                "text": f"止损：现价 {price:.2f} 跌破止损线 {stop_loss_line:.2f}（浮盈 {pnl * 100:+.1f}%），无条件离场",
            }
        )
        reason, ratio = ExitReason.STOP_LOSS, 1.0

    # 2) 假突破：跌回触发价 98% 以下
    elif ctx.trigger_price and price < float(ctx.trigger_price) * (1 - p["false_breakout_buffer"]):
        exits.append(
            {
                "kind": "exit",
                "text": f"假突破：现价 {price:.2f} 跌回触发价 {float(ctx.trigger_price):.2f} 下方，按纪律离场",
            }
        )
        reason, ratio = ExitReason.FALSE_BREAKOUT, 1.0

    # 3) 三买三卖卖点（S3/SafetyNet/S2/S1/TrailingStop）
    else:
        st, sell_ratio, sig_reasons = _pick_signal(ctx.signal)
        if st:
            signal_type = st
            exits.append(
                {
                    "kind": "exit",
                    "text": "；".join(sig_reasons) or f"触发{SIGNAL_LABELS.get(st, st)}",
                }
            )
            reason, ratio = ExitReason.SIGNAL, sell_ratio

    # 4) 移动止盈线：跌破 MA5（盘中仅预警，收盘确认离场）
    if not exits and ctx.ma5 and price < float(ctx.ma5):
        if ctx.is_intraday:
            warns.append({"kind": "warn", "text": f"跌破 MA5（{float(ctx.ma5):.2f}）：盘中预警，收盘确认跌破则离场"})
        else:
            exits.append({"kind": "exit", "text": f"收盘跌破 MA5（{float(ctx.ma5):.2f}）：按移动止盈纪律离场"})
            reason, ratio = ExitReason.MA_BREAK, 1.0

    # 5) 止盈：交易计划止盈价优先（须高于成本），否则默认 +15%；先卖一半
    plan_take_profit = (
        float(ctx.take_profit_price)
        if ctx.take_profit_price and ctx.take_profit_price > buy_price
        else None
    )
    take_profit_target = plan_take_profit or buy_price * (1 + p["take_profit_pct"])
    if not exits and price >= take_profit_target:
        target_desc = "交易计划止盈价" if plan_take_profit else f"默认 +{p['take_profit_pct']:.0%}"
        exits.append(
            {
                "kind": "exit",
                "text": f"盈利 {pnl:.1%} 达到{target_desc} {take_profit_target:.2f}，建议先卖出 {int(p['take_profit_sell_ratio'] * 100)}% 锁定利润",
            }
        )
        reason, ratio = ExitReason.TAKE_PROFIT, p["take_profit_sell_ratio"]

    # 6) 均线止盈：低位买入后反弹回到 MA20 附近（±3%）且已有浮盈
    if (
        not exits
        and ctx.ma20
        and float(ctx.ma20) > 0
        and buy_price < float(ctx.ma20)
        and pnl > 0
        and abs(price / float(ctx.ma20) - 1) <= p["ma_take_profit_band"]
    ):
        ma_diff = price / float(ctx.ma20) - 1
        exits.append(
            {
                "kind": "exit",
                "text": f"价格反弹至 MA20（{float(ctx.ma20):.2f}）附近（偏离 {ma_diff:+.1%}），均线止盈离场",
            }
        )
        reason, ratio = ExitReason.TAKE_PROFIT, 1.0

    # 7) 时间止损：超过 30 天无进展 → 预警
    if holding_days > p["max_hold_days"]:
        warns.append(
            {"kind": "warn", "text": f"持仓 {holding_days} 天超过 {p['max_hold_days']} 天周期，考虑释放资金"}
        )

    # T+1：买入当日离场信号降级为预警
    if t1_locked and exits:
        warns = [
            {"kind": "warn", "text": f"{e['text']}（T+1，次一交易日执行）"} for e in exits
        ] + warns
        exits = []
        reason, ratio = ExitReason.NONE, 0.0

    all_reasons = exits + warns
    if exits:
        state = "exit"
    elif warns:
        state = "warn"
    else:
        state = "normal"
    detail = (exits or warns)[0]["text"] if (exits or warns) else ""

    return ExitSignal(
        symbol=ctx.symbol,
        should_exit=bool(exits),
        reason=reason,
        suggested_sell_ratio=ratio,
        detail=detail,
        current_pnl_pct=pnl,
        holding_days=holding_days,
        state=state,
        reasons=all_reasons,
        stop_loss_line=stop_loss_line,
        trailing_line=trailing_line,
        t1_locked=t1_locked,
        signal_type=signal_type,
    )
