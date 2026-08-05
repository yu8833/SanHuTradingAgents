"""策略系统模块 — 移植自 tickflow-stock-panel 的策略筛选与回测引擎。

自包含实现（pandas/numpy），从 MongoDB stock_daily_quotes 读取行情，
即时计算技术指标并执行策略筛选与回测，独立于本项目其它模块。
"""