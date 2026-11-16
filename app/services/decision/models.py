"""决策层数据结构（纯数据，不含 IO）。

所有价格/金额单位为元，比例均为 0-1 小数。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Direction:
    """L1 方向：来自大盘研判「今日结论」的结构化行业结论。"""

    status: str = "unavailable"  # ok | unavailable
    attack: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    as_of: str | None = None
    direction: str | None = None  # 偏多/偏空/中性
    conclusion: str = ""
    note: str = ""  # 不可用原因（给前端展示，避免静默）

    @property
    def usable(self) -> bool:
        return self.status == "ok"


@dataclass(frozen=True)
class Candidate:
    """L2 候选：B2 已触发 或 观察池待触发。"""

    code: str
    name: str
    industry: str  # 已归一为同花顺 90 行业
    price: float | None
    price_source: str  # live | close | signal | none
    trigger_price: float | None
    source: str  # b2 | pool
    score: int = 0
    bias60: float | None = None
    structure_stop: float | None = None
    trigger_date: str | None = None
    status: str = "triggered"  # triggered | watching
    held: bool = False
    stale: bool = False  # 触发信号已过期（退回观察）
    reasons: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Holding:
    """持仓（模拟账本 + 纪律账本合并后的单条结论）。"""

    code: str
    name: str
    industry: str
    source: str  # paper | cockpit
    state: str  # exit | warn | normal
    quantity: float | None = None
    market_value: float = 0.0
    avg_cost: float | None = None
    current_price: float | None = None
    pnl_pct: float | None = None
    advice: str = ""
    advice_label: str = ""
    sell_pct: float = 0.0
    reference_price: float | None = None
    stop_loss_price: float | None = None
    position_id: str | None = None
    buy_date: str | None = None
    reasons: tuple[dict, ...] = ()
    t1_locked: bool = False


@dataclass(frozen=True)
class Snapshot:
    """一次决策所需的全部输入（构建后不可变）。"""

    as_of: str
    trade_date: str
    is_intraday: bool
    quote_as_of: str | None
    gate: str  # green | yellow | red
    gate_label: str
    gate_degraded: bool
    gate_position_hint: str
    direction: Direction
    candidates: tuple[Candidate, ...] = ()
    holdings: tuple[Holding, ...] = ()
    cash: float = 0.0
    equity: float = 0.0
    day_drawdown_pct: float | None = None
    mainlines: dict[str, dict] = field(default_factory=dict)
    data_quality: tuple[str, ...] = ()

    @property
    def held_codes(self) -> frozenset[str]:
        return frozenset(h.code for h in self.holdings)
