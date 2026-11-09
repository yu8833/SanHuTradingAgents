"""
策略池（自选池）生命周期 防回归测试。

背景：常用策略（如「超跌反弹」）命中后会把股票并入自选，原先只进不出，自选池累积到数百只。
现按策略口径维护：命中多少只纳入多少只（不设上限、不按评分截断），触发策略离场信号即移出，
手动自选与持仓不受影响。

本测试验证：
1. 买入命中全部纳入自选（数量不设上限）；
2. 触发离场信号的标的被移出，非离场标的全部保留（不做评分/规模裁剪）；
3. 持仓中的标的即使触发离场也不从自选移出；
4. 当日日线未入库（as_of 落后于交易日）时不维护，避免用昨日数据误判；
5. 同一交易日只维护一次（幂等）；
6. 只识别策略自动纳入的条目，手动自选绝不被管理。
"""
import asyncio
import datetime

import pytest

import app.services.monitor_service as ms
import app.strategy_system.screener as screener_mod
from app.services.favorites_service import favorites_service

pytestmark = [pytest.mark.regression, pytest.mark.unit]


def _owned(n: int = 25) -> list[dict]:
    return [
        {
            "stock_code": f"C{i:02d}",
            "source_strategy": "oversold_bounce",
            "strategy_entry_score": float(i),
            "tags": ["超跌反弹"],
            "added_at": f"2026-11-{i:02d} 10:00:00",
        }
        for i in range(1, n + 1)
    ]


def _rule() -> dict:
    return {"id": "r1", "strategy_id": "oversold_bounce", "tag": "超跌反弹",
            "scope": "watchlist", "user_id": "U1", "tbs_dir": "buy"}


def _patch_common(monkeypatch, service, owned, exits, held, as_of):
    removed: list[list[str]] = []

    async def fake_get_owned(user_id, strategy_id, tag):
        return owned

    async def fake_remove(user_id, codes):
        removed.append(list(codes))
        return len(codes)

    async def fake_positions(user_id):
        return list(held)

    async def fake_record(user_id, strategy_id, entries, exit_date):
        return len(entries or [])

    monkeypatch.setattr(favorites_service, "get_strategy_favorites", fake_get_owned)
    monkeypatch.setattr(favorites_service, "remove_favorites_batch", fake_remove)
    monkeypatch.setattr(favorites_service, "record_strategy_exits", fake_record)
    monkeypatch.setattr(service, "_resolve_position_symbols", fake_positions)
    monkeypatch.setattr(ms, "get_mongo_db_sync", lambda: object())
    monkeypatch.setattr(screener_mod, "_resolve_as_of", lambda db, default: as_of)
    monkeypatch.setattr(
        screener_mod,
        "run_strategy_signals",
        lambda db, sid, pool, as_of_date, persistent: {"exit": list(exits)},
    )
    monkeypatch.setattr(ms, "is_trading_day", lambda d: True)
    monkeypatch.setattr(ms, "now_tz", lambda: datetime.datetime(2026, 11, 5, 19, 0))
    return removed


def test_pool_removes_exit_only(monkeypatch):
    """离场即移出，其余全部保留（不按评分/规模裁剪），持仓不因离场被移出。"""
    service = ms.MonitorService()
    owned = _owned(25)
    removed = _patch_common(
        monkeypatch, service, owned,
        exits=["C03", "C05", "C07"], held=["C03"],
        as_of="2026-11-05",
    )

    out = asyncio.run(service._sync_strategy_pool("U1", _rule()))
    assert out["removed"] == ["C05", "C07"]
    assert out["kept"] == [o["stock_code"] for o in owned if o["stock_code"] not in {"C05", "C07"}]
    assert len(out["kept"]) == 23  # 不截断到 20
    assert removed == [["C05", "C07"]]


def test_pool_sync_waits_for_today_eod(monkeypatch):
    """当日日线未入库（as_of 仍是上一交易日）时不维护。"""
    service = ms.MonitorService()
    owned = _owned(25)
    removed = _patch_common(monkeypatch, service, owned, exits=[], held=[], as_of="2026-11-04")

    assert asyncio.run(service._sync_strategy_pool("U1", _rule())) == {}
    assert removed == []


