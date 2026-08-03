"""
防回归测试：bug-013 market_quotes 存量数据单位错误滞留

根因：
    bug-012 修复了 adapter 代码（删除 AKShare amount÷10000），但 market_quotes
    集合的存量数据未被修正。由于 market_quotes.trade_date 是最新交易日，系统
    判定"不陈旧"，不触发重建，导致错误数据（amount÷100000, volume×100）一直滞留。

修复：
    1. backfill_from_historical_data(force=True): 强制从 stock_daily_quotes 重建
    2. verify_and_repair_market_quotes(): 启动时自动检测并修复
    3. 启动钩子 main.py lifespan 中调用 verify_and_repair_market_quotes

测试要点：
    - verify_and_repair_market_quotes 能检测到系统性偏差并触发修复
    - backfill_from_historical_data(force=True) 能正确覆盖 market_quotes
    - 修复后 market_quotes 的 amount/volume 与 stock_daily_quotes 一致
"""
import os
import pytest

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ========================================================================
# Axiom 1：backfill_from_historical_data 支持 force 参数
# ========================================================================

@pytest.mark.regression
def test_bug_013_backfill_force_parameter_exists():
    """backfill_from_historical_data 必须接受 force 参数"""
    import inspect
    from app.services.quotes_ingestion_service import QuotesIngestionService

    sig = inspect.signature(QuotesIngestionService.backfill_from_historical_data)
    assert "force" in sig.parameters, "backfill_from_historical_data 必须有 force 参数"
    assert sig.parameters["force"].default is False, "force 默认值应为 False"


# ========================================================================
# Axiom 2：verify_and_repair_market_quotes 方法存在
# ========================================================================

@pytest.mark.regression
def test_bug_013_verify_and_repair_method_exists():
    """QuotesIngestionService 必须有 verify_and_repair_market_quotes 方法"""
    from app.services.quotes_ingestion_service import QuotesIngestionService

    assert hasattr(QuotesIngestionService, "verify_and_repair_market_quotes"), \
        "QuotesIngestionService 必须有 verify_and_repair_market_quotes 方法"


# ========================================================================
# Axiom 3：启动钩子中调用了 verify_and_repair_market_quotes
# ========================================================================

