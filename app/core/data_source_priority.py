"""多源行情数据的统一取源优先级（单一事实来源）。

背景：stock_daily_quotes 等行情集合为多数据源混合存储（tushare/akshare/sina/baostock），
同一股票同一交易日可能并存多个源的记录（唯一索引含 data_source）。
所有需要"确定性取源"的读取点（回测面板、零售筛选、个股趋势帧、昨收兜底等）
统一引用本优先级，避免各处自行定义导致取源顺序不一致、回测/展示数值漂移。

优先级依据：tushare（官方付费源，字段最全最规范）> baostock > akshare > sina
（sina 为历史存量兜底源，字段口径历史上存在 volume 单位等已知差异，故排最后）。
"""

# 优先级从高到低；读取时同 (code, trade_date) 多源并存取优先级最高者。
DATA_SOURCE_PRIORITY = ["tushare", "baostock", "akshare", "sina"]


def source_rank(source: str | None) -> int:
    """返回数据源的优先级名次（越小越优先）；未知源排最后。"""
    try:
        return DATA_SOURCE_PRIORITY.index(source or "")
    except ValueError:
        return len(DATA_SOURCE_PRIORITY)