def test_pool_sync_once_per_trading_day(monkeypatch):
    """同一交易日重复调用不重复维护。"""
    service = ms.MonitorService()
    owned = _owned(25)
    removed = _patch_common(monkeypatch, service, owned, exits=["C05"], held=[], as_of="2026-11-05")

    first = asyncio.run(service._sync_strategy_pool("U1", _rule()))
    second = asyncio.run(service._sync_strategy_pool("U1", _rule()))
    assert first["removed"] == ["C05"]
    assert second == {}
    assert len(removed) == 1


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeColl:
    def __init__(self, docs=None):
        self.docs = docs or []
        self.inserted = []

    def find(self, query):
        return _FakeCursor(self.docs)

    async def insert_one(self, doc):
        self.inserted.append(doc)
        return type("R", (), {"inserted_id": f"id{len(self.inserted)}"})()


class _FakeDB:
    def __init__(self, rules):
        self.rules = _FakeColl(rules)
        self.orders = _FakeColl()

    def __getitem__(self, name):
        return {"monitor_rules": self.rules, "monitor_tbs_orders": self.orders}[name]


def test_entry_hits_all_added_without_cap(monkeypatch):
    """买入命中全部纳入自选并生成指令，不设数量上限。"""
    service = ms.MonitorService()
    rule = _rule()
    db = _FakeDB([rule])
    entries = [f"E{i:02d}" for i in range(30)]
    added: list[str] = []

    async def fake_get_db():
        return db

    async def fake_positions(user_id):
        return []

    async def fake_sell_pool(user_id, strategy_id):
        return []

    async def fake_item(sym):
        return {"name": sym, "close": 10.0}

    async def fake_tag(user_id, sym, item, r, score=None, signal_date=None):
        added.append(sym)
        return True

    async def fake_publish(order):
        return None

    async def fake_sync(user_id, r):
        return {}

    monkeypatch.setattr(service, "_get_db", fake_get_db)
    monkeypatch.setattr(service, "_resolve_position_symbols", fake_positions)
    monkeypatch.setattr(service, "_resolve_strategy_position_symbols", fake_sell_pool)
    monkeypatch.setattr(service, "_strategy_item", fake_item)
    monkeypatch.setattr(service, "_ensure_watchlist_tagged", fake_tag)
    monkeypatch.setattr(service, "_publish_new_order", fake_publish)
    monkeypatch.setattr(service, "_sync_strategy_pool", fake_sync)
    monkeypatch.setattr(ms, "get_mongo_db_sync", lambda: object())
    monkeypatch.setattr(ms, "is_trading_time", lambda: False)
    monkeypatch.setattr(ms, "now_tz", lambda: datetime.datetime(2026, 11, 5, 19, 0))
    monkeypatch.setattr(
        screener_mod,
        "run_strategy_signals",
        lambda db, sid, pool, as_of_date=None, persistent=False: {
            "entry": list(entries), "exit": [], "entry_scores": {},
        },
    )

    created = asyncio.run(service.scan_strategy_instructions())
    assert added == entries
    assert created == len(entries) == 30
    assert len(db.orders.inserted) == 30


def test_strategy_favorites_excludes_manual(monkeypatch):
    """只识别策略自动纳入的条目：无策略标记/标签的手动自选绝不被管理。"""
    raw = [
        {"stock_code": "600001", "tags": ["超跌反弹"]},                  # 历史数据：标签兜底
        {"stock_code": "600002", "source_strategy": "oversold_bounce"},  # 显式来源标记
        {"stock_code": "600003", "tags": []},                            # 手动自选
        {"stock_code": "600004", "source_strategy": "other"},            # 其他策略
    ]

    async def fake_db():
        return object()

    async def fake_raw(db, user_id):
        return raw

    monkeypatch.setattr(favorites_service, "_get_db", fake_db)
    monkeypatch.setattr(favorites_service, "_get_raw_favorites", fake_raw)

    out = asyncio.run(
        favorites_service.get_strategy_favorites("U1", "oversold_bounce", "超跌反弹")
    )
    assert [o["stock_code"] for o in out] == ["600001", "600002"]