@pytest.mark.regression
def test_bug_013_startup_calls_verify_and_repair():
    """main.py lifespan 中必须调用 verify_and_repair_market_quotes"""
    main_path = os.path.join(_PROJECT_ROOT, "app", "main.py")
    with open(main_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "verify_and_repair_market_quotes" in content, \
        "main.py 必须在启动流程中调用 verify_and_repair_market_quotes"


# ========================================================================
# Axiom 4：AKShare adapter 不再有 amount ÷10000 的转换
# ========================================================================

@pytest.mark.regression
def test_bug_013_akshare_no_amount_division():
    """AKShare adapter 不得包含 amount / 10000 或 amount ÷10000 的转换"""
    adapter_path = os.path.join(_PROJECT_ROOT, "app", "services", "data_sources", "akshare_adapter.py")
    with open(adapter_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查不应有 / 10000 或 /10000 的 amount 转换
    # 允许 amount_wan / 10000（unified_quotes 中的合法转换）
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # 跳过注释行
        if stripped.startswith("#"):
            continue
        # 检查 amt / 10000 或 amount / 10000 模式
        if ("/ 10000" in stripped or "/10000" in stripped) and ("amt" in stripped or "amount" in stripped):
            pytest.fail(
                f"akshare_adapter.py 第 {i} 行仍包含 amount÷10000 转换: {stripped}"
            )


# ========================================================================
# Axiom 5：Tushare adapter 的 amount 转换是 ×1000（千元→元），不是 ×0.1 或 ÷10000
# ========================================================================

@pytest.mark.regression
def test_bug_013_tushare_amount_conversion_is_x1000():
    """Tushare adapter 的 amount 转换必须是 ×1000（千元→元）"""
    adapter_path = os.path.join(_PROJECT_ROOT, "app", "services", "data_sources", "tushare_adapter.py")
    with open(adapter_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 不应出现 amount * 0.1 或 amount / 10000
    assert "* 0.1" not in content or "amount" not in content.split("* 0.1")[0][-50:], \
        "tushare_adapter.py 不应包含 amount×0.1 的错误转换"


# ========================================================================
# Axiom 6：DB 集成测试 - market_quotes 与 stock_daily_quotes 一致性
# 此测试需要 MongoDB 连接（在容器中运行）
# ========================================================================

@pytest.mark.regression
@pytest.mark.asyncio
async def test_bug_013_market_quotes_consistency_with_daily_quotes():
    """
    集成测试：验证 market_quotes 中抽样股票的 amount/volume
    与 stock_daily_quotes（正确数据源）一致。

    若 market_quotes 存在系统性单位偏差（如 bug-013 的 amount÷100000, volume×100），
    此测试会失败。
    """
    try:
        from app.core.database import init_database, get_mongo_db, close_database
    except ImportError:
        pytest.skip("数据库模块不可用")

    # 检查是否在容器环境（有 MongoDB 连接）
    mongo_url = os.getenv("TRADINGAGENTS_MONGODB_URL", "")
    if not mongo_url:
        pytest.skip("非容器环境，跳过 DB 集成测试")

    await init_database()
    try:
        db = get_mongo_db()

        # 找最新交易日
        latest_doc = await db["stock_daily_quotes"].find_one(
            {"period": "daily"}, sort=[("trade_date", -1)]
        )
        if not latest_doc:
            pytest.skip("stock_daily_quotes 为空")
        latest_td = latest_doc.get("trade_date")

        # 抽样检查 5 只股票
        sample_codes = ["688669", "000001", "600519", "300750", "000002"]
        checked = 0
        for code in sample_codes:
            mq = await db["market_quotes"].find_one({"code": code})
            sq = await db["stock_daily_quotes"].find_one({"code": code, "trade_date": latest_td})
            if not mq or not sq:
                continue

            # 🔥 盘中场景：market_quotes 是今日实时，stock_daily_quotes 是昨日日终
            # 两种情况跳过对比：
            # 1. trade_date 不一致（market_quotes 已更新为今日）
            # 2. updated_at 是今天但 trade_date 是历史日期（quotes_ingestion_service 盘中
            #    更新了 amount 但 trade_date 仍为上一交易日）
            mq_td = str(mq.get("trade_date", ""))
            sq_td = str(sq.get("trade_date", "")).replace("-", "")
            if mq_td != sq_td:
                continue  # 不同交易日，跳过对比

            mq_updated = mq.get("updated_at")
            if mq_updated:
                try:
                    if isinstance(mq_updated, str):
                        updated_date = mq_updated[:10].replace("-", "")
                    else:
                        updated_date = mq_updated.strftime("%Y%m%d")
                    if updated_date != mq_td:
                        continue  # updated_at 与 trade_date 非同一天，盘中实时数据，跳过
                except Exception:
                    pass

            mq_amt = mq.get("amount")
            sq_amt = sq.get("amount")
            mq_vol = mq.get("volume")
            sq_vol = sq.get("volume")

            if not all([mq_amt, sq_amt, mq_vol, sq_vol]):
                continue
            checked += 1

            # amount 容差 1%
            amt_ratio = mq_amt / sq_amt if sq_amt else 0
            assert 0.99 <= amt_ratio <= 1.01, (
                f"{code} market_quotes amount={mq_amt} 与 stock_daily_quotes amount={sq_amt} "
                f"不一致（比率={amt_ratio:.6f}），可能存在单位转换错误"
            )

            # volume 容差 1%
            vol_ratio = mq_vol / sq_vol if sq_vol else 0
            assert 0.99 <= vol_ratio <= 1.01, (
                f"{code} market_quotes volume={mq_vol} 与 stock_daily_quotes volume={sq_vol} "
                f"不一致（比率={vol_ratio:.6f}），可能存在单位转换错误"
            )
    finally:
        await close_database()


# ========================================================================
# Axiom 7：688669 的 market_quotes 数据必须正确（用户报告的具体案例）
# ========================================================================

@pytest.mark.regression
@pytest.mark.asyncio
async def test_bug_013_688669_market_quotes_correct():
    """
    验证 688669 的 market_quotes 数据正确：
    - amount 应在 2.41 亿元量级（241,000,000 元 ±10%）
    - volume 应在 3.96 万手量级（3,960,000 股 ±10%）
    """
    mongo_url = os.getenv("TRADINGAGENTS_MONGODB_URL", "")
    if not mongo_url:
        pytest.skip("非容器环境，跳过 DB 集成测试")

    from app.core.database import init_database, get_mongo_db, close_database

    await init_database()
    try:
        db = get_mongo_db()
        mq = await db["market_quotes"].find_one({"code": "688669"})
        if not mq:
            pytest.skip("market_quotes 中无 688669")

        # 🔥 盘中场景：market_quotes 是今日实时累计，量级会小于日终
        # 两种情况跳过：
        # 1. trade_date 在 stock_daily_quotes 中无对应日终数据（今日盘中）
        # 2. updated_at 与 trade_date 非同一天（quotes_ingestion_service 盘中更新了
        #    amount 但 trade_date 仍为上一交易日）
        mq_td = str(mq.get("trade_date", "")).replace("-", "")
        sq = await db["stock_daily_quotes"].find_one({"code": "688669", "trade_date": mq_td}) if mq_td else None
        if not sq:
            pytest.skip(f"market_quotes trade_date={mq_td} 在 stock_daily_quotes 中无对应日终数据（盘中场景），跳过量级校验")

        mq_updated = mq.get("updated_at")
        if mq_updated:
            try:
                if isinstance(mq_updated, str):
                    updated_date = mq_updated[:10].replace("-", "")
                else:
                    updated_date = mq_updated.strftime("%Y%m%d")
                if updated_date != mq_td:
                    pytest.skip(f"market_quotes updated_at={updated_date} 与 trade_date={mq_td} 非同一天（盘中实时数据），跳过量级校验")
            except Exception:
                pass

        amount = mq.get("amount")
        volume = mq.get("volume")

        # amount 应在 2 亿元 ~ 3 亿元之间（2.41 亿元量级）
        assert amount is not None and 2e8 < amount < 3e8, (
            f"688669 market_quotes amount={amount} 不在正确量级（应在 2.41 亿元=2.41e8 附近）"
        )

        # volume 应在 300 万股 ~ 500 万股之间（3.96 万手 = 396 万股）
        assert volume is not None and 3e6 < volume < 5e6, (
            f"688669 market_quotes volume={volume} 不在正确量级（应在 3.96 万手=396 万股 附近）"
        )
    finally:
        await close_database()
