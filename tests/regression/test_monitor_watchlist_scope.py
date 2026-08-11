"""
监控规则「自选股」作用域 防回归测试。

背景：用户以自选股为主进行监控，但自选股较多、逐个输入代码费劲，且新增自选股不会自动纳入
已建规则。为此新增 scope=watchlist：规则只绑定 user_id，评估时动态解析该用户当前自选股，
从而新增自选股自动纳入、无需手动维护代码列表。

本测试验证：
1. validate 接受 scope=watchlist（需绑定 user_id），缺失 user_id 时拒绝；
2. normalize 对 watchlist 作用域清空 symbols；
3. run_evaluation 动态解析自选股并评估，命中规则写入告警；
4. 新增自选股（改变解析结果）后，同一规则自动纳入新标的。
"""
import asyncio

import pytest

import app.services.monitor_service as ms

pytestmark = [pytest.mark.regression, pytest.mark.unit]


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class _FakeRulesColl:
    def __init__(self, rules):
        self._rules = rules

    def find(self, query):
        return _FakeCursor(self._rules)


class _FakeAlertsColl:
    def __init__(self):
        self.inserted = []

    async def insert_many(self, events):
        self.inserted.extend(events)


class _FakeDB:
    def __init__(self, rules):
        self.rules_coll = _FakeRulesColl(rules)
        self.alerts_coll = _FakeAlertsColl()

    def __getitem__(self, name):
        return {
            "monitor_rules": self.rules_coll,
            "monitor_alerts": self.alerts_coll,
        }[name]


def _make_rule(scope: str, symbols: list[str] | None = None, user_id: str | None = None) -> dict:
    return {
        "id": "r1", "name": "测试", "enabled": True, "type": "price",
        "scope": scope, "symbols": symbols or [], "user_id": user_id,
        "conditions": [{"field": "pct_chg", "op": ">", "value": 5}],
        "logic": "and", "cooldown_seconds": 0, "severity": "info", "message": "",
    }


def test_validate_watchlist_requires_user_id():
    """scope=watchlist 必须绑定 user_id。"""
    ms.validate(_make_rule("watchlist", user_id="U1"))  # 不抛异常
    with pytest.raises(ValueError):
        ms.validate(_make_rule("watchlist", user_id=None))


def test_normalize_watchlist_clears_symbols():
    """watchlist 作用域的 symbols 应被清空，避免展示冗余代码。"""
    r = _make_rule("watchlist", symbols=["000001"], user_id="U1")
    n = ms.normalize(r)
    assert n["symbols"] == []
    assert n["user_id"] == "U1"


def test_run_evaluation_resolves_watchlist(monkeypatch):
    """评估时动态解析自选股，仅命中条件的标的写入告警。"""
    service = ms.MonitorService()
    rule = _make_rule("watchlist", user_id="U1")
    db = _FakeDB([rule])

    async def fake_get_db():
        return db

    async def fake_resolve(user_id):
        return ["000001", "000002"]

    async def fake_quotes(syms):
        return {
            "000001": {"name": "A", "price": 12.0, "pct_chg": 6.0},
            "000002": {"name": "B", "price": 8.0, "pct_chg": 1.0},
        }

    monkeypatch.setattr(service, "_get_db", fake_get_db)
    monkeypatch.setattr(service, "_resolve_watchlist_symbols", fake_resolve)
    monkeypatch.setattr(service, "_fetch_symbol_quotes", fake_quotes)
    monkeypatch.setattr(ms, "is_trading_time", lambda: True)

    n = asyncio.run(service.run_evaluation())
    assert n == 1
    assert len(db.alerts_coll.inserted) == 1
    assert db.alerts_coll.inserted[0]["symbol"] == "000001"


def test_new_watchlist_symbol_auto_included(monkeypatch):
    """自选股新增后，同一规则自动纳入新标的（动态解析）。"""
    service = ms.MonitorService()
    rule = _make_rule("watchlist", user_id="U1")
    db = _FakeDB([rule])

    # 模拟自选股从 [000001] 扩展到 [000001, 000003]
    resolve_calls = {"n": 0}

    async def fake_get_db():
        return db

    async def fake_resolve(user_id):
        resolve_calls["n"] += 1
        return ["000001", "000003"] if resolve_calls["n"] > 1 else ["000001"]

    # 000001 不满足 pct_chg>5，始终不命中；只有新增的 000003 命中
    async def fake_quotes(syms):
        return {
            "000001": {"name": "A", "price": 12.0, "pct_chg": 1.0},
            "000003": {"name": "C", "price": 9.0, "pct_chg": 7.0},
        }

    monkeypatch.setattr(service, "_get_db", fake_get_db)
    monkeypatch.setattr(service, "_resolve_watchlist_symbols", fake_resolve)
    monkeypatch.setattr(service, "_fetch_symbol_quotes", fake_quotes)
    monkeypatch.setattr(ms, "is_trading_time", lambda: True)

    # 第一次评估：自选股仅 [000001]，且其不命中 → 0 条
    n1 = asyncio.run(service.run_evaluation())
    assert n1 == 0
    assert db.alerts_coll.inserted == []

    # 第二次评估：新增的 000003 被自动纳入并命中
    n2 = asyncio.run(service.run_evaluation())
    assert n2 == 1
    assert db.alerts_coll.inserted[-1]["symbol"] == "000003"