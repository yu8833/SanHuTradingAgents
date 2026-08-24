"""
防回归测试：bug-024 数据健康检查的历史K线状态恒为 "unknown / 日期解析失败"

根因：
    `data_status._check_historical_data_status` 用 `now_tz()`（带时区）减去
    `datetime.strptime(...)`（naive）计算 days_diff 时抛 `TypeError: can't subtract
    offset-naive and offset-aware datetimes`，异常被捕获后返回 `{"status": "unknown",
    "message": "日期解析失败"}`。即便数据本身是新鲜的（latest_date 为最新交易日），
    也会把整体健康状态拉低为"部分数据源存在问题"，速览页历史K线显示"未知"。

修复：
    解析出的日期通过 `.replace(tzinfo=get_tz())` 挂上配置时区，使其与 `now_tz()`
    同为带时区 datetime，减法正常计算新鲜度。

测试要点：
    - 源码必须对 strptime 结果做 tz 挂接（静态断言）
    - 容器内集成验证：存在最新交易日数据时，历史状态应为 healthy/stale/critical 而非 unknown
"""
import os

import pytest


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ========================================================================
# Axiom 1：data_status.py 必须对 strptime 解析出的 naive 日期挂接配置时区
# ========================================================================

@pytest.mark.regression
def test_bug_024_source_attaches_tz_to_parsed_date():
    """解析 latest_date 后必须 `.replace(tzinfo=get_tz())`，避免 naive 与 aware 相减抛错"""
    path = os.path.join(_PROJECT_ROOT, "app", "routers", "data_status.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "replace(tzinfo=get_tz())" in content, \
        "data_status.py 必须对 strptime 结果调用 replace(tzinfo=get_tz())，否则与 now_tz() 相减会抛错"
    assert "from app.utils.timezone import get_tz" in content or "get_tz" in content, \
        "data_status.py 必须导入 get_tz"


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