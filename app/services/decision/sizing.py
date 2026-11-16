"""L3 仓位计算（纯函数）。

口径（用户拍板，改动需同步测试）：
- equity = 现金 + 持仓市值
- 单笔风险预算 R = equity × risk_pct，risk_pct 按评分：≥80 → 0.8%，≥70 → 0.5%，其余 0.3%
- 止损 = max(结构止损, entry × 0.92)，且必须低于 entry、距离在 1%~8% 之间，否则放弃
- 股数 = floor(R / 每股风险 / 100) × 100
- 单票 ≤ 15% equity；持仓 ≤ 6 只；组合风险 ≤ 3% equity；单行业 ≤ 30%（黄灯 15%）
"""

from __future__ import annotations

from dataclasses import dataclass, field

RISK_PCT_HIGH = 0.008
RISK_PCT_MID = 0.005
RISK_PCT_LOW = 0.003

MAX_SINGLE_PCT = 0.15
MAX_POSITIONS = 6
MAX_PORTFOLIO_RISK_PCT = 0.03
MAX_INDUSTRY_PCT = 0.30

YELLOW_MAX_POSITIONS = 3
YELLOW_INDUSTRY_PCT = 0.15

STOP_FLOOR_PCT = 0.08  # 兜底止损：entry × (1 - 8%)
MIN_STOP_DIST_PCT = 0.01
MAX_STOP_DIST_PCT = 0.08
LOT_SIZE = 100


def risk_pct_for(score: int) -> float:
    if score >= 80:
        return RISK_PCT_HIGH
    if score >= 70:
        return RISK_PCT_MID
    return RISK_PCT_LOW


def stop_price(entry: float, structure_stop: float | None) -> float:
    """结构止损与 -8% 兜底取更紧的一条（价高者优先触发）。"""
    floor = entry * (1 - STOP_FLOOR_PCT)
    if structure_stop and structure_stop > 0:
        return round(max(float(structure_stop), floor), 3)
    return round(floor, 3)


def stop_distance_ok(entry: float, stop: float) -> bool:
    if entry <= 0 or stop <= 0 or stop >= entry:
        return False
    dist = (entry - stop) / entry
    # 浮点误差容忍（如 10 → 9.2 恰好 8%，二进制计算会略小于 0.08）
    return MIN_STOP_DIST_PCT - 1e-9 <= dist <= MAX_STOP_DIST_PCT + 1e-9


@dataclass
class SizingResult:
    qty: int = 0
    amount: float = 0.0
    position_pct: float = 0.0
    stop: float | None = None
    risk_amount: float = 0.0
    blocked: bool = False
    block_reason: str = ""
    caps: list[str] = field(default_factory=list)  # 命中的约束，便于解释


def size_position(
    *,
    entry: float | None,
    structure_stop: float | None,
    score: int,
    equity: float,
    cash: float,
    gate: str,
    position_count: int,
    industry: str,
    industry_exposure: float,
    portfolio_risk_used: float,
) -> SizingResult:
    """按单票/组合/行业/现金约束计算股数；不满足硬约束时返回 blocked。"""
    if not entry or entry <= 0:
        return SizingResult(blocked=True, block_reason="取不到现价，无法计算仓位与止损")
    if equity <= 0:
        return SizingResult(blocked=True, block_reason="账户总资产为 0 或数据缺失，无法计算仓位")

    yellow = gate == "yellow"
    max_positions = YELLOW_MAX_POSITIONS if yellow else MAX_POSITIONS
    if position_count >= max_positions:
        return SizingResult(blocked=True, block_reason=f"持仓已达上限 {max_positions} 只，不再开新仓")

    stop = stop_price(entry, structure_stop)
    if not stop_distance_ok(entry, stop):
        return SizingResult(
            blocked=True,
            stop=stop,
            block_reason=(
                f"止损价 {stop:.2f} 不合法（需低于买入价且距离 1%~8%），放弃该标的"
            ),
        )

    per_share_risk = entry - stop
    risk_pct = risk_pct_for(score)
    risk_budget = equity * risk_pct * (0.5 if yellow else 1.0)

    # 组合风险上限
    portfolio_cap = equity * MAX_PORTFOLIO_RISK_PCT
    room = portfolio_cap - max(portfolio_risk_used, 0.0)
    caps: list[str] = []
    if room <= 0:
        return SizingResult(blocked=True, block_reason="组合风险预算已用尽（≤3% equity），暂停开新仓")
    if risk_budget > room:
        risk_budget = room
        caps.append("组合风险≤3%")

    qty = int(risk_budget / per_share_risk / LOT_SIZE) * LOT_SIZE

    # 单票上限
    single_cap = equity * MAX_SINGLE_PCT
    qty_single = int(single_cap / entry / LOT_SIZE) * LOT_SIZE
    if qty > qty_single:
        qty = qty_single
        caps.append("单票≤15%")

    # 单行业上限
    industry_cap_pct = YELLOW_INDUSTRY_PCT if yellow else MAX_INDUSTRY_PCT
    industry_room = equity * industry_cap_pct - max(industry_exposure, 0.0)
    qty_industry = int(max(industry_room, 0.0) / entry / LOT_SIZE) * LOT_SIZE
    if qty > qty_industry:
        qty = qty_industry
        caps.append(f"行业「{industry or '未知'}」≤{industry_cap_pct:.0%}")

    # 现金约束
    qty_cash = int(max(cash, 0.0) / entry / LOT_SIZE) * LOT_SIZE
    if qty > qty_cash:
        qty = qty_cash
        caps.append("可用现金")

    if qty < LOT_SIZE:
        return SizingResult(
            blocked=True,
            stop=stop,
            block_reason="按风险预算与仓位上限算出的股数不足 1 手（100 股），放弃该标的",
            caps=caps,
        )

    amount = qty * entry
    return SizingResult(
        qty=qty,
        amount=round(amount, 2),
        position_pct=round(amount / equity, 4),
        stop=stop,
        risk_amount=round(qty * per_share_risk, 2),
        blocked=False,
        caps=caps,
    )
