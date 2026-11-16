"""今日待办决策层：L1 方向 → L2 候选 → L3 规则执行。

- L1 方向：大盘研判「今日结论」的结构化主攻/回避行业；
- L2 候选：全市场 B2 + 观察池，经主攻/回避行业过滤；
- L3 执行：纯规则计算仓位、止损、组合约束，AI 不产出订单参数。
"""

from app.services.decision.rules import decide

__all__ = ["decide"]
