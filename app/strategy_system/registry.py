"""策略注册表 —— 策略的元数据驱动注册源。

目标：新增策略"注册即生效"，回测列依赖由显式声明（required_columns / needs_fundamentals）
取代 backtest 的 AST 源码解析；前端策略卡片由 schema（scenarios + frontend 元数据）驱动。

用法（新策略）：
    from app.strategy_system.registry import strategy, Strategy, FrontendSpec

    @strategy(
        id="volume_bottom", name="底部放量", description="长期下跌后底部放量企稳，潜在反转",
        tags=["反转", "底部", "放量"],
        params=[...],
        scoring={"momentum_20d": 0.5, "vol_ratio_5d": 0.3, "change_pct": 0.2},
        required_columns={"low_60d", "ma20", "vol_ratio"},   # ★ 显式声明，取代 AST 解析
        needs_fundamentals=False,
        entry_signals=[], exit_signals=[],
        buy_desc=["..."], sell_desc=["..."],
        frontend=FrontendSpec(icon="📊", order=1),
        market_regimes=["熊市恐慌", "震荡蓄势"],               # 大盘适配画像
    )
    def volume_bottom_filter(df, params):
        return df["..."] > 0

兼容：存量策略仍通过 strategies._def() 注册，BUILTIN_STRATEGIES 构建后由
_bootstrap() 批量同步进本注册表；get_strategies/get_strategy/run_strategy_filter
在 strategies.py 内转调本模块，对外签名不变（screener/war_room 零改动）。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrontendSpec:
    """前端策略卡片展示元数据（schema 驱动，前端不硬编码策略 id→样式）。"""

    icon: str = "📊"
    color: str = "#409EFF"
    order: int = 0
    badge: str | None = None


@dataclass
class Strategy:
    id: str
    name: str
    description: str
    tags: list[str]
    params: list[dict]
    scoring: dict[str, float]
    filter: Callable[[object, dict], object]
    required_columns: set[str] = field(default_factory=set)   # ★ 显式列依赖
    needs_fundamentals: bool = False                          # ★ 显式基本面依赖
    entry_signals: list[str] = field(default_factory=list)
    exit_signals: list[str] = field(default_factory=list)
    buy_desc: list[str] = field(default_factory=list)
    sell_desc: list[str] = field(default_factory=list)
    order_by: str = "score"
    descending: bool = True
    limit: int = 100
    source: str = "builtin"
    asset_types: list[str] = field(default_factory=lambda: ["stock", "etf"])
    frontend: FrontendSpec = FrontendSpec()
    market_regimes: list[str] = field(default_factory=list)   # 大盘适配画像标签

    def to_dict(self, include_filter: bool = False) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "params": self.params,
            "scoring": self.scoring,
            "entry_signals": self.entry_signals,
            "exit_signals": self.exit_signals,
            "buy_desc": self.buy_desc,
            "sell_desc": self.sell_desc,
            "order_by": self.order_by,
            "descending": self.descending,
            "limit": self.limit,
            "source": self.source,
            "asset_types": self.asset_types,
            "frontend": {
                "icon": self.frontend.icon,
                "color": self.frontend.color,
                "order": self.frontend.order,
                "badge": self.frontend.badge,
            },
            "market_regimes": self.market_regimes,
        }
        if include_filter:
            d["filter"] = self.filter
        return d


class StrategyRegistry:
    """策略注册表（进程内单例）。"""

    def __init__(self) -> None:
        self._strategies: dict[str, Strategy] = {}

    def register(self, s: Strategy) -> Strategy:
        self._strategies[s.id] = s
        return s

    def register_dict(self, d: dict) -> Strategy:
        """从 strategies._def() 产出 dict 兼容注册（存量 shim 用）。"""
        # 从 dict 还原 filter 已含；required_columns 默认空集（旧策略由 backtest
        # AST 推导作为兜底，新策略显式声明）。
        s = Strategy(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            tags=list(d.get("tags") or []),
            params=list(d.get("params") or []),
            scoring=dict(d.get("scoring") or {}),
            filter=d["filter"],
            entry_signals=list(d.get("entry_signals") or []),
            exit_signals=list(d.get("exit_signals") or []),
            buy_desc=list(d.get("buy_desc") or []),
            sell_desc=list(d.get("sell_desc") or []),
            order_by=d.get("order_by", "score"),
            descending=d.get("descending", True),
            limit=d.get("limit", 100),
            source=d.get("source", "builtin"),
            asset_types=list(d.get("asset_types") or ["stock", "etf"]),
            market_regimes=list(d.get("market_regimes") or []),
        )
        return self.register(s)

    def get(self, strategy_id: str) -> Strategy | None:
        return self._strategies.get(strategy_id)

    def all(self) -> list[Strategy]:
        return sorted(self._strategies.values(), key=lambda s: s.frontend.order)

    def ids(self) -> list[str]:
        return list(self._strategies.keys())

    def schemas(self, include_filter: bool = False) -> list[dict]:
        return [s.to_dict(include_filter=include_filter) for s in self.all()]


registry = StrategyRegistry()


def strategy(**meta):
    """策略注册装饰器：@strategy(...) 一行声明即注册。

    用法见模块 docstring。filter 函数作为被装饰对象传入。
    """
    def deco(filter_fn: Callable) -> Callable:
        merged = dict(meta)
        merged["filter"] = filter_fn
        s = Strategy(**merged)
        registry.register(s)
        logger.info("✅ 策略已注册: %s (%s)", s.id, s.name)
        return filter_fn
    return deco


def _bootstrap_from_dicts(items: list[dict]) -> None:
    """存量策略（strategies.BUILTIN_STRATEGIES 的 _def 产出）批量注册进 registry。"""
    for d in items:
        registry.register_dict(d)