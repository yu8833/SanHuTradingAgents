import asyncio


def test_offhours_backfill_when_empty(monkeypatch):
    import app.services.quotes_ingestion_service as qis_mod
    from app.services.quotes_ingestion_service import QuotesIngestionService

    # M1 起 run_once 在非严格交易时段走 backfill；这里强制 off-hours 并显式开启
    # QUOTES_BACKFILL_ON_OFFHOURS，让 backfill_last_close_snapshot_if_needed
    # 命中「集合为空 → 从历史导入」路径。
    monkeypatch.setattr(QuotesIngestionService, "_is_strict_trading_time", lambda self, now=None: False, raising=True)
    monkeypatch.setattr(qis_mod.settings, "QUOTES_BACKFILL_ON_OFFHOURS", True, raising=True)

    # Fake DataSourceManager：历史导入需要最新交易日
    class _FakeManager:
        def find_latest_trade_date_with_fallback(self):
            return "20250102"

    monkeypatch.setattr(qis_mod, "DataSourceManager", _FakeManager, raising=True)

    # Fake DB/collection
    class _FakeResult:
        def __init__(self, upserted):
            self.matched_count = 0
            self.modified_count = 0
            self.upserted_ids = {i: None for i in range(upserted)}

    class _FakeCursor:
        def __init__(self, docs):
            self._docs = docs

        async def to_list(self, length):
            return self._docs

    class _FakeColl:
        def __init__(self):
            self.last_ops = None

        async def create_index(self, *args, **kwargs):
            return "ok"

        async def estimated_document_count(self):
            return 0  # empty -> should trigger backfill

        def find(self, query, projection=None):
            # 历史数据来源：stock_daily_quotes 返回两条收盘数据
            return _FakeCursor([
                {"symbol": "000001", "close": 10.2, "pct_chg": 0.2, "amount": 1.1e8, "volume": 1000},
                {"symbol": "600000", "close": 9.7, "pct_chg": -0.4, "amount": 7.1e7, "volume": 2000},
            ])

        async def bulk_write(self, ops, ordered=False):
            self.last_ops = ops
            return _FakeResult(len(ops))

    class _FakeDB:
        def __init__(self):
            self._coll = _FakeColl()

        def __getitem__(self, name: str):
            # market_quotes 与 stock_daily_quotes 都返回同一 fake collection
            return self._coll

    fake_db = _FakeDB()

    def _fake_get_mongo_db():
        return fake_db

    monkeypatch.setattr(qis_mod, "get_mongo_db", _fake_get_mongo_db, raising=True)

    async def _run():
        svc = QuotesIngestionService()
        await svc.run_once()
        assert fake_db._coll.last_ops is not None
        assert len(fake_db._coll.last_ops) == 2

    asyncio.run(_run())

