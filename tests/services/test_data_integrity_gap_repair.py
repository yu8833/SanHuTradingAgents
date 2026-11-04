"""缺口审计 / 缺口修复的集成测试（使用临时 Mongo 库，不污染业务库）。"""

import uuid
from datetime import datetime

import pandas as pd
import pytest
from motor.motor_asyncio import AsyncIOMotorClient

import app.services.data_integrity_service as dis
import app.services.historical_data_service as hds
from app.core.config import settings

TEST_DAYS = ["2026-10-29", "2026-10-30"]


async def _fake_trade_days(start, end):
    return list(TEST_DAYS)


@pytest.fixture
async def db():
    try:
        client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=1200)
        await client.admin.command("ping")
    except Exception as e:  # pragma: no cover
        pytest.skip(f"MongoDB 不可用: {e}")

    name = f"tradingagents_test_gap_{uuid.uuid4().hex[:8]}"
    database = client[name]
    await database.stock_daily_quotes.create_index(
        [("symbol", 1), ("trade_date", 1), ("data_source", 1), ("period", 1)], unique=True
    )
    await database.stock_daily_basic.create_index([("code", 1), ("trade_date", 1)], unique=True)
    await database.stock_daily_moneyflow.create_index([("code", 1), ("trade_date", 1)], unique=True)
    try:
        yield database
    finally:
        await client.drop_database(name)
        client.close()


def _quote(symbol, date, source, *, valid=True):
    return {
        "symbol": symbol,
        "code": symbol,
        "trade_date": date,
        "period": "daily",
        "data_source": source,
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.0,
        "pre_close": 9.9 if valid else None,
        "pct_chg": 1.0 if valid else None,
        "volume": 100000,
        "amount": 1_000_000,
    }


async def _seed(database):
    await database.stock_basic_info.insert_many([
        {"code": "000001", "name": "甲", "market_info": {"market": "CN"}, "is_active": True, "list_date": "19900101"},
        {"code": "000002", "name": "乙", "market_info": {"market": "CN"}, "is_active": True, "list_date": "19900101"},
        {"code": "000003", "name": "丙", "market_info": {"market": "CN"}, "is_active": True, "list_date": "19900101"},
        # 10-30 新上市：10-29 不应计入应有数量
        {"code": "000004", "name": "丁", "market_info": {"market": "CN"}, "is_active": True, "list_date": "20261030"},
        # 已退市：任何日期都不应计入
        {"code": "000005", "name": "退市戊", "market_info": {"market": "CN"}, "is_active": False, "list_date": "19900101"},
    ])

    await database.stock_daily_quotes.insert_many([
        _quote("000001", "2026-10-29", "akshare"),
        _quote("000002", "2026-10-29", "akshare"),
        _quote("000003", "2026-10-29", "akshare"),
        _quote("000001", "2026-10-30", "akshare"),
        # 低质量：涨跌字段全空
        _quote("000002", "2026-10-30", "akshare", valid=False),
    ])

    await database.stock_daily_basic.insert_many([
        {"code": "000001", "trade_date": "2026-10-29"},
        {"code": "000002", "trade_date": "2026-10-29"},
        {"code": "000003", "trade_date": "2026-10-29"},
        {"code": "000001", "trade_date": "2026-10-30"},
    ])


class FakeAdapter:
    """模拟 Tushare：批量返回 000002/000003/000004 及一个不在目标集合的 000099。"""

    def _rows(self, codes):
        return [
            {
                "ts_code": f"{c}.SZ",
                "trade_date": "20261030",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.0,
                "pre_close": 9.9,
                "pct_chg": 1.01,
                "vol": 1000,
                "amount": 2000,
            }
            for c in codes
        ]

    def get_daily_by_date(self, trade_date):
        return pd.DataFrame(self._rows(["000002", "000003", "000004", "000099"]))

    def get_daily_by_stock(self, ts_code, start_date, end_date):
        return None  # 无数据（如停牌）

    def get_daily_basic(self, trade_date):
        return pd.DataFrame([
            {"ts_code": f"{c}.SZ", "total_mv": 1_000_000, "circ_mv": 900_000, "pe": 12.0, "pb": 1.2}
            for c in ["000001", "000002", "000003", "000004", "000099"]
        ])

    def get_moneyflow(self, trade_date):
        return pd.DataFrame([
            {"ts_code": f"{c}.SZ", "main_net": 100_000.0}
            for c in ["000001", "000002", "000003", "000004", "000099"]
        ])


def _make_service(database):
    svc = dis.DataIntegrityService()
    svc.db = database
    return svc


@pytest.mark.asyncio
async def test_audit_uses_unique_symbols_and_filters_new_and_delisted(db, monkeypatch):
    await _seed(db)
    monkeypatch.setattr("app.services.trade_calendar_service.query_trade_days", _fake_trade_days)
    monkeypatch.setattr(dis.DataIntegrityService, "_latest_settled_trade_day", lambda self: "2026-10-30")

    svc = _make_service(db)
    audit = await svc.audit_coverage(2, include_codes=False)

    assert audit["window_start"] == "2026-10-29"
    assert audit["window_end"] == "2026-10-30"
    assert audit["universe_count"] == 4  # 退市 000005 不计入

    by_date = {d["trade_date"]: d for d in audit["quotes"]["dates"]}
    # 10-29：新上市 000004 尚未上市，应有 3 只且全部有数据
    assert by_date["2026-10-29"]["expected"] == 3
    assert by_date["2026-10-29"]["status"] == "ok"
    # 10-30：应有 4 只，实际 2 只；000003/000004 缺失，000002 低质量
    assert by_date["2026-10-30"]["expected"] == 4
    assert by_date["2026-10-30"]["actual"] == 2
    assert by_date["2026-10-30"]["status"] == "gap"
    assert by_date["2026-10-30"]["missing_count"] == 2
    assert by_date["2026-10-30"]["low_quality_count"] == 1
    assert audit["totals"]["quotes_gap_dates"] == 1
    assert audit["has_gaps"] is True


