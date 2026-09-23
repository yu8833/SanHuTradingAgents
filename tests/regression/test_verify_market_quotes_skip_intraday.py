"""
防回归测试：verify_and_repair_market_quotes 不得把当日盘中实时行情回滚成昨日收盘

事故背景（2026-09-23）：
    后端重启时启动期调用 verify_and_repair_market_quotes()，抽样 20 只对比
    market_quotes（当日实时金额）与 stock_daily_quotes（昨日日线金额），
    盘中口径必然不一致 → 误判「数据异常（19/20 不一致）」→
    backfill_from_historical_data(force=True) 用昨日收盘覆盖全表 →
    market_quotes 当日数据被清空 → 个股趋势当日帧只剩 14 只。

修复：
    verify_and_repair_market_quotes 在 market_quotes 最新交易日超前于日线最新交易日
    时（即库中已含当日实时快照），直接跳过一致性抽样与强制重建。

测试要点：
    - market_quotes 最新交易日 > 日线最新交易日：立即返回 True，不触发采样/重建
    - 两者一致（含 dash/compact 格式差异）：继续走原有校验逻辑（不误伤 bug-013 检测）
"""
import pytest
from unittest.mock import patch


class _FakeColl:
    """find_one 忽略查询条件返回预置文档；find().to_list 返回空（采样应被跳过）。"""

    def __init__(self, doc):
        self._doc = doc

    async def find_one(self, *args, **kwargs):
        return self._doc

    def find(self, *args, **kwargs):
        class _Cursor:
            def limit(self, n):
                return self

            async def to_list(self, length=None):
                return []
        return _Cursor()


class _FakeDB(dict):
    """支持 db["collection"] 下标访问的假数据库（与 get_mongo_db 返回对象一致）。"""

    def __init__(self, mq_newest_td: str, daily_td: str):
        super().__init__(
            stock_daily_quotes=_FakeColl({"trade_date": daily_td}),
            market_quotes=_FakeColl({"trade_date": mq_newest_td}),
        )


def _make_trading_flag():
    """返回 (recorder, setter 用的可调用) —— 记录 _is_trading_time 被调用的次数。"""
    state = {"calls": 0}

    def _flag() -> bool:
        state["calls"] += 1
        return True  # 模拟交易时段（走跳过日终校准、直接到抽样的一致路径）

    return state, _flag


@pytest.mark.regression
@pytest.mark.asyncio
async def test_verify_skips_when_market_quotes_newer_than_daily():
    """market_quotes 已含当日实时快照（超前于日线）→ 守卫直接返回 True，不进入采样/重建"""
    from app.services.quotes_ingestion_service import QuotesIngestionService

    svc = QuotesIngestionService()
    state, flag = _make_trading_flag()
    svc._is_trading_time = flag
    db = _FakeDB(mq_newest_td="20260923", daily_td="2026-09-22")
    with patch("app.services.quotes_ingestion_service.get_mongo_db", return_value=db):
        ok = await svc.verify_and_repair_market_quotes()
    assert ok is True
    assert state["calls"] == 0, "守卫应拦截：已含当日快照时不得再调用 _is_trading_time 深入校验"


@pytest.mark.regression
@pytest.mark.asyncio
async def test_verify_proceeds_when_trade_dates_match():
    """最新交易日一致（含 dash/compact 格式差异）→ 不拦截，继续走原有校验逻辑（不可误伤 bug-013 检测）"""
    from app.services.quotes_ingestion_service import QuotesIngestionService

    svc = QuotesIngestionService()
    state, flag = _make_trading_flag()
    svc._is_trading_time = flag
    db = _FakeDB(mq_newest_td="2026-09-22", daily_td="20260922")
    with patch("app.services.quotes_ingestion_service.get_mongo_db", return_value=db):
        ok = await svc.verify_and_repair_market_quotes()
    assert ok is True
    assert state["calls"] == 1, "日期一致时应继续执行校验逻辑（必须经过 _is_trading_time 分支）"