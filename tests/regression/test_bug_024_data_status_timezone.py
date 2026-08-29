"""
防回归测试：bug-024 数据健康检查的历史K线状态恒为 "unknown / 日期解析失败"

根因（旧）：
    `data_status._check_historical_data_status` 用 `now_tz()`（带时区）减去
    `datetime.strptime(...)`（naive）计算 days_diff 时抛 `TypeError: can't subtract
    offset-naive and offset-aware datetimes`，异常被捕获后返回 `{"status": "unknown",
    "message": "日期解析失败"}`。即便数据本身是新鲜的（latest_date 为最新交易日），
    也会把整体健康状态拉低为"部分数据源存在问题"，速览页历史K线显示"未知"。

修复（现行）：
    彻底移除「自然日差」减法逻辑，改用交易日差 `calc_stale_days`
    （自动跳过周末/节假日），与 /api/screening/data-freshness 口径一致：
    - 盘中（交易日 16:00 前）数据到上一个交易日即算最新
    - 收盘后/非交易日 stale_days <= 0 才算最新
    该方案同时解决了 bug-024（no naive/aware 相减）与周末/节假日
    误报"数据已过期 N 天"的问题。

测试要点：
    - 源码不得再用自然日差减法（days_diff），必须使用交易日差 calc_stale_days
    - 容器内集成验证：存在最新交易日数据时，历史状态应为 healthy/stale/critical 而非 unknown
"""
import os

import pytest


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ========================================================================
# Axiom 1：data_status.py 必须用交易日差判新鲜度，不得用自然日差减法
# ========================================================================

@pytest.mark.regression
def test_bug_024_source_uses_trading_day_staleness():
    """历史K线新鲜度必须用交易日差 calc_stale_days，且不得再用自然日差减法（days_diff）"""
    path = os.path.join(_PROJECT_ROOT, "app", "routers", "data_status.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "calc_stale_days" in content, \
        "data_status.py 必须使用交易日差 calc_stale_days，否则周末/节假日会把最新数据误报为过期"
    assert "days_diff" not in content, \
        "data_status.py 不得再用自然日差减法（(now - latest_dt).days），应改用交易日差"


# ========================================================================
# Axiom 2：容器内集成 - 有最新交易日数据时历史K线状态不得为 unknown/解析失败
# ========================================================================

@pytest.mark.regression
@pytest.mark.asyncio
async def test_bug_024_historical_status_not_unknown():
    """
    集成测试：当 stock_daily_quotes 存在最新交易日数据时，
    _check_historical_data_status 应返回 healthy/stale/critical，而不是 unknown。
    """
    mongo_url = os.getenv("TRADINGAGENTS_MONGODB_URL", "")
    if not mongo_url:
        pytest.skip("非容器环境，跳过 DB 集成测试")

    from app.core.database import init_database, get_mongo_db, close_database
    from app.routers.data_status import _check_historical_data_status

    await init_database()
    try:
        db = get_mongo_db()
        latest_doc = await db["stock_daily_quotes"].find_one(
            {"period": "daily"}, sort=[("trade_date", -1)]
        )
        if not latest_doc:
            pytest.skip("stock_daily_quotes 为空")

        result = await _check_historical_data_status()
        assert result.get("status") in ("healthy", "stale", "critical"), (
            f"存在最新数据 {latest_doc.get('trade_date')}，但历史状态为 unknown: {result}"
        )
        msg = result.get("message", "")
        assert "解析失败" not in msg and "日期格式异常" not in msg and "无法判断新鲜度" not in msg, (
            f"历史状态不应为解析类异常消息: {msg}"
        )
    finally:
        await close_database()