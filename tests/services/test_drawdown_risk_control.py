"""账户级回撤风控模块（drawdown_risk_control）单元测试。

覆盖教材第五章风控规则：
- 周回撤 > 3% → 降仓至 50%（level 1）
- 月回撤 > 5% → 降仓至 30%（level 2）
- 月回撤 > 8% → 清仓暂停 1 周（level 3）
- 连续止损 ≥ 3 次 → 暂停该标的
- enforce_buy 按风控上限折算股数 / 暂停时拒绝
- compute_holding_health 持仓全红率计算
"""

import asyncio
from datetime import datetime, timedelta

import pytest

DRC = "app.services.retail.drawdown_risk_control"


# ── 内存版 MongoDB mock（支持 find/find_one/insert/update）──────────────
class _FindResult:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, key, direction=1):
        self.docs = sorted(self.docs, key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    async def to_list(self, length=None):
        return list(self.docs)


class _MemColl:
    def __init__(self, docs=None):
        self.docs = list(docs) if docs else []
        self._id = 0

    @staticmethod
    def _match(doc, query):
        for k, v in query.items():
            if not isinstance(v, dict) or not any(
                op in v for op in ("$gte", "$gt", "$lte", "$lt")
            ):
                if doc.get(k) != v:
                    return False
            else:
                for op, val in v.items():
                    dv = doc.get(k)
                    if op == "$gte" and (dv is None or dv < val):
                        return False
                    if op == "$gt" and (dv is None or dv <= val):
                        return False
                    if op == "$lte" and (dv is None or dv > val):
                        return False
                    if op == "$lt" and (dv is None or dv >= val):
                        return False
        return True

    def find(self, query):
        return _FindResult([d for d in self.docs if self._match(d, query)])

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self._id += 1
        new = dict(doc)
        new["_id"] = self._id
        self.docs.append(new)
        return {"_id": self._id}

    async def update_one(self, filter_doc, update):
        for d in self.docs:
            if self._match(d, filter_doc):
                if "$set" in update:
                    d.update(update["$set"])
                if "$inc" in update:
                    for k, v in update["$inc"].items():
                        d[k] = d.get(k, 0) + v
                return {"matched_count": 1, "modified_count": 1}
        return {"matched_count": 0, "modified_count": 0}


class _MemDB:
    def __init__(self):
        self._colls = {}

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _MemColl()
        return self._colls[name]


def _patch_db(monkeypatch, db):
    mod = __import__(DRC, fromlist=["*"])
    monkeypatch.setattr(mod, "get_mongo_db", lambda: db, raising=True)


def _patch_last_price(monkeypatch, value=10.0):
    import app.services.paper_executor as pexec
    monkeypatch.setattr(pexec, "get_last_price", _async_const(value), raising=True)


def _async_const(value):
    async def _f(*args, **kwargs):
        return value
    return _f


def _eq_docs(dd_last, dd_week, dd_month):
    """构造近30天净值快照 docs，返回最后一个为当前净值。"""
    now = datetime.now()
    docs = []
    for days, eq in ((0, dd_last), (7, dd_week), (30, dd_month)):
        docs.append({
            "user_id": "u1",
            "date": (now - timedelta(days=days)).strftime("%Y-%m-%d"),
            "equity": eq,
        })
    return docs


# ── _risk_level 纯函数阈值边界 ─────────────────────────────────────────
@pytest.mark.unit
def test_risk_level_thresholds():
    from app.services.retail.drawdown_risk_control import _risk_level
    # 月回撤 > 8% → 3（优先级最高）
    assert _risk_level(0.0, 8.5) == 3
    assert _risk_level(10.0, 9.0) == 3
    # 月回撤 == 8 不触发 clear，走 >5 → 2
    assert _risk_level(0.0, 8.0) == 2
    # 月回撤 > 5% → 2
    assert _risk_level(0.0, 5.5) == 2
    assert _risk_level(0.0, 5.0) == 0  # ==5 不触发
    # 周回撤 > 3% → 1（月回撤未超阈值时）
    assert _risk_level(3.5, 2.0) == 1
    assert _risk_level(3.0, 2.0) == 0  # ==3 不触发
    # 全部正常 → 0
    assert _risk_level(0.0, 0.0) == 0
    assert _risk_level(2.0, 4.0) == 0


# ── compute_drawdown ───────────────────────────────────────────────────
@pytest.mark.unit
def test_compute_drawdown_no_history(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    _patch_last_price(monkeypatch, 10.0)
    # 无账户 → snapshot 后当前净值 0，回撤 0，level 0
    async def _run():
        from app.services.retail.drawdown_risk_control import compute_drawdown
        res = await compute_drawdown("u_empty")
        assert res["level"] == 0
        assert res["max_position_pct"] == 1.0
        assert res["weekly_dd_pct"] == 0.0
        assert res["monthly_dd_pct"] == 0.0
    asyncio.run(_run())


@pytest.mark.unit
def test_compute_drawdown_weekly_exceed(monkeypatch):
    db = _MemDB()
    # 当前 96，7天前峰值 100 → 周回撤 4% > 3 → level 1
    db["paper_equity_history"].docs = _eq_docs(96, 100, 100)
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import compute_drawdown
        res = await compute_drawdown("u1")
        assert res["weekly_dd_pct"] == 4.0
        assert res["monthly_dd_pct"] == 4.0
        assert res["level"] == 1
        assert res["max_position_pct"] == 0.50
    asyncio.run(_run())


@pytest.mark.unit
def test_compute_drawdown_monthly_reduce(monkeypatch):
    db = _MemDB()
    # 当前 94，7天前 100，30天前 100 → 周回撤 6% 但月回撤 6% > 5 → level 2
    db["paper_equity_history"].docs = _eq_docs(94, 100, 100)
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import compute_drawdown
        res = await compute_drawdown("u1")
        assert res["monthly_dd_pct"] == 6.0
        assert res["level"] == 2
        assert res["max_position_pct"] == 0.30
    asyncio.run(_run())


@pytest.mark.unit
def test_compute_drawdown_monthly_clear(monkeypatch):
    db = _MemDB()
    # 当前 90，30天前峰值 100 → 月回撤 10% > 8 → level 3
    db["paper_equity_history"].docs = _eq_docs(90, 100, 100)
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import compute_drawdown
        res = await compute_drawdown("u1")
        assert res["monthly_dd_pct"] == 10.0
        assert res["level"] == 3
        assert res["max_position_pct"] == 0.0
    asyncio.run(_run())


# ── enforce_buy ────────────────────────────────────────────────────────
@pytest.mark.unit
def test_enforce_buy_normal_full(monkeypatch):
    db = _MemDB()
    db["paper_equity_history"].docs = _eq_docs(100, 100, 100)  # level 0
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import enforce_buy
        res = await enforce_buy("u1", "600000", 1000, 10.0)
        assert res["allowed"] is True
        assert res["qty"] == 1000
        assert res["level"] == 0
    asyncio.run(_run())


@pytest.mark.unit
def test_enforce_buy_caps_qty(monkeypatch):
    db = _MemDB()
    # 当前 50000，7天前/30天前峰值 52000 → 周回撤 3.85% > 3 → level 1, 0.5
    db["paper_equity_history"].docs = _eq_docs(50000, 52000, 52000)
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import enforce_buy
        # 净值 50000，50% → 25000，price 10 → 25000/10/100*100 = 2500 股
        res = await enforce_buy("u1", "600000", 10000, 10.0)
        assert res["allowed"] is True
        assert res["qty"] == 2500
        assert res["level"] == 1
        assert res["max_position_pct"] == 0.50
    asyncio.run(_run())


@pytest.mark.unit
def test_enforce_buy_account_paused(monkeypatch):
    db = _MemDB()
    db["paper_equity_history"].docs = _eq_docs(100, 100, 100)  # level 0
    _patch_db(monkeypatch, db)
    async def _run():
        # 账户暂停记录（paused_until 在未来）
        await db["paper_symbol_risk"].insert_one({
            "user_id": "u1", "scope": "account",
            "paused_until": (datetime.now() + timedelta(days=1)).isoformat(),
        })
        from app.services.retail.drawdown_risk_control import enforce_buy
        res = await enforce_buy("u1", "600000", 1000, 10.0)
        assert res["allowed"] is False
        assert res["qty"] == 0
        assert res["level"] == 3
    asyncio.run(_run())


@pytest.mark.unit
def test_enforce_buy_symbol_paused(monkeypatch):
    db = _MemDB()
    db["paper_equity_history"].docs = _eq_docs(100, 100, 100)  # level 0
    _patch_db(monkeypatch, db)
    async def _run():
        await db["paper_symbol_risk"].insert_one({
            "user_id": "u1", "scope": "symbol", "symbol": "600000",
            "paused_until": (datetime.now() + timedelta(days=1)).isoformat(),
        })
        from app.services.retail.drawdown_risk_control import enforce_buy
        res = await enforce_buy("u1", "600000", 1000, 10.0)
        assert res["allowed"] is False
        assert res["qty"] == 0
    asyncio.run(_run())


# ── record_exit 连续止损记账 ───────────────────────────────────────────
@pytest.mark.unit
def test_record_exit_loss_consecutive(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import record_exit
        r1 = await record_exit("u1", "600000", -100.0)
        assert r1["consecutive_stop_losses"] == 1
        assert r1["paused"] is False
        r2 = await record_exit("u1", "600000", -50.0)
        assert r2["consecutive_stop_losses"] == 2
    asyncio.run(_run())


@pytest.mark.unit
def test_record_exit_loss_pauses_after_3(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import record_exit
        await record_exit("u1", "600000", -100.0)
        await record_exit("u1", "600000", -100.0)
        r3 = await record_exit("u1", "600000", -100.0)
        assert r3["consecutive_stop_losses"] == 3
        assert r3["paused"] is True
        assert r3["paused_until"] != ""
    asyncio.run(_run())


@pytest.mark.unit
def test_record_exit_profit_resets(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    async def _run():
        from app.services.retail.drawdown_risk_control import record_exit
        await record_exit("u1", "600000", -100.0)
        await record_exit("u1", "600000", -100.0)
        r = await record_exit("u1", "600000", 200.0)
        assert r["consecutive_stop_losses"] == 0
        assert r["paused"] is False
    asyncio.run(_run())


# ── compute_holding_health 持仓全红率 ──────────────────────────────────
@pytest.mark.unit
def test_compute_holding_health(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    # 通过 get_last_price 控制盈亏：600000 盈利、300000 亏损、000001 平
    async def _fake_last(code, market):
        if code == "600000":
            return 12.0  # avg_cost 10 → 盈利
        if code == "300000":
            return 8.0   # avg_cost 10 → 亏损
        return 10.0      # avg_cost 10 → 平（green）
    import app.services.paper_executor as pexec
    monkeypatch.setattr(pexec, "get_last_price", _fake_last, raising=True)
    async def _run():
        for code, cost, qty in (("600000", 10.0, 100), ("300000", 10.0, 100), ("000001", 10.0, 100)):
            await db["paper_positions"].insert_one({
                "user_id": "u1", "code": code, "market": "CN",
                "quantity": qty, "avg_cost": cost, "stock_name": code,
            })
        from app.services.retail.drawdown_risk_control import compute_holding_health
        res = await compute_holding_health("u1")
        assert res["total"] == 3
        assert res["red"] == 1
        assert res["green"] == 2
        assert res["all_red_rate"] == round(1 / 3 * 100, 2)
    asyncio.run(_run())


# ── snapshot_equity 每日去重 ───────────────────────────────────────────
@pytest.mark.unit
def test_snapshot_equity_dedupes_per_day(monkeypatch):
    db = _MemDB()
    _patch_db(monkeypatch, db)
    _patch_last_price(monkeypatch, 10.0)
    async def _run():
        from app.services.retail.drawdown_risk_control import snapshot_equity
        e1 = await snapshot_equity("u1")
        e2 = await snapshot_equity("u1")
        assert e1 == e2
        coll = db["paper_equity_history"]
        assert len(coll.docs) == 1  # 同日去重，仅一条
    asyncio.run(_run())