@pytest.mark.asyncio
async def test_repair_only_writes_gaps_idempotent_and_never_touches_market_quotes(db, monkeypatch):
    await _seed(db)
    monkeypatch.setattr("app.services.trade_calendar_service.query_trade_days", _fake_trade_days)
    monkeypatch.setattr(dis.DataIntegrityService, "_latest_settled_trade_day", lambda self: "2026-10-30")
    monkeypatch.setattr(
        "app.services.data_sources.tushare_adapter.TushareAdapter", lambda: FakeAdapter()
    )

    # 使用真实标准化逻辑，但把集合指向临时库
    real_svc = hds.HistoricalDataService()
    real_svc.collection = db.stock_daily_quotes

    async def _fake_get_service():
        return real_svc

    monkeypatch.setattr(hds, "get_historical_data_service", _fake_get_service)

    def _no_redis():
        raise RuntimeError("redis disabled in test")

    monkeypatch.setattr("app.core.redis_client.get_redis_service", _no_redis)

    svc = _make_service(db)
    run_id = uuid.uuid4().hex
    await db["data_integrity_repairs"].insert_one(
        {"run_id": run_id, "status": "running", "started_at": datetime.now()}
    )
    await svc._execute_repair(run_id, 2)

    # 10-30：原有 2 条 akshare + 补 3 条 tushare（000002/000003/000004）
    assert await db.stock_daily_quotes.count_documents({"trade_date": "2026-10-30"}) == 5
    assert await db.stock_daily_quotes.count_documents(
        {"trade_date": "2026-10-30", "data_source": "tushare"}
    ) == 3
    # 目标集合之外的代码绝不写入
    assert await db.stock_daily_quotes.count_documents({"symbol": "000099"}) == 0
    # 已完整日期不被重写
    assert await db.stock_daily_quotes.count_documents({"trade_date": "2026-10-29"}) == 3
    # 市场行情快照表不能被触碰
    assert await db.market_quotes.count_documents({}) == 0

    tushare_doc = await db.stock_daily_quotes.find_one(
        {"symbol": "000003", "trade_date": "2026-10-30", "data_source": "tushare"}
    )
    assert tushare_doc["volume"] == 1000 * 100  # 手 → 股
    assert tushare_doc["amount"] == 2000 * 1000  # 千元 → 元

    # 唯一键幂等：同一 (symbol, trade_date, tushare, daily) 只有一条
    assert await db.stock_daily_quotes.count_documents(
        {"symbol": "000003", "trade_date": "2026-10-30", "data_source": "tushare", "period": "daily"}
    ) == 1

    run = await db["data_integrity_repairs"].find_one({"run_id": run_id})
    assert run["status"] == "completed"
    assert run["written"]["quotes"] == 3
    # 仅“原本缺失”的 000003/000004 可回滚；000002 属低质量覆盖，不记回滚
    assert {k["symbol"] for k in run["rollback"]["keys"]} == {"000003", "000004"}

    # 二次执行：审计已无缺口，不再写入
    run2 = uuid.uuid4().hex
    await db["data_integrity_repairs"].insert_one(
        {"run_id": run2, "status": "running", "started_at": datetime.now()}
    )
    before = await db.stock_daily_quotes.count_documents({})
    await svc._execute_repair(run2, 2)
    assert await db.stock_daily_quotes.count_documents({}) == before
    run2_doc = await db["data_integrity_repairs"].find_one({"run_id": run2})
    assert run2_doc["status"] == "no_gaps"


def test_build_quote_row_validation_and_target_filtering():
    svc = dis.DataIntegrityService()

    good = {"open": 10.0, "high": 10.5, "low": 9.8, "close": 10.0,
            "pre_close": 9.9, "pct_chg": 1.01, "vol": 1000, "amount": 2000}
    row = svc._build_quote_row(good, "2026-10-30")
    assert row["volume"] == 100000
    assert row["amount"] == 2_000_000
    assert row["close"] == 10.0

    assert svc._build_quote_row({**good, "close": 0}, "2026-10-30") is None
    assert svc._build_quote_row({**good, "high": 9.0, "low": 10.0}, "2026-10-30") is None
    assert svc._build_quote_row({**good, "pct_chg": 120}, "2026-10-30") is not None  # 新股首日
    assert svc._build_quote_row({**good, "pct_chg": 1200}, "2026-10-30") is None
    assert svc._build_quote_row({**good, "amount": -1}, "2026-10-30") is None
    assert svc._build_quote_row({**good, "close": float("nan")}, "2026-10-30") is None

    df = pd.DataFrame([
        {**good, "ts_code": "000003.SZ", "trade_date": "20261030"},
        {**good, "ts_code": "000099.SZ", "trade_date": "20261030"},
    ])
    rows = svc._extract_quote_rows(df, "2026-10-30", {"000003"})
    assert [c for c, _ in rows] == ["000003"]


@pytest.mark.asyncio
async def test_repair_by_stock_without_data_is_not_an_error(db):
    svc = _make_service(db)
    res = await svc._repair_quotes_by_stock(FakeAdapter(), "000003", {"2026-10-30"})
    assert res == {"written": 0}


def test_norm_date_str_supports_both_formats():
    assert dis.DataIntegrityService._norm_date_str("20261030") == "2026-10-30"
    assert dis.DataIntegrityService._norm_date_str("2026-10-30") == "2026-10-30"
    assert dis.DataIntegrityService._norm_date_str(None) is None
