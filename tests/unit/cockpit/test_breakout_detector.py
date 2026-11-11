"""盘中突破检测（breakout_detector）单元测试。

覆盖：盘中时间进度归一、B2 突破买点确认、每码每日去重（内存 + 文档双保险）、
临近状态流转、持仓盘中预警（含 T+1 跳过）。
"""
from datetime import datetime
from types import SimpleNamespace

import pytest
from bson import ObjectId

from app.core.collections import Collections
from app.services.cockpit import breakout_detector as bd

TRADE_DATE = "2026-11-10"
T_1030 = datetime(2026, 11, 10, 10, 30)


# ---------- 最小 Fake ----------

def _match(doc: dict, query: dict) -> bool:
    for k, cond in (query or {}).items():
        if isinstance(cond, dict):
            if "$in" in cond and doc.get(k) not in cond["$in"]:
                return False
            if "$gt" in cond and not (doc.get(k) or 0) > cond["$gt"]:
                return False
            if "$exists" in cond and ((k in doc) != cond["$exists"]):
                return False
        elif doc.get(k) != cond:
            return False
    return True


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, _n):
        return self._docs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]
        self.inserted = []

    def find(self, query=None, _projection=None):
        return FakeCursor([dict(d) for d in self.docs if _match(d, query)])

    async def update_one(self, query, update):
        for d in self.docs:
            if _match(d, query):
                d.update(update.get("$set", {}))

    async def insert_one(self, doc):
        self.inserted.append(doc)

    async def distinct(self, field, query=None):
        return sorted({str(d[field]) for d in self.docs if _match(d, query) and d.get(field)})


class FakeDB:
    def __init__(self, colls):
        self._colls = colls

    def __getitem__(self, name):
        return self._colls[name]


class FakeQuotes:
    def __init__(self, quotes):
        self._q = quotes

    async def get_quotes(self, codes):
        return {c: self._q[c] for c in codes if c in self._q}


class FakeNotif:
    def __init__(self):
        self.sent = []

    async def create_and_publish(self, payload):
        self.sent.append(payload)


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _reset_dedup_state():
    bd._last_fire.clear()
    bd._last_pos_warn.clear()
    yield
    bd._last_fire.clear()
    bd._last_pos_warn.clear()


def _wire(monkeypatch, pool_docs, quotes, now=T_1030, positions=None, paper=None, b2=None):
    pool = FakeCollection(pool_docs)
    alerts = FakeCollection()
    db = FakeDB(
        {
            Collections.cockpit_watch_pool: pool,
            Collections.cockpit_positions: FakeCollection(positions or []),
            Collections.paper_positions: FakeCollection(paper or []),
            Collections.monitor_alerts: alerts,
        }
    )
    notif = FakeNotif()
    monkeypatch.setattr(bd, "now_tz", lambda: now)
    monkeypatch.setattr(bd, "is_trading_day", lambda _ymd: True)
    monkeypatch.setattr(bd, "get_mongo_db", lambda: db)
    monkeypatch.setattr(bd, "get_quotes_service", lambda: FakeQuotes(quotes))
    monkeypatch.setattr(bd, "get_notifications_service", lambda: notif)

    # 三买三卖 B2 检测替换为可控假实现
    async def _fake_check(code: str):
        res = (b2 or {}).get(code)
        return dict(res) if res else None

    monkeypatch.setattr(bd, "_check_b2", _fake_check)

    # 卖点信号默认置空（持仓预警只验证价格规则；卖点消费另行单测）
    from app.services import intraday_guide_service as igs

    async def _fake_sell_signal(_code: str):
        return None

    monkeypatch.setattr(igs, "evaluate_sell_signal", _fake_sell_signal)
    return SimpleNamespace(db=db, pool=pool, alerts=alerts, notif=notif)


def _pool_doc(**kw):
    base = {
        "code": "000001",
        "name": "平安银行",
        "industry": "银行",
        "status": "watching",
        "trigger_price": 10.0,
        "avg_amount_5d": 1e8,
    }
    base.update(kw)
    return base


# ---------- 盘中时间进度 ----------

class TestSessionProgress:
    @pytest.mark.parametrize(
        "hm,expected",
        [
            ((9, 30), 0.0),
            ((10, 30), 0.25),
            ((11, 30), 0.5),
            ((13, 0), 0.5),
            ((14, 0), 0.75),
            ((15, 0), 1.0),
            ((9, 15), None),
            ((12, 30), None),
            ((15, 30), None),
        ],
    )
    def test_progress(self, hm, expected):
        dt = datetime(2026, 11, 10, hm[0], hm[1])
        assert bd._session_progress(dt) == expected


# ---------- B2 突破确认 ----------

def _b2_result(close: float, has_b2: bool = True, vol: float = 2.2, code: str = "000001") -> dict:
    return {
        "success": True,
        "code": code,
        "close": close,
        "signals": (
            [{"type": "B2", "trigger_price": close, "volume_ratio": vol, "ma55": 9.8, "ma60": 9.7}]
            if has_b2
            else []
        ),
    }


class TestBreakoutSignals:
    async def test_trigger_fires_and_dedup_same_day(self, monkeypatch):
        env = _wire(
            monkeypatch,
            [_pool_doc()],
            {},
            positions=[{"user_id": "u1", "status": "open"}],
            b2={"000001": _b2_result(10.5)},
        )
        await bd.check_breakout_signals()
        assert len(env.notif.sent) == 1
        assert len(env.alerts.inserted) == 1
        doc = env.pool.docs[0]
        assert doc["status"] == "triggered"
        assert doc["last_triggered_date"] == TRADE_DATE
        assert doc["b2_volume_ratio"] == 2.2
        assert doc["distance_to_trigger"] == 0.05

        # 当日再扫：内存去重，不重复通知/写 alerts
        await bd.check_breakout_signals()
        assert len(env.notif.sent) == 1
        assert len(env.alerts.inserted) == 1

    async def test_doc_level_dedup_after_restart(self, monkeypatch):
        """内存清空（模拟进程重启）后，文档 last_triggered_date 仍防重。"""
        env = _wire(
            monkeypatch,
            [_pool_doc(last_triggered_date=TRADE_DATE)],
            {},
            positions=[{"user_id": "u1", "status": "open"}],
            b2={"000001": _b2_result(10.5)},
        )
        await bd.check_breakout_signals()
        assert len(env.notif.sent) == 0
        assert len(env.alerts.inserted) == 0
        assert env.pool.docs[0]["status"] == "triggered"  # 状态仍刷新

    async def test_near_and_fallback_to_watching(self, monkeypatch):
        env = _wire(
            monkeypatch,
            [_pool_doc()],
            {},
            b2={"000001": _b2_result(9.9, has_b2=False)},  # distance = -0.01 → 临近
        )
        await bd.check_breakout_signals()
        assert env.pool.docs[0]["status"] == "near"

        # 价格回落超 2% → near 回退 watching
        env2 = _wire(
            monkeypatch,
            [_pool_doc(status="near")],
            {},
            b2={"000001": _b2_result(9.4, has_b2=False)},
        )
        await bd.check_breakout_signals()
        assert env2.pool.docs[0]["status"] == "watching"

    async def test_price_above_trigger_without_b2_not_triggered(self, monkeypatch):
        """价格到位但未满足 B2（放量中阳站上 MA55/60）→ 不触发。"""
        env = _wire(
            monkeypatch,
            [_pool_doc()],
            {},
            positions=[{"user_id": "u1", "status": "open"}],
            b2={"000001": _b2_result(10.5, has_b2=False)},
        )
        await bd.check_breakout_signals()
        assert len(env.notif.sent) == 0
        assert env.pool.docs[0]["status"] == "watching"


# ---------- 持仓盘中预警 ----------

class TestPositionExitWarnings:
    def _pos(self, **kw):
        base = {
            "_id": ObjectId(),
            "user_id": "u1",
            "code": "000001",
            "name": "平安银行",
            "buy_price": 10.0,
            "buy_date": "2026-11-09",
            "status": "open",
            "trigger_price": 10.0,
        }
        base.update(kw)
        return base

    async def test_false_breakout_warns_once_per_day(self, monkeypatch):
        env = _wire(
            monkeypatch,
            [_pool_doc(ma5=9.0)],
            {"000001": {"close": 9.7, "amount": 0.0}},  # 9.7 < 10.0*0.98=9.8
            positions=[self._pos()],
        )
        await bd.check_position_exit_warnings()
        assert len(env.notif.sent) == 1
        assert env.notif.sent[0].source == "cockpit_exit"
        assert env.notif.sent[0].severity == "warning"

        await bd.check_position_exit_warnings()
        assert len(env.notif.sent) == 1  # 每仓每日每类一次

    async def test_ma5_break_warns(self, monkeypatch):
        env = _wire(
            monkeypatch,
            [_pool_doc(ma5=10.3)],
            {"000001": {"close": 10.1, "amount": 0.0}},  # 高于 9.8、跌破 MA5
            positions=[self._pos()],
        )
        await bd.check_position_exit_warnings()
        assert len(env.notif.sent) == 1
        assert env.notif.sent[0].metadata["warn_type"] == "ma5_break"

    async def test_t1_buy_day_skipped(self, monkeypatch):
        """T+1：买入当日无法卖出，不发预警。"""
        env = _wire(
            monkeypatch,
            [_pool_doc(ma5=9.0)],
            {"000001": {"close": 9.5, "amount": 0.0}},
            positions=[self._pos(buy_date=TRADE_DATE)],
        )
        await bd.check_position_exit_warnings()
        assert len(env.notif.sent) == 0
